#!/usr/bin/env python3
"""Plan or start one bounded source-first pass for unstaged missing JA episodes.

Read-only by default. --start explicitly reuses the installed dashboard's
owner source launcher, with its worker lock, quota handling and progress receipt.
This never starts translation, replaces source media, or erases prior subtitles.
"""
from __future__ import annotations
import argparse
from collections import Counter
import json
from pathlib import Path
import sqlite3
import sys

HOST = Path.home() / "bruiser-pilot/subhub-control"
MODULES = HOST if (HOST / "ja_first_stage_saved_batch.py").is_file() else Path(__file__).resolve().parent
if str(MODULES) not in sys.path:
    sys.path.insert(0,str(MODULES))
import benchmark_subtitle_search_paths as benchmark
import ja_first_stage_saved_batch as staging

ROOT = Path.home() / "bruiser-pilot/ja-first-inventory"

def read_db(filename, query):
    path = ROOT / filename
    staging.private_file(path)
    with sqlite3.connect("file:"+str(path.resolve())+"?mode=ro",
                         uri=True,timeout=15) as db:
        return db.execute(query).fetchall()

def prepare(rows, staged_ids, series, sidecar_checker=staging.japanese_sidecar_exists):
    """Only exact-library media with no installed JA and no saved stage."""
    unstaged, already_staged, existing = [], [], []
    for row in rows:
        if not isinstance(row,dict) or row.get("kind") != "Episode" or row.get("series_title") != series:
            continue
        if row.get("status") != "ready_ja_search":
            continue
        video = Path(str(row.get("host_path") or ""))
        if not video.is_file() or video.is_symlink():
            # Never blindly source against missing or swapped physical video.
            continue
        if sidecar_checker(video):
            existing.append(row)
        elif str(row.get("jellyfin_id")) in staged_ids:
            already_staged.append(row)
        else:
            unstaged.append(row)
    order=lambda r:(int(r.get("season") or 0),int(r.get("episode") or 0))
    return sorted(unstaged,key=order),sorted(already_staged,key=order),existing

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--series",required=True)
    ap.add_argument("--start",action="store_true",
                    help="explicitly launch only the unstaged missing items through existing dashboard")
    args=ap.parse_args()
    if not 1<=len(args.series)<=160:
        ap.error("series name must be 1..160 characters")
    rows=benchmark.load_latest_manifest()
    stages=read_db("japanese-stage.sqlite3",
                   "SELECT DISTINCT jellyfin_id FROM staged WHERE status IN ('staged','published')")
    staged_ids={str(x[0]) for x in stages}
    searches=read_db("japanese-search.sqlite3",
                     "SELECT jellyfin_id,outcome,results_json FROM searches")
    history={str(jid):(str(outcome),raw) for jid,outcome,raw in searches}
    unstaged,already_staged,existing=prepare(rows,staged_ids,args.series)
    print("=== SOURCE-FIRST UNSTAGED JAPANESE RECOVERY ===",flush=True)
    print("SERIES:",args.series,flush=True)
    print("MISSING_WITH_SAVED_JA_STAGE:",len(already_staged),flush=True)
    print("ALREADY_PUBLISHED_BUT_STALE_MANIFEST:",len(existing),flush=True)
    print("MISSING_WITH_NO_JA_STAGE:",len(unstaged),flush=True)
    for row in unstaged:
        jid=str(row["jellyfin_id"])
        outcome,raw=history.get(jid,("never_searched","{}"))
        try:
            detail=json.loads(raw or "{}")
        except (ValueError,TypeError):
            detail={}
        tags=",".join(str(x) for x in detail.get("incomplete_providers") or [])
        print(f'S{row["season"]:02d}E{row["episode"]:02d} '
              f'| prior={outcome} | saved={len(detail.get("candidates") or [])} '
              f'| rejected={len(detail.get("rejected_candidates") or [])} '
              f'| provider_hits={detail.get("provider_total","?")} '
              f'| incomplete={tags or "-"}',
              flush=True)
    if not args.start:
        print("READ ONLY: No source worker launched. Pass --start for a real bounded job.",
              flush=True)
        return
    if not unstaged:
        print("NO UNSTAGED SOURCE ITEMS: nothing launched.",flush=True)
        return
    # Use the EXISTING dashboard launcher, preserving real Active Work status,
    # provider rate caps, and one selector-scoped receipt. No bespoke worker.
    DASH = Path.home() / ".local/share/bruiser-subhub-dashboard"
    if str(DASH) not in sys.path:
        sys.path.insert(0,str(DASH))
    import subhub_dashboard_server as dashboard
    doc={"series":args.series,
         "picks":[{"season":r["season"],"episode":r["episode"]}
                  for r in unstaged]}
    result=dashboard.start_jellyfin_source(doc)
    print("SOURCE JOB ACCEPTED:",json.dumps(result,sort_keys=True),flush=True)

if __name__=="__main__":
    main()
