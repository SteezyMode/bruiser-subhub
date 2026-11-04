#!/usr/bin/env python3
"""Reusable read-only monitor for ALL Bruiser SubHub subtitle jobs.

Shows actual per-cue SQLite checkpoint progress, GPU temperature/utilization/
VRAM/power, Ollama model placement, and Ollama/worker process CPU usage.
Never writes to SQLite, contacts subtitle providers, starts workers or modifies
the media library. Ctrl+C stops monitoring, not translation.
"""
from __future__ import annotations

import argparse
from collections import deque
import json
import os
import re
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
from urllib.parse import quote

DB = Path.home() / "bruiser-pilot/subhub1-state/jobs.sqlite3"


def command(args, timeout=5):
    try:
        result = subprocess.run(
            args, capture_output=True, text=True, timeout=timeout,
            stdin=subprocess.DEVNULL)
        return result.stdout.strip() if result.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def active_worker_job():
    """Identify the actual live single-title worker, not the oldest queued job.

    A running worker can temporarily report SQLite state 'queued', especially
    while opening the model; PID commandline is therefore more reliable than
    an ordering over queued job states. Only a verified one-job process counts.
    """
    processes = command(["ps", "-eo", "comm=,args="], timeout=5)
    matches = []
    for line in processes.splitlines():
        if "daily_worker.py" not in line:
            continue
        parts = line.strip().split(None, 1)
        if len(parts) != 2 or not parts[0].startswith("python"):
            continue
        args = parts[1]
        match = re.search(r"(?:^|\s)--job-id(?:=|\s+)(daily-[a-z0-9-]{1,95})(?:\s|$)",
                          args)
        if match:
            matches.append(match.group(1))
    return matches[-1] if len(matches) == 1 else None


def profile_info(job, root=None):
    """Provenance of a job; current Ollama residency is NOT historic evidence."""
    root = root or DB.parent
    path = root / "model-profiles" / (job["id"] + ".json")
    if path.is_symlink() or not path.is_file():
        return "MODEL PROFILE: not recorded (older/legacy job; model not provable)"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if (data.get("job_id") != job["id"] or
                data.get("source_sha") != job.get("source_sha")):
            return "MODEL PROFILE: mismatched job/source (hold)"
        model = data.get("model")
        if not isinstance(model, str) or not model.strip():
            return "MODEL PROFILE: missing pinned model"
        return "PINNED TRANSLATOR: " + model
    except (OSError, ValueError):
        return "MODEL PROFILE: unreadable; do not infer model identity"


def queue_summary(db_path=DB):
    if not db_path.is_file() or db_path.is_symlink():
        return "QUEUE: unavailable"
    uri = "file:" + quote(str(db_path.resolve()), safe="/") + "?mode=ro"
    with sqlite3.connect(uri, uri=True, timeout=6) as con:
        con.execute("PRAGMA query_only=ON")
        counts = con.execute(
            "SELECT status,COUNT(*) FROM jobs WHERE id LIKE 'daily-%' GROUP BY status"
        ).fetchall()
    return "DAILY JOBS: " + (", ".join(
        f"{state}: {count}" for state, count in counts) if counts else "none")


def checkpoint(db_path=DB, job_id=None):
    if not db_path.is_file() or db_path.is_symlink():
        raise RuntimeError("SubHub checkpoint database not found or is symlinked")
    if db_path.stat().st_uid != os.getuid():
        raise RuntimeError("SubHub checkpoint database not owned by current user")
    uri = "file:" + quote(str(db_path.resolve()), safe="/") + "?mode=ro"
    with sqlite3.connect(uri, uri=True, timeout=6) as con:
        con.execute("PRAGMA query_only=ON")
        # Default to the actual active single-title worker before falling back
        # to existing queued or most recently completed daily jobs.
        if not job_id:
            job_id = active_worker_job()
        if job_id:
            row = con.execute(
                """SELECT id,status,source_cues,updated,last_error,source_sha,video FROM jobs
                   WHERE id=?""", (job_id,)).fetchone()
        else:
            row = con.execute(
                """SELECT id,status,source_cues,updated,last_error FROM jobs
                   WHERE id LIKE 'daily-%'
                   ORDER BY CASE WHEN status = 'translating' THEN 0
                                      WHEN status = 'translated' THEN 1
                                      WHEN status = 'queued' THEN 2 ELSE 3 END,
                            created DESC LIMIT 1"""
            ).fetchone()
        if row is None:
            return None
        jid, state, total, updated, error, source_sha, video = row
        completed, stalled, recorded = con.execute(
            """SELECT
                 COALESCE(SUM(CASE WHEN japanese IS NOT NULL
                                         AND TRIM(japanese) != '' THEN 1 ELSE 0 END),0),
                 COALESCE(SUM(CASE WHEN japanese IS NULL
                                         AND failed>=5 THEN 1 ELSE 0 END),0),
                 COUNT(*)
               FROM cues WHERE job_id=?""", (jid,)
        ).fetchone()
        return {
            "id": str(jid), "status": str(state),
            "total": int(total), "completed": int(completed),
            "held": int(stalled), "recorded": int(recorded),
            "updated": str(updated), "error": str(error or ""),
            "source_sha": str(source_sha),
            "title": Path(str(video)).stem if video else str(jid),
        }


