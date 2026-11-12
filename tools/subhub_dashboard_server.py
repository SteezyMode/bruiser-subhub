#!/usr/bin/env python3
"""Standalone SubHub status and bounded owner controls over existing services.

No direct subtitle or provider calls. HTTP binds only to loopback and owner
actions require the token plus an exact same-origin request.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import secrets
import hmac
from pathlib import Path
import re
import sqlite3
import subprocess
import tempfile
import time
from urllib.parse import urlsplit, parse_qs, quote
import sys

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
    from . import ja_first_source_tracker as source_tracker
except ImportError:
    import ja_first_source_tracker as source_tracker
try:
    from . import subhub_translation_batch as season_batch
except ImportError:
    import subhub_translation_batch as season_batch
try:
    from . import subhub_season_sources as season_sources
except ImportError:
    import subhub_season_sources as season_sources
try:
    from . import subhub_finish_scope as finish_scope
except ImportError:
    import subhub_finish_scope as finish_scope

try:
    from . import subhub_library_coverage as global_coverage
except ImportError:
    import subhub_library_coverage as global_coverage
try:
    from . import subhub_library_browser as media_browser
except ImportError:
    import subhub_library_browser as media_browser
try:
    from . import subhub_finish_titles as finish_titles
except ImportError:
    import subhub_finish_titles as finish_titles

TRANSLATION_UNIT = "bruiser-subhub-translation-batch.service"
FINISH_UNIT = "bruiser-subhub-finish-scope.service"
FINISH_EXEC = Path(__file__).with_name("subhub_finish_scope.py")
SEASON_SOURCE_UNIT = "bruiser-subhub-season-sources.service"
SEASON_SOURCE_EXEC = Path(__file__).with_name("subhub_season_sources.py")
BATCH_EXEC = Path(__file__).with_name("subhub_translation_batch.py")
MOVIE_EXEC = Path(__file__).with_name("subhub_movie_job.py")
MOVIE_UNIT = "bruiser-subhub-movie-ja.service"
JELLYFIN_SOURCE_UNIT = "bruiser-subhub-jellyfin-source.service"
JELLYFIN_SOURCE_EXEC = Path.home() / "bruiser-pilot/subhub-control/subhub_jellyfin_batch.py"
JELLYFIN_SOURCE_STATE = (Path.home() /
                         "bruiser-pilot/ja-first-inventory/jellyfin-source-batch.json")
JELLYFIN_SOURCE_LAUNCH = (Path.home() /
                          "bruiser-pilot/ja-first-inventory/jellyfin-source-launch.json")
DOWNLOAD_LEDGER_DB = (Path.home() /
                      "bruiser-pilot/ja-first-inventory/subhub-provider-download-ledger.sqlite3")
MOVIE_ROOTS = (
    Path("/mnt/2TB/Plex Expansion/Movies"),
    Path("/mnt/BigDisk/Video/Movies"),
)
MOVIE_EXT = {".mkv", ".mp4", ".avi", ".m4v", ".mov"}

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


def american_dad_batch_activity():
    """Verify the saved batch PID belongs to the current PLaMo batch process.

    The queue's completed checkpoints alone never establish live processing.
    This reads only the owner's PID/log and Linux procfs; no worker changes.
    """
    base=PLAMO_EPISODES
    pidfile=base/"batch.pid"
    log=base/"batch.log"
    result={"active":False,"episode":"","pid":None}
    try:
        if (pidfile.is_symlink() or not pidfile.is_file()
                or pidfile.stat().st_uid!=os.getuid()
                or pidfile.stat().st_size>32):
            return result
        raw=pidfile.read_text("ascii").strip()
        if not re.fullmatch(r"[1-9][0-9]{0,9}",raw):
            return result
        pid=int(raw)
        process=Path("/proc")/str(pid)
        if process.stat().st_uid!=os.getuid():
            return result
        command=(process/"cmdline").read_bytes().replace(b"\0",b" ").decode("utf-8","replace")
        if not re.search(r"(?:^|[\s/])plamo8b_american_dad_existing_en_batch\.py(?:\s|$)",command):
            return result
        result.update(active=True,pid=pid)
        if log.is_file() and not log.is_symlink() and log.stat().st_uid==os.getuid():
            lines=tail_lines(log,max_bytes=120_000)
            for line in reversed(lines):
                match=re.search(r"=== EPISODE \d+/\d+: (S\d{2}E\d{2,3}) ===",line)
                if match:
                    result["episode"]=match.group(1)
                    break
                if "=== COMPLETE: published" in line or line.startswith("BATCH_PAUSED"):
                    break
    except (OSError,UnicodeError,ValueError):
        return {"active":False,"episode":"","pid":None}
    return result


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
    held_details = []
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
            if held:
                held_details = [
                    {"cue": int(number), "english": safe_text(en, 300),
                     "japanese": safe_text(ja, 300)}
                    for number, en, ja in db.execute(
                        "SELECT id, english, japanese FROM translation "
                        "WHERE status='held_translation' ORDER BY idx LIMIT 12")
                ]
    if processed>total or translated+held+non_dialogue!=processed:
        return None
    sidecar=video.with_name(video.stem+".ja.PLaMo8B.srt")
    published=(not sidecar.is_symlink() and sidecar.is_file()
               and 0<sidecar.stat().st_size<=2_000_000)
    # Movie jobs have individual process identities. The older American Dad
    # batch does not expose which episode is active; do not guess.
    active=((jid in running_ids) if kind=="movie" else
            bool(batch_running and meta.get("episode")==batch_running))
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
    # The generic PLaMo checkpoint folder is shared by movies AND TV.
    # An episode's immediate parent is often "Season 06", not its title.
    if kind=="movie" and meta.get("kind")=="Episode":
        match=re.search(r"S([0-9]{1,2})E([0-9]{1,3})",video.name,re.I)
        if match:
            series=video.parent.parent.name
            title=(series+" S"+match.group(1).zfill(2)+
                   "E"+match.group(2).zfill(2))
        else:
            title=video.stem
    else:
        title=(video.parent.name if kind=="movie" else
               "American Dad! "+safe_text(meta.get("episode"),20))
    title=safe_text(title,110)
    return {
        "id":safe_text(folder.name,72),"kind":kind,
        "jellyfin_id":jid if kind=="movie" else "",
        "title":title,"state":state,"active":active,
        "processed":int(processed),"translated":int(translated),
        "held":int(held),"held_details":held_details,
        "non_dialogue":int(non_dialogue),
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
    batch=american_dad_batch_activity()
    batch_running=batch["episode"] if batch["active"] else ""
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
                if item and (item["active"] or item["processed"]>0
                             or item["published"]):
                    # A prepared manifest is not a launched translation job.
                    # Exclude no-cue entries such as the unstarted movie pilots.
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
    batch=american_dad_batch_activity()
    return {"state":"active" if running or batch["active"] else "idle",
            "engine":"PLaMo 8B","jobs":jobs,
            "american_dad_batch":batch,
            "total_jobs":len(jobs),"active_jobs":running,
            "held_cues":sum(job["held"] for job in jobs),
            "published_jobs":sum(int(job["published"]) for job in jobs),
            "by_state":dict(counts)}



_SOURCE_CACHE={"when":0.0,"state":None,"active":None}

def scheduled_source_activity(active, max_lines=5000):
    """Current source cycle metrics from the existing, tested journal parser.

    Never mix yesterday's manual-batch counters with the active source worker.
    """
    idle={"active":False,"metrics_available":False,"provider_limited":False,
          "scope":"all",
          "phase":"idle","phase_label":"No automatic source cycle running",
          "current_item":"","events":[],"sample_window":"","started":0,
          "last_event":0,"search_completed":0,"search_planned":0,
          "search_found":0,"search_none":0,"search_review":0,"search_errors":0,
          "search_partial":0,"search_deferred":0,"search_stopped_early":False,"search_stop_reason":"",
          "stage_attempts":0,"stage_planned":0,"staged":0,"stage_holds":0,
          "publish_title_checked":0,"publish_title_planned":0,"published":0,
          "publish_holds":0,"skipped_unchanged":0,"next_actions":{}}
    now=time.monotonic()
    if (_SOURCE_CACHE["state"] is not None and
            _SOURCE_CACHE.get("active") is active and
            now-_SOURCE_CACHE["when"]<8):
        return dict(_SOURCE_CACHE["state"])
    try:
        completed=subprocess.run(
            ["journalctl","--user","-u",SCHEDULED_UNIT,
             "-o","json","-n",str(max_lines),"--no-pager"],
            capture_output=True,text=True,timeout=8,
            stdin=subprocess.DEVNULL,check=False)
        if completed.returncode:
            raise RuntimeError("journal_unavailable")
        details=source_tracker.parse(
            source_tracker.events_from_jsonl(completed.stdout))
        if not details.get("has_run",False):
            if not active:
                return idle
            raise RuntimeError("current_cycle_not_in_journal_window")
        status="source_running" if active else "source_interrupted"
        if details.get("failed",False):
            status="source_held"
        elif details.get("complete",False):
            status="source_completed"
        phase=details.get("phase","Working on Japanese subtitles") if active else {
            "source_held":"Most recent automatic source cycle failed",
            "source_completed":("Source stages finished; search deferred by provider"
                                if details.get("search_stopped_early")
                                else "Selected searches finished; provider coverage incomplete"
                                if details.get("search_partial")
                                else "Most recent automatic source cycle completed"),
            "source_interrupted":"Most recent automatic source cycle interrupted",
        }[status]
        current=safe_text(details.get("current",""),150)
        data={**idle,"active":active,"metrics_available":True,
              "scope":details.get("scope","all"),
              "provider_limited":details.get("provider_limited",False),
              "phase":status,
              "phase_label":safe_text(phase,105),
              "current_item":current or "Preparing the next item",
              "events":[safe_text(x,160) for x in details.get("recent",[])][-9:],
              "sample_window":"latest "+str(max_lines)+" journal events",
              "started":details.get("started",0),
              "last_event":details.get("last_event",0),
              "search_completed":details.get("search_completed",0),
              "search_planned":details.get("search_planned",0),
              "search_found":details.get("search_found",0),
              "search_none":details.get("search_none",0),
              "search_review":details.get("search_review",0),
              "search_partial":details.get("search_partial",0),
              "search_errors":details.get("search_errors",0),
              "search_deferred":details.get("search_deferred",0),
              "search_stopped_early":details.get("search_stopped_early",False),
              "search_stop_reason":details.get("search_stop_reason",""),
              "stage_attempts":details.get("stage_attempts",0),
              "stage_planned":details.get("stage_planned",0),
              "staged":details.get("staged",0),
              "stage_holds":details.get("stage_holds",0),
              "publish_title_checked":details.get("publish_title_checked",0),
              "publish_title_planned":details.get("publish_title_planned",0),
              "published":details.get("published",0),
              "publish_holds":details.get("publish_holds",0),
              "skipped_unchanged":details.get("skipped_unchanged",0),
              "next_actions":details.get("next_actions",{})}
    except (OSError,ValueError,RuntimeError,KeyError,TypeError,subprocess.TimeoutExpired) as exc:
        data={**idle,"active":active,"phase":"source_running",
              "phase_label":"Source worker active — progress unavailable",
              "current_item":safe_text(str(exc),110)}
    _SOURCE_CACHE.update(when=now,state=data,active=active)
    return dict(data)


def live_source_snapshot(result, scheduled):
    """Show scheduled work as LIVE; old manual batch remains a distinct record."""
    result["source_job"]=scheduled
    result["source_active"]=bool(result.get("batch_active") or scheduled["active"])
    result["manual_batch_history"]={
        "batch_id":result.get("batch_id",""),
        "state":result.get("state","idle"),
        "phase":result.get("phase","idle"),
        "last_item":result.get("current_item","")}
    if not scheduled["active"] and scheduled["metrics_available"] and not result.get("batch_active"):
        result["state"]=("completed" if scheduled["phase"]=="source_completed"
                         else "failed" if scheduled["phase"]=="source_held"
                         else "interrupted")
        result["phase_label"]=scheduled["phase_label"]
        result["current_item"]="Last run: "+str(scheduled["search_found"])+" matched, "+str(scheduled["staged"])+" downloaded, "+str(scheduled["published"])+" published"
        result["events"]=scheduled["events"]
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


def movie_subtitle_status(path, *, runner=subprocess.run):
    """Inspect exact movie bytes/sidecars; never trust absence in a stale queue."""
    path=Path(path)
    prefix=path.stem.casefold()+"."
    ext={".srt",".ass",".ssa",".vtt"}
    try:
        for candidate in path.parent.iterdir():
            if candidate.is_symlink() or not candidate.is_file():
                continue
            if candidate.suffix.casefold() not in ext or not (
                    candidate.name.casefold().startswith(prefix)):
                continue
            ending=candidate.name[len(prefix):-len(candidate.suffix)]
            tokens=re.findall(r"[a-z0-9]+",ending.casefold())
            if (any(t in ("ja","jp","jpn","japanese") for t in tokens)
                    and not any(t in ("forced","signs") for t in tokens)):
                return "present", "Japanese subtitle sidecar"
    except OSError:
        return "unknown", "Cannot inspect movie subtitle files"
    try:
        proc=runner([
            "ffprobe","-v","error",
            "-show_entries",
            "stream=codec_type:stream_tags=language:stream_disposition=forced",
            "-of","json",str(path)
        ],capture_output=True,timeout=12,check=False)
        if proc.returncode:
            return "unknown", "Embedded subtitles not verified"
        streams=json.loads(proc.stdout).get("streams")
        if not isinstance(streams,list):
            return "unknown", "Embedded subtitles not verified"
        for item in streams:
            if item.get("codec_type")!="subtitle":
                continue
            language=str((item.get("tags") or {}).get("language") or "").lower()
            forced=(item.get("disposition") or {}).get("forced")
            if language.split("-")[0] in ("ja","jp","jpn","japanese") and forced not in (1,True):
                return "present", "Japanese subtitle embedded in video"
        return "missing", "No Japanese subtitle detected"
    except (OSError,ValueError,TypeError,subprocess.TimeoutExpired):
        return "unknown", "Embedded subtitles not verified"


def movie_jellyfin_inventory(paths):
    """Read last complete Jellyfin movie subtitle classification, if present."""
    result={}
    wanted=set(str(p) for p in paths)
    manifest=global_coverage.latest_manifest()
    if manifest is None:
        return result
    try:
        doc=json.loads(manifest.read_text("utf-8"))
        if doc.get("schema")!=1 or not isinstance(doc.get("items"),list):
            return result
        for entry in doc["items"]:
            if not isinstance(entry,dict) or entry.get("kind")!="Movie":
                continue
            path=str(entry.get("host_path") or "")
            if path in wanted:
                result[path]={
                    "jellyfin_inventory_status":str(entry.get("status") or ""),
                    "jellyfin_inventory_generated":str(doc.get("generated_utc") or ""),
                    "jellyfin_id":str(entry.get("jellyfin_id") or ""),
                }
    except (OSError,ValueError,TypeError):
        return {}
    return result


def movie_queue_evidence(paths):
    """Existing coverage queue and previous Japanese searches; read-only."""
    found={str(p):{"search_attempted":False,"search_outcome":"never",
                   "jellyfin_id":"","fallback_ready":False} for p in paths}
    dbfile=Path.home()/"bruiser-pilot/coverage-queue/coverage.sqlite3"
    searchfile=Path.home()/"bruiser-pilot/ja-first-inventory/japanese-search.sqlite3"
    if not dbfile.is_file() or dbfile.is_symlink():
        return found
    try:
        with sqlite3.connect("file:"+quote(str(dbfile.resolve()),safe="/")+"?mode=ro",uri=True,timeout=3) as db:
            for path,jid,action,state in db.execute("""
                SELECT m.path,m.jellyfin_id,t.action,t.state
                FROM media m LEFT JOIN tasks t ON t.path=m.path
                     AND t.target='ja' AND t.active=1
                WHERE m.kind='Movie'
            """):
                if path not in found:
                    continue
                record=found[path]
                record["jellyfin_id"]=str(jid or "")
                record["fallback_ready"]=bool(
                    action in ("validate_english_for_ja_fallback",
                               "recover_english_for_ja_fallback")
                    and state=="pending")
        if searchfile.is_file() and not searchfile.is_symlink():
            with sqlite3.connect("file:"+quote(str(searchfile.resolve()),safe="/")+"?mode=ro",uri=True,timeout=3) as db:
                byid={v["jellyfin_id"]:v for v in found.values() if v["jellyfin_id"]}
                for jid,outcome in db.execute("SELECT jellyfin_id,outcome FROM searches"):
                    if jid in byid:
                        byid[jid]["search_attempted"]=outcome not in ("in_progress","deferred")
                        byid[jid]["search_outcome"]=str(outcome or "unknown")[:30]
    except (OSError,sqlite3.Error,ValueError):
        pass
    return found


def search_movie_files(title, *, roots=MOVIE_ROOTS):
    """Exact filesystem discovery, independent of stale Jellyfin snapshots.

    Read-only, limited results and traversal. No new directories, media writes
    or provider calls. The movie job revalidates the exact selected file.
    """
    title = str(title or "").strip()
    if not 3 <= len(title) <= 120 or not re.fullmatch(r"[\w\s.,'!():-]+", title):
        raise ValueError("enter_a_movie_title_to_search")
    terms = [t.casefold() for t in re.findall(r"[\w]+", title) if len(t) >= 2]
    if not terms:
        raise ValueError("enter_a_movie_title_to_search")
    matches = []
    visited = 0
    for root in roots:
        if not root.is_dir() or root.is_symlink():
            continue
        for base, folders, files in os.walk(root, followlinks=False):
            depth = len(Path(base).relative_to(root).parts)
            if depth >= 5:
                folders[:] = []
            else:
                folders[:] = [x for x in folders
                              if not (Path(base) / x).is_symlink()]
            for name in files:
                visited += 1
                if visited > 120_000:
                    raise RuntimeError("movie_library_search_limit_reached")
                path = Path(base) / name
                if (path.suffix.casefold() not in MOVIE_EXT or path.is_symlink()
                        or not all(t in (name + " " + path.parent.name).casefold()
                                   for t in terms)):
                    continue
                matches.append({"filename": name, "path": str(path)})
                if len(matches) >= 30:
                    break
            if len(matches) >= 30:
                break
        if len(matches) >= 30:
            break
    evidence=movie_queue_evidence([m["path"] for m in matches])
    jellyfin=movie_jellyfin_inventory([m["path"] for m in matches])
    for movie in matches:
        status,reason=movie_subtitle_status(movie["path"])
        movie.update(evidence.get(movie["path"],{}))
        prior=jellyfin.get(movie["path"],{})
        if prior.get("jellyfin_id") and not movie.get("jellyfin_id"):
            movie["jellyfin_id"]=prior["jellyfin_id"]
        if (status!="present" and
                prior.get("jellyfin_inventory_status")=="existing_japanese_subtitle"):
            status="present"
            reason=("Jellyfin inventory reports Japanese subtitle (as of "
                    +prior.get("jellyfin_inventory_generated","")+")")
        movie.update(japanese_status=status,japanese_detail=reason)
    return matches


def movie_source_status():
    active = unit_active(MOVIE_UNIT)
    recent = []
    try:
        proc = subprocess.run(
            ["journalctl", "--user", "-u", MOVIE_UNIT,
             "-n", "50", "--no-pager", "-o", "cat"],
            capture_output=True, text=True, stdin=subprocess.DEVNULL,
            timeout=4, check=False)
        if proc.returncode == 0:
            recent = [safe_text(x, 280) for x in proc.stdout.splitlines()
                      if x.startswith(("MOVIE_JA_RESULT ", "MOVIE_JA_HELD "))]
    except (OSError, subprocess.TimeoutExpired):
        pass
    return {"active": active,
            "available": MOVIE_EXEC.is_file() and not MOVIE_EXEC.is_symlink(),
            "last_result": recent[-1] if recent else
                           "No recent movie job",
            "description": "Searching Japanese subtitles and synchronizing" if active
                           else "No movie job running"}


def start_movie_source(doc):
    if not isinstance(doc, dict) or set(doc) != {"video", "title", "year"}:
        raise ValueError("invalid_movie_request")
    video, title, year = doc["video"], doc["title"], doc["year"]
    if not isinstance(video, str) or len(video)>1000 or not Path(video).is_absolute():
        raise ValueError("invalid_video_path")
    if not isinstance(title, str) or not 3<=len(title)<=120:
        raise ValueError("invalid_movie_title")
    if type(year) is not int or not 1880<=year<=2100:
        raise ValueError("invalid_release_year")
    path=Path(video)
    if (path.suffix.casefold() not in MOVIE_EXT or path.is_symlink()
            or not path.is_file() or not any(path.is_relative_to(root)
                                            for root in MOVIE_ROOTS)):
        raise ValueError("selected_movie_no_longer_available")
    if (unit_active(FINISH_UNIT) or unit_active(BATCH_UNIT) or
            unit_active(SCHEDULED_UNIT) or unit_active(SEASON_SOURCE_UNIT)
            or unit_active(JELLYFIN_SOURCE_UNIT)
            or unit_active(MOVIE_UNIT) or translation_busy()):
        raise RuntimeError("another_source_or_translation_worker_is_active")
    if not movie_source_status()["available"]:
        raise RuntimeError("movie_source_controller_not_installed")
    command=["systemd-run","--user","--unit=bruiser-subhub-movie-ja",
             "--collect","--property=KillMode=control-group","--",
             sys.executable,"-B","-u",str(MOVIE_EXEC),
             "--video",str(path),"--title",title,
             "--year",str(year),"--apply"]
    done=subprocess.run(command,capture_output=True,text=True,
                        stdin=subprocess.DEVNULL,timeout=20,check=False)
    if done.returncode:
        raise RuntimeError("movie_source_start_failed: "+
                           safe_text(done.stderr or done.stdout,160))
    return {"ok":True,"video":path.name,"action":"get_japanese_subtitles"}


def start_movie_translation(doc):
    """Owner-selected ONE source-exhausted movie; existing PLaMo engine only."""
    if not isinstance(doc,dict) or set(doc)!={"video","jellyfin_id"}:
        raise ValueError("invalid_movie_translation_request")
    video,jid=doc["video"],doc["jellyfin_id"]
    if (not isinstance(video,str) or len(video)>1000
            or not isinstance(jid,str) or not re.fullmatch(r"[a-f0-9]{32}",jid)):
        raise ValueError("invalid_movie_translation_identity")
    path=Path(video)
    if (path.is_symlink() or not path.is_file()
            or not any(path.is_relative_to(root) for root in MOVIE_ROOTS)):
        raise RuntimeError("movie_file_not_available_in_approved_library")
    if movie_subtitle_status(path)[0]!="missing":
        raise RuntimeError("japanese_already_present_or_coverage_unverified")
    evidence=movie_queue_evidence([path]).get(str(path),{})
    if (evidence.get("jellyfin_id")!=jid or not evidence.get("fallback_ready")
            or evidence.get("search_outcome") not in ("none","review","plausible")):
        raise RuntimeError("movie_not_in_verified_japanese_fallback_queue")
    if (unit_active(FINISH_UNIT) or unit_active(BATCH_UNIT) or
            unit_active(SCHEDULED_UNIT) or unit_active(SEASON_SOURCE_UNIT)
            or unit_active(JELLYFIN_SOURCE_UNIT)
            or unit_active(MOVIE_UNIT) or translation_busy()):
        raise RuntimeError("another_source_or_translation_worker_is_active")
    if not season_batch.ENGINE.is_file() or season_batch.ENGINE.is_symlink():
        raise RuntimeError("subhub_ai_not_installed")
    with season_batch.read_queue() as db:
        rows=db.execute("""
            SELECT m.path,m.kind,t.action,t.state
            FROM media AS m JOIN tasks AS t ON t.path=m.path
            WHERE m.jellyfin_id=? AND m.kind='Movie' AND t.target='ja'
              AND t.active=1
        """,(jid,)).fetchall()
    if (len(rows)!=1 or rows[0]["path"]!=video
            or rows[0]["action"] not in (
                "validate_english_for_ja_fallback","recover_english_for_ja_fallback")
            or rows[0]["state"]!="pending"):
        raise RuntimeError("selected_movie_source_queue_changed")
    command=[
        "systemd-run","--user","--unit=bruiser-subhub-translation-batch",
        "--collect","--property=KillMode=control-group","--",
        str(season_batch.ENGINE),"--apply","--jellyfin-id",jid,
    ]
    done=subprocess.run(command,capture_output=True,text=True,
                        stdin=subprocess.DEVNULL,timeout=20,check=False)
    if done.returncode:
        raise RuntimeError("movie_translation_start_failed: "+
                           safe_text(done.stderr or done.stdout,160))
    return {"ok":True,"accepted":1,"action":"movie_english_sync_then_plamo"}


def stop_movie_source():
    if not unit_active(MOVIE_UNIT):
        raise RuntimeError("no_movie_source_job_running")
    done=subprocess.run(["systemctl","--user","stop","--no-block",MOVIE_UNIT],
                        capture_output=True,text=True,stdin=subprocess.DEVNULL,
                        timeout=15,check=False)
    if done.returncode:
        raise RuntimeError("movie_source_stop_failed")
    return {"ok":True,"action":"stop_movie_source"}


def download_ledger_status():
    """Read only actual instrumented download requests; never guess quotas."""
    path=DOWNLOAD_LEDGER_DB
    empty={"available":False,"today_downloaded":0,"today_attempted":0,
           "today_quota_blocked":0,"today_failed":0,"today_pending":0,
           "providers":{},"recent_days":[],"quota_limit":None,
           "quota_reset":None,"account_wide_total_known":False,
           "basis":"Only instrumented SubHub downloads, beginning at installation"}
    try:
        if (not path.is_file() or path.is_symlink() or
                path.stat().st_mode & 0o077):
            return empty
        jst=timezone(timedelta(hours=9))
        today=datetime.now(jst).date()
        since=(today-timedelta(days=6)).isoformat()
        uri="file:"+quote(str(path.resolve()),safe="/")+"?mode=ro"
        with sqlite3.connect(uri,uri=True,timeout=3) as db:
            rows=db.execute("""SELECT day_jst,provider,outcome,count(*)
                 FROM download_event WHERE day_jst>=?
                 GROUP BY day_jst,provider,outcome""",(since,)).fetchall()
        day_map={}
        for day,provider,outcome,n in rows:
            if (not isinstance(day,str) or len(day)!=10 or
                    provider not in ("opensubtitles","subdl","yify","other","unknown") or
                    outcome not in ("pending","downloaded","quota_blocked","failed")):
                continue
            dayrecord=day_map.setdefault(day,{"day":day,"downloaded":0,
                                              "attempted":0,"quota_blocked":0,
                                              "failed":0,"pending":0,"providers":{}})
            for record in (dayrecord,dayrecord["providers"].setdefault(provider,{
                    "downloaded":0,"attempted":0,"quota_blocked":0,
                    "failed":0,"pending":0})):
                record["attempted"]+=n
                record[outcome]+=n
        current=day_map.get(today.isoformat(),{
            "downloaded":0,"attempted":0,"quota_blocked":0,
            "failed":0,"pending":0,"providers":{}})
        return {**empty,"available":True,
                "today_downloaded":current["downloaded"],
                "today_attempted":current["attempted"],
                "today_quota_blocked":current["quota_blocked"],
                "today_failed":current["failed"],
                "today_pending":current["pending"],
                "providers":current["providers"],
                "recent_days":[{"day":(today-timedelta(days=i)).isoformat(),
                                **day_map.get((today-timedelta(days=i)).isoformat(),
                                              {"downloaded":0,"attempted":0,
                                               "quota_blocked":0,"failed":0,
                                               "pending":0,"providers":{}})}
                               for i in range(7)]}
    except (OSError,sqlite3.Error,ValueError,TypeError):
        return empty


def configured_source_scope():
    """Read owner scope without altering any provider/worker state."""
    path=Path.home()/"bruiser-pilot/ja-first-inventory/.source-scope.json"
    if not path.exists() and not path.is_symlink():
        return "all"
    try:
        if (path.is_symlink() or not path.is_file() or path.stat().st_mode&0o077
                or path.stat().st_uid!=os.getuid() or path.stat().st_size>500):
            return "unavailable"
        record=json.loads(path.read_text("utf-8"))
        if isinstance(record,dict) and set(record)=={"scope"} and record["scope"] in (
                "all","horror-drama-folders","movies-no-anime"):
            return record["scope"]
    except (OSError,ValueError,TypeError):
        pass
    return "unavailable"


def status_payload():
    doc = checked_state()
    log = trusted_log(doc) if doc else None
    lines = tail_lines(log)
    manual=unit_active(BATCH_UNIT)
    scheduled=unit_active(SCHEDULED_UNIT)
    result=snapshot(doc, manual, False, lines)
    result=live_source_snapshot(result,scheduled_source_activity(scheduled))
    result["translation"]=translation_snapshot()
    result["season_translation"]=season_batch_status()
    result["finish_scope"]=finish_scope_status()
    result["season_sources"]=season_sources_status()
    result["jellyfin_source"]=jellyfin_source_status()
    result["download_usage"]=download_ledger_status()
    result["source_config_scope"]=configured_source_scope()
    try:
        result["library_japanese_coverage"]=global_coverage.pulse()
    except (OSError,ValueError,TypeError,RuntimeError,json.JSONDecodeError):
        result["library_japanese_coverage"]={
            "available":False,"reason":"inventory_coverage_unavailable"}
    result["movie_source"]=movie_source_status()
    result["controls"]=control_availability()
    return result



def source_controls(action):
    """Bounded owner commands only; re-use existing source services/locks."""
    manual=unit_active(BATCH_UNIT)
    scheduled=unit_active(SCHEDULED_UNIT)
    script=Path.home()/".local/bin/bruiser-subs"
    # The established autofill service is source-only and already scans
    # the entire Jellyfin inventory in resumable provider-limited batches.
    # Do not route this through legacy manual controllers with AI fallbacks.
    if action=="start-manual":
        raise RuntimeError("legacy_manual_worker_disabled_use_source_only_service")
    if action in ("start-auto", "start-manual") and not (manual or scheduled):
        if translation_busy():
            raise RuntimeError("translation_active_cannot_start_source_worker")
        if unit_active(SEASON_SOURCE_UNIT):
            raise RuntimeError("season_source_active_cannot_start_source_worker")
        if unit_active(JELLYFIN_SOURCE_UNIT):
            raise RuntimeError("Jellyfin source batch already running")
        if unit_active(FINISH_UNIT):
            raise RuntimeError("TV completion job already running")
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


def translation_busy():
    """Prevent concurrent source starts with any known local PLaMo worker."""
    return (unit_active(TRANSLATION_UNIT) or
            american_dad_batch_activity()["active"] or
            bool(_plamo_running_ids()))


def control_availability():
    manual=unit_active(BATCH_UNIT)
    scheduled=unit_active(SCHEDULED_UNIT)
    can_start=not manual and not scheduled and not unit_active(SEASON_SOURCE_UNIT)
    if can_start:
        can_start=not translation_busy() and not unit_active(JELLYFIN_SOURCE_UNIT) and not unit_active(FINISH_UNIT)
    return {"available":True,
            "start_auto":can_start,
            "stop_auto":scheduled,
            "start_manual":False,
            "stop_manual":manual,
            "reason":"Library-wide Japanese-only sourcing, provider quotas enforced"}



BATCH_EVENT = re.compile(
    r"^BATCH_(?:BEGIN |ITEM |ITEM_OK |ITEM_HELD |BLOCKED |DONE |STOPPED |HELD )")
BATCH_TAG = re.compile(r"^(S[0-9]{2}E[0-9]{2,3})(?:\s|$)")


def season_batch_progress(lines, active):
    """Only real BATCH_* journal events count toward batch-level completion.

    A partially processed current episode is NOT a finished episode.
    Old historical batches must never be presented as current progress.
    """
    starts = [i for i, line in enumerate(lines) if line.startswith("BATCH_BEGIN ")]
    if not starts:
        return {"known": False, "active": active}
    events = lines[starts[-1]:]
    try:
        plan = json.loads(events[0][len("BATCH_BEGIN "):])
        total = plan.get("selected")
        if type(total) is not int or not 1 <= total <= 200:
            return {"known": False, "active": active}
    except (ValueError, TypeError, AttributeError):
        return {"known": False, "active": active}
    published, held, blocked = set(), set(), set()
    current = ""
    ended = False
    for line in events[1:]:
        for prefix, group in (("BATCH_ITEM_OK ", published),
                              ("BATCH_ITEM_HELD ", held),
                              ("BATCH_BLOCKED ", blocked)):
            if line.startswith(prefix):
                match = BATCH_TAG.match(line[len(prefix):])
                if match:
                    group.add(match.group(1))
                    if current == match.group(1):
                        current = ""
                break
        else:
            if line.startswith("BATCH_ITEM "):
                match = BATCH_TAG.match(line[len("BATCH_ITEM "):])
                if match:
                    current = match.group(1)
            elif line.startswith(("BATCH_DONE ", "BATCH_STOPPED ",
                                  "BATCH_HELD ")):
                ended = True
                current = ""
    finished = len(published | held | blocked)
    return {"known": True, "active": active, "series": safe_text(plan.get("series"), 120),
            "total": total, "finished": min(finished, total),
            "remaining": max(0, total-finished),
            "published": len(published), "held": len(held),
            "blocked": len(blocked), "current": current if active else "",
            "state": "running" if active else
                     "finished" if ended else "interrupted"}


def season_batch_status():
    """Read batch-wide progress from real per-episode worker events."""
    active = unit_active(TRANSLATION_UNIT)
    recent = []
    try:
        res = subprocess.run(
            ["journalctl", "--user", "-u", TRANSLATION_UNIT,
             "--no-pager", "-o", "cat", "-n", "450", "--grep",
             BATCH_EVENT.pattern],
            capture_output=True, text=True, check=False,
            stdin=subprocess.DEVNULL, timeout=4)
        if res.returncode == 0:
            # journalctl --grep together with -n implicitly enables --reverse:
            # newest event FIRST. Parse in chronological order, otherwise
            # BATCH_BEGIN appears after its ITEM_OK/HELD records and the
            # dashboard falsely reports 0/N despite completed episodes.
            recent = [safe_text(x, 350) for x in res.stdout.splitlines()
                      if BATCH_EVENT.match(x)][-450:]
            recent.reverse()
    except (OSError, subprocess.TimeoutExpired):
        pass
    return {
        "active": active,
        "available": BATCH_EXEC.is_file() and not BATCH_EXEC.is_symlink()
                     and season_batch.ENGINE.is_file()
                     and not season_batch.ENGINE.is_symlink(),
        "progress": season_batch_progress(recent, active),
        "recent": recent[-12:],
    }



def finish_source_progress(receipt):
    """Read the active scope's real child checkpoint, not an old GUI launch.

    A finish worker runs the existing source engine as a subprocess, so
    bruiser-subhub-jellyfin-source.service is correctly inactive. Its JSON
    checkpoint still advances every episode and every ~10 seconds.
    """
    source=_private_jellyfin_json(JELLYFIN_SOURCE_STATE)
    if not source or source.get("schema")!="jellyfin-source-batch-v1":
        return None
    series=receipt.get("series")
    seasons=receipt.get("seasons")
    expected={"series":series,"seasons":seasons,"picks":[]}
    if source.get("selector")!=expected:
        return None
    try:
        # Reject yesterday's source pass with the same series/season selection.
        # Both timestamps are set when each actual worker begins, in UTC.
        from datetime import datetime
        launch=datetime.fromisoformat(receipt["updated_utc"]).timestamp()
        started=float(source.get("started_at") or 0)
        if started < launch-3:
            return None
    except (KeyError,ValueError,TypeError,OverflowError):
        return None
    items=source.get("items")
    if not isinstance(items,list) or len(items)>500:
        return None
    counts=Counter(str(x.get("status")) for x in items if isinstance(x,dict))
    total=int_value(source.get("pass_total"))
    processed=int_value(source.get("pass_processed"))
    # Work counters and publication outcomes are deliberately distinct.
    return {
        "processed":min(max(0,processed),max(0,total)),
        "total":max(0,total),
        "phase":safe_text(source.get("phase"),56),
        "current":safe_text(source.get("current"),145),
        "searches":int_value(source.get("searches_this_run")),
        "downloads":int_value(source.get("downloads_this_run")),
        "published":counts["published"],
        "covered":counts["covered"],
        "held":counts["held"],
        "deferred":counts["deferred"],
        "no_match":counts["no_match"],
        "age_seconds":max(0,int(time.time())-int_value(source.get("updated_at"))),
        "worker_state":safe_text(source.get("state"),32),
    }


def finish_scope_status():
    active=unit_active(FINISH_UNIT)
    available=FINISH_EXEC.is_file() and not FINISH_EXEC.is_symlink()
    try:
        doc=_private_jellyfin_json(finish_scope.STATE)
        if doc and doc.get("schema")!="subhub-finish-scope-v1":
            doc=None
    except (OSError,ValueError,TypeError,RuntimeError,json.JSONDecodeError):
        doc=None
    if not doc:
        return {"active":active,"available":available,
                "state":"starting" if active else "idle"}
    state=str(doc.get("state") or "unknown")
    if state in ("starting","running") and not active:
        state="interrupted"
    before=doc.get("before") or {}
    after=doc.get("after") or {}
    now=int(time.time())
    heartbeat_at=int_value(doc.get("heartbeat_at"))
    last_output_at=int_value(doc.get("last_real_output_at"))
    worker_pid=int_value(doc.get("worker_pid"))
    heartbeat_age=max(0,now-heartbeat_at) if heartbeat_at else None
    last_event_or_start=last_output_at or int_value(doc.get("item_started_at"))
    silent_age=(max(0,now-last_event_or_start)
                if last_event_or_start else None)
    if not active:
        monitor="stopped"
    elif state=="waiting_retry":
        monitor="scheduled_retry"
    elif not heartbeat_at:
        monitor="old_worker_without_heartbeat"
    elif heartbeat_age>35:
        monitor="heartbeat_lost"
    elif worker_pid>0:
        monitor="child_process_alive"
    else:
        monitor="preparing_next_process"
    result={"active":active,"available":available,"state":state,
            "phase":safe_text(doc.get("phase"),42),
            "series":safe_text(doc.get("series"),160),
            "current":safe_text(doc.get("current"),160),
            "detail":safe_text(doc.get("detail"),160),
            "elapsed_seconds":max(0,int(time.time())-int_value(
                doc.get("started_at"))) if doc.get("started_at") else 0,
            "item_elapsed_seconds":max(0,int(time.time())-int_value(
                doc.get("item_started_at"))) if doc.get("item_started_at") else 0,
            "last_issue":safe_text(doc.get("last_issue"),160),
            "monitor":monitor,
            "heartbeat_age_seconds":heartbeat_age,
            "real_output_age_seconds":silent_age,
            "worker_pid":worker_pid,
            "retry_in_seconds":max(0,int_value(doc.get("next_retry_at"))-now)
                               if state=="waiting_retry" else None,
            "flow_counts":{
                "total":int_value(doc.get("total_exact_files")),
                "covered":int_value(doc.get("covered_exact_files")),
                "source":int_value(doc.get("source_pending")),
                "plamo":int_value(doc.get("plamo_pending")),
                "round":int_value(doc.get("round")),
                "source_attempts":int_value(doc.get("source_attempts")),
                "plamo_attempts":int_value(doc.get("plamo_attempts")),
                "attempted_unique":int_value(doc.get("attempted_unique")),
                "initially_covered":int_value(doc.get("initially_covered")),
                "unique_instrumented":"attempted_unique" in doc}
                if "total_exact_files" in doc else None,
            "seasons":doc.get("seasons",[]),
            "missing_before":int_value(before.get("missing")),
            "covered_before":int_value(before.get("covered")),
            "remaining":int_value(doc.get("remaining",
                after.get("missing",before.get("missing")))),
            "intensive_progress":{
                "seasons_done":int_value(doc.get("intensive_seasons_done")),
                "seasons_total":int_value(doc.get("intensive_seasons_total")),
                "trials":int_value(doc.get("intensive_trials")),
                "titles_checked":int_value(doc.get("intensive_titles_checked")),
                "published":int_value(doc.get("intensive_published")),
                "current":safe_text(doc.get("intensive_current"),120)}
                if active and doc.get("phase")=="intensive_recovery" else None}
    if active and doc.get("phase")=="source" and "total_exact_files" not in doc:
        try:
            result["source_progress"]=finish_source_progress(doc)
        except (OSError,ValueError,TypeError,RuntimeError,json.JSONDecodeError):
            result["source_progress"]=None
    return result


def start_finish_scope(doc):
    """One owner action for selected TV seasons, exact movies or movie scope."""
    if not isinstance(doc,dict):
        raise ValueError("invalid_finish_scope")
    series=""
    selected=[]
    movie_ids=[]
    movie_scope=None
    item_ids=[]
    library_folder=None
    library_group=None
    library_genre=None
    library_kind=None
    if set(doc)=={"library_genre","kind"} and isinstance(
            doc["library_genre"],str) and doc["kind"] in ("Movie","Episode"):
        library_genre=doc["library_genre"]
        library_kind=doc["kind"]
        preview=finish_scope.movie_plan(
            library_genre=library_genre,library_kind=library_kind)
        kind="library_genre"
    elif set(doc)=={"item_ids"} and isinstance(doc["item_ids"],list):
        item_ids=doc["item_ids"]
        if (not 1<=len(item_ids)<=300 or
                len(set(str(v) for v in item_ids))!=len(item_ids) or
                any(not isinstance(v,str) or not re.fullmatch("[a-f0-9]{32}",v)
                    for v in item_ids)):
            raise ValueError("invalid_selected_media")
        preview=finish_scope.movie_plan(item_ids=item_ids)
        kind="selected_items"
    elif set(doc)=={"library_folder"} and isinstance(doc["library_folder"],str):
        library_folder=doc["library_folder"]
        preview=finish_scope.movie_plan(library_folder=library_folder)
        kind="library_folder"
    elif set(doc)=={"library_group"} and doc["library_group"] in ("Movie","Episode"):
        library_group=doc["library_group"]
        preview=finish_scope.movie_plan(library_group=library_group)
        kind="library_group"
    elif set(doc)=={"movie_ids"} and isinstance(doc["movie_ids"],list):
        movie_ids=doc["movie_ids"]
        if not 1<=len(movie_ids)<=100 or len(movie_ids)!=len(set(
                str(v) for v in movie_ids)) or any(
                not isinstance(v,str) or not re.fullmatch("[a-f0-9]{32}",v)
                for v in movie_ids):
            raise ValueError("invalid_movie_ids")
        preview=finish_scope.movie_plan(movie_ids)
        kind="selected_movies"
    elif set(doc)=={"movie_scope"} and isinstance(doc["movie_scope"],str):
        movie_scope=doc["movie_scope"]
        preview=finish_scope.movie_plan(movie_scope=movie_scope)
        kind="movie_scope"
    elif isinstance(doc.get("series"),str):
        series=doc["series"]
        if set(doc)=={"series","all"} and doc["all"] is True:
            selected=[]
        elif set(doc)=={"series","seasons"} and isinstance(doc["seasons"],list):
            selected=doc["seasons"]
            if (not selected or len(selected)>60 or
                    any(type(x) is not int or not 1<=x<=60 for x in selected) or
                    len(set(selected))!=len(selected)):
                raise ValueError("invalid_finish_seasons")
        else:
            raise ValueError("choose_selected_seasons_or_all")
        preview=finish_scope.plan(series,selected)
        kind="whole_series" if not selected else "selected_seasons"
    else:
        raise ValueError("invalid_finish_scope")
    if (unit_active(FINISH_UNIT) or unit_active(BATCH_UNIT) or
            unit_active(SCHEDULED_UNIT) or unit_active(SEASON_SOURCE_UNIT) or
            unit_active(JELLYFIN_SOURCE_UNIT) or unit_active(MOVIE_UNIT) or
            translation_busy()):
        raise RuntimeError("another_source_or_translation_worker_is_active")
    if not FINISH_EXEC.is_file() or FINISH_EXEC.is_symlink():
        raise RuntimeError("finish_scope_controller_not_installed")
    if (not finish_scope.DEEP_SOURCE.is_file() or
            finish_scope.DEEP_SOURCE.is_symlink() or
            not finish_scope.AUTO_PLAMO.is_file() or
            finish_scope.AUTO_PLAMO.is_symlink()):
        raise RuntimeError("exhaustive_source_or_plamo_worker_not_installed")
    if preview["missing"]==0:
        return {"ok":True,"state":"already_covered",
                "covered":preview["covered"]}
    receipt={"schema":"subhub-finish-scope-v1","state":"starting",
             "phase":"starting","series":series,"seasons":preview["seasons"],
             "before":{k:v for k,v in preview.items() if k!="picks"}}
    finish_scope.write_state(receipt)
    args=[sys.executable,"-B","-u",str(FINISH_EXEC),"--run"]
    if series:
        args.extend(("--series",series))
        for sn in selected:
            args.extend(("--season",str(sn)))
    elif movie_scope:
        args.extend(("--movie-scope",movie_scope))
    elif library_folder:
        args.extend(("--library-folder",library_folder))
    elif library_group:
        args.extend(("--library-group",library_group))
    elif library_genre:
        args.extend(("--library-genre",library_genre,
                     "--library-kind",library_kind))
    elif item_ids:
        for jid in item_ids:
            args.extend(("--item-id",jid))
    else:
        for jid in movie_ids:
            args.extend(("--movie-id",jid))
    command=["systemd-run","--user","--unit=bruiser-subhub-finish-scope",
             "--collect","--property=KillMode=control-group","--",*args]
    result=subprocess.run(command,capture_output=True,text=True,
                          stdin=subprocess.DEVNULL,timeout=20,check=False)
    if result.returncode:
        receipt.update(state="launch_failed",phase="start_failed")
        finish_scope.write_state(receipt)
        raise RuntimeError("finish_scope_start_failed:"+safe_text(
            result.stderr or result.stdout,140))
    return {"ok":True,"accepted":preview["missing"],"covered":preview["covered"],
            "scope":kind}

def stop_finish_scope():
    if not unit_active(FINISH_UNIT):
        raise RuntimeError("no_finish_scope_worker_running")
    p=subprocess.run(["systemctl","--user","stop","--no-block",FINISH_UNIT],
                     capture_output=True,text=True,timeout=15,check=False)
    if p.returncode:
        raise RuntimeError("finish_scope_stop_failed")
    return {"ok":True,"action":"stop-finish-scope"}


def start_season_translation(doc):
    """Reject unsafe/conflicting work before passing exact selection to systemd."""
    if not isinstance(doc, dict):
        raise ValueError("invalid_batch_request")
    selected_episodes = None
    multi_picks = None
    if set(doc) == {"series","unresolved"} and doc["unresolved"] is True:
        series=doc["series"]
        season_batch.validate(series,1,1,1)
        plan=season_batch.unresolved_plan(series,limit=200)
        multi_picks=[{"season":x["season"],"episode":x["episode"]}
                     for x in plan["picks"]]
        if not multi_picks:
            raise RuntimeError("no_source_exhausted_episodes_ready_for_plamo")
    elif set(doc) == {"series", "picks"}:
        series = doc["series"]
        multi_picks = doc["picks"]
        season_batch.validate(series, 1, 40, 1)
    elif set(doc) == {"series", "season", "episodes"}:
        series, season = doc["series"], doc["season"]
        selected_episodes = doc["episodes"]
        season_batch.validate(series, season, 40, 1)
    elif set(doc) == {"series", "season", "count", "start"}:
        series, season = doc["series"], doc["season"]
        count, start = doc["count"], doc["start"]
        season_batch.validate(series, season, count, start)
    else:
        raise ValueError("invalid_batch_request")
    if (unit_active(FINISH_UNIT) or unit_active(BATCH_UNIT) or unit_active(SCHEDULED_UNIT)
            or unit_active(SEASON_SOURCE_UNIT) or unit_active(JELLYFIN_SOURCE_UNIT)
            or translation_busy()):
        raise RuntimeError("another_source_or_translation_worker_is_active")
    if (not BATCH_EXEC.is_file() or BATCH_EXEC.is_symlink()
            or not season_batch.ENGINE.is_file()
            or season_batch.ENGINE.is_symlink()):
        raise RuntimeError("translation_batch_controller_not_installed")
    chosen = (season_batch.selected_multi_plan(series, multi_picks)
              if multi_picks is not None else
              season_batch.selected_episode_plan(series, season, selected_episodes)
              if selected_episodes is not None else
              season_batch.plan(series, season, count, start))
    if not chosen["ready"]:
        raise RuntimeError("no_source_first_eligible_episodes_in_selection")
    command = [
        "systemd-run", "--user", "--unit=bruiser-subhub-translation-batch",
        "--collect", "--property=KillMode=control-group", "--",
        sys.executable, "-B", "-u", str(BATCH_EXEC), "--run",
        "--series", series, "--season",
        str(min(p["season"] for p in multi_picks) if multi_picks else season),
    ]
    if multi_picks is not None:
        for choice in sorted(multi_picks, key=lambda item:(item["season"],item["episode"])):
            command.extend(["--pick", "S%02dE%03d" % (choice["season"],choice["episode"])])
    elif selected_episodes is not None:
        for episode in sorted(selected_episodes):
            command.extend(["--episode", str(episode)])
    else:
        command.extend(["--count", str(count), "--start", str(start)])
    done = subprocess.run(command, capture_output=True, text=True,
                          stdin=subprocess.DEVNULL, timeout=20, check=False)
    if done.returncode:
        raise RuntimeError("translation_batch_start_failed: " +
                           safe_text(done.stderr or done.stdout, 160))
    return {"ok": True, "accepted": chosen["ready"],
            "blocked": chosen["blocked"],
            "seasons": chosen.get("seasons", [season] if multi_picks is None else []),
            "series": series}


def stop_season_translation():
    if not unit_active(TRANSLATION_UNIT):
        raise RuntimeError("no_translation_batch_running")
    done = subprocess.run(
        ["systemctl", "--user", "stop", "--no-block", TRANSLATION_UNIT],
        capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=15,
        check=False)
    if done.returncode:
        raise RuntimeError("translation_stop_failed: " +
                           safe_text(done.stderr or done.stdout, 160))
    return {"ok": True, "action": "stop-translation"}



def season_sources_status():
    """Read only transient season-source activity from its own systemd unit."""
    active = unit_active(SEASON_SOURCE_UNIT)
    recent = []
    try:
        log = subprocess.run(
            ["journalctl", "--user", "-u", SEASON_SOURCE_UNIT,
             "-n", "35", "--no-pager", "-o", "cat"],
            capture_output=True,text=True,timeout=4,check=False,
            stdin=subprocess.DEVNULL)
        if log.returncode == 0:
            recent=[safe_text(line,210) for line in log.stdout.splitlines()
                    if line.startswith(("SEASON_JA_BEGIN", "SEASON_JA_SOURCE_INVENTORY", "SEASON_JA_NO_WORK", "SEASON_JA_SEARCH ",
                        "SEASON_JA_SEARCH_PLANNED", "SEASON_JA_RESULT ", "SEASON_JA_CANDIDATES ",
                        "SEASON_JA_STAGE ", "SEASON_JA_STAGE_PLANNED",
                        "SEASON_JA_PUBLISH ", "SEASON_JA_PUBLISH_PLANNED",
                        "SEASON_JA_DONE", "SEASON_JA_HELD", "SEASON_JA_DEFERRED",
                        "SEASON_JA_BLOCKED", "PROVIDER_LIMIT_REACHED"))][-12:]
    except (OSError,subprocess.TimeoutExpired):
        pass
    components=("ja_first_search_pilot.py","ja_first_stage_saved_batch.py",
                "ja_first_publish_queue.py","ja_first_autofill.py")
    return {"active":active,
            "available":SEASON_SOURCE_EXEC.is_file()
                and not SEASON_SOURCE_EXEC.is_symlink()
                and all((season_sources.SOURCE_CODE/x).is_file()
                        and not (season_sources.SOURCE_CODE/x).is_symlink()
                        for x in components),
            "recent":recent}


def start_season_sources(doc):
    if not isinstance(doc, dict):
        raise ValueError("invalid_season_source_request")
    if set(doc) == {"series", "picks"}:
        series = doc["series"]
        picks = doc["picks"]
        season_batch.validate(series, 1, 40, 1)
    elif set(doc) == {"series", "season"}:
        series = doc["series"]
        season = doc["season"]
        season_batch.validate(series, season, 40, 1)
        picks = None
    else:
        raise ValueError("invalid_season_source_request")
    if (unit_active(FINISH_UNIT) or unit_active(BATCH_UNIT) or
            unit_active(SCHEDULED_UNIT) or unit_active(SEASON_SOURCE_UNIT)
            or unit_active(JELLYFIN_SOURCE_UNIT)
            or translation_busy()):
        raise RuntimeError("another_source_or_translation_worker_is_active")
    if not season_sources_status()["available"]:
        raise RuntimeError("native_source_components_unavailable")
    chosen = (season_sources.selected_scope(series, picks, recheck=True)
              if picks is not None else season_sources.scope(series, season))
    if not chosen["eligible"]:
        raise RuntimeError("no_pending_japanese_source_work_in_season")
    command=["systemd-run","--user","--unit=bruiser-subhub-season-sources",
             "--collect","--property=KillMode=control-group","--",
             sys.executable,"-B","-u",str(SEASON_SOURCE_EXEC),"--run",
             "--series",series]
    if picks is not None:
        command.append("--recheck")
        for choice in sorted(picks, key=lambda item:(item["season"],item["episode"])):
            command.extend(["--pick", "S%02dE%03d" % (choice["season"],choice["episode"])])
    else:
        command.extend(["--season",str(season)])
    result=subprocess.run(command,capture_output=True,text=True,
                          stdin=subprocess.DEVNULL,timeout=20,check=False)
    if result.returncode:
        raise RuntimeError("season_source_start_failed: "+
                           safe_text(result.stderr or result.stdout,140))
    return {"ok":True,"accepted":chosen["eligible"],
            "series":series,"seasons":chosen.get("seasons", [season] if picks is None else [])}


def _private_jellyfin_json(path):
    """Read only a known private state/launch file, never arbitrary paths."""
    if (path.is_symlink() or not path.is_file() or
            path.stat().st_mode & 0o077 or path.stat().st_size > 500_000):
        return None
    value=json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value,dict) else None


def jellyfin_job_receipts_writable():
    """Actual filesystem-namespace check for the service's narrow write exception.

    A service can read old job state under ProtectHome=read-only yet fail every
    progress write. Testing access bits alone would miss the read-only mount.
    """
    path=JELLYFIN_SOURCE_LAUNCH.parent
    if not path.is_dir() or path.is_symlink():
        return False
    try:
        fd,name=tempfile.mkstemp(prefix=".subhub-job-health-",dir=path)
        os.close(fd)
        Path(name).unlink()
        return True
    except OSError:
        return False


def write_jellyfin_launch(receipt, path=None):
    """Persist owner-accepted job independently of worker startup; no media writes."""
    path=path or JELLYFIN_SOURCE_LAUNCH
    parent=path.parent
    if (not parent.is_dir() or parent.is_symlink() or
            parent.stat().st_mode & 0o077 or path.is_symlink()):
        raise RuntimeError("Jellyfin_source_launch_directory_not_private")
    data=json.dumps(receipt,ensure_ascii=False,sort_keys=True).encode("utf-8")
    if len(data)>16_000:
        raise ValueError("invalid_launch_receipt_size")
    fd,tmp=tempfile.mkstemp(prefix=".jellyfin-source-launch-",dir=parent)
    try:
        with os.fdopen(fd,"wb") as handle:
            os.fchmod(handle.fileno(),0o600)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp,path)
    finally:
        Path(tmp).unlink(missing_ok=True)


def _jellyfin_early_error(started_at):
    """Only the matching new service's own errors; no subtitle/provider request."""
    try:
        log=subprocess.run(
            ["journalctl","--user","-u",JELLYFIN_SOURCE_UNIT,
             "--since","@"+str(max(0,int(started_at)-1)),
             "-n","40","--no-pager","-o","cat"],
            capture_output=True,text=True,check=False,
            stdin=subprocess.DEVNULL,timeout=3)
        if log.returncode:
            return ""
        failures=[safe_text(x,155) for x in log.stdout.splitlines()
                  if x.startswith("JELLYFIN_BATCH_HELD ")]
        return failures[-1] if failures else ""
    except (OSError,subprocess.TimeoutExpired,ValueError):
        return ""


