#!/usr/bin/env python3
"""Read-only full-screen live terminal monitor for the active Bruiser batch.

The running source-only worker is NOT controlled by this script. Ctrl+C
disconnects the viewer and leaves the batch and daily timer untouched.
Displays only observable state; never treats provider candidates as publications.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from zoneinfo import ZoneInfo

HOME = Path.home()
ROOT = HOME / "bruiser-pilot" / "batch-control"
STATUS = ROOT / "current.json"
UNIT = "bruiser-subhub-batch.service"
JST = ZoneInfo("Asia/Tokyo")
ESCAPE = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))")
CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
HIGHLIGHTS = ("SEARCHING:", "STAGING:", "PUBLISHED:", "STAGED:",
              "HELD:", "FFSUBSYNC HELD:", "DIRECT HELD:",
              "BRUISER_PUBLISH_ITEM:", "PROVIDER_LIMIT_REACHED",
              "BRUISER_BATCH_FAILED:", "BRUISER_BATCH_COMPLETE",
              "QUEUE SUMMARY:", "BATCH RESULT:", "CYCLE COMPLETE")
PHASES = {
    "queued": "STARTUP / PREFLIGHT",
    "reconcile_queue": "RECONCILE SAVED WORK",
    "recover_already_staged": "REPAIR SAVED JAPANESE",
    "search_opensubtitles": "SEARCH OPENSUBTITLES",
    "stage_matched_japanese": "DOWNLOAD MATCHED JAPANESE",
    "sync_and_publish": "ALIGN + PUBLISH",
    "completed": "BATCH COMPLETED",
    "failed": "BATCH FAILED",
}


def scrub(value, limit=250):
    return CONTROL.sub("", ESCAPE.sub("", str(value or "").replace("\r", " ")))[:limit]


def state(path=STATUS):
    path = Path(path)
    if not path.is_file() or path.is_symlink():
        return None
    if path.stat().st_mode & 0o077:
        raise RuntimeError("Batch status is not private; read refused")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise RuntimeError("Unexpected batch state schema")
    return data


def service_running(unit=UNIT):
    try:
        done = subprocess.run(
            ["systemctl", "--user", "is-active", "--quiet", unit],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=5, check=False)
        return done.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def recent_log(path, count=8):
    if not path:
        return []
    path = Path(path)
    if (path.parent != ROOT or path.is_symlink() or not path.is_file()
            or path.stat().st_mode & 0o077):
        return []
    with path.open("rb") as stream:
        size = path.stat().st_size
        stream.seek(max(0, size - 130000))
        buffer = stream.read(130000)
    lines = buffer.decode("utf-8", errors="replace").splitlines()
    selected = []
    for line in lines:
        line = scrub(line.strip(), 250)
        if not line:
            continue
        if "BRUISER_PUBLISH_ITEM:" in line:
            try:
                record = json.loads(line.partition("BRUISER_PUBLISH_ITEM:")[2])
                result = record.get("result")
                jid = scrub(record.get("jellyfin_id"), 14)
                reason = scrub(record.get("reason"), 85)
                line = (f"Published media {jid}" if result == "published"
                        else f"Held media {jid}: {reason}" if result == "held"
                        else f"Already published media {jid}")
            except (ValueError, TypeError):
                line = "Publication event recorded"
            selected.append(line)
        elif any(term in line for term in HIGHLIGHTS):
            selected.append(line)
    return selected[-count:]


def published_stage_progress(log_path, phase):
    """Count titles processed in the current publication pass from worker log.

    Controller's state currently does not increment phase_current for MEDIA
    events. This read-only view can recover the count without restarting the
    live batch or writing to its state database.
    """
    if phase not in ("recover_already_staged", "sync_and_publish") or not log_path:
        return None
    path = Path(log_path)
    if (path.parent != ROOT or path.is_symlink() or not path.is_file()
            or path.stat().st_mode & 0o077):
        return None
    with path.open("rb") as stream:
        stream.seek(max(0,path.stat().st_size - 1000000))
        lines = stream.read(1000000).decode("utf-8",errors="replace").splitlines()
    current = None
    for i, line in enumerate(lines):
        if line.startswith("=== PHASE "):
            stage = line[len("=== PHASE "):].split(" ",1)[0]
            if stage == phase:
                current = i
            elif current is not None:
                current = None
    if current is None:
        return None
    section = lines[current:]
    total = 0
    done = 0
    for line in section:
        if line.startswith("=== UNIFIED JAPANESE SUBTITLE PUBLISH QUEUE ==="):
            total = 0
            done = 0
        if "unique titles:" in line:
            m = re.search(r"unique titles:\s*(\d+)",line)
            if m:
                total = int(m.group(1))
        if line.startswith("MEDIA:"):
            done += 1
    return done, total


def bar(number, total, width=29):
    if not isinstance(total, int) or total <= 0:
        return "[" + "." * width + "]  not yet measurable"
    number = max(0, min(int(number or 0), total))
    filled = round(number * width / total)
    return ("[" + "#" * filled + "-" * (width - filled) +
            f"]  {number:,} / {total:,} ({100*number/total:.0f}%)")


def clock_str(when=None):
    return (when or datetime.now(timezone.utc)).astimezone(JST).strftime(
        "%a %b %d  %H:%M:%S JST")


def ago(value):
    try:
        dt = datetime.fromisoformat(str(value))
        age = max(0, int((datetime.now(timezone.utc) - dt).total_seconds()))
        if age < 60:
            return f"{age}s ago"
        if age < 3600:
            return f"{age//60}m {age%60}s ago"
        return f"{age//3600}h {age%3600//60}m ago"
    except (ValueError, TypeError):
        return "no timestamp"


def terminal_screen(data, active, log_lines, columns=88):
    columns = min(max(int(columns), 64), 132)
    hr = "=" * min(columns, 100)
    if not data:
        return "\n".join((hr,"BRUISER SUBTITLES  |  LIVE VIEW  |  " + clock_str(),
                          hr,"No batch status file yet. Start with:",
                          "  ~/.local/bin/bruiser-subs start --cycles 5",
                          "\nViewer only - Ctrl+C to exit."))
    batch = scrub(data.get("batch_id"), 45) or "(unknown)"
    phase = str(data.get("phase") or "queued")
    raw_state = str(data.get("state") or "unknown")
    service_state = ("RUNNING" if active else
                     raw_state.upper() if raw_state in ("completed","failed","stopped")
                     else "NOT RUNNING / INTERRUPTED")
    cycle = int(data.get("cycle") or 0)
    cycles = int(data.get("cycles") or 0)
    done_cycles = min(max(cycle-1, 0), cycles) if active else (
        cycles if raw_state == "completed" else min(max(cycle-1,0),cycles))
    current = data.get("phase_current")
    total = data.get("phase_total")
    if phase in ("recover_already_staged", "sync_and_publish") and not total:
        reported = published_stage_progress(data.get("log"),phase)
        if reported is not None:
            current, total = reported
    phase_progress = bar(current, total)
    counts = Counter(data.get("counts") or {})
    upper = cycles * int(data.get("search_budget") or 0)
    searched = int(counts.get("search_started", 0))
    rows = [
        hr,
        "BRUISER SUBTITLES  |  LIVE BATCH  |  " + clock_str(),
        hr,
        f"Job:      {batch}",
        f"Service:  {service_state}       Last status update: {ago(data.get('updated_utc'))}",
        f"Stage:    {PHASES.get(phase, phase.upper())}",
        "",
        "OVERALL BATCH",
        "Cycles:   " + bar(done_cycles, cycles),
        f"Current:  {cycle} / {cycles} cycles started",
        "SEARCHING",
        "All runs: " + bar(searched, upper) + " maximum planned attempts",
        "This step:" + phase_progress if phase == "search_opensubtitles"
        else "This step:" + phase_progress,
        f"Title:    {scrub(data.get('last_item'), 93) or '(awaiting current title)'}",
        "",
        "REAL WORK COUNTS (THIS BATCH)",
        f"  Searches attempted: {searched:<8}   Plausible matches: {counts.get('search_plausible',0):<8}   No matches: {counts.get('search_none',0)}",
        f"  Download attempts: {counts.get('download_attempted',0):<8}   Newly staged: {counts.get('staged',0):<8}   Provider errors: {counts.get('search_errors',0)}",
        f"  Newly published: {counts.get('published_new',0):<8}   Held titles: {counts.get('held_titles',0):<8}   Recognized old: {counts.get('recognized_prior',0)}",
        f"  Provider quota reached: {'YES - no further download attempt this quota period' if data.get('quota_exhausted') else 'not reported'}",
        "",
    ]
    if active and phase == "queued":
        rows.extend([
            "STARTUP: source lock acquired; checking Sublarr and Jellyfin.",
            "No subtitle activity can be inferred until the phase advances.",
            "",
        ])
    if not active and raw_state in ("starting", "running"):
        rows.extend([
            "WARNING: Controller state claims active, but systemd is not running.",
            "Inspect: journalctl --user -u bruiser-subhub-batch.service -n 30",
            "",
        ])
    if active and ago(data.get("updated_utc")) not in ("no timestamp",):
        try:
            dt = datetime.fromisoformat(str(data.get("updated_utc")))
            age = (datetime.now(timezone.utc)-dt).total_seconds()
            if age > 120:
                rows.append(f"WARNING: No new progress report for {int(age)}s; a slow startup or blocked operation is possible.")
                rows.append("Check service journal; do not interpret RUNNING as completed work.")
                rows.append("")
        except (ValueError, TypeError):
            pass
    holds = Counter(data.get("held_reasons") or {}).most_common(3)
    if holds:
        rows.append("TOP HOLDS: " + "; ".join(f"{scrub(k,45)} ({v})" for k,v in holds))
        rows.append("")
    rows.append("RECENT REAL ACTIVITY")
    if log_lines:
        rows.extend("  " + scrub(line, max(45,columns-4)) for line in log_lines)
    else:
        rows.append("  No captured worker event yet.")
    rows.extend(["",hr,
                 "Updates every 2 seconds. Ctrl+C closes this VIEW, NOT the batch.",
                 "Stop the actual job separately: ~/.local/bin/bruiser-subs stop"])
    return "\n".join(rows) + "\n"


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--once", action="store_true", help="draw a single snapshot")
    p.add_argument("--interval", type=float, default=2.0,
                   help="seconds between redraws, 1..30")
    p.add_argument("--recent", type=int, default=8,
                   help="recent events to display, 1..15")
    args = p.parse_args(argv)
    if not 1 <= args.interval <= 30 or not 1 <= args.recent <= 15:
        p.error("invalid refresh interval or event count")
    try:
        while True:
            doc = state()
            active = service_running()
            recent = recent_log(doc.get("log"),args.recent) if doc else []
            cols = shutil.get_terminal_size(fallback=(88,30)).columns
            output = terminal_screen(doc, active, recent, cols)
            if not args.once and sys.stdout.isatty():
                sys.stdout.write("\033[2J\033[H")
            sys.stdout.write(output)
            sys.stdout.flush()
            if args.once:
                break
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nLive view closed. Background batch unchanged.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print("BRUISER_LIVE_VIEW_ERROR:",type(exc).__name__,str(exc)[:160],
              file=sys.stderr)
        raise SystemExit(1)
