#!/usr/bin/env python3
"""Bruiser SubHub batch control: start/status/logs/stop, detached and observable.

This is an operator surface over the EXISTING source-only scripts. It does
not bypass OpenSubtitles download quota, weaken ffsubsync, replace subtitles,
or start any local model. Search history and staging remain durable.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import time

ROOT = Path.home() / "bruiser-pilot"
CODE = ROOT / "subhub-control"
QUEUE_CODE = ROOT / "coverage-queue-code" / "bruiser_coverage_queue.py"
STATE = ROOT / "batch-control"
LOCK = ROOT / "ja-first-inventory" / ".autofill.lock"
UNIT = "bruiser-subhub-batch.service"
SCHEDULED = "bruiser-ja-source-autofill.service"
BUDGET = {"cycles": 12, "search": 600, "stage": 200, "publish": 200}
PATTERN = re.compile(r"^\[(\d+)/(\d+)\]\s+(SEARCHING|STAGING):\s*(.+)")
ID = re.compile(r"\b[a-f0-9]{32}\b")


def utc():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def private_dir(folder=STATE):
    if folder.is_symlink():
        raise RuntimeError("unsafe_batch_state_symlink")
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    if folder.stat().st_mode & 0o077:
        raise RuntimeError("batch_state_folder_must_be_0700")
    return folder


def state_file():
    return private_dir() / "current.json"


def load_state():
    path = state_file()
    if not path.exists():
        return {}
    if path.is_symlink() or path.stat().st_mode & 0o077:
        raise RuntimeError("unsafe_batch_state_file")
    result = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(result, dict):
        raise RuntimeError("invalid_batch_state")
    return result


def save_state(doc):
    folder = private_dir()
    fd, name = tempfile.mkstemp(prefix=".batch-state-", dir=folder)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(doc, stream, ensure_ascii=False, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, folder / "current.json")
    finally:
        Path(name).unlink(missing_ok=True)


def active_unit(unit):
    result = subprocess.run(
        ["systemctl", "--user", "is-active", "--quiet", unit],
        capture_output=True, check=False, timeout=15)
    return result.returncode == 0


def unit_status():
    return active_unit(UNIT)


def check_manual_publishers():
    result = subprocess.run(
        ["pgrep", "-u", str(os.getuid()), "-f", "ja_first_publish_queue.py"],
        capture_output=True, text=True, timeout=10)
    # Manual publication is a separate command; a fresh manual batch must
    # never start a second copy while one is already writing source subtitles.
    return result.returncode == 0


def validate_budget(args):
    for attr, upper in BUDGET.items():
        if attr == "search":
            value = args.search_budget
        elif attr == "stage":
            value = args.stage_budget
        elif attr == "publish":
            value = args.publish_limit
        else:
            value = args.cycles
        if not 1 <= value <= upper:
            raise ValueError(f"{attr}_budget_outside_1_to_{upper}")


def start(args):
    validate_budget(args)
    if unit_status():
        print("BATCH_ALREADY_RUNNING")
        return status()
    if active_unit(SCHEDULED):
        raise RuntimeError("daily_source_job_active_try_again_after_it_finishes")
    if check_manual_publishers():
        raise RuntimeError("manual_staged_subtitle_publisher_is_still_running")
    for p in (CODE / "ja_first_autofill.py",
              CODE / "ja_first_search_pilot.py",
              CODE / "ja_first_stage_saved_batch.py",
              CODE / "ja_first_publish_queue.py", QUEUE_CODE):
        if not p.is_file() or p.is_symlink():
            raise RuntimeError("missing_required_existing_source_component:" + p.name)
    # Ensure the user has a durable real coverage queue before creating work.
    if not (ROOT / "coverage-queue" / "coverage.sqlite3").is_file():
        raise RuntimeError("coverage_queue_not_initialized")
    # A new request after an interrupted run keeps existing search/staged DBs.
    previous = load_state()
    log = private_dir() / ("batch-" + datetime.now(timezone.utc).strftime(
        "%Y%m%dT%H%M%SZ") + ".log")
    if log.exists() or log.is_symlink():
        raise RuntimeError("batch_log_name_collision")
    fd = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(fd)
    doc = {"schema": "bruiser-batch-v1", "state": "starting", "started_utc": utc(),
           "updated_utc": utc(), "batch_id": log.stem,
           "log": str(log), "cycles": args.cycles, "cycle": 0,
           "search_budget": args.search_budget,
           "stage_budget": args.stage_budget, "publish_limit": args.publish_limit,
           "previous_batch": previous.get("batch_id"),
           "phase": "queued", "phase_current": 0, "phase_total": 0,
           "last_item": "", "last_event": "controller accepted request",
           "counts": {}, "held_reasons": {}, "quota_exhausted": False}
    save_state(doc)
    command = [
        "systemd-run", "--user", "--collect",
        "--unit=bruiser-subhub-batch",
        "--description=Bruiser manually started source-only subtitle batch",
        "--property=Nice=10", "--property=IOSchedulingClass=idle",
        "--property=NoNewPrivileges=true",
        "--property=KillMode=control-group",
        "--property=TimeoutStartSec=24h",
        "/usr/bin/python3", "-u", str(Path(__file__).resolve()), "run",
        "--cycles", str(args.cycles),
        "--search-budget", str(args.search_budget),
        "--stage-budget", str(args.stage_budget),
        "--publish-limit", str(args.publish_limit),
        "--batch-id", doc["batch_id"]
    ]
    launched = subprocess.run(command, capture_output=True, text=True, timeout=30)
    if launched.returncode:
        doc.update(state="launch_failed", last_event="systemd rejected batch",
                   updated_utc=utc())
        save_state(doc)
        raise RuntimeError("systemd_run_failed:" + launched.stderr.strip()[:220])
    print("BATCH_STARTED", doc["batch_id"])
    print("BATCH_LOG", log)
    print("Detached source-only job; search can run NOW, provider download limits still apply.")
    print("Check progress: bruiser-subs status | bruiser-subs logs")
    return 0


def event(doc, line):
    line = line.strip()
    m = PATTERN.match(line)
    counts = Counter(doc.get("counts") or {})
    if m:
        current, total, op, title = m.groups()
        doc.update(phase_current=int(current), phase_total=int(total),
                   last_item=title[:140])
        if op == "SEARCHING":
            counts["search_started"] += 1
        elif op == "STAGING":
            counts["download_attempted"] += 1
    if re.search(r"^\[\d+/\d+\] PLAUSIBLE:", line):
        counts["search_plausible"] += 1
    elif re.search(r"^\[\d+/\d+\] REVIEW:", line):
        counts["search_review"] += 1
    elif re.search(r"^\[\d+/\d+\] NONE:", line):
        counts["search_none"] += 1
    elif re.search(r"^\[\d+/\d+\] ERROR:", line):
        counts["search_errors"] += 1
    if line.startswith("STAGED:"):
        counts["staged"] += 1
    if line.startswith("PROVIDER_LIMIT_REACHED"):
        doc["quota_exhausted"] = True
        doc["quota_utc_day"] = time.gmtime().tm_yday
        counts["provider_limit_events"] += 1
    if line.startswith("HELD:"):
        counts["held_events"] += 1
        key = line.split("RuntimeError", 1)[-1].strip() if "RuntimeError" in line else "unknown"
        reason = key.split(":")[0].split()[0][:65] if key else "unspecified"
        why = Counter(doc.get("held_reasons") or {})
        why[reason] += 1
        doc["held_reasons"] = dict(why)
    if line.startswith("QUEUE SUMMARY:"):
        try:
            detail = json.loads(line.partition(":")[2])
            counts["published_new"] += int(detail.get("published_new") or 0)
            counts["held_titles"] += int(detail.get("held") or 0)
            counts["recognized_prior"] += int(detail.get("retired_completed") or 0)
        except (ValueError, TypeError):
            pass
    doc["counts"] = dict(counts)
    if any(key in line for key in ("SEARCHING:", "STAGING:", "MEDIA:", "HELD:",
                                   "PROVIDER_LIMIT_REACHED", "QUEUE SUMMARY:",
                                   "BATCH RESULT:", "CYCLE COMPLETE",
                                   "CATALOG_", "STAGED:", "PUBLISHED:")):
        doc["last_event"] = line[:220]
    doc["updated_utc"] = utc()
    return doc


def lock_cycle():
    if not LOCK.parent.is_dir() or LOCK.parent.is_symlink():
        raise RuntimeError("unsafe_or_missing_existing_inventory_folder")
    fd = os.open(LOCK, os.O_CREAT | os.O_RDWR |
                 getattr(os, "O_NOFOLLOW", 0), 0o600)
    if os.fstat(fd).st_mode & 0o077:
        os.close(fd)
        raise RuntimeError("unsafe_existing_source_lock")
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        raise RuntimeError("another_source_cycle_running")
    return fd


def run_command(doc, args, phase, *, timeout):
    doc.update(phase=phase, phase_current=0, phase_total=0, updated_utc=utc())
    save_state(doc)
    with open(doc["log"], "a", encoding="utf-8", buffering=1) as out:
        out.write("\n=== PHASE " + phase + " " + utc() + " ===\n")
        command = [sys.executable, "-u", str(args[0]), *args[1:]]
        proc = subprocess.Popen(command, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL,
                                text=True, bufsize=1)
        try:
            start_time = time.monotonic()
            for line in proc.stdout:
                out.write(line)
                event(doc, line)
                save_state(doc)
                if time.monotonic() - start_time > timeout:
                    proc.terminate()
                    raise RuntimeError(phase + "_timeout")
            code = proc.wait(timeout=15)
        finally:
            if proc.poll() is None:
                proc.terminate()
        if code:
            raise RuntimeError(phase + "_exited_" + str(code))
    return doc


def reconcile(doc):
    return run_command(doc, [QUEUE_CODE, "init"], "reconcile_queue", timeout=600)


def worker(args):
    validate_budget(args)
    doc = load_state()
    if doc.get("batch_id") != args.batch_id:
        raise RuntimeError("batch_id_mismatch_cannot_take_over_newer_job")
    fd = lock_cycle()
    try:
        doc["state"] = "running"
        doc["last_event"] = "source lock acquired; beginning now"
        save_state(doc)
        from importlib.util import spec_from_file_location, module_from_spec
        source = CODE / "ja_first_autofill.py"
        spec = spec_from_file_location("bruiser_live_autofill", source)
        mod = module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.ensure_installed()
        settings = mod.config()
        mod.safe_source_settings(settings)
        if not mod.native_search_disabled(settings):
            raise RuntimeError("native_duplicate_provider_search_still_enabled")
        mod.check_scheduler_idle()
        mod.refresh_manifest()
        reconcile(doc)
        # Salvage already staged JA first (bounded, safety-gated, no downloads).
        run_command(doc, [CODE/"ja_first_publish_queue.py",
                         "--queue-staged-only","--limit","200",
                         "--max-titles","1000","--apply"],
                    "recover_already_staged", timeout=4*3600)
        reconcile(doc)
        for cycle in range(1, args.cycles+1):
            doc["cycle"] = cycle
            doc["last_event"] = "starting source cycle " + str(cycle)
            save_state(doc)
            run_command(doc, [CODE/"ja_first_search_pilot.py",
                              "--budget",str(args.search_budget)],
                        "search_opensubtitles", timeout=2*3600)
            reconcile(doc)
            # Download quota can reset while a multi-cycle job is running;
            # allow subsequent stages only after provider's next UTC day.
            if doc.get("quota_exhausted") and doc.get("quota_utc_day") != time.gmtime().tm_yday:
                doc["quota_exhausted"] = False
                doc["last_event"] = "UTC day changed; provider quota may have reset"
                save_state(doc)
            if doc.get("quota_exhausted"):
                doc["last_event"] = "download stage skipped: provider quota exhausted; searching continues"
                save_state(doc)
                with open(doc["log"],"a",encoding="utf-8") as out:
                    out.write("QUOTA_EXHAUSTED: skipped download for this cycle\n")
            else:
                run_command(doc, [CODE/"ja_first_stage_saved_batch.py",
                                  "--budget",str(args.stage_budget),"--apply"],
                            "stage_matched_japanese", timeout=3*3600)
                reconcile(doc)
                run_command(doc, [CODE/"ja_first_publish_queue.py",
                                  "--queue-staged-only","--limit",
                                  str(args.publish_limit),"--max-titles","1000","--apply"],
                            "sync_and_publish", timeout=4*3600)
                reconcile(doc)
        doc.update(state="completed", phase="completed", updated_utc=utc(),
                   last_event="requested cycles finished; source histories retained")
        save_state(doc)
        with open(doc["log"],"a",encoding="utf-8") as out:
            out.write("BRUISER_BATCH_COMPLETE " + utc() + "\n")
        return 0
    except Exception as exc:
        doc.update(state="failed", phase="failed", updated_utc=utc(),
                   last_event=type(exc).__name__ + ": " + str(exc)[:180])
        save_state(doc)
        with open(doc["log"], "a", encoding="utf-8") as out:
            out.write("BRUISER_BATCH_FAILED: " + doc["last_event"] + "\n")
        raise
    finally:
        os.close(fd)


def status():
    doc = load_state()
    if not doc:
        print("NO_BATCH: use bruiser-subs start --cycles 5")
        return 0
    active = unit_status()
    value = "running" if active else doc.get("state", "unknown")
    if not active and value in ("starting", "running"):
        value = "interrupted_or_stopped"
    print("BRUISER_BATCH_STATUS")
    print("  State:", value, "| Current phase:", doc.get("phase"),
          "| Cycle:", doc.get("cycle"), "/", doc.get("cycles"))
    print("  Phase progress:",doc.get("phase_current"),"/",doc.get("phase_total"),
          "| Subtitle:", doc.get("last_item"))
    print("  Updated UTC:",doc.get("updated_utc"))
    print("  Totals (observed events):",json.dumps(doc.get("counts",{}),sort_keys=True))
    print("  Provider quota exhausted in batch:",bool(doc.get("quota_exhausted")))
    print("  Recent issue:",doc.get("last_event"))
    reasons = Counter(doc.get("held_reasons") or {})
    print("  Top held reasons:",json.dumps(reasons.most_common(6)))
    print("  Full log:",doc.get("log"))
    print("  Manual stop: bruiser-subs stop | Resume: bruiser-subs start --cycles 5")
    return 0


def logs(args):
    doc = load_state()
    if not doc or not doc.get("log"):
        print("NO_BATCH_LOG")
        return 0
    path = Path(doc["log"])
    if path.parent != private_dir() or path.is_symlink() or not path.is_file():
        raise RuntimeError("unsafe_batch_log")
    with path.open("r", encoding="utf-8",errors="replace") as handle:
        from collections import deque
        for line in deque(handle, maxlen=args.lines):
            print(line.rstrip())
    return 0


def stop():
    if not unit_status():
        print("NO_ACTIVE_BATCH")
        return status()
    res = subprocess.run(["systemctl","--user","stop",UNIT],
                         capture_output=True,text=True,timeout=40)
    if res.returncode:
        raise RuntimeError("stop_failed:" + res.stderr.strip()[:180])
    doc = load_state()
    if doc.get("state") in ("starting","running"):
        doc.update(state="stopped",updated_utc=utc(),
                   last_event="stopped by owner; durable provider/staging history retained")
        save_state(doc)
    print("BATCH_STOPPED; restart to resume from durable provider and staging history.")
    return 0


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest="action",required=True)
    startp=sub.add_parser("start")
    runp=sub.add_parser("run",help=argparse.SUPPRESS)
    for control in (startp,runp):
        control.add_argument("--cycles",type=int,default=5)
        control.add_argument("--search-budget",type=int,default=600)
        control.add_argument("--stage-budget",type=int,default=200)
        control.add_argument("--publish-limit",type=int,default=200)
    runp.add_argument("--batch-id",required=True)
    sub.add_parser("status")
    logp=sub.add_parser("logs")
    logp.add_argument("--lines",type=int,default=40)
    sub.add_parser("stop")
    args=parser.parse_args(argv)
    if args.action=="start":
        return start(args)
    if args.action=="run":
        return worker(args)
    if args.action=="status":
        return status()
    if args.action=="logs":
        if not 1 <= args.lines <= 400:
            parser.error("--lines must be 1..400")
        return logs(args)
    return stop()


if __name__=="__main__":
    os.umask(0o077)
    try:
        raise SystemExit(main())
    except (OSError,ValueError,RuntimeError,subprocess.TimeoutExpired) as exc:
        print("BRUISER_BATCH_ERROR",type(exc).__name__,str(exc)[:240],
              file=sys.stderr)
        raise SystemExit(1) from None
