#!/usr/bin/env python3
"""Repair exactly IASIP S12E04/E05 using previously staged Japanese subtitles.

No new provider download, translation, cross-series edits, or publication gate
overrides. Uses ffsubsync, conservative end-only overlap repair, the existing
create-only publisher and the installed coverage queue reconciler.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
import os
from pathlib import Path
import subprocess
import sys

import ja_first_autofill as autofill
import ja_first_stage_saved_batch as stage
import ja_first_publish_queue as publisher
import ja_first_publish_staged as direct

SERIES = "It's Always Sunny in Philadelphia"
SEASON = 12
EPISODES = (4, 5)
CONFLICTS = (
    "bruiser-subhub-batch.service",
    "bruiser-ja-source-autofill.service",
    "bruiser-subhub-season-sources.service",
    "bruiser-subhub-translation-batch.service",
    "bruiser-subhub-s12-recovery.service",
)
COVERAGE = Path.home()/".local/share/bruiser-subhub-dashboard/bruiser_coverage_queue.py"


def event(name, **fields):
    print("S12_OVERLAP_"+name+" "+json.dumps(
        fields,ensure_ascii=False,sort_keys=True),flush=True)


def require_idle():
    for unit in CONFLICTS:
        check=subprocess.run(
            ["systemctl","--user","show","--property=ActiveState",
             "--value",unit],
            capture_output=True,text=True,check=False,timeout=10)
        if check.returncode or check.stdout.strip() not in ("inactive","failed"):
            raise RuntimeError("other_worker_active_or_unverifiable:"+unit)


def chosen_inventory():
    inventory=stage.read_inventory()
    found={}
    for episode in EPISODES:
        rows=[
            row for row in inventory.values()
            if row.get("kind")=="Episode"
            and row.get("series_title")==SERIES
            and type(row.get("season")) is int
            and row.get("season")==SEASON
            and type(row.get("episode")) is int
            and row["episode"]==episode
        ]
        if len(rows)!=1:
            raise RuntimeError(f"nonunique_S12E{episode:02d}_identity")
        row=rows[0]
        jid=str(row.get("jellyfin_id") or "")
        if not direct.EXPECTED_ID_PATTERN.fullmatch(jid):
            raise RuntimeError(f"invalid_S12E{episode:02d}_jellyfin_id")
        found[jid]=row
    if len(found)!=len(EPISODES):
        raise RuntimeError("duplicate_identity_across_episodes")
    return found


def repair_two():
    require_idle()
    # Same flock as all existing provider source workers.
    fd=autofill.lock()
    try:
        require_idle()
        inventory=chosen_inventory()
        groups=publisher.unique_titles(
            [record for record in publisher.stages()
             if str(record[0]) in inventory],len(EPISODES))
        counts=Counter()
        held_episodes=[]
        event("BEGIN",episode_numbers=list(EPISODES),
              staged_episode_count=len(groups),provider_calls=0)
        for jid,row in sorted(inventory.items(),
                              key=lambda item:item[1]["episode"]):
            ep=row["episode"]
            try:
                candidates=groups.get(jid,[])
                video=direct.safe_media_path(str(row["host_path"]))
                target=direct.video_target(video)
                if target.is_symlink():
                    raise RuntimeError("existing_subtitle_symlink")
                if not candidates and target.exists():
                    # Never claim an unrecognized existing file as our own.
                    event("ALREADY_HAS_SUBTITLE",episode=ep,
                          note="existing_JA_track_left_untouched")
                    counts["existing"]+=1
                    continue
                if not candidates:
                    raise RuntimeError("staged_candidates_missing")
                kind,_,prepared=publisher.choose(jid,candidates)
                if kind.startswith("published_"):
                    publisher.mark_completed(jid)
                    event("ALREADY_VERIFIED",episode=ep,method=kind)
                    counts["existing"]+=1
                elif kind.startswith("ready_"):
                    publisher.publish_selected(jid,kind,prepared)
                    publisher.mark_completed(jid)
                    if not target.is_file() or target.is_symlink():
                        raise RuntimeError("published_sidecar_not_verifiable")
                    overlap=(
                        prepared.get("assessment",{}).get("overlap_repaired_cues")
                        if kind=="ready_ffsubsync" else None)
                    event("PUBLISHED",episode=ep,method=kind,
                          overlaps_repaired=overlap)
                    counts["published"]+=1
                else:
                    raise RuntimeError("publication_method_not_ready:"+kind)
            except (OSError,RuntimeError,ValueError,KeyError) as exc:
                held_episodes.append(ep)
                counts["held"]+=1
                event("HELD",episode=ep,error=type(exc).__name__,
                      reason=str(exc)[:220])
        if COVERAGE.is_file() and not COVERAGE.is_symlink():
            check=subprocess.run(
                [sys.executable,"-B","-u",str(COVERAGE),"init"],
                stdin=subprocess.DEVNULL,timeout=240,check=False)
            event("COVERAGE_REFRESH",exit_code=check.returncode)
            if check.returncode:
                raise RuntimeError("coverage_refresh_failed")
        event("DONE",published=counts["published"],existing=counts["existing"],
              held=counts["held"],unresolved_episodes=held_episodes)
        return 0 if not held_episodes else 2
    finally:
        os.close(fd)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run",action="store_true",
                        help="Retry only E04/E05 from existing staging")
    args=parser.parse_args(argv)
    if not args.run:
        print("READ ONLY: pass --run to apply verified create-only publication.")
        return 0
    try:
        return repair_two()
    except (OSError,RuntimeError,ValueError) as exc:
        event("BLOCKED",error=type(exc).__name__,reason=str(exc)[:220])
        return 1


if __name__=="__main__":
    raise SystemExit(main())
