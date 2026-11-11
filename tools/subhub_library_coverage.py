#!/usr/bin/env python3
"""Read-only, library-wide JA coverage pulse from saved Jellyfin inventory.

An inventory snapshot is not a live Jellyfin scan. On each cached refresh,
also detect new external JA subtitle sidecars for the SAME media files so
successful source publication becomes visible without re-searching providers.
No ffprobe per title, network/API calls, subtitle writes, or model work.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import time

STATE = Path.home() / "bruiser-pilot/ja-first-inventory"
SUB_EXT = {".srt",".ass",".ssa",".vtt"}
TOKENS = re.compile(r"[^a-z0-9]+")
JA = {"ja","jp","jpn","japanese"}
UNSAFE = {"forced","signs"}
VIDEO_TYPES = {"Movie","Episode"}
# These statuses have reached the no-Japanese stage of the catalog's
# existing-track check. Other errors cannot establish absence reliably.
KNOWN_MISSING = {
    "ready_ja_search","review_no_movie_imdb",
    "review_missing_series_identity","review_missing_episode_number",
    "review_audio_language_unverified","japanese_audio",
}
_CACHE = {"expires":0.0,"signature":None,"result":None}


def latest_manifest(state=STATE):
    state=Path(state)
    if state.is_symlink() or not state.is_dir():
        return None
    files=sorted(state.glob("ja-intake-*.json"))
    for path in reversed(files):
        if (not path.is_symlink() and path.is_file()
                and path.stat().st_uid==os.getuid()
                and not path.stat().st_mode & 0o077
                and path.stat().st_size<=90_000_000):
            return path
    return None


def _sidecar(video, listing):
    if not isinstance(video,str) or not video.startswith("/"):
        return False
    path=Path(video)
    if path.is_symlink() or not path.is_file():
        return False
    folder=path.parent
    if folder not in listing:
        try:
            listing[folder]=tuple(
                p.name for p in folder.iterdir()
                if p.is_file() and not p.is_symlink())
        except OSError:
            listing[folder]=()
    prefix=path.stem.casefold()+"."
    for name in listing[folder]:
        suffix=Path(name).suffix.casefold()
        if suffix not in SUB_EXT or not name.casefold().startswith(prefix):
            continue
        tail=name[len(prefix):-len(suffix)]
        tags=set(t for t in TOKENS.split(tail.casefold()) if t)
        if (tags & JA) and not(tags & UNSAFE):
            return True
    return False


def summarize(items, *, generated_utc="", now=None):
    if not isinstance(items,list) or len(items)>50_000:
        raise ValueError("invalid_inventory_items")
    kinds={k:Counter() for k in VIDEO_TYPES}
    recent=0
    listing={}
    for item in items:
        if not isinstance(item,dict) or item.get("kind") not in VIDEO_TYPES:
            continue
        kind=item["kind"]
        status=str(item.get("status") or "")
        if status=="existing_japanese_subtitle":
            category="present"
        elif _sidecar(item.get("host_path"),listing):
            category="present"
            recent+=1
        elif status in KNOWN_MISSING:
            category="missing"
        else:
            category="unverified"
        kinds[kind][category]+=1
        if category=="missing" and status=="japanese_audio":
            kinds[kind]["japanese_audio_only"]+=1
    result={"available":True,
            "generated_utc":str(generated_utc),
            "checked_utc":datetime.fromtimestamp(
                time.time() if now is None else now,timezone.utc).isoformat(),
            "subtitle_sidecars_found_since_snapshot":recent,
            "note":"Jellyfin inventory snapshot plus newer exact-file Japanese sidecars; "
                   "embedded tracks and removed sidecars require an inventory refresh.",
            "by_kind":{k:{"total":sum(kinds[k][x] for x in
                              ("present","missing","unverified")),
                          "present":kinds[k]["present"],
                          "missing":kinds[k]["missing"],
                          "unverified":kinds[k]["unverified"],
                          "japanese_audio_only":kinds[k]["japanese_audio_only"]}
                       for k in ("Movie","Episode")}}
    result["total"]=sum(v["total"] for v in result["by_kind"].values())
    for key in ("present","missing","unverified","japanese_audio_only"):
        result[key]=sum(v[key] for v in result["by_kind"].values())
    return result


def pulse(state=STATE, *, now=None, ttl=60):
    now_m=time.monotonic()
    path=latest_manifest(state)
    if path is None:
        return {"available":False,"reason":"no_private_jellyfin_inventory"}
    stat=path.stat()
    signature=(str(path),stat.st_size,stat.st_mtime_ns)
    if (_CACHE["result"] is not None and
            _CACHE["signature"]==signature and now_m<_CACHE["expires"]):
        return _CACHE["result"]
    doc=json.loads(path.read_text("utf-8"))
    if not isinstance(doc,dict) or doc.get("schema")!=1:
        raise ValueError("unsupported_inventory_schema")
    result=summarize(doc.get("items"),generated_utc=doc.get("generated_utc",""),
                     now=now)
    _CACHE.update(signature=signature,result=result,expires=now_m+ttl)
    return result
