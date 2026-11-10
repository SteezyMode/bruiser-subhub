#!/usr/bin/env python3
"""Persistent coverage planning queue from the EXISTING private EN/JA matrix.

No Jellyfin/media scan; no provider calls/downloads; no AI inference; no
subtitle edits. Existing track timing problems can be explicitly flagged for
bounded, validated repair, ahead of obtaining a replacement subtitle.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import time

REPORTS = Path.home() / "bruiser-pilot/coverage-audits"
STATE = Path.home() / "bruiser-pilot/coverage-queue"
SEARCH = Path.home() / "bruiser-pilot/ja-first-inventory/japanese-search.sqlite3"
STAGES = Path.home() / "bruiser-pilot/ja-first-inventory/japanese-stage.sqlite3"
STAGED = Path.home() / "bruiser-pilot/ja-first-inventory/staged"
SCHEMA = "bruiser-full-subtitle-matrix-v1"
EN = {"en", "eng", "english"}
JA = {"ja", "jp", "jpn", "japanese"}
UNKNOWN_AUDIO = {"", "und", "unknown", "mul", "zxx", "none"}
STATES = {"pending", "held", "candidate_found", "ready_for_translation"}
VALID_TARGETS = {"en", "ja"}
# No special-case priorities for named series; all eligible media can source JA.


def stamp():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def is_true(value):
    return value is True or value == 1 or value == "True"


def language(value):
    return str(value or "").strip().casefold().split("-", 1)[0].split("_", 1)[0]


def file_identity(row):
    return str(row.get("video_path") or "")


def manifest_path(folder=REPORTS, chosen=None):
    folder = Path(folder)
    if not folder.is_dir() or folder.is_symlink() or folder.stat().st_mode & 0o077:
        raise RuntimeError("Private matrix folder must be 0700")
    if chosen:
        path = Path(chosen)
    else:
        results = sorted(p for p in folder.glob("subtitle-matrix-20*.json")
                         if p.is_file() and not p.is_symlink())
        if not results:
            raise RuntimeError("No full EN/JA inventory exists")
        path = results[-1]
    if (path.parent.resolve() != folder.resolve()
            or not path.name.startswith("subtitle-matrix-20")
            or path.suffix != ".json" or not path.is_file()
            or path.is_symlink() or path.stat().st_mode & 0o077
            or path.stat().st_size > 80_000_000):
        raise RuntimeError("Invalid private matrix file")
    return path


def load_matrix(path):
    raw = path.read_bytes()
    data = json.loads(raw)
    if (data.get("schema") != SCHEMA or not isinstance(data.get("items"), list)
            or not isinstance(data.get("summary"), dict)):
        raise RuntimeError("Unexpected bilingual matrix schema")
    rows = data["items"]
    if len(rows) != data["summary"].get("files_inspected"):
        raise RuntimeError("Matrix inventory total differs from entries")
    if len(rows) > 100000:
        raise RuntimeError("Unexpectedly large inventory")
    return rows, hashlib.sha256(raw).hexdigest()


def read_previous_searches(path=SEARCH):
    """Never spend a new provider call when evidence is already available."""
    if not path.is_file() or path.is_symlink():
        return {}
    try:
        with sqlite3.connect("file:" + str(path.resolve()) + "?mode=ro",
                             uri=True, timeout=10) as con:
            return {str(j): (str(o), int(n), int(t)) for j, o, n, t in con.execute(
                "SELECT jellyfin_id,outcome,plausible_count,searched_at FROM searches")}
    except (OSError, ValueError, sqlite3.Error):
        return {}


def read_staged(path=STAGES):
    """Already downloaded Japanese subtitles come before quota-costing downloads."""
    if not path.is_file() or path.is_symlink():
        return set()
    found = set()
    try:
        with sqlite3.connect("file:" + str(path.resolve()) + "?mode=ro",
                             uri=True, timeout=10) as con:
            for j, sid, filepath in con.execute(
                "SELECT jellyfin_id,subtitle_id,host_path FROM staged WHERE status='staged'"):
                file = Path(str(filepath))
                if (file.parent == STAGED and file.is_file() and
                        not file.is_symlink() and 0 < file.stat().st_size <= 2_000_000):
                    found.add(str(j))
    except (OSError, ValueError, sqlite3.Error):
        return set()
    return found


def read_published_staged(path=STAGES):
    """Reconcile actual published JA without another library-wide audit.

    Provider-staging DB status is only accepted when an actual create-only
    published JA sidecar can still be observed beside its exact source video.
    """
    if not path.is_file() or path.is_symlink():
        return set()
    try:
        with sqlite3.connect("file:" + str(path.resolve()) + "?mode=ro",
                             uri=True, timeout=10) as con:
            return {str(jid) for (jid,) in con.execute(
                "SELECT DISTINCT jellyfin_id FROM staged WHERE status='published'")}
    except (OSError, ValueError, sqlite3.Error):
        return set()


def real_published_sidecar(row):
    video=Path(str(row.get("video_path") or ""))
    if not video.is_absolute():
        return False
    target=video.with_name(video.stem+".ja.srt")
    try:
        return (not target.is_symlink() and target.is_file()
                and 0 < target.stat().st_size <= 2_000_000)
    except OSError:
        return False


def preference(row):
    """Soft ordering only; no 75/25 movie or TV quota."""
    if row.get("kind") == "Movie":
        folder = str(row.get("video_path") or "").rsplit("/", 1)[0]
        if re.search(r"(?i)(?<![a-z])horror(?![a-z])", folder):
            return 0
        if re.search(r"(?i)(?<![a-z])(?:drama|suspense|thriller)(?![a-z])", folder):
            return 1
    return 2


def japanese_source_plan(row, searches, staged, now=None):
    jid = str(row.get("jellyfin_id") or "")
    if jid in staged:
        return "align_existing_staged_ja", "download_already_staged_sync_and_QA_first"
    match = searches.get(jid)
    if match:
        outcome, matches, searched = match
        if outcome == "plausible" and matches > 0:
            return "download_saved_ja", "reuse_high_confidence_saved_match_then_sync"
        if outcome == "review":
            return "review_saved_ja", "confirm_identity_before_download"
        if outcome == "none" and searched > (now or time.time()) - 30 * 86400:
            # A single provider-search miss is NOT Japanese-source exhaustion.
            # It may mean no enabled providers, results lost to filters,
            # missing edition/numbering variants, or unsupported downloads.
            # Keep sourcing open; the existing saved-search cooldown still
            # prevents an ordinary cycle from repeating the same API call.
            # Translation requires a separate *explicit* owner-reviewed
            # source-exhaustion decision, never this automatic transition.
            return "search_ja", "saved_miss_expand_providers_and_recover_candidates"
    return "search_ja", "source_japanese_before_local_translation"


def tasks_for(row, searches=None, staged=None, now=None):
    """Prioritize preserving, sourcing, repairing, then translating.

    English-audio -> seek Japanese, local English->JA only after JA sourcing.
    Japanese-audio -> seek English.
    Third-language -> seek BOTH (JA first, EN second).
    Unknown/ambiguous -> plan review; don't assume a missing track.
    Timing flags are a separate persistent task table and come first.
    """
    searches, staged = searches or {}, staged or set()
    category = str(row.get("category") or "unknown")
    if category == "unknown":
        return [("review", "review_uncertain", "unlabeled_or_uncertain_language", 100)]
    has_en = is_true(row.get("english_subtitles"))
    has_ja = is_true(row.get("japanese_subtitles"))
    audio = language(row.get("audio_language"))
    # The coverage category (e.g. neither) describes available subtitle tracks,
    # NOT the original audio language. It cannot authorize JA provider search.
    if audio in UNKNOWN_AUDIO:
        if has_ja:
            return []
        # The audio language needs review, but metadata uncertainty is not
        # a reason to forbid non-destructive subtitle discovery. Record BOTH
        # jobs; candidate identity, tracks and publish safety remain separate.
        action, why=japanese_source_plan(row,searches,staged,now)
        return [("ja",action,"audio_unverified_"+why,80+preference(row)),
                ("review","review_uncertain",
                 "primary_audio_language_unverified",100)]
    rank = preference(row)
    result = []
    if audio in JA:
        if not has_en:
            result.append(("en", "search_en", "japanese_audio_english_subtitles_needed", 70 + rank))
        return result
    if not has_ja:
        action, reason = japanese_source_plan(row, searches, staged, now)
        # Reuse downloaded files and cached OpenSubtitles searches before
        # making new quota-consuming requests. Rank covers all media types.
        phases = {
            "align_existing_staged_ja": 10,
            "download_saved_ja": 20,
            "review_saved_ja": 30,
            "search_ja": 40,
            "validate_english_for_ja_fallback": 50,
            "recover_english_for_ja_fallback": 60,
        }
        result.append(("ja", action, reason, phases[action] + rank))
    if audio not in EN and not has_en:
        if audio in UNKNOWN_AUDIO:
            result.append(("en", "check_audio_then_source_en",
                           "audio_language_unverified_english_requirement", 70 + rank))
        else:
            result.append(("en", "search_en",
                           "third_language_audio_needs_english", 50 + rank))
    return result


@contextmanager
def queue_db(folder=STATE):
    folder = Path(folder)
    folder.mkdir(parents=True, mode=0o700, exist_ok=True)
    if folder.is_symlink() or folder.stat().st_mode & 0o077:
        raise RuntimeError("Queue directory must be private (0700)")
    lockfile = folder / ".queue.lock"
    if lockfile.is_symlink():
        raise RuntimeError("Queue lock cannot be a symlink")
    fd = os.open(lockfile, os.O_RDWR | os.O_CREAT |
                 getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "rb") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        path = folder / "coverage.sqlite3"
        if path.is_symlink() or (path.exists() and
                (not path.is_file() or path.stat().st_mode & 0o077)):
            raise RuntimeError("Unsafe queue database path")
        with sqlite3.connect(path, timeout=30) as db:
            db.row_factory = sqlite3.Row
            os.chmod(path, 0o600)
            db.execute("PRAGMA busy_timeout=30000")
            db.execute("PRAGMA journal_mode=DELETE")
            db.execute("PRAGMA synchronous=FULL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS media (
                    path TEXT PRIMARY KEY, jellyfin_id TEXT NOT NULL,
                    title TEXT NOT NULL, series TEXT NOT NULL,
                    kind TEXT NOT NULL, season TEXT, episode TEXT,
                    category TEXT NOT NULL, audio_language TEXT NOT NULL,
                    en_present INTEGER NOT NULL, ja_present INTEGER NOT NULL,
                    en_text INTEGER NOT NULL, source_hash TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS tasks (
                    path TEXT NOT NULL, target TEXT NOT NULL,
                    action TEXT NOT NULL, reason TEXT NOT NULL,
                    priority INTEGER NOT NULL, state TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    note TEXT NOT NULL DEFAULT '',
                    active INTEGER NOT NULL DEFAULT 1,
                    updated_utc TEXT NOT NULL,
                    PRIMARY KEY(path,target)
                );
                CREATE TABLE IF NOT EXISTS timing_flags (
                    path TEXT NOT NULL, target TEXT NOT NULL,
                    reason TEXT NOT NULL, flagged_utc TEXT NOT NULL,
                    PRIMARY KEY(path,target)
                );
                CREATE TABLE IF NOT EXISTS snapshots (
                    hash TEXT PRIMARY KEY, source TEXT NOT NULL,
                    imported_utc TEXT NOT NULL, media_count INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS tasks_next
                    ON tasks(active,state,priority,action);
            """)
            yield db


