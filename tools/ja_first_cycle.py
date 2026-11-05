#!/usr/bin/env python3
"""Bruiser SubHub: one operator command for a Japanese-first library cycle.

No new translator, provider integration, user database, or background service.

  status                 Show existing Japanese/English workflow state (read-only).
  cycle --apply          Bounded sequential provider search -> staging -> JA
                         publication -> English/Gemma handoff. NO GPU start.
  start-worker --apply   Start/resume exactly one pending subtitle-tuned E4B job.
  start-worker --apply --watch   Start and show live progress in this terminal.
  watch                  Attach read-only tracker to currently running job.
  --self-test            Verify wiring and offline contracts, no mutations.

Every dangerous action requires --apply and is bounded. Errors halt the
cycle without erasing results from already completed steps.

Install all companion tools from the SAME pinned repo commit together.
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
from urllib.parse import quote

ROOT = Path.home() / "bruiser-pilot/ja-first-inventory"
EN_ROOT = Path.home() / "bruiser-pilot/english-source-inventory"
JA_ROOT = Path.home() / "bruiser-pilot/subhub1-state"
FILES = {
    "ja_first_search_pilot.py",
    "ja_first_stage_saved_batch.py",
    "ja_first_stage_timing_audit.py",
    "ja_first_publish_staged.py",
    "ja_first_publish_shifted.py",
    "ja_first_publish_queue.py",
    "ja_first_ffsubsync.py",
    "bruiser_ja_movie_rescue.py",
    "ja_first_gemma_fallback.py",
    "daily_japanese.py",
    "daily_worker.py",
    "subtitle_publish_gate.py",
    "subtitle_quality_010.py",
    "subtitle_tuned_production.py",
    "subhub_live_tracker.py",
}
STEPS = (
    ("DISCOVERY", "ja_first_search_pilot.py", ("--budget", "8")),
    ("JAPANESE STAGING", "ja_first_stage_saved_batch.py",
     ("--budget", "2", "--apply")),
    ("JA VERIFIED PUBLICATION", "ja_first_publish_queue.py",
     ("--limit", "2", "--max-titles", "10", "--apply")),
    ("GEMMA FALLBACK HANDOFF", "ja_first_gemma_fallback.py",
     ("--probe-budget", "8", "--queue-one")),
)


def required_code(folder):
    missing = sorted(name for name in FILES
                     if (not (folder / name).is_file()
                         or (folder / name).is_symlink()))
    if missing:
        raise RuntimeError("Missing companion tools: " + ", ".join(missing))
    worker = (folder / "daily_worker.py").read_text(encoding="utf-8")
    model = (folder / "subtitle_tuned_production.py").read_text(encoding="utf-8")
    if "import subtitle_tuned_production as tuned" not in worker:
        raise RuntimeError("Unsafe legacy daily worker: missing subtitle-tuned E4B hook")
    if 'MODEL_ID_PREFIX = "9ccfc3b07081"' not in model:
        raise RuntimeError("Subtitle model pin changed; refusing legacy downgrade")


def ro_uri(path):
    """Read the existing database without changing its permissions.

    Japanese-first state is required to be private. The earlier SubHub 1.0
    queue and English inventory predate that rule and may be 0644/0664.
    Permit reading those *owned legacy files* for status only; flag their
    permissions rather than chmodding or blocking the entire controller.
    Native job launch retains its independent checks and locks.
    """
    import stat
    if path.is_symlink() or not path.is_file():
        raise RuntimeError("missing_or_unsafe_database")
    mode = path.stat()
    if not stat.S_ISREG(mode.st_mode) or mode.st_uid != os.getuid():
        raise RuntimeError("database_not_regular_or_owned_by_current_user")
    legacy = path in {JA_ROOT / "jobs.sqlite3", EN_ROOT / "catalog.sqlite3"}
    if mode.st_mode & 0o002:
        raise RuntimeError("database_world_writable")
    if mode.st_mode & 0o077:
        if not legacy:
            raise RuntimeError("japanese_first_database_not_private")
        print("STATUS WARNING:", path.name,
              "uses existing legacy database permissions; unchanged",
              flush=True)
    return "file:" + quote(str(path.resolve()), safe="/") + "?mode=ro"


def count_table(path, query):
    if not path.exists():
        return {}
    with sqlite3.connect(ro_uri(path), uri=True, timeout=6) as conn:
        return {str(k): int(v) for k, v in conn.execute(query)}


def status():
    print("=== BRUISER SUBHUB STATUS ===", flush=True)
    manifests = sorted(ROOT.glob("ja-intake-*.json")) if ROOT.is_dir() else []
    if manifests:
        manifest = manifests[-1]
        if manifest.is_symlink() or manifest.stat().st_mode & 0o077:
            raise RuntimeError("unsafe_current_inventory_manifest")
        blob = json.loads(manifest.read_text("utf-8"))
        counts = Counter(str(r.get("status") or "unknown")
                         for r in blob.get("items", []) if isinstance(r, dict))
        print("CATALOG:", len(blob.get("items", [])), "items",
              "| ready for Japanese search:", counts["ready_ja_search"],
              "| manifest:", manifest.name, flush=True)
    else:
        print("CATALOG: not yet available", flush=True)
    for title, path, query in (
        ("JAPANESE SEARCH HISTORY", ROOT / "japanese-search.sqlite3",
         "SELECT outcome,COUNT(*) FROM searches GROUP BY outcome"),
        ("JAPANESE STAGING", ROOT / "japanese-stage.sqlite3",
         "SELECT status,COUNT(*) FROM staged GROUP BY status"),
        ("GEMMA JOB QUEUE", JA_ROOT / "jobs.sqlite3",
         "SELECT status,COUNT(*) FROM jobs GROUP BY status"),
    ):
        try:
            counts = count_table(path, query)
            print(title + ":", json.dumps(counts, sort_keys=True), flush=True)
        except (RuntimeError, OSError, sqlite3.Error) as exc:
            print(title + ": unavailable (" + type(exc).__name__ + ")", flush=True)
    if (JA_ROOT / "jobs.sqlite3").exists():
        try:
            with sqlite3.connect(ro_uri(JA_ROOT / "jobs.sqlite3"),
                                 uri=True, timeout=6) as conn:
                jobs = conn.execute(
                    """SELECT j.id, j.status, j.source_cues,
                              COUNT(c.cue_id) AS saved_cues,
                              SUM(CASE WHEN c.japanese IS NOT NULL
                                            AND TRIM(c.japanese) != ''
                                       THEN 1 ELSE 0 END) AS translated,
                              SUM(CASE WHEN c.japanese IS NULL
                                            AND c.failed >= 5
                                       THEN 1 ELSE 0 END) AS held
                       FROM jobs j LEFT JOIN cues c ON c.job_id = j.id
                       WHERE j.id LIKE 'daily-%'
                         AND j.status IN ('queued','translating',
                                          'translated','needs_review')
                       GROUP BY j.id
                       ORDER BY j.created ASC, j.id LIMIT 10"""
                ).fetchall()
            for jid, state, cues, saved, completed, held in jobs:
                denominator = max(int(cues or 0), 1)
                percent = round(100.0 * int(completed or 0) / denominator, 1)
                print("GEMMA PROGRESS:", jid, "|", state, "|",
                      str(completed or 0) + "/" + str(cues),
                      "cues |", str(percent) + "%",
                      "| held cues:", held or 0, flush=True)
                if int(saved or 0) != int(cues or 0):
                    print("  WARNING: checkpoint cue count differs from job source count",
                          flush=True)
        except (RuntimeError, OSError, sqlite3.Error) as exc:
            print("PENDING GEMMA: status unavailable (",
                  type(exc).__name__, ")", flush=True)
    if (EN_ROOT / "catalog.sqlite3").exists():
        try:
            english_counts = count_table(
                EN_ROOT / "catalog.sqlite3",
                "SELECT state,COUNT(*) FROM media GROUP BY state")
            print("ENGLISH SOURCE INVENTORY:",
                  json.dumps(english_counts, sort_keys=True), flush=True)
        except (RuntimeError, OSError, sqlite3.Error) as exc:
            print("ENGLISH SOURCE INVENTORY: status unavailable (",
                  type(exc).__name__, ")", flush=True)
    log = JA_ROOT / "daily-worker.log"
    if log.is_file() and not log.is_symlink():
        print("EXISTING WORKER LOG:", str(log), flush=True)
    print("Status only: no provider calls, model jobs or file modifications.",
          flush=True)


def run_step(folder, name, file, args):
    path = folder / file
    print("\n=== " + name + " ===", flush=True)
    result = subprocess.run(
        [sys.executable, "-u", str(path), *args],
        stdin=subprocess.DEVNULL,
        timeout=1800,
    )
    if result.returncode:
        raise RuntimeError(name.lower().replace(" ", "_") +
                           "_failed_rc_" + str(result.returncode))


def cycle(folder, search_budget, stage_budget, publish_limit, fallback_budget):
    if not 1 <= search_budget <= 12:
        raise RuntimeError("search_budget_outside_1_to_12")
    if not 1 <= stage_budget <= 3:
        raise RuntimeError("stage_budget_outside_1_to_3")
    if not 1 <= publish_limit <= 3:
        raise RuntimeError("publish_limit_outside_1_to_3")
    if not 1 <= fallback_budget <= 20:
        raise RuntimeError("fallback_budget_outside_1_to_20")
    required_code(folder)
    steps = [
        ("DISCOVERY", "ja_first_search_pilot.py",
         ("--budget", str(search_budget))),
        ("STAGE CANDIDATES", "ja_first_stage_saved_batch.py",
         ("--budget", str(stage_budget), "--apply")),
        ("PUBLISH VERIFIED JA", "ja_first_publish_queue.py",
         ("--limit", str(publish_limit), "--max-titles", "12", "--apply")),
        ("QUEUE ENGLISH FALLBACK", "ja_first_gemma_fallback.py",
         ("--probe-budget", str(fallback_budget), "--queue-one")),
    ]
    print("=== ONE BOUNDED JAPANESE-FIRST PROCESSING CYCLE ===", flush=True)
    print("Limits:", json.dumps({
        "provider_searches": search_budget,
        "JA_downloads": stage_budget,
        "new_JA_publications": publish_limit,
        "fallback_EN_candidates_probed": fallback_budget,
        "Gemma_jobs_queued": 1,
        "Gemma_jobs_started": 0
    }), flush=True)
    for name, file, args in steps:
        run_step(folder, name, file, args)
    print("CYCLE COMPLETE: durable state updated; no Gemma worker started.",
          flush=True)
    status()


def start_existing_worker(folder):
    required_code(folder)
    import daily_japanese as daily

    pending = daily.pending_daily(JA_ROOT)
    if not pending:
        print("NO PENDING GEMMA JOB: nothing started", flush=True)
        return
    jid, state = pending["id"], pending["status"]
    if state not in ("queued", "translating", "translated"):
        raise RuntimeError("non_resumable_job_status")
    if not re.fullmatch(r"daily-[a-z0-9-]{1,95}", jid):
        raise RuntimeError("unexpected_job_identity")
    print("STARTING EXISTING GEMMA JOB:", jid, "|", state, flush=True)
    print("Existing SubHub worker may publish a Japanese sidecar "
          "if its native validation gates pass.", flush=True)
    result = daily.start_worker(
        JA_ROOT, jid, worker=folder / "daily_worker.py")
    print("WORKER LAUNCH:", result, flush=True)
    print("CHECKPOINT DATABASE:", JA_ROOT / "jobs.sqlite3", flush=True)
    print("WORKER LOG:", JA_ROOT / "daily-worker.log", flush=True)
    print("LIVE TRACKER: python3", folder / "ja_first_cycle.py",
          "watch (or start-worker --apply --watch)", flush=True)
    return jid


def watch(folder, job_id=None, interval=10):
    """Attach read-only tracker to a known job or active job automatically.

    Ctrl+C stops only the tracker; the worker is detached and keeps running.
    No additional GPU work or provider calls are initiated.
    """
    tracker = folder / "subhub_live_tracker.py"
    if tracker.is_symlink() or not tracker.is_file():
        raise RuntimeError("SubHub tracker missing; reinstall controller tools")
    args = [sys.executable, "-u", str(tracker), "--watch",
            "--interval", str(interval)]
    if job_id:
        if not re.fullmatch(r"daily-[a-z0-9-]{1,95}", job_id):
            raise RuntimeError("Invalid job ID for tracker")
        args.extend(["--job-id", job_id])
    try:
        return subprocess.call(args, cwd=str(folder))
    except KeyboardInterrupt:
        print("Tracker detached; translation continues.", flush=True)
        return 0


def self_test():
    import inspect
    assert len(FILES) == 13
    assert len(STEPS) == 4
    for _, file, args in STEPS:
        assert file in FILES
        assert isinstance(args, tuple)
    assert all(str(Path(x).suffix) == ".py" for x in FILES)
    # Actual progress lives in the cues table, not in jobs.ja/jobs.n.
    assert "LEFT JOIN cues c ON c.job_id = j.id" in inspect.getsource(status)
    assert "c.japanese IS NOT NULL" in inspect.getsource(status)
    print("SELF-TEST PASSED: E4B-pinned single-cycle dependency manifest, "
          "stage ordering and explicit-action gates; no file writes",
          flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("status", "cycle", "start-worker", "watch"),
                        nargs="?", default="status")
    parser.add_argument("--apply", action="store_true",
                        help="required for cycle and start-worker")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--watch", action="store_true",
                        help="attach live terminal tracker after starting a worker")
    parser.add_argument("--interval", type=int, default=10,
                        help="tracker refresh interval in seconds (5..60)")
    parser.add_argument("--search-budget", type=int, default=8)
    parser.add_argument("--stage-budget", type=int, default=2)
    parser.add_argument("--publish-limit", type=int, default=2)
    parser.add_argument("--fallback-budget", type=int, default=8)
    args = parser.parse_args(argv)
    if args.self_test:
        self_test()
        return
    if not 5 <= args.interval <= 60:
        parser.error("--interval must be 5..60")
    if args.action == "status":
        status()
        return
    folder = Path(__file__).resolve().parent
    if args.action == "watch":
        watch(folder, interval=args.interval)
        return
    if not args.apply:
        parser.error(args.action + " requires --apply")
    if args.action == "cycle":
        cycle(folder, args.search_budget, args.stage_budget,
              args.publish_limit, args.fallback_budget)
    elif args.action == "start-worker":
        job = start_existing_worker(folder)
        if args.watch and job:
            watch(folder, job_id=job, interval=args.interval)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("BRUISER CYCLE HELD:", type(exc).__name__,
              str(exc)[:180] if isinstance(exc, (ValueError, RuntimeError))
              else "", file=sys.stderr)
        raise SystemExit(1) from None
