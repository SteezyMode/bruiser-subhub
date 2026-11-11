#!/usr/bin/env python3
"""One-item proof of Jellyfin remote Japanese subtitle bytes; NO media writes.

Preview by default, using the existing private Jellyfin intake manifest.
--execute asks Jellyfin for remote candidates (provider search allowance may
be consumed). With --fetch-one --provider NAME, fetches at most ONE matching
subtitle via Jellyfin's read-only GET /Providers/Subtitles/Subtitles/{id}
into bounded memory, reporting format/cue count/Japanese character evidence.
The byte-fetch may use a provider DOWNLOAD allowance. No subtitle contents
or remote IDs are printed, no files/DB changes and NO POST to Jellyfin.

Explicitly does not save to the media library or replace the established
SubHub private staging/ALASS/publisher workflow.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import HTTPRedirectHandler, Request, build_opener

try:
    from . import benchmark_subtitle_search_paths as benchmark
    from . import ja_first_catalog_manifest as catalog
    from . import ja_first_search_pilot as search
except ImportError:
    import sys
    sys.path.insert(0, str(Path.home() / "bruiser-pilot/subhub-control"))
    import benchmark_subtitle_search_paths as benchmark
    import ja_first_catalog_manifest as catalog
    import ja_first_search_pilot as search

MAX_SUB_BYTES=2_000_000
TIME_LINE=re.compile(r"(?m)^\s*(?:\d+\s*\n)?\s*\d{1,2}:\d{2}:\d{2}[,.]\d+\s*-->\s*\d{1,2}:\d{2}:\d{2}[,.]\d+")
VTT_LINE=re.compile(r"(?m)^\s*(?:(?:\d{1,2}:)?\d{2}:\d{2}\.\d+\s*-->\s*(?:\d{1,2}:)?\d{2}:\d{2}\.\d+)")
ASS_LINE=re.compile(r"(?m)^Dialogue:")
JP_CHAR=re.compile(r"[\u3040-\u30ff\u3400-\u9fff]")


class NoRedirect(HTTPRedirectHandler):
    """Never forward the Jellyfin authentication header to a redirected URL."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError("jellyfin_redirect_not_allowed")


def local_url(path):
    base=catalog.BASE
    if base not in ("http://127.0.0.1:8096", "http://localhost:8096"):
        raise RuntimeError("jellyfin_base_must_be_local_loopback")
    return base+path


def relevant(row, result):
    """Conservative title/episode matching FOR AN IN-MEMORY PROBE ONLY.

    This is not a stageable/publishable identity verdict. Movie premiere-year
    mismatches remain REVIEW and wrong-episode/wrong-title results are excluded.
    """
    name=str(result.get("Name") or "")
    if str(result.get("ThreeLetterISOLanguageName") or "").casefold() not in ("ja","jpn"):
        return False
    if row.get("kind")=="Episode":
        season,episode=row.get("season"),row.get("episode")
        if not isinstance(season,int) or not isinstance(episode,int):
            return False
        tags=search.episode_tags(name)
        if not tags or any(x!=(season,episode) for x in tags):
            return False
        def title_words(s):
            return re.findall(r"[a-z0-9]+",str(s or "").casefold()
                              .replace("'","").replace("\u2019",""))
        whole=title_words(name)
        target=title_words(row.get("series_title"))
        return bool(target) and any(
            whole[i:i+len(target)]==target
            for i in range(len(whole)-len(target)+1))
    if row.get("kind")=="Movie":
        # Preview/fetch restricted to exact film title and year: automatically
        # fetching a 2023/2024 disputed film is not our first safety test.
        return search.candidate_grade(row,{
            "filename":name,"language":"ja","matches":[]})=="plausible"
    return False


def request_candidates(row,auth,opener):
    jid=str(row["jellyfin_id"])
    if not benchmark.ITEM_ID.fullmatch(jid):
        raise ValueError("invalid_manifest_Jellyfin_ID")
    url=local_url("/Items/"+jid+"/RemoteSearch/Subtitles/ja")
    with opener.open(Request(url,headers={"Authorization":auth}),timeout=100) as res:
        payload=res.read(1_000_001)
        if len(payload)>1_000_000:
            raise ValueError("remote_search_response_too_large")
    data=json.loads(payload)
    if not isinstance(data,list) or len(data)>5000:
        raise RuntimeError("invalid_remote_results")
    return [x for x in data if isinstance(x,dict)]