def import_snapshot(db, rows, digest, source, searches=None, staged=None,
                    published=None):
    # The same library snapshot can have NEW provider search/staging evidence.
    # Reconcile plans even on repeat imports; never reset old held/cue history
    # unless the concrete next action actually changed.
    same_snapshot = bool(db.execute(
        "SELECT 1 FROM snapshots WHERE hash=?", (digest,)).fetchone())
    searches, staged = searches or {}, staged or set()
    published = read_published_staged() if published is None else published
    flags = {(r["path"],r["target"]): r["reason"] for r in db.execute(
        "SELECT path,target,reason FROM timing_flags")}
    seen = set()
    live = set()
    outcomes = Counter()
    timestamp = stamp()
    with db:
        for row in rows:
            path = file_identity(row)
            if (not path.startswith("/") or path in seen
                    or row.get("kind") not in ("Movie", "Episode")):
                raise RuntimeError("Duplicate or invalid media in the source matrix")
            seen.add(path)
            en = is_true(row.get("english_subtitles"))
            ja = is_true(row.get("japanese_subtitles"))
            db.execute("""INSERT INTO media(path,jellyfin_id,title,series,kind,
                season,episode,category,audio_language,en_present,ja_present,
                en_text,source_hash) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(path) DO UPDATE SET
                    jellyfin_id=excluded.jellyfin_id,title=excluded.title,
                    series=excluded.series,kind=excluded.kind,
                    season=excluded.season,episode=excluded.episode,
                    category=excluded.category,audio_language=excluded.audio_language,
                    en_present=excluded.en_present,ja_present=excluded.ja_present,
                    en_text=excluded.en_text,source_hash=excluded.source_hash""",
                (path,str(row.get("jellyfin_id") or ""),
                 str(row.get("title") or ""),str(row.get("series") or ""),
                 str(row["kind"]),str(row.get("season") or ""),
                 str(row.get("episode") or ""),str(row.get("category") or ""),
                 language(row.get("audio_language")),int(en),int(ja),
                 int(is_true(row.get("english_text"))),digest))
            planned = tasks_for(row, searches, staged)
            if str(row.get("jellyfin_id") or "") in published and real_published_sidecar(row):
                planned = [task for task in planned if task[0] != "ja"]
            for lang in ("en","ja"):
                flagged = flags.get((path,lang))
                if flagged and (en if lang=="en" else ja):
                    planned = [t for t in planned if t[0] != lang]
                    planned.append((lang, "repair_existing_timing",
                                    flagged, 0))
            for target, action, reason, priority in planned:
                live.add((path,target))
                outcomes[action] += 1
                db.execute("""INSERT INTO tasks(
                    path,target,action,reason,priority,state,active,updated_utc
                    ) VALUES(?,?,?,?,?,'pending',1,?)
                    ON CONFLICT(path,target) DO UPDATE SET
                        action=excluded.action,reason=excluded.reason,
                        priority=excluded.priority,active=1,
                        state=CASE WHEN tasks.action<>excluded.action
                            THEN 'pending' ELSE tasks.state END,
                        updated_utc=excluded.updated_utc""",
                    (path,target,action,reason,priority,timestamp))
        for old in db.execute("SELECT path,target FROM tasks WHERE active=1"):
            if (old["path"],old["target"]) not in live:
                db.execute("UPDATE tasks SET active=0,updated_utc=? "
                           "WHERE path=? AND target=?",
                           (timestamp,old["path"],old["target"]))
        if not same_snapshot:
            db.execute("INSERT INTO snapshots VALUES(?,?,?,?)",
                       (digest,str(source),timestamp,len(rows)))
    return {"result":"reconciled_existing_snapshot" if same_snapshot else "imported",
            "source_snapshot":digest[:12],
            "media":len(rows),"active_tasks":len(live),
            "by_action":dict(sorted(outcomes.items()))}


