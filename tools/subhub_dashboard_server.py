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
from urllib.parse import urlsplit, parse_qs
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

TRANSLATION_UNIT = "bruiser-subhub-translation-batch.service"
SEASON_SOURCE_UNIT = "bruiser-subhub-season-sources.service"
SEASON_SOURCE_EXEC = Path(__file__).with_name("subhub_season_sources.py")
BATCH_EXEC = Path(__file__).with_name("subhub_translation_batch.py")
MOVIE_EXEC = Path(__file__).with_name("subhub_movie_job.py")
MOVIE_UNIT = "bruiser-subhub-movie-ja.service"
JELLYFIN_SOURCE_UNIT = "bruiser-subhub-jellyfin-source.service"
JELLYFIN_SOURCE_EXEC = Path.home() / "bruiser-pilot/subhub-control/subhub_jellyfin_batch.py"
JELLYFIN_SOURCE_STATE = (Path.home() /
                         "bruiser-pilot/ja-first-inventory/jellyfin-source-batch.json")
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
          "phase":"idle","phase_label":"No automatic source cycle running",
          "current_item":"","events":[],"sample_window":"","started":0,
          "last_event":0,"search_completed":0,"search_planned":0,
          "search_found":0,"search_none":0,"search_review":0,"search_errors":0,
          "search_partial":0,"search_deferred":0,"search_stopped_early":False,"search_stop_reason":"",
          "stage_attempts":0,"stage_planned":0,"staged":0,"stage_holds":0,
          "publish_title_checked":0,"publish_title_planned":0,"published":0,
          "publish_holds":0}
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
        if not details["has_run"]:
            if not active:
                return idle
            raise RuntimeError("current_cycle_not_in_journal_window")
        status="source_running" if active else "source_interrupted"
        if details["failed"]:
            status="source_held"
        elif details["complete"]:
            status="source_completed"
        phase=details["phase"] if active else {
            "source_held":"Most recent automatic source cycle failed",
            "source_completed":("Source stages finished; search deferred by provider"
                                if details.get("search_stopped_early")
                                else "Selected searches finished; provider coverage incomplete"
                                if details.get("search_partial")
                                else "Most recent automatic source cycle completed"),
            "source_interrupted":"Most recent automatic source cycle interrupted",
        }[status]
        current=safe_text(details["current"],150)
        data={**idle,"active":active,"metrics_available":True,
              "provider_limited":details.get("provider_limited",False),
              "phase":status,
              "phase_label":safe_text(phase,105),
              "current_item":current or "Preparing the next item",
              "events":[safe_text(x,160) for x in details["recent"]][-9:],
              "sample_window":"latest "+str(max_lines)+" journal events",
              "started":details["started"],
              "last_event":details["last_event"],
              "search_completed":details["search_completed"],
              "search_planned":details["search_planned"],
              "search_found":details["search_found"],
              "search_none":details["search_none"],
              "search_review":details["search_review"],
              "search_partial":details["search_partial"],
              "search_errors":details["search_errors"],
              "search_deferred":details["search_deferred"],
              "search_stopped_early":details["search_stopped_early"],
              "search_stop_reason":details["search_stop_reason"],
              "stage_attempts":details["stage_attempts"],
              "stage_planned":details["stage_planned"],
              "staged":details["staged"],
              "stage_holds":details["stage_holds"],
              "publish_title_checked":details["publish_title_checked"],
              "publish_title_planned":details["publish_title_planned"],
              "published":details["published"],
              "publish_holds":details["publish_holds"]}
    except (OSError,ValueError,RuntimeError,subprocess.TimeoutExpired) as exc:
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
                    return matches
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
    if (unit_active(BATCH_UNIT) or unit_active(SCHEDULED_UNIT)
            or unit_active(SEASON_SOURCE_UNIT) or unit_active(MOVIE_UNIT)
            or translation_busy()):
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


def stop_movie_source():
    if not unit_active(MOVIE_UNIT):
        raise RuntimeError("no_movie_source_job_running")
    done=subprocess.run(["systemctl","--user","stop","--no-block",MOVIE_UNIT],
                        capture_output=True,text=True,stdin=subprocess.DEVNULL,
                        timeout=15,check=False)
    if done.returncode:
        raise RuntimeError("movie_source_stop_failed")
    return {"ok":True,"action":"stop_movie_source"}


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
    result["season_sources"]=season_sources_status()
    result["jellyfin_source"]=jellyfin_source_status()
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
        if unit_active(JELLYFIN_SOURCE_UNIT):
            raise RuntimeError("Jellyfin source batch already running")
        if translation_busy():
            raise RuntimeError("translation_active_cannot_start_source_worker")
        if unit_active(SEASON_SOURCE_UNIT):
            raise RuntimeError("season_source_active_cannot_start_source_worker")
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
        can_start=not translation_busy() and not unit_active(JELLYFIN_SOURCE_UNIT)
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


def start_season_translation(doc):
    """Reject unsafe/conflicting work before passing exact selection to systemd."""
    if not isinstance(doc, dict):
        raise ValueError("invalid_batch_request")
    selected_episodes = None
    multi_picks = None
    if set(doc) == {"series", "picks"}:
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
    if (unit_active(BATCH_UNIT) or unit_active(SCHEDULED_UNIT)
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
    if (unit_active(BATCH_UNIT) or unit_active(SCHEDULED_UNIT)
            or unit_active(SEASON_SOURCE_UNIT) or unit_active(JELLYFIN_SOURCE_UNIT)
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
            except (OSError, ValueError, RuntimeError, TypeError, json.JSONDecodeError):
                self.write(503, b'{"error":"status_unavailable"}')
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
            self.write(200, b'{"status":"ok","mode":"owner_controls"}')
        else:
            self.write(404, b'{"error":"not_found"}')

    def do_POST(self):
        target=urlsplit(self.path).path
        if target not in (
            "/api/control/start-auto","/api/control/stop-auto",
            "/api/control/start-manual","/api/control/stop-manual",
            "/api/translation/start","/api/translation/stop",
            "/api/source-season/start","/api/source-season/stop",
            "/api/movie/start","/api/movie/stop"):
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
                     "/api/translation/start","/api/source-season/start")
                     else 1200 if target=="/api/movie/start" else 2)):
            self.write(403,b'{"error":"owner_control_access_denied"}')
            return
        try:
            if target in ("/api/translation/start","/api/source-season/start",
                          "/api/movie/start"):
                if not (2 <= int(size) <= (
                        1200 if target=="/api/movie/start" else 16000)):
                    raise ValueError("invalid_batch_request_size")
                request = json.loads(self.rfile.read(int(size)).decode("utf-8"))
                value = (start_season_translation(request)
                         if target == "/api/translation/start"
                         else start_movie_source(request)
                         if target == "/api/movie/start"
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