def jellyfin_source_status():
    """Never hide an accepted job merely because it died before writing progress."""
    active=unit_active(JELLYFIN_SOURCE_UNIT)
    base={"active":active,"available":JELLYFIN_SOURCE_EXEC.is_file() and
          not JELLYFIN_SOURCE_EXEC.is_symlink(),"known":False}
    try:
        launch=_private_jellyfin_json(JELLYFIN_SOURCE_LAUNCH)
        if launch and launch.get("schema")!="jellyfin-source-launch-v1":
            launch=None
        doc=_private_jellyfin_json(JELLYFIN_SOURCE_STATE)
        if doc and doc.get("schema")!="jellyfin-source-batch-v1":
            doc=None
        # A failed systemd launch must show its own error, not pretend that
        # the job started or display an unrelated previous receipt.
        if launch and launch.get("state")=="launch_failed":
            return {**base,"known":True,"progress_available":False,
                    "state":"launch_failed","phase":"start_failed",
                    "selector":launch.get("selector",{}),"total":0,
                    "finished":0,"pending":0,"published":0,"held":0,
                    "no_match":0,"current":safe_text(launch.get("error"),155),
                    "events":[]}
        # Old job receipts must NOT show as progress for a newly accepted job.
        if launch and (not doc or doc.get("job_id")!=launch.get("job_id")):
            eligible=launch.get("eligible",0)
            if type(eligible) is not int or not 1<=eligible<=500:
                eligible=0
            age=max(0,int(time.time())-int(launch.get("accepted_at") or 0))
            is_starting=age<15 and active
            is_working_without_receipt=active and not is_starting
            failure=(_jellyfin_early_error(launch["accepted_at"])
                     if not active and age>=8 else "")
            reason=("Waiting for first progress checkpoint"
                    if is_starting else
                    f"Worker active for {age}s, but has not recorded progress" 
                    if is_working_without_receipt else
                    "Waiting for worker process to start"
                    if age<8 else
                    failure or "Job stopped before recording progress; check service log")
            return {**base,"known":True,"progress_available":False,
                    "state":("starting" if is_starting or (not active and age<8)
                             else "no_progress" if is_working_without_receipt
                             else "failed_before_progress"),
                    "phase":"initializing" if active or age<8 else "startup_failed",
                    "selector":launch.get("selector",{}),
                    "total":eligible,"finished":0,"pending":eligible,
                    "pass_total":eligible,"pass_processed":0,
                    "published":0,"already_covered":0,"no_match":0,
                    "held":0,"deferred":0,"searches_this_run":0,
                    "search_cap":launch.get("search_cap",20),
                    "downloads_this_run":0,"current":reason,
                    "events":[{"phase":"startup","item":"",
                               "detail":reason}]}
        if not doc:
            if active:
                return {**base,"known":True,"progress_available":False,
                        "state":"starting","phase":"initializing",
                        "current":"Worker active; waiting for first progress record",
                        "total":0,"finished":0,"pending":0}
            return base
        items=doc.get("items",[])
        if not isinstance(items,list) or len(items)>500:
            return {**base,"known":True,"progress_available":False,
                    "state":"progress_unavailable",
                    "current":"Job state could not be validated"}
        counts=Counter(str(item.get("status")) for item in items if
                       isinstance(item,dict))
        total=len(items)
        finished=sum(value for state,value in counts.items()
                     if state not in ("queued","running"))
        state=str(doc.get("state") or "unknown")
        if active:
            state="running"
        elif state=="running":
            state="interrupted"
        return {**base,"known":True,"progress_available":True,
                "state":state,"phase":safe_text(doc.get("phase"),45),
                "current":safe_text(doc.get("current"),155),
                "selector":doc.get("selector",{}),
                "total":total,"finished":min(finished,total),
                "pending":counts["queued"]+counts["running"],
                "pass_total":doc.get("pass_total"),
                "pass_processed":doc.get("pass_processed"),
                "published":counts["published"],
                "already_covered":counts["covered"],
                "no_match":counts["no_match"],"held":counts["held"],
                "deferred":counts["deferred"],
                "exceptions":[{"item":safe_text(item.get("label"),125),
                               "status":item.get("status"),
                               "reason":safe_text(item.get("reason") or
                                                  "review_required",110)}
                              for item in items if isinstance(item,dict) and
                              item.get("status") in ("held","no_match","deferred")],
                "searches_this_run":int_value(doc.get("searches_this_run")),
                "search_cap":int_value(doc.get("search_cap") or 20),
                "downloads_this_run":int_value(doc.get("downloads_this_run")),
                "phase_age_seconds":max(0,int(time.time())-
                    int_value(doc.get("updated_at"))),
                "job_age_seconds":max(0,int(time.time())-
                    int_value(doc.get("started_at"))),
                "events":[{"phase":safe_text(x.get("phase"),40),
                           "item":safe_text(x.get("item"),115),
                           "detail":safe_text(x.get("detail"),135)}
                          for x in doc.get("events",[])[-8:]
                          if isinstance(x,dict)]}
    except (OSError,ValueError,TypeError,KeyError,json.JSONDecodeError):
        # A real active service should never disappear from Active Work
        # because a state file is missing, partial, or unreadable.
        return {**base,"known":active,"progress_available":False,
                "state":"progress_unavailable",
                "current":"Unable to read worker progress; check source service log"}



