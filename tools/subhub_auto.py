#!/usr/bin/env python3
"""One dispatcher, two existing scheduled phases: Japanese sourcing and PLaMo.
Reuse the existing exact-item source/QA engines, source lock, exhaustion
receipts, PLaMo checkpoints and dispatcher state. No new timers or databases.
A quota pause, a rejected release, or a missing receipt never authorizes AI.
The source phase gives unattempted movies priority and moves past exceptions.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime
import fcntl
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import time

HOME=Path.home()
ROOT=HOME/"bruiser-pilot"
STATE=ROOT/"subhub-auto"
DB=STATE/"jobs.sqlite3"
INTAKE=ROOT/"ja-first-inventory"
SOURCE_LOCK=INTAKE/".autofill.lock"
CODE=ROOT/"subhub-control"/"ja_first_catalog_manifest.py"
AI=HOME/".local/bin/subhub-ai"
JID=re.compile(r"[a-f0-9]{32}\Z")
EN={"en","eng","english"}
VIDEO={".mkv",".mp4",".avi",".m4v",".mov",".webm",".m2ts",".ts"}
HOLD_DELAY=24*3600
INTERRUPTED_DELAY=2*3600
CATALOG_TTL=6*3600
MAX_ITEMS=30000


def now():
    return int(time.time())


def private_dir(path):
    if path.is_symlink():
        raise RuntimeError("symlinked_private_directory")
    path.mkdir(mode=0o700,parents=True,exist_ok=True)
    info=path.stat()
    if not path.is_dir() or info.st_uid!=os.getuid() or info.st_mode & 0o077:
        raise RuntimeError("private_directory_owner_or_permissions_invalid")
    return path


@contextmanager
def mutex(path):
    if path.is_symlink():
        raise RuntimeError("unsafe_shared_lock_symlink")
    fd=os.open(path,os.O_RDWR|os.O_CREAT|getattr(os,"O_NOFOLLOW",0),0o600)
    try:
        st=os.fstat(fd)
        if st.st_uid!=os.getuid() or st.st_mode & 0o077:
            raise RuntimeError("unsafe_shared_lock_permissions")
        try:
            fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("source_or_translation_worker_busy") from None
        yield
    finally:
        os.close(fd)


def connection(path=DB):
    path=Path(path)
    private_dir(path.parent)
    if path.is_symlink() or (path.exists() and
            (not path.is_file() or path.stat().st_mode & 0o077)):
        raise RuntimeError("unsafe_dispatcher_database")
    fd=os.open(path,os.O_CREAT|os.O_RDWR|getattr(os,"O_NOFOLLOW",0),0o600)
    os.close(fd)
    db=sqlite3.connect(path,timeout=20)
    db.row_factory=sqlite3.Row
    db.executescript("""
        CREATE TABLE IF NOT EXISTS jobs(
            jellyfin_id TEXT PRIMARY KEY,
            video TEXT NOT NULL,
            title TEXT NOT NULL,
            state TEXT NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0,
            retry_after INTEGER NOT NULL DEFAULT 0,
            last_error TEXT NOT NULL DEFAULT '',
            updated_at INTEGER NOT NULL,
            published_path TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS jobs_next ON jobs(state,retry_after,updated_at);
    """)
    db.commit()
    return db


def update(db, item, status, reason="", retry_after=0, count_attempt=False,
           published_path=""):
    jid=str(item["jellyfin_id"])
    if not JID.fullmatch(jid):
        raise RuntimeError("invalid_dispatch_identity")
    current=db.execute("SELECT attempts FROM jobs WHERE jellyfin_id=?",
                       (jid,)).fetchone()
    attempts=(int(current["attempts"]) if current else 0)+int(count_attempt)
    db.execute("""INSERT INTO jobs(
        jellyfin_id,video,title,state,attempts,retry_after,last_error,
        updated_at,published_path) VALUES(?,?,?,?,?,?,?,?,?)
        ON CONFLICT(jellyfin_id) DO UPDATE SET
        video=excluded.video,title=excluded.title,state=excluded.state,
        attempts=excluded.attempts,retry_after=excluded.retry_after,
        last_error=excluded.last_error,updated_at=excluded.updated_at,
        published_path=excluded.published_path""",
        (jid,str(item["host_path"]),str(item.get("title") or ""),
         status,attempts,int(retry_after),str(reason)[:150],
         now(),str(published_path)))
    db.commit()


def state_for(db,jid):
    return db.execute("SELECT * FROM jobs WHERE jellyfin_id=?",(jid,)).fetchone()


def catalog_path(folder=INTAKE):
    folder=Path(folder)
    if not folder.is_dir() or folder.is_symlink() or folder.stat().st_mode & 0o077:
        raise RuntimeError("private_jellyfin_inventory_unavailable")
    files=sorted(folder.glob("ja-intake-*.json"))
    if not files:
        return None
    path=files[-1]
    if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o077:
        raise RuntimeError("unsafe_saved_catalog")
    return path


def load_catalog(path):
    if path is None:
        raise RuntimeError("missing_saved_catalog")
    if path.stat().st_size>85_000_000:
        raise RuntimeError("catalog_larger_than_safe_limit")
    data=json.loads(path.read_text("utf-8"))
    rows=data.get("items")
    if data.get("schema")!=1 or not isinstance(rows,list) or len(rows)>MAX_ITEMS:
        raise RuntimeError("unexpected_jellyfin_catalog_schema")
    return rows


def eligible(row, scope="all"):
    """Exclude Japanese-covered items and anime, not Western animation."""
    if not isinstance(row,dict) or row.get("kind") not in ("Movie","Episode"):
        return False
    if row.get("status")!="ready_ja_search" or not JID.fullmatch(
            str(row.get("jellyfin_id") or "")):
        return False
    video=Path(str(row.get("host_path") or ""))
    if not video.is_absolute() or video.suffix.lower() not in VIDEO:
        return False
    genres=row.get("genres") or []
    if any(isinstance(g,str) and re.search(r"(?i)\\banime\\b",g)
           for g in genres):
        return False
    if any(re.search(r"(?i)(?<![a-z])anime",part)
           for part in video.parts[:-1]):
        return False
    if scope!="all":
        try:
            from . import ja_first_movie_scope as movie_scope
        except ImportError:
            import ja_first_movie_scope as movie_scope
        if not movie_scope.matches(row,scope):
            return False
    return True


def source_proven(row, deep):
    """Existing exact-video proof; never ignore a saved non-core JA release."""
    jid=row["jellyfin_id"]
    if not deep.validate_exhausted(jid,row):
        return False
    search=deep.search_record(jid)
    if not isinstance(search,dict):
        return False
    # The current deep engine only exhausts the two core stage adapters.
    # Known additional-provider candidates still need their source recovery.
    return not any(isinstance(c,dict) and
                   c.get("provider") not in deep.REQUIRED_PROVIDERS
                   for c in search.get("candidates") or [])


def ordered(rows, db, phase, deep, scope="all", timestamp=None):
    timestamp=now() if timestamp is None else timestamp
    previous={r["jellyfin_id"]:r for r in db.execute("SELECT * FROM jobs")}
    result=[]
    for row in rows:
        if not eligible(row,scope):
            continue
        jid=row["jellyfin_id"]
        old=previous.get(jid)
        # A different path is new evidence and not subject to the old cooldown.
        if old and old["video"]!=row["host_path"]:
            old=None
        if old and old["retry_after"]>timestamp:
            continue
        proven=source_proven(row,deep)
        if phase=="source" and proven or phase=="translation" and not proven:
            continue
        # No title is permanently retired based on an old receipt: a fresh
        # manifest says it is missing. Fresh titles precede old failures.
        if phase=="source":
            key=(0 if old is None else 1,
                 0 if row["kind"]=="Movie" else 1,
                 old["updated_at"] if old else 0,
                 str(row.get("title") or "").casefold(),jid)
        else:
            key=(0 if old and old["state"]=="translating" else 1,
                 0 if row["kind"]=="Movie" else 1,
                 old["updated_at"] if old else 0,jid)
        result.append((key,row))
    return [r for _,r in sorted(result,key=lambda x:x[0])]


def invoke(command):
    # Inherit the service journal, including actual publication receipts.
    return subprocess.run(command,stdin=subprocess.DEVNULL,check=False).returncode


def quiet_hours():
    return 2<=datetime.now().hour<5


def dispatch(rows, db, phase, deep, *, scope="all", limit=40,
             runner=invoke, clock=now, quiet=quiet_hours):
    selected=ordered(rows,db,phase,deep,scope,clock())
    counts={"selected":min(len(selected),limit),"covered":0,
            "source_ready":0,"published":0,"retry":0}
    print("SUBHUB_AUTO_PLAN",phase,"eligible",len(selected),
          "budget",limit,flush=True)
    for row in selected[:limit]:
        if phase=="translation" and not quiet():
            print("SUBHUB_AUTO_QUIET_WINDOW_ENDED",flush=True)
            break
        jid=row["jellyfin_id"]
        video=Path(row["host_path"])
        print("SUBHUB_AUTO_SELECTED",phase,jid,row.get("title"),flush=True)
        if video.is_file() and not video.is_symlink() and deep.stage.japanese_sidecar_exists(video):
            update(db,row,"covered")
            counts["covered"]+=1
            continue
        update(db,row,"sourcing" if phase=="source" else "translating",
               retry_after=clock()+INTERRUPTED_DELAY)
        stop=False
        try:
            if phase=="source":
                report=deep.run(jid)
                outcome=report.get("result")
                reason=str(report.get("reason") or "unknown_source_result")
                if outcome=="covered":
                    update(db,row,"covered")
                    counts["covered"]+=1
                    continue
                if outcome=="plamo" and source_proven(row,deep):
                    update(db,row,"source_ready")
                    counts["source_ready"]+=1
                    continue
                if outcome=="plamo":
                    reason="source_proof_incomplete_or_other_provider_pending"
                search=deep.search_record(jid) or {}
                stop=(search.get("_outcome")=="deferred" or
                      "quota" in reason.casefold() or "cooldown" in reason.casefold())
            else:
                # Revalidate immediately before invoking the exact-media
                # handoff; its own identity, GPU and QA checks still apply.
                if not source_proven(row,deep):
                    reason="source_proof_changed"
                else:
                    rc=runner([str(AI),"--apply","--source-exhausted-auto",
                               "--jellyfin-id",jid])
                    expected=video.with_name(video.stem+".ja.PLaMo8B.srt")
                    if not rc and expected.is_file() and not expected.is_symlink():
                        update(db,row,"published",published_path=str(expected))
                        counts["published"]+=1
                        print("SUBHUB_AUTO_PUBLISHED",jid,str(expected),flush=True)
                        continue
                    reason="translation_rc_"+str(rc) if rc else "publication_missing"
        except (OSError,ValueError,RuntimeError,sqlite3.Error,
                subprocess.SubprocessError) as exc:
            reason=type(exc).__name__+":"+str(exc)[:120]
        update(db,row,phase+"_retry",reason,clock()+HOLD_DELAY,count_attempt=True)
        counts["retry"]+=1
        print("SUBHUB_AUTO_RETRY",phase,jid,reason,flush=True)
        if stop:
            print("SUBHUB_AUTO_PROVIDER_PAUSED",flush=True)
            break
    print("SUBHUB_AUTO_SUMMARY",phase,json.dumps(counts,sort_keys=True),flush=True)
    return counts


def once(phase,limit):
    try:
        from . import subhub_deep_source as deep
        from . import ja_first_autofill as source
    except ImportError:
        import subhub_deep_source as deep
        import ja_first_autofill as source
    private_dir(INTAKE)
    private_dir(STATE)
    with mutex(STATE/".runner.lock"),mutex(SOURCE_LOCK):
        if phase=="translation" and not quiet_hours():
            print("SUBHUB_AUTO_OUTSIDE_QUIET_HOURS",flush=True)
            return
        settings=source.config()
        source.safe_source_settings(settings)
        if not source.native_search_disabled(settings):
            raise RuntimeError("native_duplicate_provider_search_enabled")
        source.check_scheduler_idle()
        path=catalog_path()
        if path is None or now()-int(path.stat().st_mtime)>CATALOG_TTL:
            source.refresh_manifest()
            path=catalog_path()
        if phase=="translation" and (not AI.is_file() or AI.is_symlink()):
            raise RuntimeError("subhub_ai_handoff_not_installed")
        rows=load_catalog(path)
        with connection() as db:
            dispatch(rows,db,phase,deep,scope=source.selected_source_scope(),limit=limit)


def status(db):
    print("SUBHUB_AUTO_STATUS")
    for row in db.execute("SELECT state,COUNT(*) FROM jobs GROUP BY state ORDER BY state"):
        print("STATE",row[0],row[1])
    for row in db.execute("""SELECT jellyfin_id,title,state,attempts,
                               retry_after,last_error FROM jobs
                            ORDER BY updated_at DESC LIMIT 12"""):
        print("JOB",*row)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action",choices=("status","source","translation","once"),
                        nargs="?",default="status")
    parser.add_argument("--limit",type=int)
    args=parser.parse_args(argv)
    if args.action=="status":
        with connection() as db:
            status(db)
        return
    phase="translation" if args.action=="once" else args.action
    limit=args.limit if args.limit is not None else (60 if phase=="source" else 3)
    if not 1<=limit<=(100 if phase=="source" else 10):
        parser.error("phase limit out of range")
    once(phase,limit)


if __name__=="__main__":
    os.umask(0o077)
    try:
        main()
    except (OSError,ValueError,RuntimeError,sqlite3.Error,
            subprocess.SubprocessError) as exc:
        print("SUBHUB_AUTO_BLOCKED",type(exc).__name__,str(exc)[:200],
              file=sys.stderr)
        raise SystemExit(1) from None