def flag_timing(db, jellyfin_id, target, reason):
    if target not in VALID_TARGETS:
        raise ValueError("target must be en or ja")
    rows = db.execute("SELECT * FROM media WHERE jellyfin_id=?",
                      (jellyfin_id,)).fetchall()
    if len(rows) != 1:
        raise RuntimeError("Jellyfin ID must resolve to exactly one media file")
    row = rows[0]
    has_lang = bool(row["en_present"] if target == "en" else row["ja_present"])
    if not has_lang:
        raise RuntimeError("No existing subtitle in target language; source it instead")
    reason = str(reason or "").strip()
    if not reason or len(reason) > 300:
        raise RuntimeError("A short concrete timing issue description is required")
    timestamp = stamp()
    with db:
        db.execute("""INSERT INTO timing_flags VALUES(?,?,?,?)
            ON CONFLICT(path,target) DO UPDATE SET
              reason=excluded.reason,flagged_utc=excluded.flagged_utc""",
            (row["path"],target,reason,timestamp))
        db.execute("""INSERT INTO tasks(path,target,action,reason,priority,
             state,active,updated_utc) VALUES(?,?,'repair_existing_timing',
             ?,0,'pending',1,?)
             ON CONFLICT(path,target) DO UPDATE SET
               action='repair_existing_timing',reason=excluded.reason,
               priority=0,state='pending',active=1,updated_utc=excluded.updated_utc""",
             (row["path"],target,reason,timestamp))
    return {"title":row["title"],"language":target,
            "plan":"keep_original_validate_shift_then_create_versioned_corrected_track"}


