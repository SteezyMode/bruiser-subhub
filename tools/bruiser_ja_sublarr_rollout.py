#!/usr/bin/env python3
"""Bruiser Japanese-first activation for installed Sublarr 1.18.0.

DEFAULT: plan only. --apply: enable six *existing* paths for Japanese Wanted
scanning and bounded native-provider scheduled search+ffsubsync.
Never prompts for or prints account credentials. Never edits a subtitle itself.
All 4 formerly disabled main paths must match their expected identities.
No model, automatic translation, upgrades, health autofix or backup deletion.

Autoselected provider subs may still be mistranslated. Mechanical/source matching
does not certify semantic quality. This is a working first-tier automation
configuration, not the final editorial QA engine.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:5765"
EXPECTED = {
    1: "/media/american-dad-main",
    2: "/media/american-dad-2tb",
    3: "/media/bigdisk-video/Movies",
    4: "/media/bigdisk-video/Television",
    5: "/media/expansion-video/Movies",
    6: "/media/expansion-video/Television",
}
ROOT_KEYS = ("wanted_scan_interval_hours","wanted_search_interval_hours",
             "wanted_search_max_items_per_run","standalone_scan_interval_hours")
# Do not enable generalized auto-subtitle upgrades, ASR/Whisper transcription,
# local/remote translation, sidecar cleanup or removals.
CONFIG = {
    "source_language": "en",
    "target_language": "ja",
    "wanted_anime_only": False,
    "wanted_anime_movies_only": False,
    "wanted_auto_translate": False,
    "translation_enabled": False,
    "webhook_auto_translate": False,
    "jellyfin_play_translate_enabled": False,
    "subtitle_automation_enabled": False,
    "wanted_auto_extract": False,
    "upgrade_enabled": False,
    "upgrade_scan_interval_hours": 0,
    "subtitle_health_enabled": True,
    "subtitle_health_sweep_enabled": True,
    "subtitle_health_auto_fix": False,
    "auto_process_common_fixes": False,
    "auto_process_hi_removal": False,
    "auto_process_credit_removal": False,
    "auto_sync_after_download": True,
    "auto_sync_engine": "ffsubsync",
    "sync_sanity_threshold_ms": 30000,
    "wanted_skip_srt_on_no_ass": False,
    "provider_budget_enabled": True,
    "wanted_scan_interval_hours": 24,
    "wanted_scan_on_startup": False,
    "standalone_scan_interval_hours": 24,
    "wanted_search_interval_hours": 24,
    "wanted_search_on_startup": False,
    # Limited rollout at 40 per search cycle; raise only after observing yield.
    "wanted_search_max_items_per_run": 40,
    "max_concurrent_provider_searches": 1,
    "wanted_search_sidecar_budget_s": 0,
    "score_threshold_per_language": '{"ja":80}',
}

def request(path, headers, payload=None, method=None, timeout=25):
    if method is None: method = "GET" if payload is None else "PUT"
    b = None if payload is None else json.dumps(payload).encode("utf-8")
    h = dict(headers)
    if b is not None: h["Content-Type"] = "application/json"
    r = urllib.request.Request(BASE+path, headers=h, data=b, method=method)
    with urllib.request.urlopen(r,timeout=timeout) as response:
        return json.load(response)

def folder_plan(folders, isdir=os.path.isdir):
    if not isinstance(folders,list):
        raise RuntimeError("Unexpected standalone folders schema")
    by_id = {r.get("id"):r for r in folders if isinstance(r,dict)}
    if set(by_id) != set(EXPECTED) or len(folders) != len(EXPECTED):
        raise RuntimeError("Unexpected folder inventory; refusing blind enablement")
    changed=[]
    for ident,path in EXPECTED.items():
        r=by_id[ident]
        if r.get("path")!=path or r.get("outside_media_path"):
            raise RuntimeError(f"Folder {ident} path changed; abort")
        if not isdir(path) or not os.access(path,os.R_OK):
            raise RuntimeError(f"Folder {ident} not readable; abort")
        if not bool(r.get("enabled")):
            changed.append(ident)
    return changed

def safe_config(current):
    if not isinstance(current,dict):
        raise RuntimeError("Unexpected config schema")
    for k in CONFIG:
        if k not in current:
            raise RuntimeError("Missing known config key: "+k)
    return {k:v for k,v in CONFIG.items() if str(current[k])!=str(v)}

def exact_movie_files(roots, title):
    # Read-only file-name search, never parse media, never output plot/dialogue.
    phrase=re.sub(r"[^a-z0-9]+","",title.casefold())
    if not phrase or len(phrase)<12:
        raise RuntimeError("Ambiguous target title")
    found=[]
    skip=(".part",".tmp",".download")
    for root in roots:
        if not os.path.isdir(root):
            continue
        for directory,subdirs,files in os.walk(root,followlinks=False):
            subdirs[:]=[x for x in subdirs if not os.path.islink(os.path.join(directory,x))]
            for filename in files:
                if not filename.lower().endswith((".mkv",".mp4",".m4v",".avi",".mov")):
                    continue
                if filename.lower().endswith(skip):
                    continue
                path=os.path.join(directory,filename)
                directory_name=os.path.basename(directory)
                if phrase in re.sub(r"[^a-z0-9]+","",(filename+" "+directory_name).casefold()) \
                        and not os.path.islink(path):
                    found.append(path)
    return found[:5]

def audit(requester, health, folders, current):
    providers=health.get("providers",[]) if isinstance(health,dict) else []
    os_provider=next((x for x in providers if x.get("name")=="opensubtitles"),{})
    if os_provider.get("gate")!="ok" or not os_provider.get("initialized") \
            or os_provider.get("healthy") is not True:
        raise RuntimeError("OpenSubtitles native provider not healthy; no changes")
    sync=requester("/api/v1/sync/engines")
    engines=sync.get("engines",[]) if isinstance(sync,dict) else []
    ff=next((x for x in engines if x.get("name")=="ffsubsync"),{})
    if not ff.get("available"):
        raise RuntimeError("ffsubsync not available; no changes")
    selected=folder_plan(folders)
    config_changes=safe_config(current)
    return selected,config_changes

def run(apply=False, target="You Were Never Really Here", make_scan=True,
        requester=None):
    if requester is None:
        from config import get_settings
        key=get_settings().api_key
        headers={"X-Api-Key":key} if key else {}
        requester=lambda path,payload=None,method=None: request(
            path,headers,payload=payload,method=method)
    health=requester("/api/v1/providers/health")
    folders=requester("/api/v1/standalone/folders")
    current=requester("/api/v1/config")
    selected,changes=audit(requester,health,folders,current)
    print("SOURCES: native OpenSubtitles healthy; ffsubsync available")
    print("FOLDERS_TO_ENABLE",selected)
    print("CONFIG_CHANGES", sorted(changes))
    print("SAFE_GATES: no AI translations, no upgrades, no auto-delete/health fixes")
    # Target is sought by filename, not library metadata/plot. No content printed.
    paths=exact_movie_files([EXPECTED[k] for k in (3,4,5,6)],target)
    print("TARGET_MOVIE_FOUND",len(paths))
    for p in paths:
        print("TARGET_VIDEO_FILE",os.path.basename(p))
        print("TARGET_MEDIA_ROOT",next((k for k,v in EXPECTED.items() if p.startswith(v+"/")),"unknown"))
    if not apply:
        print("PLAN_ONLY: no settings, folders, scans, media or jobs changed")
        return dict(folders=selected,config=changes,paths=paths)
    # Change config first: ensures translation/upgrade are OFF before scanning.
    # Sublarr 1.18 uses HTTP PUT, persists only passed keys and reloads.
    if changes:
        reply=requester("/api/v1/config",changes,method="PUT")
        if not isinstance(reply,dict) or reply.get("status") not in ("success","ok","updated"):
            raise RuntimeError("Config update ambiguous; inspect live state")
        print("CONFIG_UPDATED", sorted(changes))
    for ident in selected:
        response=requester(f"/api/v1/standalone/folders/{ident}",
                           {"enabled":True}, method="PUT")
        if not isinstance(response,dict) or not response.get("enabled"):
            raise RuntimeError("Folder enable failed; stopped at folder "+str(ident))
        print("FOLDER_ENABLED",ident)
    # Verify changed settings and folders before starting any new job.
    actual=requester("/api/v1/config")
    for key,val in CONFIG.items():
        if str(actual.get(key))!=str(val):
            raise RuntimeError("Saved config mismatch "+key+"; no scan started")
    remaining=folder_plan(requester("/api/v1/standalone/folders"))
    if remaining:
        raise RuntimeError("Some folders still disabled; no scan started")
    print("ACTIVATED: Japanese-first, 40 Wanted searches/day maximum per cycle; "
          "ffsubsync enabled on downloads")
    if make_scan:
        response=requester("/api/v1/standalone/scan",{},method="POST")
        print("INITIAL_SCAN_REQUESTED", isinstance(response,dict) and
              response.get("message","").startswith("Scan"))
    print("COMPLETE: existing subtitles protected by upgrades disabled; "
          "no AI translation enabled")
    return dict(folders=selected,config=changes,paths=paths)

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--apply",action="store_true")
    p.add_argument("--target",default="You Were Never Really Here")
    p.add_argument("--no-scan",action="store_true")
    args=p.parse_args()
    try:
        run(apply=args.apply,target=args.target,make_scan=not args.no_scan)
    except (RuntimeError,OSError,urllib.error.HTTPError,ValueError) as exc:
        print("ACTIVATION_HELD",type(exc).__name__,str(exc)[:180],
              file=sys.stderr)
        sys.exit(1)
