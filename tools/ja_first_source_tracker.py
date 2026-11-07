#!/usr/bin/env python3
"""Live, read-only terminal dashboard for the sourced-Japanese autofill service.

Attaches to the EXISTING systemd journal; never invokes search, download,
subtitle publication, translation, or service start. Ctrl+C detaches only
the viewer. No extra Python packages required.
"""
from __future__ import annotations

import argparse
from collections import deque
from datetime import datetime
import json
import re
import subprocess
import sys
import time

UNIT = "bruiser-ja-source-autofill"
SERVICE = UNIT + ".service"
TIMER = UNIT + ".timer"
JOURNAL_ROWS = 16000

RE_SEARCH_PLAN = re.compile(r"Search requests planned:\s*(\d+)\s*\|\s*budget:\s*(\d+)")
RE_SEARCH_START = re.compile(r"\[(\d+)/(\d+)\] SEARCHING:\s*(.*)")
RE_SEARCH_DONE = re.compile(r"\[(\d+)/(\d+)\] (PLAUSIBLE|NONE|REVIEW|ERROR):")
RE_STAGE_PLAN = re.compile(r"Selected:\s*(\d+)\s*\|\s*budget:\s*(\d+)")
RE_STAGE_START = re.compile(r"\[(\d+)/(\d+)\] STAGING:\s*(.*)")
RE_MEDIA_PLAN = re.compile(r"Staged candidates:\s*(\d+)\s*\|\s*unique titles:\s*(\d+)")
RE_LIMITS = re.compile(r"search_budget=(\d+)\s+stage_budget=(\d+)\s+publish_limit=(\d+)")


def call(args, *, timeout=25, runner=subprocess.run):
    result = runner(args, capture_output=True, text=True, timeout=timeout,
                    check=False)
    if result.returncode:
        raise RuntimeError("read_only_command_failed:" + args[0])
    return result.stdout


def events_from_jsonl(content):
    """Journalctl -o json; ignore unrelated metadata/invalid lines."""
    result = []
    for line in content.splitlines():
        try:
            data = json.loads(line)
        except ValueError:
            continue
        if not isinstance(data, dict):
            continue
        message = data.get("MESSAGE")
        if not isinstance(message, str):
            continue
        stamp = data.get("__REALTIME_TIMESTAMP", "")
        try:
            ts = int(stamp) / 1_000_000
        except (ValueError, TypeError):
            ts = 0
        result.append((ts, message.strip()))
    return result


def latest_run(events):
    """Only the most recent source-only cycle, never cumulative old progress."""
    marker = "RUNNING_SOURCES_ONLY_CYCLE"
    start = next((i for i in range(len(events) - 1, -1, -1)
                  if marker in events[i][1]), None)
    return events[start:] if start is not None else []


