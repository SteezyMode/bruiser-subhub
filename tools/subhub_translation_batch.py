#!/usr/bin/env python3
"""Season-ordered, source-first SubHub batch selection using the existing queue.

No second task database, model implementation, or permanent worker. A selected
episode is handed to the installed, checkpointed "subhub-ai" one at a time.
A preview is read-only and shows blocked episodes rather than substituting
unrelated media to reach a requested count.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys

HOME = Path.home()
DB = HOME / "bruiser-pilot/coverage-queue/coverage.sqlite3"
WORK = HOME / "bruiser-pilot/subhub-translation"
ENGINE = HOME / ".local/bin/subhub-ai"
JELLYFIN_ID = re.compile(r"[0-9a-f]{32}\Z")
READY_ACTION = "validate_english_for_ja_fallback"
MAX_COUNT = 40


def read_queue(path=None):
    path = Path(path or DB)
    if (not path.is_file() or path.is_symlink() or
            path.stat().st_uid != os.getuid() or
            path.stat().st_mode & 0o077):
        raise RuntimeError("private_coverage_queue_unavailable")
    connection = sqlite3.connect(
        "file:" + str(path.resolve()) + "?mode=ro", uri=True, timeout=5)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    return connection


def validate(series, season, count, start):
    if (not isinstance(series, str) or not series.strip() or
            len(series) > 160 or any(ord(ch) < 32 for ch in series)):
        raise ValueError("invalid_series")
    if type(season) is not int or not 1 <= season <= 60:
        raise ValueError("invalid_season")
    if type(count) is not int or not 1 <= count <= MAX_COUNT:
        raise ValueError("invalid_episode_count")
    if type(start) is not int or not 1 <= start <= 999:
        raise ValueError("invalid_start_episode")


def catalog(path=None):
    with read_queue(path) as db:
        rows = db.execute("""
            SELECT series,season FROM media
            WHERE kind='Episode' AND TRIM(series)<>'' GROUP BY series,season
            ORDER BY series COLLATE NOCASE,season
        """).fetchall()
    result = {}
    for row in rows:
        try:
            season = int(row["season"])
        except (ValueError, TypeError):
            continue
        if 1 <= season <= 60:
            result.setdefault(row["series"], set()).add(season)
    return [{"series": s, "seasons": sorted(seasons)}
            for s, seasons in sorted(result.items(), key=lambda a: a[0].casefold())]


def _already_covered(row):
    if row["ja_present"]:
        return True
    # The matrix refresh may lag a successfully published PLaMo sidecar.
    # This is only a skip hint; the underlying engine checks ALL JA sources.
    video = Path(str(row["path"] or ""))
    target = video.with_name(video.stem + ".ja.PLaMo8B.srt")
    return (target.is_file() and not target.is_symlink()
            and 0 < target.stat().st_size <= 2_000_000)


def plan(series, season, count=20, start=1, *, path=None):
    validate(series, season, count, start)
    with read_queue(path) as db:
        rows = db.execute("""
            SELECT m.path,m.jellyfin_id,m.title,m.series,m.season,m.episode,
                   m.en_text,m.ja_present,t.action,t.state
            FROM media AS m LEFT JOIN tasks AS t
              ON t.path=m.path AND t.target='ja' AND t.active=1
            WHERE m.kind='Episode' AND m.series=? AND m.season=?
            ORDER BY m.path
        """, (series, str(season))).fetchall()
    episodes = {}
    for row in rows:
        try:
            ep = int(row["episode"])
        except (ValueError, TypeError):
            continue
        if start <= ep <= 999:
            episodes.setdefault(ep, []).append(dict(row))
    items = []
    skipped_covered = 0
    for ep in sorted(episodes):
        versions = episodes[ep]
        if any(_already_covered(row) for row in versions):
            skipped_covered += 1
            continue
        if len(versions) != 1:
            item = {"episode": ep, "title": versions[0]["title"],
                    "status": "blocked", "reason": "duplicate_episode_versions"}
        else:
            row = versions[0]
            if (row["action"] == READY_ACTION and row["state"] == "pending"
                    and row["en_text"] and
                    JELLYFIN_ID.fullmatch(str(row["jellyfin_id"] or ""))):
                status, reason = "ready", "verified_english_required_at_runtime"
            else:
                status = "blocked"
                if not row["en_text"]:
                    reason = "english_text_not_ready"
                elif row["action"] in ("search_ja", "download_saved_ja",
                                       "align_existing_staged_ja", "review_saved_ja"):
                    reason = "japanese_source_first"
                else:
                    reason = "not_ready_" + str(row["action"] or "unplanned")[:45]
            item = {"episode": ep, "title": row["title"],
                    "status": status, "reason": reason}
            if status == "ready":
                item["jellyfin_id"] = row["jellyfin_id"]
        items.append(item)
        if len(items) == count:
            break
    ready = sum(x["status"] == "ready" for x in items)
    return {"series": series, "season": season, "start_episode": start,
            "requested": count, "ready": ready, "blocked": len(items)-ready,
            "covered": skipped_covered, "selected": len(items),
            "items": items,
            "note": ("The first missing episodes in season order. Blocked episodes "
                     "are reported, never silently replaced with other seasons.")}


def _safe_work_dir():
    if WORK.is_symlink():
        raise RuntimeError("unsafe_translation_workdir")
    WORK.mkdir(parents=True, exist_ok=True, mode=0o700)
    if (WORK.stat().st_uid != os.getuid() or WORK.stat().st_mode & 0o077):
        raise RuntimeError("translation_workdir_not_private")
    return WORK


def run_batch(series, season, count, start):
    if not ENGINE.is_file() or ENGINE.is_symlink() or not os.access(ENGINE, os.X_OK):
        raise RuntimeError("subhub_ai_not_installed")
    root = _safe_work_dir()
    lock = root / ".series-batch.lock"
    if lock.is_symlink():
        raise RuntimeError("unsafe_series_batch_lock")
    with lock.open("a+b") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        selected = plan(series, season, count, start)
        print("BATCH_BEGIN " + json.dumps({
            k: v for k, v in selected.items() if k not in ("items", "note")},
            ensure_ascii=False), flush=True)
        completed = failed = 0
        for item in selected["items"]:
            tag = f'S{season:02d}E{item["episode"]:02d}'
            if item["status"] != "ready":
                print(f'BATCH_BLOCKED {tag} {item["reason"]}', flush=True)
                continue
            print(f'BATCH_ITEM {tag} {item["title"][:120]}', flush=True)
            command = [str(ENGINE), "--apply", "--jellyfin-id",
                       item["jellyfin_id"]]
            # Existing worker owns the cue checkpoints, thermal safety,
            # English verification, and create-only subtitle publication.
            fatal = False
            with subprocess.Popen(
                    command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT, text=True, bufsize=1) as child:
                for line in child.stdout:
                    print(line, end="", flush=True)
                    if any(marker in line for marker in (
                            "THERMAL_ABORT", "THERMAL_COOLDOWN_TIMEOUT",
                            "GPU_OFFLOAD_NOT_ACTIVE", "GPU_IN_USE",
                            "source_batch_still_running",
                            "CPU_THERMAL_SENSOR_MISSING")):
                        fatal = True
                code = child.wait()
            if code:
                failed += 1
                print(f"BATCH_ITEM_HELD {tag} exit={code}", flush=True)
                if fatal:
                    print("BATCH_STOPPED safety_gate_or_source_conflict", flush=True)
                    return 1
            else:
                completed += 1
                print(f"BATCH_ITEM_OK {tag}", flush=True)
        print(f"BATCH_DONE published={completed} held={failed} "
              f"blocked={selected['blocked']}", flush=True)
        return 1 if failed else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--series", required=True)
    ap.add_argument("--season", type=int, required=True)
    ap.add_argument("--count", type=int, default=20)
    ap.add_argument("--start", type=int, default=1)
    ap.add_argument("--run", action="store_true",
                    help="Run eligible selected episodes via existing subhub-ai")
    args = ap.parse_args(argv)
    try:
        if args.run:
            return run_batch(args.series, args.season, args.count, args.start)
        print(json.dumps(plan(args.series,args.season,args.count,args.start),
                         ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
        print("BATCH_HELD " + type(exc).__name__ + " " + str(exc)[:180],
              file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
