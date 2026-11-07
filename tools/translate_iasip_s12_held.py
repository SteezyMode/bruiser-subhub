#!/usr/bin/env python3
"""Finish ONLY IASIP S12E04/E05 via source-verified PLaMo fallback.

Never relax existing Japanese subtitle publish gates, rewrite source files,
or alter the global coverage queue to force an 'eligible' status.

For each episode, first retry the installed Japanese publisher using saved
candidates. If still failing for the known timing reason, verify English
availability and pass the exact episode identity to the unchanged checkpointed
PLaMo 8B handoff. Only create a sidecar after its existing safety gates pass.
No provider calls, unrelated media work, or media directory creation.
"""
from __future__ import annotations

import argparse
from collections import Counter
import fcntl
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from urllib.parse import quote

HOME=Path.home()
SOURCE=HOME/"bruiser-pilot/subhub-control"
PLAMO=HOME/"bruiser-pilot/plamo3-ab"
MODEL=PLAMO/"subhub_plamo_handoff.py"
WORK=HOME/"bruiser-pilot/subhub-translation"
COVERAGE=HOME/".local/share/bruiser-subhub-dashboard/bruiser_coverage_queue.py"
SERIES="It's Always Sunny in Philadelphia"
EPISODES=(4,5)
SERVICE_NAMES=(
    "bruiser-subhub-batch.service",
    "bruiser-ja-source-autofill.service",
    "bruiser-subhub-season-sources.service",
    "bruiser-subhub-translation-batch.service",
    "bruiser-subhub-s12-recovery.service",
    "bruiser-subhub-s12-overlap-repair.service",
)
EXPECTED_HELD="no_candidate_passed_trusted_sync_correction"


def notice(name,**items):
    print("S12_FALLBACK_"+name+" "+json.dumps(items,sort_keys=True,
                       ensure_ascii=False),flush=True)


def installed_modules():
    for path in (SOURCE,PLAMO):
        if not path.is_dir() or path.is_symlink():
            raise RuntimeError("required_source_directory_missing_or_symlink")
    if not MODEL.is_file() or MODEL.is_symlink():
        raise RuntimeError("installed_plamo_handoff_missing")
    sys.path.insert(0,str(SOURCE))
    sys.path.insert(0,str(PLAMO))
    import subhub_plamo_handoff as ai
    import ja_first_stage_saved_batch as stage
    import ja_first_publish_staged as direct
    import ja_first_publish_queue as publisher
    return ai,stage,direct,publisher


def ensure_source_idle():
    for unit in SERVICE_NAMES:
        result=subprocess.run(
            ["systemctl","--user","show","--property=ActiveState",
             "--value",unit],
            capture_output=True,text=True,stdin=subprocess.DEVNULL,
            check=False,timeout=10)
        if result.returncode or result.stdout.strip() not in ("inactive","failed"):
            raise RuntimeError("cannot_run_with_active_source_or_translation:"+unit)
    if not WORK.is_dir() or WORK.is_symlink() or WORK.stat().st_mode&0o077:
        raise RuntimeError("expected_private_translation_workspace_missing")


def exact_episode_rows(ai,stage):
    inventory=stage.read_inventory()
    selected={}
    for ep in EPISODES:
        hits=[r for r in inventory.values()
              if isinstance(r,dict)
              and r.get("kind")=="Episode"
              and r.get("series_title")==SERIES
              and type(r.get("season")) is int and r["season"]==12
              and type(r.get("episode")) is int and r["episode"]==ep]
        if len(hits)!=1:
            raise RuntimeError(f"S12E{ep:02d}_source_identity_not_unique")
        source=hits[0]
        jid=str(source.get("jellyfin_id") or "")
        if not ai.JELLYFIN_ID.fullmatch(jid):
            raise RuntimeError("invalid_Jellyfin_episode_identity")
        with ai.safe_db(ai.QUEUE) as db:
            db.row_factory=sqlite3.Row
            rows=db.execute("""
                SELECT m.jellyfin_id,m.path,m.kind,m.title,m.series,
                       m.season,m.episode,m.ja_present,m.en_text,
                       t.action,t.state,t.target
                FROM media m JOIN tasks t ON m.path=t.path
                WHERE m.jellyfin_id=? AND t.target='ja' AND t.active=1
                """,(jid,)).fetchall()
        if len(rows)!=1:
            raise RuntimeError(f"S12E{ep:02d}_coverage_identity_not_unique")
        q=dict(rows[0])
        if not all((
            q["kind"]=="Episode",q["series"]==SERIES,
            str(q["season"])=="12",str(q["episode"])==str(ep),
            q["path"]==source.get("host_path"),
            q["en_text"]==1,q["ja_present"]==0,
            q["state"]=="pending",q["target"]=="ja",
            q["action"]=="align_existing_staged_ja",
            source.get("status")=="ready_ja_search",
        )):
            raise RuntimeError(f"S12E{ep:02d}_source_first_or_EN_preflight_not_ready")
        # No sidecar should already exist for this video, including PLaMo's
        # create-only naming. The model itself rechecks embedded JA as well.
        video=Path(q["path"])
        if video.is_symlink() or not video.is_file():
            raise RuntimeError(f"S12E{ep:02d}_video_not_current_regular_file")
        selected[jid]={
            "jellyfin_id":jid,"path":q["path"],"kind":"Episode",
            "title":q["title"],"series":q["series"],
            "action":q["action"],"state":q["state"],
            "target":"ja","english_text":1,"episode":ep,
        }
    if len(selected)!=len(EPISODES):
        raise RuntimeError("different_episodes_same_identity")
    return selected