def parse(events):
    """Sole source of live progress: persisted journal output.

    Counts reflect observable events, not invented or estimated downloads.
    A search/download limit is a MAXIMUM, not the expected number of finds.
    """
    entries = latest_run(events)
    state = {
        "has_run": bool(entries),
        "started": entries[0][0] if entries else 0,
        "last_event": entries[-1][0] if entries else 0,
        "phase": "Waiting for first source cycle",
        "complete": False,
        "failed": False,
        "search_limit": 0, "stage_limit": 0, "publish_limit": 0,
        "search_planned": 0, "search_completed": 0,
        "search_found": 0, "search_none": 0, "search_review": 0,
        "search_errors": 0,
        "stage_planned": 0, "stage_attempts": 0,
        "staged": 0, "stage_holds": 0,
        "publish_title_planned": 0, "publish_title_checked": 0,
        "published": 0, "publish_holds": 0,
        "provider_limited": False,
        "existing_recognized": 0,
        "current": "",
        "recent": [],
    }
    notable = deque(maxlen=6)
    legacy_published = 0
    publisher_receipts = 0
    publisher_summaries = 0
    for _, message in entries:
        for line in message.splitlines():
            line = line.strip()
            if line.startswith("RUNNING_SOURCES_ONLY_CYCLE"):
                m = RE_LIMITS.search(line)
                if m:
                    state["search_limit"], state["stage_limit"], state["publish_limit"] = (
                        int(v) for v in m.groups())
                state["phase"] = "Preparing catalog / processing source queue"
            elif line == "=== DISCOVERY ===":
                state["phase"] = "Searching Japanese subtitle providers"
            elif line == "=== STAGE CANDIDATES ===":
                state["phase"] = "Downloading available Japanese subtitles"
                state["current"] = ""
            elif line == "=== PUBLISH VERIFIED JA ===":
                state["phase"] = "QA / timing synchronization / publication"
                state["current"] = ""
            elif (m := RE_SEARCH_PLAN.search(line)):
                state["search_planned"] = int(m.group(1))
            elif (m := RE_SEARCH_START.search(line)):
                state["current"] = m.group(3)
            elif (m := RE_SEARCH_DONE.search(line)):
                idx, _, verdict = m.groups()
                state["search_completed"] = max(state["search_completed"], int(idx))
                if verdict == "PLAUSIBLE":
                    state["search_found"] += 1
                elif verdict == "NONE":
                    state["search_none"] += 1
                elif verdict == "REVIEW":
                    state["search_review"] += 1
                else:
                    state["search_errors"] += 1
            elif (m := RE_STAGE_PLAN.search(line)):
                state["stage_planned"] = int(m.group(1))
            elif (m := RE_STAGE_START.search(line)):
                state["stage_attempts"] = max(state["stage_attempts"], int(m.group(1)))
                state["current"] = m.group(3)
            elif line.startswith("STAGED:"):
                state["staged"] += 1
                notable.append("Downloaded Japanese subtitle (staged)")
            elif line.startswith("PROVIDER_LIMIT_REACHED:"):
                state["provider_limited"] = True
                notable.append("Provider allowance reached; downloads stopped")
            elif (m := RE_MEDIA_PLAN.search(line)):
                state["publish_title_planned"] = int(m.group(2))
            elif line.startswith("MEDIA:"):
                state["publish_title_checked"] += 1
            elif line.startswith("RESULT:"):
                # An actual title label is known after its publishing decision.
                name = line.removeprefix("RESULT:").strip()
                state["current"] = name.split("|", 1)[0].strip()
                if " | published_" in line:
                    state["existing_recognized"] += 1
            elif line.startswith("PUBLISHED:"):
                legacy_published += 1
                notable.append("Published Japanese sidecar #" + str(legacy_published))
            elif line.startswith("BRUISER_PUBLISH_ITEM:"):
                # The unified publisher issues a structured receipt after a
                # create-only write. Its logs may ALSO contain PUBLISHED:.
                # Do not count the same track twice.
                try:
                    receipt = json.loads(line.split(":", 1)[1])
                    if receipt.get("result") == "published":
                        publisher_receipts += 1
                except (ValueError, AttributeError, TypeError):
                    pass
            elif line.startswith("QUEUE SUMMARY:"):
                try:
                    summary = json.loads(line.split(":", 1)[1])
                    publisher_summaries += int(summary.get("published_new") or 0)
                except (ValueError, AttributeError, TypeError):
                    pass
            elif line.startswith("HELD:"):
                if state["phase"].startswith("Downloading"):
                    state["stage_holds"] += 1
                elif state["phase"].startswith("QA"):
                    state["publish_holds"] += 1
                    notable.append("Subtitle held; no overwrite")
            elif line.startswith("AUTOFILL_CYCLE_COMPLETE"):
                state["complete"] = True
                state["phase"] = "Completed (source-only)"
                state["current"] = ""
            elif line.startswith(("JA_SOURCE_AUTOFILL_HELD", "BRUISER CYCLE HELD",
                                  "SEARCH PILOT FAILED", "STAGING ERROR",
                                  "QUEUE STOPPED")):
                state["failed"] = True
                state["phase"] = "Stopped / requires attention"
                notable.append("Pipeline error; see service journal")
    # Some publishers emit PUBLISHED, some issue structured receipts, and
    # some emit both. They describe the same writes, never three new tracks.
    state["published"] = max(legacy_published, publisher_receipts,
                             publisher_summaries)
    state["recent"] = list(notable)
    return state


def bar(done, total, width=30):
    if total <= 0:
        return "[" + "·" * width + "] pending"
    n = max(0, min(width, int(width * done / total)))
    return "[" + "█" * n + "░" * (width - n) + "] " + (
        str(min(done, total)) + "/" + str(total) + " (" +
        str(min(100, int(100 * done / total))) + "%)")


def format_time(seconds):
    if seconds < 0:
        return "unknown"
    h, m = divmod(int(seconds), 3600)
    mm, ss = divmod(m, 60)
    return (f"{h}h {mm:02}m" if h else f"{mm}m {ss:02}s")


def parse_unit_state(payload):
    props = dict(line.split("=", 1) for line in payload.splitlines() if "=" in line)
    return props.get("ActiveState", "unknown"), props.get("SubState", "unknown")


def load(*, run=call):
    raw = run(["journalctl", "--user", "-u", SERVICE,
               "-o", "json", "-n", str(JOURNAL_ROWS), "--no-pager"],
              timeout=25)
    state = parse(events_from_jsonl(raw))
    try:
        status = run(["systemctl", "--user", "show", SERVICE,
                      "-p", "ActiveState", "-p", "SubState",
                      "--no-pager"], timeout=15)
        state["service_state"], state["sub_state"] = parse_unit_state(status)
    except (RuntimeError, subprocess.TimeoutExpired):
        state["service_state"], state["sub_state"] = "unknown", "unknown"
    try:
        timer = run(["systemctl", "--user", "list-timers", "--all",
                     TIMER, "--no-pager", "--no-legend"], timeout=15)
        first = next((x.strip() for x in timer.splitlines() if TIMER in x), "")
        state["next_run"] = first.split(TIMER, 1)[0].strip() if first else "not scheduled"
    except (RuntimeError, subprocess.TimeoutExpired):
        state["next_run"] = "unavailable"
    return state


