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
    from . import subhub_media_categories as media_categories
except ImportError:
    import subhub_library_coverage as coverage
    import subhub_media_categories as media_categories

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


def movie_category(row):
    """First real folder under each Jellyfin movie root, on either drive.

    A virtual collection; original media paths and their sidecars never move.
    """
    try:
        parts=PurePosixPath(row["folder"]).relative_to(
            PurePosixPath(row["root"])).parts
    except (KeyError,TypeError,ValueError):
        return "Unsorted"
    return parts[0] if parts else "Unsorted"


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
        # A newly published JA sidecar takes precedence over stale inventory.
        has_ja=(status=="existing_japanese_subtitle"
                or coverage._sidecar(path,listing))
        state=("covered" if has_ja else
               "audio_only" if status=="japanese_audio" else
               "needs_japanese" if status=="ready_ja_search"
               else "unverified")
        files[jid]={
            "jellyfin_id":jid,"kind":r["kind"],
            "title":str(r.get("title") or "")[:180],
            "year":r.get("year") if type(r.get("year")) is int else None,
            "series":str(r.get("series_title") or "")[:160],
            "season":r.get("season") if type(r.get("season")) is int else None,
            "episode":r.get("episode") if type(r.get("episode")) is int else None,
            "folder":parent,"root":root_for(path,r["kind"]),
            "genres":[g for g in (r.get("genres") or [])
                      if isinstance(g,str) and 1<=len(g)<=60][:20],
            "state":state,"source_status":status}
    rows=list(files.values())
    _CACHE.update(signature=signature,until=now+90,
                  items=rows,generated=str(doc.get("generated_utc") or ""))
    return rows,_CACHE["generated"]


def row_categories(row):
    return media_categories.categories(
        row["kind"],row["folder"]+"/movie-or-episode.mkv",row["genres"])


def browse(*, kind="Movie", folder="", query="", page=0, state="all",
           genre="", category="", series=""):
    if kind not in KINDS or state not in (
            "all","needs_japanese","covered","audio_only","unverified"):
        raise ValueError("invalid_browse_filters")
    if not isinstance(query,str) or len(query)>100 or any(ord(c)<32 for c in query):
        raise ValueError("invalid_browse_query")
    if type(page) is not int or page<0 or page>1000:
        raise ValueError("invalid_browse_page")
    if (category and (folder or not isinstance(category,str)
                      or len(category)>120 or any(ord(c)<32 for c in category))):
        raise ValueError("invalid_combined_media_category")
    if (series and (kind!="Episode" or not category or folder
                    or not isinstance(series,str) or len(series)>160
                    or any(ord(c)<32 for c in series))):
        raise ValueError("invalid_browse_series")
    rows,generated=snapshot()
    items=[r for r in rows if r["kind"]==kind]
    available_genres=sorted({g for r in items for g in r["genres"]},
                            key=str.casefold)
    if genre:
        matched=next((g for g in available_genres
                      if g.casefold()==genre.casefold()),None)
        if matched is None:
            raise ValueError("genre_not_in_saved_jellyfin_inventory")
        items=[r for r in items if matched in r["genres"]]
    roots={r["root"] for r in items}
    if category:
        available_categories={label.casefold():label for row in items
                              for label in row_categories(row)}
        match=available_categories.get(category.casefold())
        if match is None:
            raise ValueError("media_category_not_in_jellyfin_inventory")
        items=[row for row in items if
               category.casefold() in {x.casefold() for x in row_categories(row)}]
        category=match
    if series:
        if series not in {r["series"] for r in items}:
            raise ValueError("series_not_in_selected_jellyfin_category")
        items=[r for r in items if r["series"]==series]
    if folder:
        if (folder not in roots and not any(
                within(r["folder"],folder) and within(folder,r["root"])
                for r in items)):
            raise ValueError("folder_not_in_jellyfin_inventory")
        items=[r for r in items if within(r["folder"],folder)]
    grouped=Counter(r["state"] for r in items)
    selection=[r for r in items if state=="all" or r["state"]==state]
    child={}
    def add_child(label, *, path="", category_name="", series_name=""):
        key=(series_name or label).casefold() if not path else path
        if key not in child:
            child[key]={"path":path,"category":category_name,
                        "series":series_name,"label":label,
                        "total":0,"covered":0,"needs_japanese":0,
                        "audio_only":0,"unverified":0}
        return child[key]
    if not query.strip() and not (genre and not folder) and not series:
        if not folder and not category:
            # The same Action/Documentary heading is shown ONCE, irrespective
            # of the number of Jellyfin roots or media mounts behind it.
            for row in selection:
                for label in row_categories(row):
                    group=add_child(label,category_name=label)
                    group["total"]+=1
                    group[row["state"]]+=1
            direct=[]
        elif category and kind=="Episode":
            # TV collections show series, not a wall of individual episodes.
            for row in selection:
                label=row["series"] or "Unknown series"
                group=add_child(label,category_name=category,series_name=label)
                group["total"]+=1
                group[row["state"]]+=1
            direct=[]
        else:
            if kind=="Episode" and folder:
                for row in selection:
                    if row["folder"]==folder:
                        continue
                    rel=PurePosixPath(row["folder"]).relative_to(
                        PurePosixPath(folder))
                    path=str(PurePosixPath(folder)/rel.parts[0])
                    group=add_child(PurePosixPath(path).name,path=path)
                    group["total"]+=1
                    group[row["state"]]+=1
            direct=[r for r in selection if (
                category and kind=="Movie" or
                folder and (within(r["folder"],folder) if kind=="Movie"
                            else r["folder"]==folder))]
    else:
        term=query.strip().casefold()
        direct=[r for r in selection if (not term or term in (
            r["title"]+" "+r["series"]+" "+
            PurePosixPath(r["folder"]).name).casefold())]
    direct.sort(key=lambda r:(
        (r["series"] or r["title"]).casefold(),r["season"] or 0,
        r["episode"] or 0,r["title"].casefold(),r["jellyfin_id"]))
    total=len(direct)
    return {
        "kind":kind,"folder":folder,"category":category,"series":series,
        "query":query,"state":state,
        "genre":genre,"genres":available_genres,
        "source":"saved_jellyfin_inventory_and_exact_media_paths",
        "generated_utc":generated,"scope_total":len(items),
        "scope_counts":{label:int(grouped[label]) for label in
                        ("covered","needs_japanese","audio_only","unverified")},
        "folders":sorted(child.values(),key=lambda r:r["label"].casefold()),
        "items":direct[page*PAGE_SIZE:(page+1)*PAGE_SIZE],
        "page":page,"page_size":PAGE_SIZE,"matching_items":total,
        "more":(page+1)*PAGE_SIZE<total}
