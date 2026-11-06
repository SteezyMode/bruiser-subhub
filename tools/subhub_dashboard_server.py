#!/usr/bin/env python3
"""Standalone, read-only SubHub web dashboard over durable batch state.

No source-worker imports, writes to media, provider calls or control operations.
HTTP binds ONLY to loopback. Reach remotely through an authenticated SSH tunnel.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import subprocess
from urllib.parse import urlsplit

ROOT = Path.home() / "bruiser-pilot" / "batch-control"
STATE_FILE = ROOT / "current.json"
HTML = Path(__file__).with_name("subhub_dashboard.html")
BATCH_UNIT = "bruiser-subhub-batch.service"
SCHEDULED_UNIT = "bruiser-ja-source-autofill.service"
PHASES = {
    "queued": "Preparing the source engine",
    "reconcile_queue": "Reconcile saved subtitle work",
    "recover_already_staged": "Recover previously staged Japanese subtitles",
    "search_opensubtitles": "Search OpenSubtitles for Japanese subtitles",
    "stage_matched_japanese": "Download matched Japanese subtitles",
    "sync_and_publish": "Align, validate and publish subtitles",
    "completed": "Batch complete",
    "failed": "Batch failed",
}
CLEAN = re.compile(r"[\x00-\x1f\x7f-\x9f]")
EVENTS = ("SEARCHING:", "STAGING:", "STAGED:", "PUBLISHED:",
          "HELD:", "FFSUBSYNC HELD:", "DIRECT HELD:",
          "PROVIDER_LIMIT_REACHED", "BRUISER_BATCH_COMPLETE",
          "BRUISER_BATCH_FAILED", "QUEUE SUMMARY:", "BATCH RESULT:")


def safe_text(value, limit=180):
    return CLEAN.sub(" ", str(value or ""))[:limit]


def checked_state(path=STATE_FILE):
    path = Path(path)
    if not path.exists():
        return {}
    if (path.is_symlink() or not path.is_file()
            or path.stat().st_mode & 0o077
            or path.stat().st_uid != os.getuid()):
        raise RuntimeError("unsafe batch status file")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise RuntimeError("invalid batch status format")
    return data


def unit_active(unit):
    try:
        result = subprocess.run(
            ["systemctl", "--user", "is-active", "--quiet", unit],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, check=False, timeout=4)
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def trusted_log(doc):
    raw = doc.get("log")
    if not isinstance(raw, str) or not raw:
        return None
    path = Path(raw)
    if (path.parent != ROOT or path.is_symlink() or not path.is_file()
            or path.stat().st_mode & 0o077
            or path.stat().st_uid != os.getuid()):
        return None
    return path


def tail_lines(path, max_bytes=240_000):
    if path is None:
        return []
    with path.open("rb") as stream:
        stream.seek(0, 2)
        end = stream.tell()
        stream.seek(max(0, end-max_bytes))
        return stream.read(max_bytes).decode("utf-8", "replace").splitlines()


def recent_activity(lines, limit=9):
    selected = []
    for line in lines:
        if line.startswith("BRUISER_PUBLISH_ITEM:"):
            try:
                payload = json.loads(line.partition(":")[2])
                outcome = payload.get("result")
                if outcome == "published":
                    selected.append("A Japanese subtitle was published")
                elif outcome == "held":
                    selected.append("Publication held: " +
                                    safe_text(payload.get("reason"), 110))
                else:
                    selected.append("Previously published subtitle recognized")
            except (ValueError, TypeError):
                selected.append("Publication event recorded")
        elif any(event in line for event in EVENTS):
            selected.append(safe_text(line, 200))
    return selected[-limit:]


def publishing_progress(lines, phase):
    if phase not in ("sync_and_publish", "recover_already_staged"):
        return None
    block = None
    for i, line in enumerate(lines):
        if line.startswith("=== PHASE "):
            name = line[len("=== PHASE "):].split(" ", 1)[0]
            block = i if name == phase else None
    if block is None:
        return None
    total, completed = 0, 0
    for line in lines[block:]:
        if line.startswith("=== UNIFIED JAPANESE SUBTITLE PUBLISH QUEUE ==="):
            total, completed = 0, 0
        match = re.search(r"unique titles:\s*(\d+)", line)
        if match:
            total = int(match.group(1))
        if line.startswith("MEDIA:"):
            completed += 1
    return {"current": completed, "total": total}


def int_value(value):
    try:
        return max(0, int(value))
    except (TypeError, ValueError, OverflowError):
        return 0


def snapshot(doc, batch_active=False, scheduled_active=False, lines=()):
    if not doc:
        return {
            "schema": "subhub-dashboard-v1", "state": "idle",
            "phase": "idle", "phase_label": "No batch started",
            "batch_id": "", "cycle": 0, "cycles": 0, "cycle_done": 0,
            "current_item": "", "updated_utc": "", "stale_seconds": None,
            "phase_progress": {"current": 0, "total": 0},
            "search_progress": {"current": 0, "total": 0},
            "counts": {}, "holds": [], "events": [], "quota_exhausted": False,
            "source_active": scheduled_active, "batch_active": False,
            "translation": {"state": "not_connected"},
            "controls": {"available": False, "reason": "Read-only first release"},
        }
    stored = str(doc.get("state") or "unknown")
    if batch_active:
        effective = "running"
    elif scheduled_active:
        effective = "scheduled_source_running"
    elif stored in ("running", "starting"):
        effective = "interrupted"
    else:
        effective = stored if stored in ("completed", "failed", "stopped") else "idle"
    phase = safe_text(doc.get("phase"), 60)
    counts = {safe_text(k, 50): int_value(v)
              for k, v in (doc.get("counts") or {}).items()
              if isinstance(k, str)}
    cycle = int_value(doc.get("cycle"))
    cycles = int_value(doc.get("cycles"))
    started = counts.get("search_started", 0)
    total_searches = cycles * int_value(doc.get("search_budget"))
    finished = sum(counts.get(k, 0) for k in (
        "search_plausible", "search_review", "search_none", "search_errors"))
    progress = {"current": int_value(doc.get("phase_current")),
                "total": int_value(doc.get("phase_total"))}
    if phase in ("sync_and_publish", "recover_already_staged") and not progress["total"]:
        progress = publishing_progress(lines, phase) or progress
    updated = safe_text(doc.get("updated_utc"), 48)
    stale = None
    try:
        stamp = datetime.fromisoformat(updated)
        if stamp.tzinfo is not None:
            stale = max(0, int((datetime.now(timezone.utc)-stamp).total_seconds()))
    except (ValueError, TypeError):
        pass
    holds = [{"reason": safe_text(reason, 110), "count": int_value(number)}
             for reason, number in Counter(doc.get("held_reasons") or {}).most_common(5)]
    return {
        "schema": "subhub-dashboard-v1",
        "state": effective,
        "phase": phase,
        "phase_label": PHASES.get(phase, safe_text(phase.replace("_", " ").title())),
        "batch_id": safe_text(doc.get("batch_id"), 65),
        "cycle": cycle, "cycles": cycles,
        "cycle_done": cycles if stored == "completed" else max(0, cycle-1),
        "current_item": safe_text(doc.get("last_item"), 160),
        "updated_utc": updated, "stale_seconds": stale,
        "phase_progress": progress,
        "search_progress": {"current": started, "total": total_searches},
        "counts": {**counts, "search_completed": finished,
                   "search_in_flight": max(0, started-finished)},
        "holds": holds, "events": recent_activity(lines),
        "quota_exhausted": bool(doc.get("quota_exhausted")),
        "source_active": batch_active or scheduled_active,
        "batch_active": batch_active,
        "translation": {"state": "not_connected"},
        "controls": {"available": False, "reason": "Read-only first release"},
    }


def status_payload():
    doc = checked_state()
    log = trusted_log(doc) if doc else None
    lines = tail_lines(log)
    return snapshot(doc, unit_active(BATCH_UNIT),
                    unit_active(SCHEDULED_UNIT), lines)


class Handler(BaseHTTPRequestHandler):
    server_version = "SubHubDashboard/0.1"

    def write(self, code, body, media_type="application/json; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", media_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy",
                         "default-src 'none'; connect-src 'self'; "
                         "script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
                         "frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        target = urlsplit(self.path).path
        if target == "/":
            try:
                body = HTML.read_bytes()
            except OSError:
                self.write(503, b"Dashboard assets unavailable", "text/plain")
                return
            self.write(200, body, "text/html; charset=utf-8")
        elif target == "/api/status":
            try:
                body = json.dumps(status_payload(), ensure_ascii=False).encode("utf-8")
                self.write(200, body)
            except (OSError, ValueError, RuntimeError, TypeError, json.JSONDecodeError):
                self.write(503, b'{"error":"status_unavailable"}')
        elif target == "/healthz":
            self.write(200, b'{"status":"ok","mode":"read_only"}')
        else:
            self.write(404, b'{"error":"not_found"}')

    def do_POST(self):
        self.write(405, b'{"error":"controls_not_available_in_v0_1"}')

    def log_message(self, format, *args):
        # No query strings or auth metadata in process logs.
        pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=17876)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("port must be 1024..65535")
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    server.daemon_threads = True
    print("SUBHUB_DASHBOARD_READY loopback-only port=" + str(args.port), flush=True)
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