def render(state, now=None):
    now = time.time() if now is None else now
    service = state.get("service_state", "unknown")
    current = state["current"][:92] if state["current"] else "No active title"
    output = [
        "BRUISER SUBHUB  |  JAPANESE SOURCED-SUBTITLE MONITOR",
        "=" * 68,
        f"Service: {service}/{state.get('sub_state', 'unknown')}  |  "
        f"Phase: {state['phase']}",
    ]
    if state["has_run"] and state["started"]:
        output.append("Elapsed since cycle start: " +
                      format_time(max(0, now - state["started"])))
    else:
        output.append("No source-only cycle found in the recent journal.")
    output.extend([
        "",
        "SEARCH      " + bar(state["search_completed"], state["search_planned"]),
        "  Matched titles: " + str(state["search_found"]) +
        "  |  No results: " + str(state["search_none"]) +
        "  |  Review: " + str(state["search_review"]) +
        "  |  Errors: " + str(state["search_errors"]),
        "DOWNLOADS   " + bar(state["stage_attempts"], state["stage_planned"]),
        "  Staged: " + str(state["staged"]) +
        "  |  Held: " + str(state["stage_holds"]) +
        "  |  Download ceiling: " + str(state["stage_limit"] or "?"),
        "PUBLISHING  " + bar(state["publish_title_checked"],
                              state["publish_title_planned"]),
        "  Newly published: " + str(state["published"]) +
        "  |  Held: " + str(state["publish_holds"]) +
        "  |  Recognized earlier: " + str(state["existing_recognized"]) +
        "  |  Publication ceiling: " + str(state["publish_limit"] or "?"),
        "",
        "Current: " + current,
        "Next scheduled: " + state.get("next_run", "unknown"),
        "",
        "RECENT ACTIVITY",
    ])
    output.extend("  " + x for x in (state["recent"] or ["No activity yet"]))
    output.extend([
        "",
        "Read-only. Ctrl+C closes this dashboard; the OptiPlex job keeps running.",
        "Progress bars reflect selected/checked items, not guaranteed availability.",
    ])
    if state["failed"]:
        output.append("WARNING: See journalctl --user -u " + SERVICE + " -n 80")
    return "\n".join(output)


def self_test():
    sample = [
        (10, "RUNNING_SOURCES_ONLY_CYCLE search_budget=600 stage_budget=200 publish_limit=200"),
        (11, "=== DISCOVERY ==="),
        (12, "Search requests planned: 4 | budget: 600"),
        (13, "[1/4] SEARCHING: Fargo (1996)"),
        (14, "[1/4] PLAUSIBLE: plausible=1"),
        (15, "[2/4] SEARCHING: Baskin (2015)"),
        (16, "[2/4] NONE: plausible=0"),
        (17, "=== STAGE CANDIDATES ==="),
        (18, "Selected: 1 | budget: 200"),
        (19, "[1/1] STAGING: Fargo (1996)"),
        (20, "STAGED: /tmp/example.ja.srt"),
        (21, "=== PUBLISH VERIFIED JA ==="),
        (22, "Staged candidates: 2 | unique titles: 2 | max new sidecars: 200"),
        (23, "MEDIA: ffffff | candidate IDs: 123"),
        (24, "RESULT: Fargo (1996) | ready_ffsubsync"),
        (25, "PUBLISHED: /media/example.ja.srt"),
        (26, "AUTOFILL_CYCLE_COMPLETE"),
    ]
    s = parse(sample)
    assert s["search_completed"] == 2 and s["search_planned"] == 4
    assert s["search_found"] == 1 and s["search_none"] == 1
    assert s["stage_attempts"] == 1 and s["staged"] == 1
    assert s["published"] == 1 and s["complete"]
    assert "50%" in bar(2, 4)
    assert "Newly published: 1" in render(s, now=29)
    print("SOURCE TRACKER SELF-TEST PASSED: journal parsing, bars, no worker actions")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--watch", action="store_true",
                        help="refresh in place, showing the existing systemd worker")
    parser.add_argument("--interval", type=int, default=8,
                        help="watch refresh in seconds (5..120)")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)
    if args.self_test:
        self_test()
        return
    if not 5 <= args.interval <= 120:
        parser.error("--interval must be 5..120")
    try:
        while True:
            try:
                view = render(load())
            except (RuntimeError, subprocess.TimeoutExpired, OSError) as error:
                view = ("SOURCE DASHBOARD UNAVAILABLE: " + type(error).__name__ +
                        "\nCheck the OptiPlex user-systemd journal.")
            if args.watch and sys.stdout.isatty():
                print("\x1b[H\x1b[2J", end="")
            print(view, flush=True)
            if not args.watch:
                break
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nDashboard detached. The source-only service remains running.",
              flush=True)


if __name__ == "__main__":
    main()
