#!/usr/bin/env python3
"""Season-scoped JA source-first pass using the existing SubHub workers.

The only automatic work is Japanese-provider discovery, high-confidence
staging, verified create-only JA publication, and queue reconciliation.
No English ASR, AI inference, torrent actions, directory creation in media,
or media replacement. A single transient systemd unit owns each run.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time

try:
    from . import subhub_translation_batch as batch
except ImportError:
    import subhub_translation_batch as batch

SOURCE_CODE = Path.home() / "bruiser-pilot/subhub-control"
SOURCE_UNIT = "bruiser-subhub-season-sources.service"
SOURCE_ACTIONS = frozenset({
    "search_ja", "download_saved_ja", "align_existing_staged_ja"
})
MAX_EPISODES = 40


def scope(series, season, *, path=None):
    """Existing private coverage queue is the authoritative season identity."""
    batch.validate(series, season, MAX_EPISODES, 1)
    with batch.read_queue(path) as db:
        rows = db.execute("""
            SELECT m.path,m.jellyfin_id,m.title,m.episode,m.ja_present,
                   t.action,t.state
              FROM media AS m LEFT JOIN tasks AS t
                ON t.path=m.path AND t.target='ja' AND t.active=1
             WHERE m.kind='Episode' AND m.series=? AND m.season=?
        """, (series, str(season))).fetchall()
    episodes = defaultdict(list)
    for item in rows:
        try:
            ep = int(item["episode"])
        except (TypeError, ValueError):
            continue
        if 1 <= ep <= 999:
            episodes[ep].append(item)
    selected = {}
    held = Counter()
    for ep in sorted(episodes):
        versions = episodes[ep]
        if any(batch._already_covered(row) for row in versions):
            held["already_covered"] += 1
            continue
        if len(versions) != 1:
            held["duplicate_episode"] += 1
            continue
        row = versions[0]
        if row["state"] != "pending" or row["action"] not in SOURCE_ACTIONS:
            held["not_source_ready"] += 1
            continue
        jid = str(row["jellyfin_id"] or "")
        if not batch.JELLYFIN_ID.fullmatch(jid) or jid in selected:
            held["invalid_identity"] += 1
            continue
        selected[jid] = str(row["path"])
        if len(selected) > MAX_EPISODES:
            raise RuntimeError("season_exceeds_safe_episode_limit")
    return {"series": series, "season": season, "ids": selected,
            "eligible": len(selected), "skipped": dict(held)}


def native():
    """Import existing installed search/stage/publish components, unchanged."""
    path = SOURCE_CODE
    expected = (
        "ja_first_autofill.py", "ja_first_search_pilot.py",
        "ja_first_stage_saved_batch.py", "ja_first_publish_queue.py",
        "ja_first_priority.py", "ja_first_catalog_manifest.py"
    )
    if not path.is_dir() or path.is_symlink() or any(
        not (path / name).is_file() or (path / name).is_symlink()
        for name in expected
    ):
        raise RuntimeError("existing_source_controller_not_installed")
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
    import ja_first_autofill as autofill
    import ja_first_search_pilot as search
    import ja_first_stage_saved_batch as stage
    import ja_first_publish_queue as publish
    return autofill, search, stage, publish


def find_japanese(ids, search, budget):
    """Existing Sublarr provider endpoint and existing result classification.

    The ordinary source script does not yet offer season filtering; select the
    exact approved IDs in memory, but reuse its eligibility, scoring, history
    and native Sublarr API worker without changing its installed behavior.
    """
    paths = sorted(search.ROOT.glob("ja-intake-*.json"))
    if not paths:
        raise RuntimeError("source_manifest_unavailable")
    manifest = search.private_manifest(paths[-1])
    rows = [row for row in manifest["items"]
            if isinstance(row, dict) and str(row.get("jellyfin_id")) in ids
            and row.get("host_path") == ids[str(row.get("jellyfin_id"))]]
    counts = Counter()
    with closing(search.open_db()) as db:
        jobs = search.pick(rows, db, budget)
        print("SEASON_JA_SEARCH_PLANNED",len(jobs),flush=True)
        for idx, job in enumerate(jobs, 1):
            row = job["row"]
            label = str(row.get("series_title") or "") + (
                f' S{row["season"]:02d}E{row["episode"]:02d}')
            print("SEASON_JA_SEARCH",idx,len(jobs),label,flush=True)
            search.save_attempt(db, job, "in_progress")
            try:
                run = subprocess.run(
                    ["docker", "exec", "-i", "-e", "PYTHONPATH=/app",
                     "sublarr-pilot", "python3", "-c", search.CONTAINER_WORKER],
                    input=json.dumps([{"id":job["id"],"query":job["query"]}]),
                    capture_output=True, text=True, timeout=110, check=False)
                if run.returncode:
                    raise RuntimeError("native_container_search_failed")
                messages = [json.loads(line) for line in run.stdout.splitlines()
                            if line.startswith("{")]
                result = next((x for x in messages
                               if str(x.get("id")) == job["id"]), None)
                if not result or not result.get("ok"):
                    raise RuntimeError("native_provider_search_failed")
                options = result.get("results") or []
                rated = [(grade,r) for r in options if isinstance(r,dict)
                         for grade in [search.candidate_grade(row,r)]
                         if grade != "reject"]
                plausible = sum(grade == "plausible" for grade,_ in rated)
                review = sum(grade == "review" for grade,_ in rated)
                status = "plausible" if plausible else (
                    "review" if review else "none")
                search.save_attempt(db,job,status,result.get("total"),rated)
                counts[status] += 1
                print("SEASON_JA_RESULT",label,status,
                      "plausible",plausible,"review",review,flush=True)
            except (OSError,RuntimeError,ValueError,subprocess.TimeoutExpired) as exc:
                search.save_attempt(db,job,"error")
                counts["error"] += 1
                print("SEASON_JA_HELD",label,type(exc).__name__,flush=True)
            if idx < len(jobs):
                time.sleep(3.2)  # Keep Sublarr's existing 20 searches/minute pace.
    return counts


def stage_japanese(ids, stage, budget):
    inventory = {jid:row for jid,row in stage.read_inventory().items()
                 if jid in ids and row.get("host_path") == ids[jid]}
    saved = [row for row in stage.read_saved_searches()
             if str(row[0]) in inventory]
    chosen = stage.choices(inventory,saved,stage.read_staged(),budget,"episode")
    counts = Counter()
    print("SEASON_JA_STAGE_PLANNED",len(chosen),flush=True)
    if not chosen:
        return counts
    with closing(stage.stage_db()) as db:
        for idx,job in enumerate(chosen,1):
            print("SEASON_JA_STAGE",idx,len(chosen),job["label"],flush=True)
            try:
                result = stage.run_one(job,db)
                counts[result] += 1
            except (OSError,RuntimeError,ValueError,subprocess.TimeoutExpired) as exc:
                counts["held"] += 1
                detail = str(exc).lower()
                print("SEASON_JA_HELD",job["label"],type(exc).__name__,
                      str(exc)[:100],flush=True)
                if any(word in detail for word in (
                    "quota","rate_limit","ratelimit","cooling",
                    "exhausted","download_limit","download limit",
                    "allowed subtitles","429","406"
                )):
                    counts["provider_limited"] += 1
                    print("PROVIDER_LIMIT_REACHED",flush=True)
                    break
    return counts


def publish_japanese(ids, publish, limit):
    # The established publisher enforces timing identity and never overwrites.
    rows = [row for row in publish.stages() if str(row[0]) in ids]
    grouped = publish.unique_titles(rows,MAX_EPISODES)
    counts = Counter()
    print("SEASON_JA_PUBLISH_PLANNED",len(grouped),flush=True)
    for jid,candidates in grouped.items():
        if counts["published_new"] >= limit:
            break
        print("SEASON_JA_PUBLISH",jid,flush=True)
        try:
            kind,row,chosen = publish.choose(jid,candidates)
            if kind.startswith("published_"):
                publish.mark_completed(jid)
                counts["already_published"] += 1
            elif kind.startswith("ready_"):
                publish.publish_selected(jid,kind,chosen)
                publish.mark_completed(jid)
                counts["published_new"] += 1
            else:
                counts["held"] += 1
        except (OSError,RuntimeError,ValueError,KeyError,sqlite3.Error) as exc:
            counts["held"] += 1
            print("SEASON_JA_HELD",jid,type(exc).__name__,
                  str(exc)[:100],flush=True)
    return counts


def reconcile():
    try:
        from . import bruiser_coverage_queue as coverage
    except ImportError:
        import bruiser_coverage_queue as coverage
    return coverage.main(["init"])


def run(series,season):
    selection = scope(series,season)
    ids = selection["ids"]
    print("SEASON_JA_BEGIN",json.dumps({
        "series":series,"season":season,"eligible":len(ids),
        "skipped":selection["skipped"]},ensure_ascii=False),flush=True)
    if not ids:
        print("SEASON_JA_DONE no_eligible_source_tasks",flush=True)
        return 0
    autofill,search,stage,publish = native()
    fd = autofill.lock()  # same inter-process lock as the daily source worker
    try:
        autofill.ensure_installed()
        settings = autofill.config()
        autofill.safe_source_settings(settings)
        if not autofill.native_search_disabled(settings):
            raise RuntimeError("native_provider_search_still_active")
        autofill.check_scheduler_idle()
        autofill.refresh_manifest()
        # Recheck scope after obtaining the shared source lock.
        current=scope(series,season)
        if current["ids"] != ids:
            raise RuntimeError("source_scope_changed_repreview_required")
        budget=min(MAX_EPISODES,len(ids))
        searched=find_japanese(ids,search,budget)
        staged=stage_japanese(ids,stage,budget)
        published=publish_japanese(ids,publish,budget)
        # Re-plan from the existing inventory after new provider evidence.
        # This transitions 'search_ja' -> fallback ONLY after a real no-match.
        reconcile()
        print("SEASON_JA_DONE",json.dumps({
            "searched":dict(searched),"staged":dict(staged),
            "published":dict(published)
        },sort_keys=True),flush=True)
    finally:
        os.close(fd)
    return 0


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--series",required=True)
    parser.add_argument("--season",type=int,required=True)
    parser.add_argument("--run",action="store_true")
    args=parser.parse_args(argv)
    if args.run:
        return run(args.series,args.season)
    result=scope(args.series,args.season)
    print(json.dumps({k:v for k,v in result.items() if k!="ids"},
                     ensure_ascii=False))
    return 0


if __name__=="__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError,ValueError,OSError,sqlite3.Error) as exc:
        print("SEASON_JA_BLOCKED",type(exc).__name__,str(exc)[:140],
              file=sys.stderr,flush=True)
        raise SystemExit(1)