def validate_prior_source_failure(row,publisher,direct,candidates):
    jid=row["jellyfin_id"]
    video=direct.safe_media_path(row["path"])
    target=direct.video_target(video)
    if target.is_symlink() or target.exists():
        raise RuntimeError("japanese_sidecar_exists_do_not_translate")
    if not candidates:
        raise RuntimeError("source_not_really_staged")
    try:
        kind,_,candidate=publisher.choose(jid,candidates)
    except (RuntimeError,OSError,sqlite3.Error) as exc:
        if str(exc)!=EXPECTED_HELD:
            raise RuntimeError("unexpected_source_qa_failure:"+str(exc)[:150])
        notice("JA_SOURCE_EXHAUSTED",episode=row["episode"],
               reason=EXPECTED_HELD)
        return False
    if kind.startswith("ready_"):
        # A source may have become repairable since the prior failed attempt:
        # use it instead of expending GPU work.
        publisher.publish_selected(jid,kind,candidate)
        publisher.mark_completed(jid)
        notice("JA_SOURCE_PUBLISHED",episode=row["episode"],method=kind)
        return True
    if kind.startswith("published_"):
        publisher.mark_completed(jid)
        notice("JA_ALREADY_PUBLISHED",episode=row["episode"],method=kind)
        return True
    raise RuntimeError("unexpected_source_state:"+str(kind))


def prepare_and_translate(ai,row):
    jid=row["jellyfin_id"]
    model_modules=ai.modules()
    folder=ai.private_folder(jid,row["path"])
    if folder.is_symlink():
        raise RuntimeError("unsafe_translation_checkpoint_symlink")
    folder.mkdir(mode=0o700,parents=False,exist_ok=True)
    if folder.stat().st_mode&0o077:
        raise RuntimeError("translation_checkpoint_not_private")
    _,cues,record=ai.prepared_source(row,folder,model_modules)
    notice("EN_VERIFIED",episode=row["episode"],
           cues=len(cues),origin=record.get("origin"))
    ai.translate(row,folder,model_modules)
    result=folder/"result.json"
    if not result.is_file() or result.is_symlink():
        raise RuntimeError("translation_result_not_published")
    outcome=json.loads(result.read_text("utf-8"))
    if (outcome.get("state")!="published" or
            outcome.get("jellyfin_id")!=jid):
        raise RuntimeError("translation_result_identity_not_published")
    notice("TRANSLATED",episode=row["episode"],
           cues=outcome.get("cue_count"),
           held_cues=outcome.get("held_count"),
           subtitle_name=outcome.get("subtitle_name"))


def run():
    ensure_source_idle()
    ai,stage,direct,publisher=installed_modules()
    chosen=exact_episode_rows(ai,stage)
    # Same lock used by existing SubHub AI (NOT a second translation lock).
    lock=WORK/".translation.lock"
    if lock.is_symlink():
        raise RuntimeError("unsafe_existing_translation_lock")
    count=Counter()
    held=[]
    with lock.open("a+b") as stream:
        fcntl.flock(stream.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        ensure_source_idle()
        all_staged=publisher.unique_titles(
            [r for r in publisher.stages() if str(r[0]) in chosen],len(EPISODES))
        notice("BEGIN",episodes=list(EPISODES),staged=len(all_staged),
               source_queries=0)
        for jid,row in sorted(chosen.items(),key=lambda item:item[1]["episode"]):
            ep=row["episode"]
            try:
                if validate_prior_source_failure(row,publisher,direct,
                                                 all_staged.get(jid,[])):
                    count["ja_source"]+=1
                else:
                    notice("TRANSLATE_START",episode=ep,
                           model="installed_PLaMo_8B")
                    prepare_and_translate(ai,row)
                    count["translated"]+=1
            except (OSError,RuntimeError,ValueError,KeyError,sqlite3.Error,
                    subprocess.TimeoutExpired) as exc:
                held.append(ep)
                notice("HELD",episode=ep,error=type(exc).__name__,
                       reason=str(exc)[:190])
                if any(x in str(exc) for x in (
                    "THERMAL_ABORT","THERMAL_COOLDOWN_TIMEOUT",
                    "GPU_IN_USE","GPU_OFFLOAD_NOT_ACTIVE",
                    "source_batch_still_running","CPU_THERMAL_SENSOR_MISSING",
                    "model_hash","weight_hash")):
                    notice("STOPPED",reason="model_or_temperature_safety_gate")
                    break
    # Refresh coverage using existing helper only if it is already installed.
    if COVERAGE.is_file() and not COVERAGE.is_symlink():
        proc=subprocess.run(
            [sys.executable,"-B","-u",str(COVERAGE),"init"],
            timeout=240,stdin=subprocess.DEVNULL,check=False)
        notice("QUEUE_REFRESH",exit_code=proc.returncode)
    notice("DONE",ja_source_published=count["ja_source"],
           translated=count["translated"],held=held)
    return 0 if not held else 2


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run",action="store_true")
    args=parser.parse_args()
    if not args.run:
        print("DRY RUN: explicit --run required before touching media.")
        return 0
    try:
        return run()
    except (OSError,RuntimeError,ValueError,sqlite3.Error,
            subprocess.TimeoutExpired) as exc:
        notice("BLOCKED",error=type(exc).__name__,reason=str(exc)[:190])
        return 1


if __name__=="__main__":
    raise SystemExit(main())