def gpu():
    data = command([
        "nvidia-smi",
        "--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw,power.limit",
        "--format=csv,noheader,nounits"
    ])
    if not data:
        return "GPU telemetry unavailable (nvidia-smi not responding)"
    fields = [s.strip() for s in data.splitlines()[0].split(",")]
    if len(fields) != 6:
        return "GPU telemetry returned an unexpected format: " + data.splitlines()[0][:90]
    util, vram, maximum, temp, power, limit = fields
    try:
        fraction = round(100.0 * float(vram) / float(maximum), 1)
        mem = f"{int(float(vram)):,} / {int(float(maximum)):,} MiB ({fraction}%)"
    except (ValueError, ZeroDivisionError):
        mem = vram + " / " + maximum + " MiB"
    return (
        f"GPU {util}% | {temp} C | VRAM {mem}\n"
        f"Power draw {power} W | GPU limit {limit} W"
    )


def model_placement():
    result = command(["ollama", "ps"], timeout=5)
    if not result:
        return "Ollama placement: unavailable (try `ollama ps` on host)"
    lines = result.splitlines()
    if len(lines) < 2:
        return "Ollama placement: no currently loaded model reported"
    header = lines[0]
    processor = header.find("PROCESSOR")
    if processor >= 0:
        until = header.find("UNTIL", processor + len("PROCESSOR"))
        formatted = []
        for line in lines[1:4]:
            placement = line[processor:until if until > processor else None].strip()
            model = line.split()[0] if line.split() else "unknown"
            formatted.append(model + ": " + (placement or "unknown"))
        return "Ollama model placement: " + "; ".join(formatted)
    return "Ollama models: " + "; ".join(
        line.split()[0] for line in lines[1:4] if line.split()
    ) + " (run `ollama ps` to see CPU/GPU placement)"


def process_cpu(jid):
    """CPU percent is per one logical CPU core, not total machine utilization."""
    rows = command(["ps", "-eo", "pid=,pcpu=,comm=,args="], timeout=5)
    if not rows:
        return "Process CPU telemetry unavailable"
    worker = []
    ollama = []
    for line in rows.splitlines():
        pieces = line.strip().split(None, 3)
        if len(pieces) < 4:
            continue
        pid, percentage, name, args = pieces
        try:
            percent = float(percentage)
        except ValueError:
            continue
        if "daily_worker.py" in args and jid in args and name.startswith("python"):
            worker.append((pid, percent))
        elif name.lower().startswith("ollama"):
            ollama.append((pid, percent))
    worker_summary = (
        ", ".join(f"PID {pid}: {p:.1f}%" for pid, p in worker)
        if worker else "not detected"
    )
    ollama_summary = (
        ", ".join(f"PID {pid}: {p:.1f}%" for pid, p in ollama[:4])
        if ollama else "not detected"
    )
    return (
        f"Worker CPU: {worker_summary}\n"
        f"Ollama CPU: {ollama_summary}\n"
        "(CPU % is per logical core; above 100% means multiple cores)"
    )


def format_duration(seconds):
    n = max(0, int(seconds))
    hours, rem = divmod(n, 3600)
    minutes, rem = divmod(rem, 60)
    return f"{hours}h {minutes}m" if hours else f"{minutes}m {rem}s"


