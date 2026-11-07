#!/usr/bin/env python3
"""Read exact OpenSubtitles account allowance using Sublarr's saved credentials.

No downloads, subtitle searches, or credentials printed. When unavailable,
return unknown rather than guessing a plan limit. Standalone on the host.
"""
from __future__ import annotations

import json
import subprocess
import sys

RESERVE = 5
WORKER = r'''
import json, os, sqlite3
from pathlib import Path
from urllib.parse import quote
from flask import Flask
from config import get_settings
from extensions import db as flask_db
from db.repositories.provider_account_pool import ProviderAccountPoolRepository
from services.key_selector import get_key_selector
from providers.opensubtitles import OpenSubtitlesProvider
from config_crypto import decrypt

def account():
    cfg=get_settings()
    if cfg.database_url and not str(cfg.database_url).startswith("sqlite"):
        raise RuntimeError("external_database_not_supported")
    path=Path(cfg.db_path)
    keyfile=Path(os.environ.get("SUBLARR_CONFIG_DIR",cfg.config_dir)) / ".encryption_key"
    if not path.is_file() or path.is_symlink() or not keyfile.is_file() or keyfile.is_symlink():
        raise RuntimeError("existing_config_unavailable")
    app=Flask("bruiser_quota_readonly")
    app.config["SQLALCHEMY_DATABASE_URI"]=cfg.get_database_url()
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"]=False
    flask_db.init_app(app)
    with app.app_context():
        repository=ProviderAccountPoolRepository()
        entries=repository.get_all_for("opensubtitles")
        if entries:
            selected=get_key_selector().pick(
                "opensubtitles", provider_rate_limits=OpenSubtitlesProvider.rate_limits)
            if not selected:
                raise RuntimeError("account_pool_unavailable")
            return (selected.get("api_key") or "", selected.get("username") or "",
                    selected.get("password") or "")
    uri="file:"+quote(str(path.resolve()),safe="/")+"?mode=ro"
    with sqlite3.connect(uri,uri=True,timeout=8) as db:
        entries=dict(db.execute(
            "SELECT key,value FROM config_entries WHERE key IN "
            "('opensubtitles_api_key','opensubtitles_username','opensubtitles_password')"
        ).fetchall())
    return tuple(decrypt(entries.get(x)) or "" for x in
                 ("opensubtitles_api_key","opensubtitles_username","opensubtitles_password"))

try:
    key,username,password=account()
    if not (key and username and password):
        raise RuntimeError("authenticated_account_required")
    p=OpenSubtitlesProvider(api_key=key,username=username,password=password)
    p.initialize()
    try:
        if not p.session or not getattr(p,"_token",None):
            raise RuntimeError("authenticated_session_unavailable")
        response=p.session.get(p._api_base+"/infos/user",timeout=12)
        if response.status_code!=200:
            raise RuntimeError("account_info_http_"+str(response.status_code))
        data=response.json().get("data",{})
        allowed=data.get("allowed_downloads")
        used=data.get("downloads_count")
        remaining=data.get("remaining_downloads")
        if any(type(x) is not int or x<0 for x in (allowed,used,remaining)):
            raise RuntimeError("quota_fields_missing")
        print("BRUISER_QUOTA_JSON:"+json.dumps({
            "known":True,"allowed":allowed,"used":used,"remaining":remaining,
            "reserve":5,"automatic_budget":max(0,remaining-5),
            "reset":data.get("reset_time_utc") or None,
        }),flush=True)
    finally:
        p.terminate()
except Exception as exc:
    print("BRUISER_QUOTA_JSON:"+json.dumps({
        "known":False,"reason":type(exc).__name__+":"+str(exc)[:65]}),flush=True)
'''

def get_quota(timeout=45):
    completed=subprocess.run(
        ["docker","exec","-i","-e","PYTHONPATH=/app","sublarr-pilot",
         "python3","-c",WORKER],
        capture_output=True,text=True,stdin=subprocess.DEVNULL,timeout=timeout,
        check=False)
    lines=[line for line in completed.stdout.splitlines()
           if line.startswith("BRUISER_QUOTA_JSON:")]
    if completed.returncode or not lines:
        return {"known":False,"reason":"account_quota_probe_failed"}
    try:
        data=json.loads(lines[-1].split(":",1)[1])
        if data.get("known") is True and all(
            type(data.get(k)) is int for k in ("allowed","used","remaining","automatic_budget")
        ):
            return data
        return {"known":False,"reason":str(data.get("reason") or "account_unavailable")[:80]}
    except (ValueError,TypeError):
        return {"known":False,"reason":"quota_response_invalid"}

if __name__=="__main__":
    json.dump(get_quota(),sys.stdout,sort_keys=True)
    sys.stdout.write("\n")
