#!/usr/bin/env python3
"""Durable, one-at-a-time source-first EN->JA dispatcher for Bruiser SubHub.

Operates on Jellyfin-authoritative movie inventory. Existing Japanese source
provider acquisition remains the responsibility of the single installed source
worker; this translates only source-exhausted items, or provider-quota-paused
items without a cached plausible Japanese result and with an actual English
SRT on disk. No provider calls, changes to media bytes, or new accounts.

Run by one user systemd timer, after installation/enable; no cron, no daemon
or background subprocesses. A kernel lock prevents collisions with JA sourcing.
PLaMo stores every completed cue in its existing SQLite progress database.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
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
BATCH=ROOT/"batch-control"/"current.json"
SEARCH=INTAKE/"japanese-search.sqlite3"
STAGES=INTAKE/"japanese-stage.sqlite3"
AI=HOME/".local/bin/subhub-ai"
JID=re.compile(r"[a-f0-9]{32}\Z")
EN={"en","eng","english"}
VIDEO={".mkv",".mp4",".avi",".m4v",".mov",".webm",".m2ts",".ts"}
SOURCE_WAIT=6*3600
HOLD_DELAY=12*3600
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


def source_quota_paused(path=BATCH):
    path=Path(path)
    if not path.is_file() or path.is_symlink() or path.stat().st_mode & 0o077:
        return False
    data=json.loads(path.read_text("utf-8"))
    if not data.get("quota_exhausted"):
        return False
    # Old batch status is NOT permission to bypass the source-first order.
    # Only accept a quota flag observed in the last 24 hours.
    raw=data.get("updated_utc") or ""
    try:
        stamp=datetime.fromisoformat(raw.replace("Z","+00:00"))
        age=datetime.now(timezone.utc)-stamp.astimezone(timezone.utc)
        return 0<=age.total_seconds()<=86400
    except (TypeError,ValueError):
        return False


def read_searches(path=SEARCH):
    if not path.is_file() or path.is_symlink() or path.stat().st_mode & 0o077:
        return {}
    with sqlite3.connect("file:"+str(path.resolve())+"?mode=ro",uri=True,timeout=8) as db:
        return {str(j):(str(outcome),int(searched)) for j,outcome,searched in
                db.execute("SELECT jellyfin_id,outcome,searched_at FROM searches")}


def read_staged(path=STAGES):
    if not path.is_file() or path.is_symlink() or path.stat().st_mode & 0o077:
        return set()
    with sqlite3.connect("file:"+str(path.resolve())+"?mode=ro",uri=True,timeout=8) as db:
        return {str(j) for (j,) in db.execute(
            "SELECT DISTINCT jellyfin_id FROM staged WHERE status IN ('staged','published')")}


def local_en(video):
    """A real, language-tagged source, not catalog's speculative EN flag."""
    prefix=video.stem.casefold()+"."
    try:
        for item in video.parent.iterdir():
            if item.is_symlink() or not item.is_file() or item.suffix.casefold()!=".srt":
                continue
            if not item.name.casefold().startswith(prefix):
                continue
            tokens={t for t in re.findall(r"[a-z0-9]+",
                    item.name[len(video.stem)+1:-4].casefold())}
            if tokens & EN and not tokens & {"ja","jp","jpn","forced"}:
                if 0<item.stat().st_size<=2_000_000:
                    return True
    except OSError:
        return False
    return False


def local_ja(video):
    prefix=video.stem.casefold()+"."
    try:
        for item in video.parent.iterdir():
            if item.name.casefold().startswith(prefix) and (
                    item.is_symlink() or item.is_file()):
                if item.suffix.casefold() not in {".srt",".vtt",".ass",".ssa"}:
                    continue
                tokens={t for t in re.findall(r"[a-z0-9]+",
                        item.name[len(video.stem)+1:-len(item.suffix)].casefold())}
                if tokens & {"ja","jp","jpn","japanese","editorial"}:
                    return True
    except OSError:
        return True
    return False


def candidates(rows, searches, staged, quota_paused, timestamp=None):
    """Select movies with verified metadata and a real EN source; fail closed."""
    timestamp=now() if timestamp is None else timestamp
    good=[]
    for row in rows:
        if not isinstance(row,dict) or row.get("kind")!="Movie" or (
                row.get("status")!="ready_ja_search"):
            continue
        jid=str(row.get("jellyfin_id") or "")
        audio=str(row.get("audio_language") or "").strip().lower()
        path=str(row.get("host_path") or "")
        if not JID.fullmatch(jid) or audio not in EN or jid in staged:
            continue
        video=Path(path)
        if not video.is_absolute() or video.suffix.lower() not in VIDEO or (
                video.is_symlink() or not video.is_file()):
            continue
        if local_ja(video) or not local_en(video):
            continue
        history=searches.get(jid)
        if history:
            outcome,when=history
            if outcome in ("plausible","review","in_progress"):
                continue
            if outcome=="none" and when>timestamp-30*86400:
                pass
            elif quota_paused and outcome in ("none","error"):
                pass
            else:
                continue
        elif not quota_paused:
            continue
        good.append(row)
    good.sort(key=lambda x:(
        0 if x.get("kind")=="Movie" and "horror" in (
            str(x.get("genres") or "")+" "+str(x.get("host_path") or "")).lower() else 1,
        str(x.get("title") or "").casefold(),str(x["jellyfin_id"])))
    return good