def get_remote_bytes(candidate,auth,opener):
    ident=candidate.get("Id")
    if not isinstance(ident,str) or not (2<=len(ident)<=512):
        raise ValueError("no_valid_remote_subtitle_id")
    endpoint=local_url("/Providers/Subtitles/Subtitles/"+quote(ident,safe=""))
    with opener.open(Request(endpoint,headers={"Authorization":auth}),timeout=100) as res:
        ct=(res.headers.get("Content-Type") or "").split(";",1)[0].lower()
        if not (ct.startswith("text/") or ct in (
                "application/octet-stream","application/x-subrip",
                "application/x-ass","application/ass","application/subrip","")):
            raise RuntimeError("unexpected_remote_subtitle_content_type")
        data=res.read(MAX_SUB_BYTES+1)
    if not 0<len(data)<=MAX_SUB_BYTES:
        raise RuntimeError("remote_subtitle_empty_or_oversize")
    return data,ct


def characterize(data,ct):
    if data.startswith(b"\xef\xbb\xbf"):
        decoded=data.decode("utf-8-sig")
    elif data.startswith(b"\xff\xfe") or data.startswith(b"\xfe\xff"):
        decoded=data.decode("utf-16")
    else:
        try:
            decoded=data.decode("utf-8")
        except UnicodeError:
            return {"bytes":len(data),"content_type":ct,"sha256_prefix":
                    hashlib.sha256(data).hexdigest()[:16],
                    "text_decoded":False,"timed_cues":0,"japanese_characters":0}
    srt=len(TIME_LINE.findall(decoded))
    vtt=len(VTT_LINE.findall(decoded))
    ass=len(ASS_LINE.findall(decoded))
    return {"bytes":len(data),"content_type":ct,"sha256_prefix":
            hashlib.sha256(data).hexdigest()[:16],
            "text_decoded":True,"timed_cues":max(srt,vtt,ass),
            "japanese_characters":len(JP_CHAR.findall(decoded)),
            "looks_like_timed_japanese":max(srt,vtt,ass)>0 and
            len(JP_CHAR.findall(decoded))>=10}


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    group=ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--movie",metavar="TITLE")
    group.add_argument("--episode",metavar="SERIES SxxExxx")
    ap.add_argument("--provider",default="subbuzz",
                    help="exact Jellyfin provider label, default subbuzz")
    ap.add_argument("--execute",action="store_true",
                    help="ONE Jellyfin remote search; upstream quota may be used")
    ap.add_argument("--fetch-one",action="store_true",
                    help="with --execute, ONE read-only remote subtitle GET; download quota may be used")
    args=ap.parse_args()
    if args.fetch_one and not args.execute:
        ap.error("--fetch-one requires --execute")
    rows=benchmark.select(benchmark.load_latest_manifest(),
                          [args.movie] if args.movie else [],
                          [args.episode] if args.episode else [],limit=1)
    row=rows[0]
    title=(row["title"] if row["kind"]=="Movie" else
           row["series_title"]+f' S{row["season"]:02d}E{row["episode"]:02d}')
    print("ITEM:",title,"| SAVED SUBHUB:",json.dumps(benchmark.saved(row),
          ensure_ascii=False),flush=True)
    if not args.execute:
        print("PREVIEW ONLY. --execute: ONE remote-provider search; "+
              "--fetch-one: at most ONE in-memory provider download.")
        return

    op=build_opener(NoRedirect())
    auth=catalog.load_auth()
    try:
        candidates=request_candidates(row,auth,op)
    except (HTTPError,URLError,OSError,RuntimeError,ValueError) as exc:
        print("REMOTE SEARCH HELD:",type(exc).__name__,flush=True)
        return
    print("JELLYFIN_REMOTE_RESULTS:",len(candidates),flush=True)
    selected=[]
    for x in candidates:
        name=str(x.get("Name") or "")
        match=relevant(row,x)
        is_provider=str(x.get("ProviderName") or "").casefold()==args.provider.casefold()
        print(" CANDIDATE",json.dumps({
            "provider":str(x.get("ProviderName") or "")[:65],
            "filename":name[:130],"language":x.get("ThreeLetterISOLanguageName"),
            "exact_item_name":match,"selected_provider":is_provider,
            "format":str(x.get("Format") or "")[:12]
        },ensure_ascii=False),flush=True)
        if match and is_provider:
            selected.append(x)

    if not args.fetch_one:
        print("SEARCH ONLY. NO subtitle bytes fetched or media modified.")
        return
    if not selected:
        print("FETCH HELD: no matching candidate from selected provider.")
        return
    # One and ONLY one GET, and no POST whatsoever. The candidate is not
    # published/staged; this is a safe proof that bytes are obtainable.
    try:
        data,ct=get_remote_bytes(selected[0],auth,op)
        print("REMOTE_BYTES_PROBE:",json.dumps(characterize(data,ct)),
              flush=True)
    except (HTTPError,URLError,OSError,RuntimeError,ValueError) as exc:
        print("REMOTE_BYTES_HELD:",type(exc).__name__,flush=True)
        return
    print("IN-MEMORY ONLY: no subtitle contents printed, no files or DB altered. "+
          "No ALASS or publication attempted.")


if __name__=="__main__":
    main()
