#!/usr/bin/env python3
"""Standalone SubHub status and bounded owner controls over existing services.

No direct subtitle or provider calls. HTTP binds only to loopback and owner
actions require the token plus an exact same-origin request.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import secrets
import hmac
from pathlib import Path
import re
import sqlite3
import subprocess
import time
from urllib.parse import urlsplit

ROOT = Path.home() / "bruiser-pilot" / "batch-control"
STATE_FILE = ROOT / "current.json"
HTML = Path(__file__).with_name("subhub_dashboard.html")
BATCH_UNIT = "bruiser-subhub-batch.service"
SCHEDULED_UNIT = "bruiser-ja-source-autofill.service"
PLAMO_MOVIES = Path.home() / "bruiser-pilot/subhub-translation"
PLAMO_EPISODES = Path.home() / "bruiser-pilot/plamo3-ab/american-dad-existing-english-batch"
PLAMO_SINGLE = Path.home() / "bruiser-pilot/plamo3-ab/american-dad-one-episode"
PLAMO_MOVIE_UNIT = "bruiser-asabove-plamo.service"
OWNER_TOKEN = secrets.token_urlsafe(32)
try:
    from .subhub_opensubtitles_quota import get_quota
except ImportError:
    from subhub_opensubtitles_quota import get_quota
_QUOTA_CACHE = {"at":0.0,"value":{"known":False,"reason":"not_checked"}}


def quota_snapshot():
    now = time.monotonic()
    if now - _QUOTA_CACHE["at"] >= 300 or not _QUOTA_CACHE["at"]:
        try:
            value=get_quota(timeout=28)
        except (OSError,RuntimeError,subprocess.TimeoutExpired):
            value={"known":False,"reason":"quota_probe_unavailable"}
        _QUOTA_CACHE.update(at=now,value=value)
    return dict(_QUOTA_CACHE["value"])

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
EVENTS = ("SEARCHING:", "STAGING:", "STAGED:", "PUBLISHED:", "RESULT:",
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
    """Treat long-running oneshot 'activating' as BUSY, never safe to start again."""
    try:
        result = subprocess.run(
            ["systemctl", "--user", "show", "--property=ActiveState",
             "--value", unit],
            stdin=subprocess.DEVNULL, capture_output=True, text=True,
            check=False, timeout=4)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError("cannot_verify_service_state") from exc
    if result.returncode:
        raise RuntimeError("cannot_verify_service_state")
    state = result.stdout.strip()
    if state in ("active", "activating", "reloading", "deactivating"):
        return True
    if state in ("inactive", "failed"):
        return False
    raise RuntimeError("unknown_service_state")


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


def publishing_item_label(lines, phase):
    """Show the actual publication phase, never a stale search/staging title.

    The running worker logs MEDIA IDs before processing but only reveals the
    human-readable title in a RESULT line after validation. Until then, show
    the actual live position, not a guessed movie name.
    """
    progress = publishing_progress(lines, phase)
    if progress is None:
        return "Checking saved Japanese subtitles (current title unavailable)"
    current, total = progress["current"], progress["total"]
    result_title = ""
    seen_phase = False
    for line in lines:
        if line.startswith("=== PHASE "):
            stage = line[len("=== PHASE "):].split(" ", 1)[0]
            seen_phase = stage == phase
            if seen_phase:
                result_title = ""
        elif seen_phase and line.startswith("MEDIA:"):
            result_title = ""
        elif seen_phase and line.startswith("RESULT:"):
            result_title = safe_text(line[len("RESULT:"):].split(" | ", 1)[0].strip(), 110)
    position = f"{current} / {total}" if total else str(current)
    if result_title:
        return f"Last evaluated: {result_title} (item {position})"
    if current:
        return f"Validating subtitle {position} (title not yet reported)"
    return "Preparing Japanese subtitles for validation"


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
        "current_item": (publishing_item_label(lines, phase)
                         if phase in ("sync_and_publish", "recover_already_staged")
                         else safe_text(doc.get("last_item"), 160)
                         if phase in ("search_opensubtitles", "stage_matched_japanese")
                         else "Checking saved subtitle queue" if phase == "reconcile_queue"
                         else "Batch complete" if phase == "completed"
                         else "Worker preparing next operation"),
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



def _plamo_running_ids():
    """Observe actual worker process commands, never assume queued == running."""
    try:
        result=subprocess.run(
            ["ps","-eo","args="],capture_output=True,text=True,check=False,
            stdin=subprocess.DEVNULL,timeout=4)
        if result.returncode:
            return set()
        return {match.group(1) for line in result.stdout.splitlines()
                if "subhub_plamo_handoff.py" in line
                for match in [re.search(
                    r"--jellyfin-id(?:=|\s+)([a-f0-9]{32})(?:\s|$)",line)]
                if match}
    except (OSError,subprocess.TimeoutExpired):
        return set()


def _plamo_checkpoint(folder, meta, kind, running_ids, batch_running):
    """Immutable source identity + actual SQLite committed cues, no media edits."""
    jid=str(meta.get("jellyfin_id") or "")
    video=Path(str(meta.get("video") or ""))
    total=meta.get("cue_count")
    if (not isinstance(total,int) or not 1<=total<=12000
            or not video.is_absolute() or not video.suffix.lower()
            in (".mp4",".mkv",".avi",".m4v",".webm",".mov",".ts",".m2ts")):
        return None
    if kind=="movie" and not re.fullmatch(r"[a-f0-9]{32}",jid):
        return None
    db_path=folder/"progress.sqlite3"
    processed, translated, held, non_dialogue, compute_seconds=(0,0,0,0,0.)
    if db_path.exists():
        if (db_path.is_symlink() or not db_path.is_file()
                or db_path.stat().st_uid!=os.getuid()
                or db_path.stat().st_mode & 0o002):
            return None
        with sqlite3.connect("file:"+str(db_path.resolve())+"?mode=ro",
                             uri=True,timeout=2) as db:
            db.execute("PRAGMA query_only=ON")
            processed,translated,held,non_dialogue,compute_seconds=db.execute("""
                SELECT COUNT(*),
                    COALESCE(SUM(CASE WHEN status='translated' THEN 1 ELSE 0 END),0),
                    COALESCE(SUM(CASE WHEN status='held_translation' THEN 1 ELSE 0 END),0),
                    COALESCE(SUM(CASE WHEN status='non_dialogue_passthrough'
                                      THEN 1 ELSE 0 END),0),
                    COALESCE(SUM(seconds),0)
                FROM translation""").fetchone()
    if processed>total or translated+held+non_dialogue!=processed:
        return None
    sidecar=video.with_name(video.stem+".ja.PLaMo8B.srt")
    published=(not sidecar.is_symlink() and sidecar.is_file()
               and 0<sidecar.stat().st_size<=2_000_000)
    # Movie jobs have individual process identities. The older American Dad
    # batch does not expose which episode is active; do not guess.
    active=(jid in running_ids) if kind=="movie" else False
    if published:
        state="published_with_review" if held else "published"
    elif active:
        state="translating"
    elif processed==total and total:
        state="awaiting_publication"
    elif held:
        state="needs_resume_with_holds"
    else:
        state="needs_resume" if processed else "ready_or_queued"
    title=(video.parent.name if kind=="movie" else
           "American Dad! "+safe_text(meta.get("episode"),20))
    title=safe_text(title,110)
    return {
        "id":safe_text(folder.name,72),"kind":kind,
        "jellyfin_id":jid if kind=="movie" else "",
        "title":title,"state":state,"active":active,
        "processed":int(processed),"translated":int(translated),
        "held":int(held),"non_dialogue":int(non_dialogue),
        "total":total,"percent":round(100*processed/total,1),
        "compute_seconds":round(float(compute_seconds),1),
        "published":published,
        "last_checkpoint_utc":(
            datetime.fromtimestamp(db_path.stat().st_mtime,timezone.utc).isoformat()
            if db_path.exists() else ""),
    }


def translation_jobs(movie_root=PLAMO_MOVIES,
                     episode_root=PLAMO_EPISODES,
                     single_root=PLAMO_SINGLE):
    """One read-only view of existing PLaMo jobs; no Gemma or provider calls."""
    running_ids=_plamo_running_ids()
    batch_running=False  # Legacy batch lacks per-episode identity.
    jobs=[]
    locations=(
        (movie_root,"movie","ja-*","manifest.json"),
        (episode_root,"episode","S*","episode.json"),
        (single_root.parent,"episode",single_root.name,"episode.json"),
    )
    for root,kind,pattern,manifest_name in locations:
        if not root.is_dir() or root.is_symlink():
            continue
        if root.stat().st_uid!=os.getuid():
            continue
        for folder in list(root.glob(pattern))[:300]:
            if not folder.is_dir() or folder.is_symlink():
                continue
            manifest=folder/manifest_name
            if (not manifest.is_file() or manifest.is_symlink()
                    or manifest.stat().st_uid!=os.getuid()
                    or manifest.stat().st_mode & 0o077
                    or manifest.stat().st_size>50_000):
                continue
            try:
                meta=json.loads(manifest.read_text("utf-8"))
                if not isinstance(meta,dict):
                    continue
                item=_plamo_checkpoint(folder,meta,kind,running_ids,batch_running)
                if item:
                    jobs.append(item)
            except (OSError,ValueError,TypeError,sqlite3.Error,RuntimeError):
                continue
    jobs.sort(key=lambda x:(
        0 if x["active"] else 1,
        0 if not x["published"] else 1,
        x["title"].casefold()))
    # Do not silently omit running jobs if previous batches have many artifacts.
    return jobs[:150]


def translation_snapshot():
    jobs=translation_jobs()
    counts=Counter(job["state"] for job in jobs)
    running=sum(1 for job in jobs if job["active"])
    return {"state":"active" if running else "idle",
            "engine":"PLaMo 8B","jobs":jobs,
            "total_jobs":len(jobs),"active_jobs":running,
            "held_cues":sum(job["held"] for job in jobs),
            "published_jobs":sum(int(job["published"]) for job in jobs),
            "by_state":dict(counts)}



def scheduled_source_activity(active, max_lines=240):
    """Observe the CURRENT scheduled publisher, not yesterday's manual batch.

    Journal is bounded. Numbers derived here are explicitly counts within
    the returned journal window, never lifetime source totals.
    """
    result={"active":bool(active),"phase":"idle","phase_label":"No scheduled source job running",
            "current_item":"","last_completed":"","recent_publications":0,
            "events":[],"sample_window":"latest 240 journal lines"}
    if not active:
        return result
    try:
        completed=subprocess.run([
            "journalctl","--user","-u",SCHEDULED_UNIT,"-o","cat",
            "-n",str(max_lines),"--no-pager"],
            capture_output=True,text=True,timeout=5,
            stdin=subprocess.DEVNULL,check=False)
    except (OSError,subprocess.TimeoutExpired):
        result.update(phase="running",phase_label="Automatic subtitle processing",
                      current_item="Worker active; journal unavailable")
        return result
    if completed.returncode:
        result.update(phase="running",phase_label="Automatic subtitle processing",
                      current_item="Worker active; journal unavailable")
        return result
    lines=completed.stdout.splitlines()
    recent=[]
    last_media=""
    last_result=""
    last_published=""
    for line in lines:
        line=line.strip()
        if line.startswith("MEDIA:"):
            last_media=safe_text(line.split("|",1)[0].removeprefix("MEDIA:").strip(),45)
        elif line.startswith("RESULT:"):
            last_result=safe_text(line.removeprefix("RESULT:").split("|",1)[0].strip(),100)
            recent.append("Validated "+last_result)
        elif line.startswith("PUBLISHED:"):
            result["recent_publications"]+=1
            last_published=last_result or "Untitled media"
            recent.append("Published "+last_published)
            last_result=""
        elif any(term in line for term in ("SEARCHING:","STAGING:",
                                           "THERMAL_PAUSE","HELD:",
                                           "PROVIDER_LIMIT_REACHED")):
            recent.append(safe_text(line,160))
    # The publisher often emits MEDIA:<id> first, then RESULT:<title>.
    # Do not repeat the previous title as if it were the current title.
    publish_active=False
    try:
        ps=subprocess.run(["ps","-eo","args="],capture_output=True,text=True,
                          timeout=4,stdin=subprocess.DEVNULL,check=False)
        publish_active=(ps.returncode==0 and
            any("ja_first_publish_queue.py" in line and
                "/usr/bin/python3" in line for line in ps.stdout.splitlines()))
    except (OSError,subprocess.TimeoutExpired):
        pass
    result.update(phase="publishing" if publish_active else "running",
                  phase_label=("Publishing Japanese subtitles"
                               if publish_active else "Automatic Japanese sourcing"),
                  current_item=("Processing media "+last_media+" (title pending)"
                                if publish_active and last_media else
                                "Working through the automatic subtitle queue"),
                  last_completed=last_published,
                  events=recent[-9:])
    return result


def live_source_snapshot(result, scheduled):
    """Show scheduled work as LIVE; old manual batch remains a distinct record."""
    result["source_job"]=scheduled
    result["source_active"]=bool(result.get("batch_active") or scheduled["active"])
    result["manual_batch_history"]={
        "batch_id":result.get("batch_id",""),
        "state":result.get("state","idle"),
        "phase":result.get("phase","idle"),
        "last_item":result.get("current_item","")}
    if scheduled["active"]:
        result["state"]="scheduled_source_running"
        result["phase"]="scheduled_"+scheduled["phase"]
        result["phase_label"]=scheduled["phase_label"]
        result["current_item"]=scheduled["current_item"]
        result["updated_utc"]=""  # old manual timestamp must NOT be shown as live
        result["stale_seconds"]=None
        result["events"]=scheduled["events"]
        result["batch_id"]=""      # not yesterday's manual job
    return result


def status_payload():
    doc = checked_state()
    log = trusted_log(doc) if doc else None
    lines = tail_lines(log)
    manual=unit_active(BATCH_UNIT)
    scheduled=unit_active(SCHEDULED_UNIT)
    result=snapshot(doc, manual, False, lines)
    result=live_source_snapshot(result,scheduled_source_activity(scheduled))
    result["translation"]=translation_snapshot()
    result["provider_quota"]=quota_snapshot()
    result["controls"]=control_availability()
    return result



def source_controls(action):
    """Bounded owner commands only; re-use existing source services/locks."""
    manual=unit_active(BATCH_UNIT)
    scheduled=unit_active(SCHEDULED_UNIT)
    script=Path.home()/".local/bin/bruiser-subs"
    if action=="start-auto":
        if manual or scheduled:
            raise RuntimeError("Source job already running")
        command=["systemctl","--user","start","--no-block",SCHEDULED_UNIT]
    elif action=="stop-auto":
        if not scheduled:
            raise RuntimeError("No automatic job running")
        command=["systemctl","--user","stop","--no-block",SCHEDULED_UNIT]
    elif action=="start-manual":
        if manual or scheduled:
            raise RuntimeError("Another source job is active")
        if not script.is_file() or script.is_symlink():
            raise RuntimeError("Installed bruiser-subs controller unavailable")
        command=[str(script),"start","--cycles","1"]
    elif action=="stop-manual":
        if not manual:
            raise RuntimeError("No manual batch running")
        if not script.is_file() or script.is_symlink():
            raise RuntimeError("Installed bruiser-subs controller unavailable")
        command=[str(script),"stop"]
    else:
        raise ValueError("unsupported_control")
    done=subprocess.run(command,capture_output=True,text=True,
                        stdin=subprocess.DEVNULL,timeout=45,check=False)
    if done.returncode!=0:
        raise RuntimeError("Command failed: "+safe_text(done.stderr or done.stdout,180))
    return {"ok":True,"action":action,"result":safe_text(done.stdout,150)}


def control_availability():
    manual=unit_active(BATCH_UNIT)
    scheduled=unit_active(SCHEDULED_UNIT)
    return {"available":True,
            "start_auto":not manual and not scheduled,
            "stop_auto":scheduled,
            "start_manual":not manual and not scheduled,
            "stop_manual":manual}


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
        elif target == "/api/owner-token":
            self.write(200,json.dumps({"token":OWNER_TOKEN}).encode("utf-8"))
        elif target == "/healthz":
            self.write(200, b'{"status":"ok","mode":"owner_controls"}')
        else:
            self.write(404, b'{"error":"not_found"}')

    def do_POST(self):
        target=urlsplit(self.path).path
        if target not in (
            "/api/control/start-auto","/api/control/stop-auto",
            "/api/control/start-manual","/api/control/stop-manual"):
            self.write(405,b'{"error":"controls_not_available_in_v0_1"}')
            return
        origin=self.headers.get("Origin","")
        allowed={
            "http://127.0.0.1:"+str(self.server.server_port),
            "http://localhost:"+str(self.server.server_port)
        }
        host=self.headers.get("Host","")
        token=self.headers.get("X-Subhub-Token","")
        size=self.headers.get("Content-Length","")
        if (origin not in allowed or
                host not in {str(self.server.server_address[0])+":"+
                             str(self.server.server_port),
                             "localhost:"+str(self.server.server_port)} or
                not hmac.compare_digest(token,OWNER_TOKEN) or
                self.headers.get("Content-Type","").split(";")[0].strip()
                != "application/json" or size not in ("0","2")):
            self.write(403,b'{"error":"owner_control_access_denied"}')
            return
        if size=="2" and self.rfile.read(2)!=b"{}":
            self.write(400,b'{"error":"empty_json_object_required"}')
            return
        try:
            value=source_controls(target.rsplit("/",1)[-1])
            self.write(200,json.dumps(value).encode("utf-8"))
        except (OSError,RuntimeError,subprocess.TimeoutExpired) as exc:
            self.write(409,json.dumps(
                {"error":safe_text(str(exc),180)}).encode("utf-8"))

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