def update_task_state(db, jellyfin_id, target, desired, note):
    """Record resumable human/worker handoffs; does not run any work.

    'completed' is deliberately NOT a task state: a verified new JA/EN file
    must appear in a fresh matrix before the task can retire safely.
    """
    if target not in VALID_TARGETS or desired not in STATES:
        raise ValueError("Invalid target language or queue state")
    note = str(note or "").strip()
    if len(note) > 400:
        raise RuntimeError("State note too long")
    matched = db.execute(
        "SELECT t.path,t.action,m.title FROM tasks t "
        "JOIN media m ON m.path=t.path WHERE m.jellyfin_id=? "
        "AND t.target=? AND t.active=1", (jellyfin_id,target)).fetchall()
    if len(matched) != 1:
        raise RuntimeError("Exactly one active media/language task required")
    row = matched[0]
    with db:
        db.execute("UPDATE tasks SET state=?,note=?,attempts=attempts+1,"
                   "updated_utc=? WHERE path=? AND target=?",
                   (desired,note,stamp(),row["path"],target))
    return {"title":row["title"],"target":target,
            "action":row["action"],"state":desired}


def next_tasks(db, limit=20, action=None):
    args = []
    where = "WHERE t.active=1 AND t.state='pending'"
    if action:
        where += " AND t.action=?"
        args.append(action)
    args.append(limit)
    return [dict(r) for r in db.execute(
        """SELECT t.target,t.action,t.reason,t.priority,t.state,
                  m.kind,m.title,m.series,m.season,m.episode,m.jellyfin_id
           FROM tasks t JOIN media m ON m.path=t.path """
        + where + """ ORDER BY t.priority,t.updated_utc,m.series,m.title LIMIT ?""",
        args)]


