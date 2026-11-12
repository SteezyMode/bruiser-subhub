#!/usr/bin/env python3
"""Read-only folder browser over the saved Jellyfin movie/episode inventory.

These are actual indexed *media folders*, not fabricated Jellyfin collection
identifiers. Browser does not scan media files or contact subtitle providers.
The existing completion controller independently checks every selected ID.
"""
from __future__ import annotations

from collections import Counter
import json
from pathlib import Path, PurePosixPath
import re
import time

try:
    from . import subhub_library_coverage as coverage
except ImportError:
    import subhub_library_coverage as coverage

KINDS=("Movie","Episode")
MAX_ITEMS=50_000
PAGE_SIZE=80
ID=re.compile(r"[0-9a-f]{32}\Z")
_CACHE={"until":0.0,"signature":None,"items":None,"generated":""}


def root_for(path,kind):
    """Prefer existing media-folder labels, keeping multiple drives separate."""
    parts=PurePosixPath(path).parts
    matches=(("movies","films","film") if kind=="Movie"
             else ("episodic","television","tv","shows"))
    hits=[i for i,p in enumerate(parts[:-1]) if p.casefold() in matches]
    if hits:
        index=max(hits) if kind=="Episode" else min(hits)
        return str(PurePosixPath(*parts[:index+1]))
    # Not all mount names are standard. A grounded parent path is still
    # navigable; never invent a Jellyfin library name.
    return str(PurePosixPath(*parts[:min(4,len(parts)-1)]))


def within(path,folder):
    """Path-boundary aware containment, never string startswith."""
    try:
        return PurePosixPath(path).is_relative_to(PurePosixPath(folder))
    except (ValueError,TypeError):
        return False


def snapshot():
    path=coverage.latest_manifest()
    if not path:
        raise RuntimeError("jellyfin_inventory_not_found")
    stat=path.stat()
    signature=(str(path),stat.st_mtime_ns,stat.st_size)
    now=time.monotonic()
    if (_CACHE["items"] is not None and
            _CACHE["signature"]==signature and now<_CACHE["until"]):
        return _CACHE["items"],_CACHE["generated"]
    doc=json.loads(path.read_text("utf-8"))
    if (not isinstance(doc,dict) or doc.get("schema")!=1
            or not isinstance(doc.get("items"),list)
            or len(doc["items"])>MAX_ITEMS):
        raise RuntimeError("invalid_jellyfin_browse_inventory")
    files={}
    listing={}
    for r in doc["items"]:
        if not isinstance(r,dict) or r.get("kind") not in KINDS:
            continue
        jid=str(r.get("jellyfin_id") or "")
        path=r.get("host_path")
        if (not ID.fullmatch(jid) or not isinstance(path,str)
                or not path.startswith("/") or ".." in PurePosixPath(path).parts):
            continue
        parent=str(PurePosixPath(path).parent)
        status=str(r.get("status") or "")
        has_ja=(status in ("existing_japanese_subtitle","japanese_audio")
                or coverage._sidecar(path,listing))
        state=("covered" if has_ja else
               "needs_japanese" if status in coverage.KNOWN_MISSING
               else "unverified")
        files[jid]={
            "jellyfin_id":jid,"kind":r["kind"],
            "title":str(r.get("title") or "")[:180],
            "year":r.get("year") if type(r.get("year")) is int else None,
            "series":str(r.get("series_title") or "")[:160],
            "season":r.get("season") if type(r.get("season")) is int else None,
            "episode":r.get("episode") if type(r.get("episode")) is int else None,
            "folder":parent,"root":root_for(path,r["kind"]),
            "state":state,"source_status":status}
    rows=list(files.values())
    _CACHE.update(signature=signature,until=now+90,
                  items=rows,generated=str(doc.get("generated_utc") or ""))
    return rows,_CACHE["generated"]


def browse(*, kind="Movie", folder="", query="", page=0, state="all"):
    if kind not in KINDS or state not in ("all","needs_japanese","covered","unverified"):
        raise ValueError("invalid_browse_filters")
    if not isinstance(query,str) or len(query)>100 or any(ord(c)<32 for c in query):
        raise ValueError("invalid_browse_query")
    if type(page) is not int or page<0 or page>1000:
        raise ValueError("invalid_browse_page")
    rows,generated=snapshot()
    items=[r for r in rows if r["kind"]==kind]
    roots={r["root"] for r in items}
    if folder:
        if (folder not in roots and not any(
                within(r["folder"],folder) and within(folder,r["root"])
                for r in items)):
            raise ValueError("folder_not_in_jellyfin_inventory")
        items=[r for r in items if within(r["folder"],folder)]
    grouped=Counter(r["state"] for r in items)
    selection=[r for r in items if state=="all" or r["state"]==state]
    child={}
    if not query.strip():
        for r in selection:
            if not folder:
                child_path=r["root"]
            else:
                if r["folder"]==folder:
                    continue
                # One direct child directory below the current folder.
                rel=PurePosixPath(r["folder"]).relative_to(PurePosixPath(folder))
                child_path=str(PurePosixPath(folder)/rel.parts[0])
            if child_path not in child:
                child[child_path]={"path":child_path,
                    "label":PurePosixPath(child_path).name,
                    "total":0,"covered":0,"needs_japanese":0,"unverified":0}
            child[child_path]["total"]+=1
            child[child_path][r["state"]]+=1
        direct=[r for r in selection if folder and r["folder"]==folder]
    else:
        term=query.strip().casefold()
        direct=[r for r in selection if term in (
            r["title"]+" "+r["series"]+" "+
            PurePosixPath(r["folder"]).name).casefold()]
    direct.sort(key=lambda r:(
        (r["series"] or r["title"]).casefold(),r["season"] or 0,
        r["episode"] or 0,r["title"].casefold(),r["jellyfin_id"]))
    total=len(direct)
    return {
        "kind":kind,"folder":folder,"query":query,"state":state,
        "source":"saved_jellyfin_inventory_and_exact_media_paths",
        "generated_utc":generated,"scope_total":len(items),
        "scope_counts":dict(grouped),
        "folders":sorted(child.values(),key=lambda r:r["label"].casefold()),
        "items":direct[page*PAGE_SIZE:(page+1)*PAGE_SIZE],
        "page":page,"page_size":PAGE_SIZE,"matching_items":total,
        "more":(page+1)*PAGE_SIZE<total}