def jellyfin_source_arguments(doc):
    """Server checks scope; worker checks exact Jellyfin catalog identities."""
    if not isinstance(doc,dict):
        raise ValueError("invalid_jellyfin_source_request")
    if set(doc) in ({"movie_ids"},{"item_ids"}):
        kind="movie_ids" if "movie_ids" in doc else "item_ids"
        ids=doc[kind]
        if (not isinstance(ids,list) or not 1<=len(ids)<=300 or
                any(not isinstance(jid,str) or not re.fullmatch(r"[a-f0-9]{32}",jid)
                    for jid in ids) or len(set(ids))!=len(ids)):
            raise ValueError("invalid_selected_source_ids")
        flag="--movie-id" if kind=="movie_ids" else "--item-id"
        return [part for jid in sorted(ids) for part in (flag,jid)]
    if set(doc) in ({"library_folder","kind"},{"library_genre","kind"}):
        kind=doc["kind"]
        if kind not in ("Movie","Episode"):
            raise ValueError("invalid_source_library_kind")
        if "library_folder" in doc:
            folder=doc["library_folder"]
            if (not isinstance(folder,str) or not folder.startswith("/")
                    or len(folder)>1000 or ".." in Path(folder).parts):
                raise ValueError("invalid_source_library_folder")
            # Only paths actually in Jellyfin's saved inventory are accepted.
            media_browser.browse(kind=kind,folder=folder)
            return ["--library-folder",folder,"--library-kind",kind]
        genre=doc["library_genre"]
        if (not isinstance(genre,str) or not 1<=len(genre)<=60
                or any(ord(c)<32 for c in genre)):
            raise ValueError("invalid_source_library_genre")
        media_browser.browse(kind=kind,genre=genre)
        return ["--library-genre",genre,"--library-kind",kind]
    if set(doc)=={"series"}:
        series=doc["series"];rest=[]
    elif set(doc)=={"series","seasons"}:
        series=doc["series"];numbers=doc["seasons"]
        if (not isinstance(numbers,list) or not 1<=len(numbers)<=40 or
                any(type(x) is not int or not 1<=x<=99 for x in numbers) or
                len(set(numbers))!=len(numbers)):
            raise ValueError("invalid_seasons")
        rest=[arg for n in sorted(numbers) for arg in ("--season",str(n))]
    elif set(doc)=={"series","picks"}:
        series=doc["series"];picks=doc["picks"]
        if not isinstance(picks,list) or not 1<=len(picks)<=500:
            raise ValueError("invalid_jellyfin_episode_selection")
        numbers=[]
        for pick in picks:
            if not isinstance(pick,dict) or set(pick)!={"season","episode"}:
                raise ValueError("invalid_jellyfin_episode_selection")
            season,episode=pick["season"],pick["episode"]
            if (type(season) is not int or type(episode) is not int
                    or not 1<=season<=99 or not 1<=episode<=999):
                raise ValueError("invalid_jellyfin_episode_selection")
            numbers.append((season,episode))
        if len(set(numbers))!=len(numbers):
            raise ValueError("duplicate_jellyfin_episode")
        rest=[arg for sn,en in sorted(numbers)
              for arg in ("--pick",f"S{sn:02d}E{en:03d}")]
    else:
        raise ValueError("invalid_jellyfin_source_selection")
    if not isinstance(series,str) or not 1<=len(series)<=160 or any(
            ord(c)<32 for c in series):
        raise ValueError("invalid_jellyfin_series")
    return ["--series",series,*rest]