def choose(rows, db, searches, staged, quota_paused, timestamp=None):
    timestamp=now() if timestamp is None else timestamp
    listing=candidates(rows,searches,staged,quota_paused,timestamp)
    recover=[]
    fresh=[]
    for row in listing:
        previous=state_for(db,row["jellyfin_id"])
        if previous and previous["state"]=="published":
            continue
        if previous and previous["retry_after"]>timestamp:
            continue
        if previous and previous["state"] in ("preparing","translating"):
            recover.append(row)
        else:
            fresh.append(row)
    return (recover+fresh)[0] if recover or fresh else None


def invoke(command, on_line=None, runner=None):
    """Stream model events into journal, no shell command or secrets in logs."""
    if runner is not None:
        return runner(command)
    process=subprocess.Popen(command,stdin=subprocess.DEVNULL,
                              stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                              text=True,bufsize=1)
    assert process.stdout is not None
    for line in process.stdout:
        line=line.rstrip()
        if (line.startswith("SUBHUB_AI_") or line.startswith("SUBHUB_AI_HELD")):
            print(line,flush=True)
            if on_line:
                on_line(line)
    return process.wait()


def once(db=None, *, runner=invoke, clock=now, refresh=True):
    """One media item per invocation. A user timer handles reboot and retries."""
    private_dir(INTAKE)
    private_dir(STATE)
    with mutex(STATE/".runner.lock"):
        # Same source lock as the existing source-only user timer / manual batch.
        with mutex(SOURCE_LOCK):
            if refresh:
                path=catalog_path()
                if path is None or clock()-int(path.stat().st_mtime)>CATALOG_TTL:
                    if not CODE.is_file() or CODE.is_symlink():
                        raise RuntimeError("catalog_refresh_component_missing")
                    print("SUBHUB_AUTO_CATALOG_REFRESH",flush=True)
                    subprocess.run([sys.executable,"-u",str(CODE),"--save"],
                                   stdin=subprocess.DEVNULL,timeout=1800,check=True)
            items=load_catalog(catalog_path())
            histories=read_searches()
            staged=read_staged()
            paused=source_quota_paused()
            if not AI.is_file() or AI.is_symlink():
                raise RuntimeError("subhub_ai_handoff_not_installed")
            managed=db is None
            connection_db=db if db is not None else connection()
            try:
                row=choose(items,connection_db,histories,staged,paused,clock())
                if row is None:
                    print("SUBHUB_AUTO_NO_READY_ENGLISH_MOVIES",
                          "quota_paused="+str(paused),flush=True)
                    return None
                jid=row["jellyfin_id"]
                video=row["host_path"]
                print("SUBHUB_AUTO_SELECTED",jid,row.get("title"),flush=True)
                common=["--explicit-movie-pilot","--jellyfin-id",jid,
                        "--movie-path",video]
                update(connection_db,row,"preparing")
                prep=runner([str(AI),"--prepare",*common])
                if prep:
                    update(connection_db,row,"held","english_prepare_rc_"+str(prep),
                           clock()+HOLD_DELAY,count_attempt=True)
                    print("SUBHUB_AUTO_HELD",jid,"english_prepare_rc",prep,flush=True)
                    return jid
                update(connection_db,row,"translating")
                rc=runner([str(AI),"--apply",*common])
                if rc:
                    update(connection_db,row,"held","translation_rc_"+str(rc),
                           clock()+HOLD_DELAY,count_attempt=True)
                    print("SUBHUB_AUTO_HELD",jid,"translation_rc",rc,flush=True)
                    return jid
                expected=Path(video).with_name(Path(video).stem+".ja.PLaMo8B.srt")
                if not expected.is_file() or expected.is_symlink():
                    update(connection_db,row,"held","publication_missing",
                           clock()+HOLD_DELAY,count_attempt=True)
                    return jid
                update(connection_db,row,"published",published_path=str(expected))
                print("SUBHUB_AUTO_PUBLISHED",jid,str(expected),flush=True)
                return jid
            finally:
                if managed:
                    connection_db.close()


def status(db):
    print("SUBHUB_AUTO_STATUS")
    for row in db.execute(
        "SELECT state,COUNT(*) FROM jobs GROUP BY state ORDER BY state"):
        print("STATE",row[0],row[1])
    for row in db.execute("""SELECT jellyfin_id,title,state,attempts,
                                  retry_after,last_error FROM jobs
                             ORDER BY updated_at DESC LIMIT 12"""):
        print("JOB",*row)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action",choices=("status","once"),nargs="?",default="status")
    args=parser.parse_args(argv)
    if args.action=="once":
        return once()
    with connection() as db:
        status(db)


if __name__=="__main__":
    try:
        main()
    except (OSError,ValueError,RuntimeError,sqlite3.Error,
            subprocess.SubprocessError) as exc:
        print("SUBHUB_AUTO_BLOCKED",type(exc).__name__,str(exc)[:200],
              file=sys.stderr)
        raise SystemExit(1) from None
