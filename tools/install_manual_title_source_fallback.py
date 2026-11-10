#!/usr/bin/env python3
"""Patch ONLY current SubHub manual Japanese sourcing to retry by title.

No whole-dashboard reinstall, no media creation/modification, no services
other than a dashboard restart, and no provider requests. Every source edit
is anchored and create-only backed up. Refuse unknown/partial installations.
"""
from __future__ import annotations

import ast
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime

SOURCE = Path.home()/"bruiser-pilot/subhub-control/ja_first_search_pilot.py"
SEASON = Path.home()/".local/share/bruiser-subhub-dashboard/subhub_season_sources.py"
BACKUP_ROOT=Path.home()/"bruiser-pilot/subhub-control"
UNIT="bruiser-subhub-dashboard.service"

SRC_OLD_ONE = '''        req = Request(url, data=json.dumps(payload).encode(), headers=headers, method="POST")
        with urlopen(req, timeout=90) as res:
            data = json.load(res)
        results = []
'''
SRC_NEW_ONE = '''        req = Request(url, data=json.dumps(payload).encode(), headers=headers, method="POST")
        with urlopen(req, timeout=90) as res:
            data = json.load(res)
        original_total = data.get("total")
        query_variant = "original"
        # Manual, selected-episode recheck only. OpenSubtitles can return zero
        # for an upload not linked to the IMDb ID / video hash even when a
        # series-title + SxxExx search finds an exact release. Do not use this
        # fallback in scheduled/default provider searches.
        if (job.get("retry_by_title") is True and
            payload.get("series_title") and
            type(payload.get("season")) is int and
            type(payload.get("episode")) is int and
            (payload.get("imdb_id") or payload.get("file_path")) and
            original_total == 0 and not data.get("results")):
            title_payload = dict(payload)
            title_payload.pop("imdb_id", None)
            title_payload["file_path"] = ""
            time.sleep(3.3)  # Sublarr limit 20 / minute
            req = Request(url, data=json.dumps(title_payload).encode(),
                          headers=headers, method="POST")
            with urlopen(req, timeout=90) as res:
                data = json.load(res)
            query_variant = "title_only_fallback"
        results = []
'''
SRC_OLD_TWO = '''        out = {"id": job["id"], "ok": True, "total": data.get("total"),
               "results": results}'''
SRC_NEW_TWO = '''        out = {"id": job["id"], "ok": True, "total": data.get("total"),
               "initial_total": original_total,
               "query_variant": query_variant, "results": results}'''

SEASON_OLD_ONE = '''                    input=json.dumps([{"id":job["id"],"query":job["query"]}]),
'''
SEASON_NEW_ONE = '''                    input=json.dumps([{"id":job["id"],"query":job["query"],
                                       "retry_by_title":bool(recheck)}]),
'''
SEASON_OLD_TWO = '''                options = result.get("results") or []
                # Keep ALL provider results, even identity rejects, as
'''
SEASON_NEW_TWO = '''                options = result.get("results") or []
                if result.get("query_variant") == "title_only_fallback":
                    print("SEASON_JA_TITLE_FALLBACK",label,
                          "initial_total",result.get("initial_total"),
                          "title_total",result.get("total"),flush=True)
                # Keep ALL provider results, even identity rejects, as
'''

def fail(msg):
    raise RuntimeError(msg)

def safe_file(path):
    if not path.is_file() or path.is_symlink():
        fail(f"Missing or symlinked existing source: {path}")
    if path.stat().st_uid != os.getuid():
        fail(f"Source not owned by current user: {path}")

def check_idle():
    for unit in ("bruiser-ja-source-autofill.service",
                 "bruiser-subhub-season-sources.service",
                 "bruiser-subhub-batch.service"):
        result=subprocess.run(
            ["systemctl","--user","is-active",unit],
            capture_output=True,text=True,timeout=15)
        if result.stdout.strip() in ("active","activating","reloading"):
            fail("Source worker currently active: "+unit)

def patch_one(path,patches):
    safe_file(path)
    original=path.read_text(encoding="utf-8")
    current=original
    installed=True
    for old,new in patches:
        if current.count(new)==1 and old not in current:
            continue
        installed=False
        if current.count(old)!=1 or new in current:
            fail(f"Unknown or partial source version, refusing: {path.name}")
        current=current.replace(old,new)
    ast.parse(current,filename=str(path))
    if path==SOURCE:
        if 'query_variant = "title_only_fallback"' not in current or current.count("retry_by_title")<1:
            fail("Source fallback preflight did not match")
    if path==SEASON and "retry_by_title" not in current:
        fail("Season worker preflight did not match")
    return original,current,installed

def write_atomic(path,data):
    fd,name=tempfile.mkstemp(prefix="."+path.name+".tmp-",dir=path.parent)
    try:
        with os.fdopen(fd,"w",encoding="utf-8") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(name,path.stat().st_mode & 0o777)
        os.replace(name,path)
    finally:
        Path(name).unlink(missing_ok=True)

def service_restart():
    return subprocess.run(["systemctl","--user","restart",UNIT],
                          capture_output=True,text=True,timeout=40)

def main():
    check_idle()
    files=[
      (SOURCE,[(SRC_OLD_ONE,SRC_NEW_ONE),(SRC_OLD_TWO,SRC_NEW_TWO)]),
      (SEASON,[(SEASON_OLD_ONE,SEASON_NEW_ONE),(SEASON_OLD_TWO,SEASON_NEW_TWO)])
    ]
    prepared=[]
    for path,patches in files:
        before,after,installed=patch_one(path,patches)
        prepared.append((path,before,after,installed))
        print(path.name,"already_current" if installed else "patch_preflight_passed")
    if all(i for *_,i in prepared):
        print("ALREADY INSTALLED: no changes")
        return
    if any(i for *_,i in prepared):
        fail("Partially installed across files; manual comparison required")
    if not BACKUP_ROOT.is_dir() or BACKUP_ROOT.is_symlink():
        fail("Existing private SubHub code directory unavailable")
    backup=BACKUP_ROOT/(".manual-ja-source-backup-"+datetime.now().strftime("%Y%m%dT%H%M%S"))
    backup.mkdir(mode=0o700)
    for path,before,_,_ in prepared:
        dest=backup/path.name
        with open(dest,"x",encoding="utf-8") as stream:
            stream.write(before)
        os.chmod(dest,0o600)
    print("ORIGINALS SAVED:",backup)

    changed=[]
    try:
        for path,before,after,_ in prepared:
            write_atomic(path,after)
            changed.append((path,before))
        # Do not silently touch a stopped dashboard.
        state=subprocess.run(["systemctl","--user","is-active",UNIT],
                             capture_output=True,text=True,timeout=15)
        if state.stdout.strip()=="active":
            result=service_restart()
            if result.returncode:
                fail("Dashboard restart failed; changes will be rolled back")
            print("DASHBOARD: restarted existing service")
        else:
            print("DASHBOARD: not active; no service started")
    except Exception:
        for path,before in changed:
            write_atomic(path,before)
        print("ROLLBACK: source files restored; backup remains",backup,file=sys.stderr)
        raise
    print("INSTALLED: explicit selected-episode recheck gains title-only fallback")
    print("Existing 30-day scheduled-search policy and provider settings unchanged")
    print("MEDIA: no downloads, translation, subtitles, or video files modified")

if __name__=="__main__":
    try:main()
    except (OSError,ValueError,RuntimeError,subprocess.SubprocessError) as err:
        print("INSTALL HELD:",type(err).__name__,str(err)[:200],file=sys.stderr)
        raise SystemExit(1)