def render(job, samples):
    complete, total = job["completed"], job["total"]
    fraction = complete / total if total else 0
    width = 36
    filled = min(width, round(fraction * width))
    bar = "[" + "#" * filled + "." * (width - filled) + "]"
    output = [
        "BRUISER SUBHUB | LIVE TRANSLATION TRACKER",
        "Read-only: Ctrl+C exits tracker; translation keeps running.",
        "",
        "TITLE  " + job.get("title", job["id"]),
        "JOB    " + job["id"],
        "STATE  " + job["status"],
        f"CUES   {complete:,}/{total:,} ({fraction * 100:.1f}%)",
        bar,
    ]
    if len(samples) >= 2:
        begin_t, begin_n = samples[0]
        end_t, end_n = samples[-1]
        seconds = max(end_t - begin_t, 0.001)
        rate = max(end_n - begin_n, 0) / seconds
        if rate > 0:
            output.append(
                f"PACE   {rate * 60:.1f} cues/min (recent sampling window)"
            )
            output.append(
                f"ETA    ~{format_duration((total - complete) / rate)} "
                "(rough estimate)"
            )
        else:
            output.append("PACE   No new checkpoint since tracker started")
    else:
        output.append("PACE   Collecting initial samples...")
    output.append("HELD   " + str(job["held"]) + " cues")
    output.append("JOB UPDATED " + job["updated"])
    if job["error"]:
        output.append("JOB ERROR RECORDED: " + job["error"][:130])
    if job["recorded"] != total:
        output.append("WARNING: cue table count differs from source cue count")
    output.extend(["", profile_info(job), queue_summary(),
                   gpu(), model_placement(), process_cpu(job["id"])])
    output.append("")
    output.append(
        "Interpretation: 100% GPU in Ollama placement means model weights fit "
        "on GPU; lower percentages can indicate CPU offload."
    )
    return "\n".join(output)


def self_test():
    assert format_duration(65) == "1m 5s"
    assert format_duration(3665) == "1h 1m"
    job = {
        "id": "daily-test", "status": "queued",
        "total": 200, "completed": 50,
        "held": 0, "recorded": 200, "updated": "test",
        "error": "",
    }
    # Check formatting without requiring host NVIDIA/Ollama/SQLite binaries.
    global gpu, model_placement, process_cpu, profile_info, queue_summary
    old = (gpu, model_placement, process_cpu, profile_info, queue_summary)
    try:
        gpu = lambda: "GPU offline test"
        model_placement = lambda: "Ollama offline test"
        process_cpu = lambda jid: "CPU offline test"
        profile_info = lambda job: "Model offline test"
        queue_summary = lambda: "Queue offline test"
        out = render(job, deque([(0, 10), (60, 50)]))
        assert "25.0%" in out
        assert "40.0 cues/min" in out
        assert "GPU offline test" in out
        assert "Model offline test" in out
    finally:
        gpu, model_placement, process_cpu, profile_info, queue_summary = old
    print("SELF-TEST PASSED: progress, pace, ETA, display; no reads or writes")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job-id", default=None,
                        help="exact SubHub daily job ID; default running job, else pending/recent")
    parser.add_argument("--watch", action="store_true",
                        help="refresh until Ctrl+C; otherwise print one snapshot")
    parser.add_argument("--interval", type=int, default=10,
                        help="watch refresh seconds (5..60)")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    if not 5 <= args.interval <= 60:
        parser.error("--interval must be 5..60 seconds")
    observations = deque(maxlen=18)
    last_job = None
    while True:
        current = checkpoint(job_id=args.job_id)
        if current is None:
            print("No daily Gemma job found in SubHub checkpoint database")
            return
        if current["id"] != last_job:
            observations.clear()
            last_job = current["id"]
        observations.append((time.monotonic(), current["completed"]))
        view = render(current, observations)
        if args.watch and sys.stdout.isatty():
            sys.stdout.write("\033[2J\033[H")
        print(view, flush=True)
        if not args.watch or current["status"] in ("published", "publish_hold", "needs_review", "hold"):
            return
        time.sleep(args.interval)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nTracker closed. Existing translation job is unaffected.")
    except (OSError, RuntimeError, sqlite3.Error) as exc:
        print("TRACKER UNAVAILABLE:", type(exc).__name__, str(exc)[:140],
              file=sys.stderr)
        raise SystemExit(1) from None
