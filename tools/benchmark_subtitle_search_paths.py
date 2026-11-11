#!/usr/bin/env python3
"""Bounded comparison of Jellyfin's EXISTING remote-subtitle search with saved SubHub history.

Default is an offline preview; --execute performs up to three authenticated
Jellyfin GET remote subtitle SEARCHES. Those MAY consume the provider's search
allowance. No downloads, source changes, subtitle writes, new credentials, or
filesystem mutations. Supports any movies and any named TV episode in the
existing Jellyfin-authoritative intake manifest. This is a benchmark, NOT a
second sourcing pipeline.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import json
import re
import sqlite3
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

try:
    from . import ja_first_catalog_manifest as catalog
    from . import ja_first_search_pilot as search
except ImportError:
    # A pinned benchmark script can be executed from a temporary file on the
    # OptiPlex; import only the EXISTING installed SubHub source directory.
    import sys
    sys.path.insert(0, str(Path.home() / "bruiser-pilot/subhub-control"))
    import ja_first_catalog_manifest as catalog
    import ja_first_search_pilot as search

EPISODE = re.compile(r"^(.+)\s+S(\d{1,2})E(\d{1,3})$",re.I)
ITEM_ID = re.compile(r"^[a-f0-9]{32}$",re.I)


def load_latest_manifest(folder=None):
    folder = Path(folder or search.ROOT)
    if not folder.is_dir() or folder.is_symlink() or folder.stat().st_mode & 0o077:
        raise RuntimeError("unsafe_private_manifest_directory")
    choices=sorted(folder.glob("ja-intake-*.json"))
    if not choices:
        raise RuntimeError("no_private_Jellyfin_intake_manifest")
    path=choices[-1]
    if (not path.is_file() or path.is_symlink()
            or path.stat().st_mode & 0o077):
        raise RuntimeError("unsafe_private_Jellyfin_intake_manifest")
    data=json.loads(path.read_text(encoding="utf-8"))
    rows=data.get("items")
    if not isinstance(rows,list):
        raise RuntimeError("invalid_Jellyfin_manifest")
    return rows


def select(rows, movies, episodes, limit=3):
    if not 1<=limit<=3:
        raise ValueError("compare_at_most_three_titles")
    selectors=[("Movie",str(name).strip()) for name in movies]
    selectors += [("Episode",str(name).strip()) for name in episodes]
    if not selectors or len(selectors)>limit:
        raise ValueError("choose_between_one_and_three_explicit_items")
    result=[]
    seen=set()
    for kind,label in selectors:
        if kind=="Episode":
            parts=EPISODE.fullmatch(label)
            if not parts:
                raise ValueError("episode_requires_series_title_SxxExxx")
            series,season,episode=parts.group(1),int(parts.group(2)),int(parts.group(3))
            candidates=[row for row in rows if isinstance(row,dict)
                        and row.get("kind")=="Episode"
                        and str(row.get("series_title") or "").casefold()==series.casefold()
                        and row.get("season")==season and row.get("episode")==episode]
        else:
            candidates=[row for row in rows if isinstance(row,dict)
                        and row.get("kind")=="Movie"
                        and str(row.get("title") or "").casefold()==label.casefold()]
        if len(candidates)!=1:
            raise ValueError("media_identity_missing_or_ambiguous:"+label[:70])
        candidate=candidates[0]
        key=str(candidate.get("jellyfin_id") or "")
        if not ITEM_ID.fullmatch(key) or key in seen:
            raise ValueError("duplicate_or_invalid_Jellyfin_media_id")
        seen.add(key)
        result.append(candidate)
    return result


def saved(row, database=None):
    database=Path(database or search.DB)
    if not database.is_file() or database.is_symlink():
        return {"state":"no_saved_search"}
    with sqlite3.connect("file:"+str(database)+"?mode=ro",uri=True,timeout=10) as con:
        found=con.execute(
            "SELECT outcome,plausible_count,results_json FROM searches "
            "WHERE jellyfin_id=?",(row["jellyfin_id"],)).fetchone()
    if not found:
        return {"state":"never_searched"}
    outcome,plausible,raw=found
    try:
        data=json.loads(raw or "{}")
    except (ValueError,TypeError):
        data={}
    if not isinstance(data,dict):
        data={}
    return {
        "state":outcome,"plausible":plausible,
        "provider_reported_hits":data.get("provider_total"),
        "saved_candidates":len(data.get("candidates") or []),
        "rejected_saved":len(data.get("rejected_candidates") or []),
        "version":data.get("strategy_version"),
        "incomplete_providers":data.get("incomplete_providers") or []
    }


def jellyfin_search(row, authorization, language="ja", opener=urlopen):
    # Only the vetted local loopback endpoint. Never send credentials to a
    # provider URL, never persist the resulting remote IDs, never download.
    key=row["jellyfin_id"]
    if not ITEM_ID.fullmatch(str(key)) or language not in ("ja","jpn"):
        raise ValueError("unsafe_remote_search_parameters")
    endpoint=(catalog.BASE + "/Items/" + quote(key,safe="") +
              "/RemoteSearch/Subtitles/" + language)
    try:
        with opener(Request(endpoint,headers={"Authorization":authorization}),
                    timeout=100) as response:
            entries=json.load(response)
    except HTTPError as exc:
        return {"error":"HTTP_"+str(exc.code)}
    except (OSError,URLError,TimeoutError):
        return {"error":"remote_search_unavailable"}
    if not isinstance(entries,list):
        return {"error":"invalid_remote_subtitle_response"}
    examples=[]
    for entry in entries[:10]:
        if not isinstance(entry,dict):
            continue
        examples.append({
            "provider":str(entry.get("ProviderName") or "")[:65],
            "name":str(entry.get("Name") or "")[:130],
            "language":str(entry.get("ThreeLetterISOLanguageName") or "")[:16],
            "hash_match":entry.get("IsHashMatch") is True,
        })
    return {
        "remote_count":len(entries),
        "examples":examples,
        "note":"Search results only. No downloads; no media identity or timing verified."
    }


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--movie",action="append",default=[],metavar="TITLE")
    ap.add_argument("--episode",action="append",default=[],metavar="SERIES SxxExxx")
    ap.add_argument("--execute",action="store_true",help="perform 1-3 Jellyfin GET remote subtitle searches (provider credits possible)")
    ap.add_argument("--language",choices=("ja","jpn"),default="ja")
    args=ap.parse_args()
    rows=select(load_latest_manifest(),args.movie,args.episode)
    auth=catalog.load_auth() if args.execute else None
    for row in rows:
        name=(str(row.get("title")) if row["kind"]=="Movie" else
              str(row.get("series_title"))+f' S{row["season"]:02d}E{row["episode"]:02d}')
        status={"title":name,"kind":row["kind"],"year":row.get("year"),
                "saved_subhub":saved(row)}
        if auth is not None:
            status["jellyfin_remote"]=jellyfin_search(row,auth,args.language)
        else:
            status["jellyfin_remote"]="NOT SEARCHED: rerun --execute for bounded comparison"
        print(json.dumps(status,ensure_ascii=False))
    print("COMPARISON ONLY: no subtitles downloaded, no database or media changed.")
    if not args.execute:
        print("No provider searches performed. --execute makes "+
              str(len(rows))+" Jellyfin remote-search requests; underlying plugin "
              "provider calls and allowances can differ.")


if __name__=="__main__":
    main()