def start_jellyfin_source(doc):
    if (unit_active(FINISH_UNIT) or unit_active(BATCH_UNIT) or
            unit_active(SCHEDULED_UNIT) or unit_active(SEASON_SOURCE_UNIT)
            or unit_active(JELLYFIN_SOURCE_UNIT)
            or unit_active(MOVIE_UNIT) or translation_busy()):
        raise RuntimeError("another_source_or_translation_worker_is_active")
    if not JELLYFIN_SOURCE_EXEC.is_file() or JELLYFIN_SOURCE_EXEC.is_symlink():
        raise RuntimeError("Jellyfin_source_worker_not_installed")
    args=jellyfin_source_arguments(doc)
    # Whole-series retry is an EXPLICIT large-scope action; exact movie
    # selections and selected TV seasons/episodes use at most 20 searches.
    # Each worker checks for existing Japanese subtitles before provider use.
    search_cap=200 if set(doc)=={"series"} else 20
    preview=subprocess.run([sys.executable,"-B",str(JELLYFIN_SOURCE_EXEC),
                            *args,"--max-searches",str(search_cap)],
                           capture_output=True,text=True,stdin=subprocess.DEVNULL,
                           timeout=60,check=False)
    if preview.returncode:
        raise ValueError("Jellyfin source selection invalid: "+
                         safe_text(preview.stderr or preview.stdout,155))
    try:
        plan=json.loads(preview.stdout.strip())
        eligible=int(plan["eligible"])
    except (ValueError,KeyError,TypeError):
        raise RuntimeError("Jellyfin_source_preview_invalid")
    if eligible<=0:
        raise ValueError("No missing Japanese titles in the selected scope")
    job_id=secrets.token_hex(8)
    selection=({"movie_ids":sorted(doc["movie_ids"])}
               if "movie_ids" in doc else
               {"item_ids":sorted(doc["item_ids"])}
               if "item_ids" in doc else
               {"library_folder":doc["library_folder"],"kind":doc["kind"]}
               if "library_folder" in doc else
               {"library_genre":doc["library_genre"],"kind":doc["kind"]}
               if "library_genre" in doc else
               {"series":doc["series"],
                "seasons":sorted(doc.get("seasons",[])),
                "picks":[[p["season"],p["episode"]] for p in
                         doc.get("picks",[])]})
    receipt={
        "schema":"jellyfin-source-launch-v1","job_id":job_id,
        "selector":selection,"eligible":eligible,
        "search_cap":search_cap,"accepted_at":int(time.time())}
    # IMPORTANT: Check our ability to report a job BEFORE starting it.
    # Previously systemd-run started searching and the subsequent write
    # could raise EROFS, incorrectly telling the owner "Not started".
    write_jellyfin_launch(receipt)
    cmd=["systemd-run","--user","--unit=bruiser-subhub-jellyfin-source",
         "--collect","--property=KillMode=control-group","--",
         sys.executable,"-B","-u",str(JELLYFIN_SOURCE_EXEC),
         *args,"--max-searches",str(search_cap),
         "--job-id",job_id,"--run"]
    p=subprocess.run(cmd,capture_output=True,text=True,
                     stdin=subprocess.DEVNULL,timeout=20,check=False)
    if p.returncode:
        failure="Jellyfin_source_start_failed: "+safe_text(p.stderr or p.stdout,155)
        receipt["state"]="launch_failed"
        receipt["error"]=failure
        write_jellyfin_launch(receipt)
        raise RuntimeError(failure)
    return {"ok":True,"eligible":eligible,"max_searches_this_run":search_cap,
            "note":"Background source job accepted; real progress appears in Active work"}


