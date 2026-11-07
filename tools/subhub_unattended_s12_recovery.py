#!/usr/bin/env python3
"""Unattended, source-only Japanese subtitle recovery and bounded library cycle.

On the existing OptiPlex: retry the two un-published IASIP S12 tracks using
proven candidate selection/synchronization; stage at most one different saved
candidate per held episode; then run one bounded source-only library cycle.

Never overwrites a media file or any Japanese sidecar. Does NOT start AI.
Use systemd-run --user to make the work survive terminal disconnects.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import time

HOME = Path.home()
SOURCE = HOME / "bruiser-pilot/subhub-control"
DASHBOARD = HOME / ".local/share/bruiser-subhub-dashboard"
SERIES = "It's Always Sunny in Philadelphia"
SEASON = 12
UNIT = "bruiser-subhub-unattended-source.service"
OTHER_UNITS = (
    "bruiser-subhub-season-sources.service",
    "bruiser-ja-source-autofill.service",
    "bruiser-subhub-batch.service",
    "bruiser-subhub-translation-batch.service",
)
SEARCH_LIMIT = 30
STAGE_LIMIT = 70
PUBLISH_LIMIT = 70
MAX_STAGING_ALTERNATES = 2
MAX_SECONDS = 7 * 3600 + 45 * 60
JID = re.compile(r"[a-f0-9]{32}\Z")


def banner(name, **data):
    print("UNATTENDED_" + name, json.dumps(data, ensure_ascii=False,
                                      sort_keys=True), flush=True)


def modules():
    if SOURCE.is_symlink() or not SOURCE.is_dir():
        raise RuntimeError("source_tools_unavailable")
    if str(SOURCE) not in sys.path:
        sys.path.insert(0, str(SOURCE))
    import ja_first_autofill as autofill
    import ja_first_stage_saved_batch as stage
    import ja_first_publish_queue as publisher
    import ja_first_publish_staged as direct
    return autofill, stage, publisher, direct


def check_services():
    for unit in OTHER_UNITS:
        result = subprocess.run(
            ["systemctl", "--user", "show", unit,
             "--property=ActiveState", "--value"],
            text=True, capture_output=True, check=False, timeout=8)
        if result.returncode:
            raise RuntimeError("cannot_verify_service_state:" + unit)
        state = result.stdout.strip()
        if state not in ("inactive", "failed"):
            raise RuntimeError("conflicting_service:" + unit + ":" + state)


def season_inventory(stage):
    manifest = stage.read_inventory()
    matches = {
        str(row.get("jellyfin_id")): row
        for row in manifest.values()
        if (isinstance(row, dict)
            and row.get("kind") == "Episode"
            and row.get("series_title") == SERIES
            and row.get("season") == SEASON
            and type(row.get("episode")) is int
            and 1 <= row["episode"] <= 10)
    }
    episodes = {row["episode"] for row in matches.values()}
    if len(matches) != 10 or episodes != set(range(1, 11)):
        raise RuntimeError("IASIP_S12_identity_inventory_not_exact_ten")
    if any(not JID.fullmatch(jid) for jid in matches):
        raise RuntimeError("IASIP_S12_invalid_jellyfin_id")
    return matches


def held_candidates(stage, publisher, direct, inventory):
    staged = publisher.stages()
    grouped = publisher.unique_titles(
        [r for r in staged if str(r[0]) in inventory], 10
    )
    held = {}
    for jid, candidates in grouped.items():
        row = inventory[jid]
        video = direct.safe_media_path(str(row["host_path"]))
        target = direct.video_target(video)
        if target.is_symlink():
            raise RuntimeError("JA_target_is_symlink")
        if target.is_file():
            # An existing track must be verified by the native publisher.
            # It can recognize byte-proven originals and derived corrections.
            verdict, _, _ = publisher.choose(jid, candidates)
            if not verdict.startswith("published_"):
                raise RuntimeError("unrecognized_preexisting_JA_track")
            publisher.mark_completed(jid)
            banner("ALREADY_PUBLISHED",episode=row["episode"],jid=jid)
            continue
        held[jid] = candidates
    if len(held) > 2:
        raise RuntimeError("more_than_two_S12_staged_holds_recheck_required")
    return held


def retry_publish(publisher, held, inventory):
    pending = {}
    for jid, candidates in sorted(
        held.items(), key=lambda x: inventory[x[0]]["episode"]
    ):
        ep = inventory[jid]["episode"]
        banner("REPAIR_ATTEMPT",episode=ep, candidates=len(candidates))
        try:
            verdict, row, prepared = publisher.choose(jid,candidates)
            if verdict.startswith("ready_"):
                publisher.publish_selected(jid,verdict,prepared)
                publisher.mark_completed(jid)
                banner("REPAIR_PUBLISHED",episode=ep,method=verdict)
            elif verdict.startswith("published_"):
                publisher.mark_completed(jid)
                banner("REPAIR_ALREADY_PRESENT",episode=ep,method=verdict)
            else:
                pending[jid] = candidates
                banner("REPAIR_HELD",episode=ep,reason="native_not_ready")
        except (OSError,RuntimeError,ValueError,KeyError,sqlite3.Error,
                subprocess.TimeoutExpired) as exc:
            pending[jid] = candidates
            banner("REPAIR_HELD",episode=ep,error=type(exc).__name__,
                   reason=str(exc)[:250])
    return pending


def alternative_stage(stage, inventory, pending):
    """Try a *different* previously discovered provider candidate at most once
    per held episode. Never re-search or select an unverified identity."""
    if not pending:
        return 0,False
    saved = {str(jid):body for jid,body in stage.read_saved_searches()}
    existing = stage.read_staged()
    staged_new = 0
    limited = False
    with stage.stage_db() as db:
        for jid in sorted(pending,key=lambda k:inventory[k]["episode"]):
            row = inventory[jid]
            if row.get("status") != "ready_ja_search":
                banner("ALTERNATE_HELD",episode=row["episode"],
                       reason="source_inventory_not_search_ready")
                continue
            try:
                obj=json.loads(saved[jid])
                candidates=obj.get("candidates") or []
            except (KeyError,TypeError,ValueError):
                candidates=[]
            options = [
                candidate for candidate in candidates
                if isinstance(candidate,dict)
                and stage.identity_ok(row,candidate)
                and (jid,str(candidate.get("subtitle_id"))) not in existing
            ]
            options.sort(key=lambda c:(-int(c.get("score") or 0),
                                       str(c.get("subtitle_id"))))
            if not options:
                banner("ALTERNATE_UNAVAILABLE",episode=row["episode"])
                continue
            candidate=options[0]
            label=f"IASIP S{SEASON:02d}E{row['episode']:02d}"
            banner("ALTERNATE_ATTEMPT",episode=row["episode"])
            try:
                stage.run_one({"row":row,"candidate":candidate,
                               "label":label},db)
                staged_new+=1
            except (OSError,RuntimeError,ValueError,sqlite3.Error,
                    subprocess.TimeoutExpired) as exc:
                detail=str(exc)
                banner("ALTERNATE_HELD",episode=row["episode"],
                       reason=detail[:180])
                if any(t in detail.casefold() for t in (
                    "quota","ratelimit","rate_limit","httperror",
                    "429","406","download_limit","download limit")):
                    limited=True
                    banner("PROVIDER_LIMIT",reason="alternate_download_refused")
                    break
            if staged_new>=MAX_STAGING_ALTERNATES:
                break
    return staged_new,limited


def reconcile():
    helper=DASHBOARD/"bruiser_coverage_queue.py"
    if helper.is_file() and not helper.is_symlink():
        result=subprocess.run(
            [sys.executable,"-B","-u",str(helper),"init"],
            stdin=subprocess.DEVNULL,timeout=240,check=False)
        banner("QUEUE_RECONCILED",exit_code=result.returncode)
        if result.returncode:
            raise RuntimeError("coverage_queue_reconciliation_failed")
    else:
        banner("QUEUE_HELD",reason="installed_coverage_queue_helper_missing")


def broad_source_only():
    """One bounded library-wide cycle; the parent holds the daily source lock.

    The existing controller handles provider history, timing gates, staged-only
    recovery, and create-only publication; no translation model is launched.
    """
    exe=SOURCE/"ja_first_cycle.py"
    if not exe.is_file() or exe.is_symlink():
        raise RuntimeError("existing_source_cycle_not_installed")
    command=[sys.executable,"-B","-u",str(exe),"cycle",
             "--sources-only","--apply",
             "--search-budget",str(SEARCH_LIMIT),
             "--stage-budget",str(STAGE_LIMIT),
             "--publish-limit",str(PUBLISH_LIMIT)]
    banner("BACKLOG_STARTED",search_limit=SEARCH_LIMIT,
           download_limit=STAGE_LIMIT,publish_limit=PUBLISH_LIMIT,
           model="not_started")
    result=subprocess.run(command,stdin=subprocess.DEVNULL,
                          timeout=MAX_SECONDS,check=False)
    banner("BACKLOG_FINISHED",exit_code=result.returncode)
    if result.returncode:
        raise RuntimeError("bounded_source_cycle_failed")
    return 0


def run():
    autofill,stage,publisher,direct=modules()
    check_services()
    # This is the *same* non-blocking flock as daily source automation.
    fd=autofill.lock()
    try:
        autofill.ensure_installed()
        settings=autofill.config()
        autofill.safe_source_settings(settings)
        if not autofill.native_search_disabled(settings):
            raise RuntimeError("duplicate_native_provider_search_enabled")
        autofill.check_scheduler_idle()
        autofill.refresh_manifest()
        inventory=season_inventory(stage)
        held=held_candidates(stage,publisher,direct,inventory)
        banner("BEGIN",season=12,staged_unpublished=len(held),
               source_only=True)
        pending=retry_publish(publisher,held,inventory)
        new,quota_stop=alternative_stage(stage,inventory,pending)
        if new:
            records=publisher.stages()
            grouped=publisher.unique_titles(
                [r for r in records if str(r[0]) in pending],2)
            pending=retry_publish(publisher,grouped,inventory)
        reconcile()
        banner("S12_REPAIR_SUMMARY",attempted=len(held),
               published=len(held)-len(pending),held=len(pending),
               unresolved_episodes=sorted(
                   inventory[jid]["episode"] for jid in pending))
        if quota_stop:
            banner("BACKLOG_SKIPPED",reason="provider_limit_detected")
        else:
            broad_source_only()
        reconcile()
        banner("DONE",unresolved_S12=sorted(
            inventory[jid]["episode"] for jid in pending),
            next_step="review_held_then_translate_if_source_exhausted")
    finally:
        os.close(fd)
    return 0


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run",action="store_true")
    args=parser.parse_args(argv)
    if not args.run:
        print("DRY RUN: only --run starts the guarded unattended source cycle.")
        return 0
    return run()


if __name__=="__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError,ValueError,OSError,KeyError,sqlite3.Error,
            subprocess.TimeoutExpired) as exc:
        banner("BLOCKED",error=type(exc).__name__,reason=str(exc)[:200])
        raise SystemExit(1)