def report(db):
    return {"media":db.execute("SELECT COUNT(*) FROM media").fetchone()[0],
            "active_tasks":db.execute("SELECT COUNT(*) FROM tasks WHERE active=1").fetchone()[0],
            "by_action":{r[0]:r[1] for r in db.execute(
                "SELECT action,COUNT(*) FROM tasks WHERE active=1 GROUP BY action")},
            "by_state":{r[0]:r[1] for r in db.execute(
                "SELECT state,COUNT(*) FROM tasks WHERE active=1 GROUP BY state")},
            "timing_repairs_flagged":db.execute(
                "SELECT COUNT(*) FROM timing_flags").fetchone()[0],
            "snapshots":db.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=("init","status","next","flag-timing","set-state"))
    p.add_argument("--matrix", type=Path)
    p.add_argument("--reports", type=Path, default=REPORTS)
    p.add_argument("--state", type=Path, default=STATE)
    p.add_argument("--limit", type=int, default=15)
    p.add_argument("--filter-action")
    p.add_argument("--jellyfin-id")
    p.add_argument("--language", choices=("en","ja"))
    p.add_argument("--reason")
    p.add_argument("--queue-state", choices=sorted(STATES))
    p.add_argument("--note", default="")
    args = p.parse_args(argv)
    if not 1 <= args.limit <= 100:
        raise ValueError("next limit must be between 1 and 100")
    if args.action == "init":
        selected = manifest_path(args.reports,args.matrix)
        rows,digest = load_matrix(selected)
        searches = read_previous_searches()
        staged = read_staged()
        with queue_db(args.state) as db:
            result = import_snapshot(db,rows,digest,selected,searches,staged)
            print("COVERAGE_QUEUE_INIT",json.dumps(result,sort_keys=True))
            print("COVERAGE_QUEUE_STATUS",json.dumps(report(db),sort_keys=True))
    elif args.action == "status":
        with queue_db(args.state) as db:
            print("COVERAGE_QUEUE_STATUS",json.dumps(report(db),sort_keys=True))
    elif args.action == "next":
        with queue_db(args.state) as db:
            print("COVERAGE_QUEUE_STATUS",json.dumps(report(db),sort_keys=True))
            for item in next_tasks(db,args.limit,args.filter_action):
                print("QUEUE_ITEM",json.dumps(item,ensure_ascii=False,sort_keys=True))
    elif args.action == "flag-timing":
        if not args.jellyfin_id or not args.language or not args.reason:
            raise ValueError("flag-timing requires --jellyfin-id, --language and --reason")
        with queue_db(args.state) as db:
            value=flag_timing(db,args.jellyfin_id,args.language,args.reason)
            print("TIMING_REPAIR_QUEUED",json.dumps(value,ensure_ascii=False))
    elif args.action == "set-state":
        if not args.jellyfin_id or not args.language or not args.queue_state:
            raise ValueError("set-state needs --jellyfin-id --language --queue-state")
        with queue_db(args.state) as db:
            result=update_task_state(
                db,args.jellyfin_id,args.language,args.queue_state,args.note)
            print("COVERAGE_TASK_UPDATED",json.dumps(result,ensure_ascii=False))
    return 0


if __name__ == "__main__":
    os.umask(0o077)
    try:
        raise SystemExit(main())
    except (OSError,RuntimeError,ValueError,sqlite3.Error) as exc:
        print("COVERAGE_QUEUE_BLOCKED",type(exc).__name__,str(exc)[:100],
              file=sys.stderr)
        raise SystemExit(1)