def stop_jellyfin_source():
    if not unit_active(JELLYFIN_SOURCE_UNIT):
        raise RuntimeError("no_Jellyfin_source_job_running")
    p=subprocess.run(["systemctl","--user","stop","--no-block",
                     JELLYFIN_SOURCE_UNIT],capture_output=True,text=True,
                     stdin=subprocess.DEVNULL,timeout=15,check=False)
    if p.returncode:
        raise RuntimeError("Jellyfin_source_stop_failed")
    return {"ok":True,"action":"stop-jellyfin-source"}


def stop_season_sources():
    if not unit_active(SEASON_SOURCE_UNIT):
        raise RuntimeError("no_season_source_worker_running")
    result=subprocess.run(
        ["systemctl","--user","stop","--no-block",SEASON_SOURCE_UNIT],
        capture_output=True,text=True,stdin=subprocess.DEVNULL,
        timeout=15,check=False)
    if result.returncode:
        raise RuntimeError("season_source_stop_failed: "+
                           safe_text(result.stderr or result.stdout,140))
    return {"ok":True,"action":"stop-season-sources"}


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
            except (OSError, ValueError, RuntimeError, TypeError, KeyError,
                    sqlite3.Error, json.JSONDecodeError):
                self.write(503, b'{"error":"status_unavailable"}')
        elif target == "/api/finish/items":
            try:
                params=parse_qs(urlsplit(self.path).query,keep_blank_values=True)
                if (len(urlsplit(self.path).query)>100 or
                        set(params)-{"state","page"} or
                        any(len(v)!=1 for v in params.values())):
                    raise ValueError("invalid_finish_items_query")
                receipt=_private_jellyfin_json(finish_scope.STATE)
                data=finish_titles.report(
                    receipt,
                    state=params.get("state",["all"])[0],
                    page=int(params.get("page",["0"])[0]))
                self.write(200,json.dumps(data,ensure_ascii=False).encode("utf-8"))
            except (ValueError,OSError,RuntimeError,TypeError,sqlite3.Error,
                    subprocess.TimeoutExpired,json.JSONDecodeError) as exc:
                self.write(503,json.dumps(
                    {"error":safe_text(str(exc),130)}).encode("utf-8"))
        elif target == "/api/library/browse":
            try:
                params=parse_qs(urlsplit(self.path).query,keep_blank_values=True)
                if (len(urlsplit(self.path).query)>1000 or
                        set(params)-{"kind","folder","query","page","state","genre"} or
                        any(len(v)!=1 for v in params.values())):
                    raise ValueError("invalid_library_browse_request")
                data=media_browser.browse(
                    kind=params.get("kind",["Movie"])[0],
                    folder=params.get("folder",[""])[0],
                    query=params.get("query",[""])[0],
                    page=int(params.get("page",["0"])[0]),
                    state=params.get("state",["all"])[0],
                    genre=params.get("genre",[""])[0])
                self.write(200,json.dumps(data,ensure_ascii=False).encode("utf-8"))
            except (ValueError,OSError,RuntimeError,TypeError,sqlite3.Error) as exc:
                self.write(400,json.dumps(
                    {"error":safe_text(str(exc),130)}).encode("utf-8"))
        elif target == "/api/movies/search":
            try:
                params=parse_qs(urlsplit(self.path).query)
                query=urlsplit(self.path).query
                if len(query)>200 or set(params)!={"title"} or len(params["title"])!=1:
                    raise ValueError("invalid_movie_search")
                matches=search_movie_files(params["title"][0])
                self.write(200,json.dumps({"movies":matches},ensure_ascii=False).encode("utf-8"))
            except (ValueError,OSError,RuntimeError) as exc:
                self.write(400,json.dumps(
                    {"error":safe_text(str(exc),130)}).encode("utf-8"))
        elif target == "/api/translation/catalog":
            try:
                self.write(200, json.dumps(
                    {"series": season_batch.catalog()},
                    ensure_ascii=False).encode("utf-8"))
            except (OSError, RuntimeError, sqlite3.Error):
                self.write(503, b'{"error":"queue_unavailable"}')
        elif target == "/api/translation/unresolved":
            try:
                params=parse_qs(urlsplit(self.path).query)
                if (len(urlsplit(self.path).query)>280
                        or set(params)!={"series"} or len(params["series"])!=1):
                    raise ValueError("invalid_unresolved_preview_request")
                value=season_batch.unresolved_plan(params["series"][0],limit=200)
                self.write(200,json.dumps(value,ensure_ascii=False).encode("utf-8"))
            except (ValueError,RuntimeError,OSError,sqlite3.Error) as exc:
                self.write(400,json.dumps(
                    {"error":safe_text(str(exc),130)}).encode("utf-8"))
        elif target == "/api/translation/plan":
            try:
                params = parse_qs(urlsplit(self.path).query)
                if len(urlsplit(self.path).query) > 600 or not all(
                    len(params.get(key, [])) == 1
                    for key in ("series", "season", "count", "start")):
                    raise ValueError("invalid_plan_query")
                obj = season_batch.plan(
                    params["series"][0], int(params["season"][0]),
                    int(params["count"][0]), int(params["start"][0]))
                self.write(200, json.dumps(obj, ensure_ascii=False).encode("utf-8"))
            except (OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
                self.write(400, json.dumps(
                    {"error": safe_text(str(exc), 120)}).encode("utf-8"))
        elif target == "/api/translation/coverage":
            try:
                params = parse_qs(urlsplit(self.path).query)
                if (len(urlsplit(self.path).query) > 600 or
                        set(params) != {"series", "season"} or
                        any(len(v) != 1 for v in params.values())):
                    raise ValueError("invalid_coverage_query")
                report = season_batch.season_report(
                    params["series"][0], int(params["season"][0]))
                self.write(200, json.dumps(report, ensure_ascii=False).encode("utf-8"))
            except (OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
                self.write(400, json.dumps(
                    {"error": safe_text(str(exc), 120)}).encode("utf-8"))
        elif target == "/api/owner-token":
            self.write(200,json.dumps({"token":OWNER_TOKEN}).encode("utf-8"))
        elif target == "/healthz":
            self.write(200,json.dumps({
                "status":"ok","mode":"owner_controls",
                "job_receipts_writable":jellyfin_job_receipts_writable()
            }).encode("utf-8"))
        else:
            self.write(404, b'{"error":"not_found"}')

    def do_POST(self):
        target=urlsplit(self.path).path
        if target not in (
            "/api/control/start-auto","/api/control/stop-auto",
            "/api/control/start-manual","/api/control/stop-manual",
            "/api/translation/start","/api/translation/stop",
            "/api/source-season/start","/api/source-season/stop",
            "/api/jellyfin-source/start","/api/jellyfin-source/stop",
            "/api/movie/start","/api/movie/stop",
            "/api/translation/movie/start","/api/finish/start",
            "/api/finish/stop"):
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
                != "application/json" or not size.isdecimal() or
                 int(size) > (16000 if target in (
                     "/api/translation/start","/api/source-season/start",
                     "/api/jellyfin-source/start","/api/finish/start")
                     else 1200 if target in ("/api/movie/start",
                                            "/api/translation/movie/start") else 2)):
            self.write(403,b'{"error":"owner_control_access_denied"}')
            return
        try:
            if target in ("/api/translation/start","/api/source-season/start",
                          "/api/movie/start","/api/jellyfin-source/start",
                          "/api/translation/movie/start","/api/finish/start"):
                if not (2 <= int(size) <= (
                        1200 if target in ("/api/movie/start",
                                           "/api/translation/movie/start") else 16000)):
                    raise ValueError("invalid_batch_request_size")
                request = json.loads(self.rfile.read(int(size)).decode("utf-8"))
                value = (start_season_translation(request)
                         if target == "/api/translation/start"
                         else start_finish_scope(request)
                         if target == "/api/finish/start"
                         else start_movie_translation(request)
                         if target == "/api/translation/movie/start"
                         else start_movie_source(request)
                         if target == "/api/movie/start"
                         else start_jellyfin_source(request)
                         if target == "/api/jellyfin-source/start"
                         else start_season_sources(request))
            else:
                if size=="2" and self.rfile.read(2)!=b"{}":
                    raise ValueError("empty_json_object_required")
                if target == "/api/movie/stop":
                    value = stop_movie_source()
                elif target == "/api/translation/stop":
                    value = stop_season_translation()
                elif target == "/api/source-season/stop":
                    value = stop_season_sources()
                elif target == "/api/jellyfin-source/stop":
                    value = stop_jellyfin_source()
                elif target == "/api/finish/stop":
                    value = stop_finish_scope()
                else:
                    value=source_controls(target.rsplit("/",1)[-1])
            self.write(200,json.dumps(value).encode("utf-8"))
        except (ValueError, TypeError) as exc:
            self.write(400,json.dumps({"error":safe_text(str(exc),180)}).encode("utf-8"))
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
