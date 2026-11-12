#!/usr/bin/env python3
"""Durable exact-title Finish job index + read-only legacy journal display.

The Finisher is the *sole writer* to its own SQLite table. The dashboard reads
it through readonly SQLite. For a previously installed, uninstrumented job,
journal reconstruction is explicitly partial and never called a full history.
No subtitle provider calls, media mutations or implicit human-review actions.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import time
from urllib.parse import quote

ROOT=Path.home()/"bruiser-pilot/ja-first-inventory"
DB=ROOT/"finish-scope-items.sqlite3"
ID=re.compile(r"[0-9a-f]{32}\Z")
STATES=frozenset(("source_pending","source_active","source_retry",
    "plamo_queued","plamo_active","covered_initial","covered_observed",
    "published_source","published_plamo"))
FILTERS=frozenset(("all","current","sourcing","plamo","published","covered"))
LIMIT=75
_MAX_LOG_LINES=9000
_CACHE={"when":0.0,"key":None,"value":None}


def label(row,season=0,episode=0):
    kind=str(row.get("kind") or "")
    title=str(row.get("title") or "Untitled")[:170]
    year=row.get("year")
    if kind=="Episode" or season:
        series=str(row.get("series_title") or row.get("series") or "")[:140]
        prefix=f"{series} S{int(season):02d}E{int(episode):02d} "
        return (prefix+title)[:250]
    return (title+(f" ({year})" if isinstance(year,int) else ""))[:250]


def _secure_path(create=False):
    if (not ROOT.is_dir() or ROOT.is_symlink() or
            ROOT.stat().st_mode & 0o077):
        raise RuntimeError("finish_titles_root_not_private")
    if DB.is_symlink():
        raise RuntimeError("finish_titles_symlink")
    if not DB.exists() and create:
        fd=os.open(DB,os.O_WRONLY|os.O_CREAT|os.O_EXCL|
                   getattr(os,"O_NOFOLLOW",0),0o600)
        os.close(fd)
    if DB.exists() and (not DB.is_file() or DB.stat().st_mode & 0o077):
        raise RuntimeError("finish_titles_not_private")
    return DB.exists()


def _connect(write=False):
    if not _secure_path(create=write):
        return None
    if write:
        return sqlite3.connect(DB,timeout=15)
    uri="file:"+quote(str(DB.resolve()),safe="/")+"?mode=ro"
    return sqlite3.connect(uri,uri=True,timeout=8)


def initialize(run_id,selection,metadata,initial_covered):
    """One atomic, bounded current-job snapshot, including preexisting JP."""
    if not isinstance(run_id,str) or not re.fullmatch(r"[0-9]+-[0-9]+\Z",run_id):
        raise ValueError("invalid_finish_run_id")
    if len(selection)>60_000:
        raise RuntimeError("finish_selection_too_large")
    now=int(time.time())
    entries=[]
    for season,episode,jid in selection:
        if not ID.fullmatch(str(jid)):
            raise ValueError("invalid_finish_item_id")
        row=metadata.get(jid,{})
        entries.append((jid,label(row,season,episode),
                        str(row.get("kind") or ("Episode" if season else "Movie")),
                        "covered_initial" if jid in initial_covered else "source_pending",
                        "",now))
    with _connect(write=True) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS items(
            jellyfin_id TEXT PRIMARY KEY,title TEXT NOT NULL,
            kind TEXT NOT NULL,state TEXT NOT NULL,
            detail TEXT NOT NULL,updated_at INTEGER NOT NULL)""")
        db.execute("CREATE INDEX IF NOT EXISTS items_state_idx ON items(state,updated_at)")
        db.execute("CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL)")
        db.execute("DELETE FROM items")
        db.executemany("INSERT INTO items VALUES(?,?,?,?,?,?)",entries)
        db.execute("INSERT OR REPLACE INTO metadata VALUES('run_id',?)",(run_id,))
        db.execute("INSERT OR REPLACE INTO metadata VALUES('created_at',?)",(str(now),))
        db.commit()


def update(jid,state,detail=""):
    if not ID.fullmatch(str(jid)) or state not in STATES:
        raise ValueError("invalid_finish_title_update")
    with _connect(write=True) as db:
        cursor=db.execute(
            "UPDATE items SET state=?,detail=?,updated_at=? WHERE jellyfin_id=?",
            (state,str(detail)[:160],int(time.time()),jid))
        if cursor.rowcount!=1:
            raise RuntimeError("finish_item_not_in_current_queue")
        db.commit()


def _filter(state):
    if state=="current":
        return "state IN ('source_active','plamo_active')"
    if state=="sourcing":
        return "state IN ('source_pending','source_active','source_retry')"
    if state=="plamo":
        return "state IN ('plamo_queued','plamo_active')"
    if state=="published":
        return "state IN ('published_source','published_plamo')"
    if state=="covered":
        return "state IN ('covered_initial','covered_observed','published_source','published_plamo')"
    return "1=1"


def _limit(state,page):
    if state not in FILTERS or type(page) is not int or not 0<=page<=1000:
        raise ValueError("invalid_finish_title_filter")


def persisted(run_id,state="all",page=0):
    _limit(state,page)
    if not run_id:
        return None
    db=_connect()
    if db is None:
        return None
    with db:
        try:
            found=db.execute("SELECT value FROM metadata WHERE key='run_id'").fetchone()
            if not found or found[0]!=run_id:
                return None
            counts=dict(db.execute("SELECT state,COUNT(*) FROM items GROUP BY state"))
            condition=_filter(state)
            total=db.execute("SELECT COUNT(*) FROM items WHERE "+condition).fetchone()[0]
            rows=db.execute(
                "SELECT jellyfin_id,title,kind,state,detail,updated_at FROM items "
                "WHERE "+condition+" ORDER BY updated_at DESC,title COLLATE NOCASE "
                "LIMIT ? OFFSET ?",(LIMIT,page*LIMIT)).fetchall()
        except sqlite3.OperationalError:
            return None
    return {"source":"durable_finish_job","complete_history":True,
            "run_id":run_id,"counts":counts,"state":state,"page":page,
            "total_matching":total,"more":(page+1)*LIMIT<total,
            "items":[dict(zip(("jellyfin_id","title","kind","state","detail",
                                "updated_at"),row)) for row in rows]}


