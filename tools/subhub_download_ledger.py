#!/usr/bin/env python3
"""Actual SubHub subtitle download accounting, not an invented provider quota.

Only downloads through instrumented SubHub paths are observed; native Jellyfin,
manual users and third-party tools may spend the same account allowance without
appearing here. Days are grouped in Asia/Tokyo calendar time; provider quota
reset windows may differ. Pending attempts indicate interrupted/unknown results.
No credentials, URLs, media titles, Jellyfin IDs, candidate IDs, or subtitle
contents are persisted.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone, timedelta
import os
from pathlib import Path
import re
import sqlite3
import time
from zoneinfo import ZoneInfo

ROOT=Path.home()/"bruiser-pilot/ja-first-inventory"
LEDGER=ROOT/"subhub-provider-download-ledger.sqlite3"
JST=ZoneInfo("Asia/Tokyo")
PROVIDERS={"opensubtitles","subdl","yify","other","unknown"}
ROUTES={"jellyfin_subbuzz","jellyfin_native","sublarr_native","other"}
RESULTS={"pending","downloaded","quota_blocked","failed"}


def jellyfin_provider(candidate):
    """Use the actual encoded subbuzz backend when discoverable, else unknown."""
    ident=str(candidate.get("Id") or "").casefold()
    label=str(candidate.get("ProviderName") or "").casefold()
    if "opensubtitles" in ident or "open subtitles" in label:
        return "opensubtitles"
    if "subdl" in ident or label.startswith("subdl"):
        return "subdl"
    if "yify" in ident or label.startswith("yify"):
        return "yify"
    return "unknown"


def private_path(path):
    folder=path.parent
    if (not folder.is_dir() or folder.is_symlink() or
            folder.stat().st_mode & 0o077):
        raise RuntimeError("download_ledger_private_directory_invalid")
    if (path.is_symlink() or (path.exists() and
            (not path.is_file() or path.stat().st_mode & 0o077))):
        raise RuntimeError("download_ledger_private_database_invalid")


def connect(path=None):
    path=path or LEDGER
    private_path(path)
    mask=os.umask(0o077)
    try:
        con=sqlite3.connect(path,timeout=10)
    finally:
        os.umask(mask)
    con.execute("PRAGMA busy_timeout=10000")
    con.execute("""CREATE TABLE IF NOT EXISTS download_event (
       id INTEGER PRIMARY KEY,
       time_utc INTEGER NOT NULL,
       day_jst TEXT NOT NULL,
       provider TEXT NOT NULL,
       route TEXT NOT NULL,
       outcome TEXT NOT NULL,
       bytes INTEGER,
       error_kind TEXT
    )""")
    con.execute("""CREATE INDEX IF NOT EXISTS download_day
                   ON download_event(day_jst,provider)""")
    con.commit()
    return con


def begin(provider,route,*,at=None,path=None):
    """Commit intent BEFORE the external request so crashes stay visible."""
    if provider not in PROVIDERS or route not in ROUTES:
        raise ValueError("download_ledger_invalid_provider_or_route")
    at=int(time.time()) if at is None else int(at)
    if at<0:
        raise ValueError("download_ledger_invalid_time")
    day=datetime.fromtimestamp(at,timezone.utc).astimezone(JST).date().isoformat()
    with connect(path) as con:
        cur=con.execute("""INSERT INTO download_event
             (time_utc,day_jst,provider,route,outcome)
             VALUES(?,?,?,?,'pending')""",(at,day,provider,route))
        return cur.lastrowid


def finish(event_id,outcome,*,byte_count=None,error_kind=None,path=None):
    if type(event_id) is not int or event_id<1 or outcome not in RESULTS-{"pending"}:
        raise ValueError("download_ledger_invalid_result")
    if byte_count is not None and (type(byte_count) is not int or
                                   not 0<=byte_count<=5_000_000):
        raise ValueError("download_ledger_invalid_byte_count")
    if error_kind is not None and (not isinstance(error_kind,str) or
            not re.fullmatch(r"[A-Za-z0-9_]{1,48}",error_kind)):
        raise ValueError("download_ledger_invalid_error_kind")
    if outcome=="downloaded" and (byte_count is None or byte_count<=0):
        raise ValueError("download_ledger_success_requires_bytes")
    with connect(path) as con:
        changed=con.execute("""UPDATE download_event
            SET outcome=?,bytes=?,error_kind=? WHERE id=? AND outcome='pending'""",
            (outcome,byte_count,error_kind,event_id)).rowcount
        if changed!=1:
            raise RuntimeError("download_ledger_event_already_closed_or_missing")


def record_completed(provider,route,byte_count,*,at=None,path=None):
    """Record a verified successful native result without duplicating old caches."""
    event=begin(provider,route,at=at,path=path)
    finish(event,"downloaded",byte_count=byte_count,path=path)


def summary(*,at=None,path=None,days=7):
    """Only factual observed events; no guessed account-wide allowance."""
    if not 1<=days<=31:
        raise ValueError("download_ledger_invalid_history_length")
    at=int(time.time()) if at is None else int(at)
    today=datetime.fromtimestamp(at,timezone.utc).astimezone(JST).date()
    day_keys=[(today-timedelta(days=i)).isoformat() for i in range(days)]
    with connect(path) as con:
        rows=con.execute("""SELECT day_jst,provider,outcome,count(*),sum(bytes)
             FROM download_event WHERE day_jst >= ?
             GROUP BY day_jst,provider,outcome""",(day_keys[-1],)).fetchall()
    daily={day:{"downloaded":0,"attempted":0,"quota_blocked":0,
                "failed":0,"pending":0,"bytes":0,"providers":{}}
           for day in day_keys}
    for day,provider,outcome,count,nbytes in rows:
        if day not in daily:continue
        record=daily[day]
        entry=record["providers"].setdefault(provider,{
            "downloaded":0,"attempted":0,"quota_blocked":0,
            "failed":0,"pending":0,"bytes":0})
        for target in (record,entry):
            target["attempted"]+=count
            target[outcome]+=count
            if outcome=="downloaded":
                target["bytes"]+=nbytes or 0
    return {
       "available":True,"basis":"instrumented_SubHub_download_requests_only",
       "calendar":"Asia/Tokyo","quota_limit":None,
       "quota_reset":None,"account_wide_total_known":False,
       "today":daily[day_keys[0]],
       "recent_days":[{"date":day,**daily[day]} for day in day_keys],
    }