def _catalog_titles():
    """Only index saved Jellyfin names, no media probes or reindexing."""
    try:
        from . import subhub_library_coverage as coverage
    except ImportError:
        import subhub_library_coverage as coverage
    path=coverage.latest_manifest()
    if path is None:
        return {}
    if path.stat().st_size>60_000_000:
        raise RuntimeError("finish_catalog_too_large")
    doc=json.loads(path.read_text("utf-8"))
    titles={}
    for row in doc.get("items",[]):
        if not isinstance(row,dict):
            continue
        jid=str(row.get("jellyfin_id") or "")
        if ID.fullmatch(jid):
            titles[jid]=(label(row,int(row.get("season") or 0),
                                      int(row.get("episode") or 0)),
                         str(row.get("kind") or "Movie"))
    return titles


def _journal(receipt):
    """Legacy active job: only last N lines, never claim exhaustive history."""
    since=int(receipt.get("started_at") or time.time()-86400)
    since_text=datetime.fromtimestamp(since,timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S UTC")
    cmd=["journalctl","--user","-u","bruiser-subhub-finish-scope.service",
         "--since",since_text,"-n",str(_MAX_LOG_LINES),
         "--no-pager","-o","cat"]
    run=subprocess.run(cmd,capture_output=True,text=True,timeout=15)
    if run.returncode:
        raise RuntimeError("finish_journal_unavailable")
    return run.stdout.splitlines()


def legacy(receipt,state="all",page=0):
    """Read-only title reconstruction for running pre-instrumentation workers."""
    _limit(state,page)
    key=(receipt.get("started_at"),receipt.get("updated_utc"))
    now=time.monotonic()
    if _CACHE["value"] is None or _CACHE["key"]!=key or now-_CACHE["when"]>12:
        titles=_catalog_titles()
        transitions={}
        for line in _journal(receipt):
            match=re.search(r"FINISH_(COVERED|PLAMO_QUEUE|PLAMO_PUBLISHED|"
                            r"PLAMO_RETRY|SOURCE_RETRY|SOURCE_REQUEUE):\s*([a-f0-9]{32})",
                            line)
            if not match:
                continue
            event,jid=match.group(1),match.group(2)
            status={
                # The pre-instrumentation worker did not record whether
                # coverage was genuinely NEW versus already installed.
                "COVERED":"covered_observed",
                "PLAMO_QUEUE":"plamo_queued",
                "PLAMO_PUBLISHED":"published_plamo",
                "PLAMO_RETRY":"plamo_queued",
                "SOURCE_RETRY":"source_retry",
                "SOURCE_REQUEUE":"source_retry"
            }[event]
            name,kind=titles.get(jid,(jid,"Unknown"))
            transitions[jid]={"jellyfin_id":jid,"title":name,
                              "kind":kind,"state":status,"detail":"",
                              "updated_at":0}
        raw_current=str(receipt.get("current") or "")
        ids=re.findall(r"\b[a-f0-9]{32}\b",raw_current)
        if ids and receipt.get("state")=="running":
            jid=ids[-1]
            name,kind=titles.get(jid,(jid,"Unknown"))
            phase=str(receipt.get("phase") or "")
            transitions[jid]={"jellyfin_id":jid,"title":name,
                              "kind":kind,
                              "state":"plamo_active" if phase=="translation"
                                      else "source_active",
                              "detail":"Current item per saved job receipt",
                              "updated_at":int(time.time())}
        _CACHE.update(when=now,key=key,value=list(transitions.values()))
    rows=_CACHE["value"]
    condition=state
    if condition=="all":
        selected=rows
    elif condition=="current":
        selected=[r for r in rows if r["state"] in
                  ("source_active","plamo_active")]
    elif condition=="sourcing":
        selected=[r for r in rows if r["state"] in
                  ("source_retry","source_active")]
    elif condition=="plamo":
        selected=[r for r in rows if r["state"] in
                  ("plamo_queued","plamo_active")]
    elif condition=="published":
        selected=[r for r in rows if r["state"] in
                  ("published_source","published_plamo")]
    else:
        selected=[r for r in rows if r["state"] in
                  ("covered_observed","published_source","published_plamo")]
    selected=sorted(selected,key=lambda r:(
        0 if r["state"] in ("source_active","plamo_active") else 1,
        r["title"].casefold()))
    total=len(selected)
    return {"source":"recent_worker_journal","complete_history":False,
            "note":"Reconstructed from recent journal lines only; older title "
                   "events may be absent. FINISH_COVERED is not proof of a "
                   "new publication and preexisting Japanese is not counted.",
            "state":state,"page":page,"total_matching":total,
            "more":(page+1)*LIMIT<total,
            "counts":dict(Counter(r["state"] for r in rows)),
            "items":selected[page*LIMIT:(page+1)*LIMIT]}


def report(receipt,state="all",page=0):
    """Prefer complete durable current-run table, fall back to legacy journal."""
    _limit(state,page)
    if not isinstance(receipt,dict):
        raise ValueError("no_finish_scope_receipt")
    found=persisted(receipt.get("run_id"),state,page)
    return found if found is not None else legacy(receipt,state,page)
