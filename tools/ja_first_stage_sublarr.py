#!/usr/bin/env python3
"""Provider-agnostic Sublarr Japanese subtitle download to PRIVATE SubHub staging.

Default is READ ONLY. --apply is owner-selected, one exact Jellyfin title,
uses existing saved candidate identities, and NEVER writes media sidecars or
runs translation. All providers use Sublarr's own ProviderManager.download().
Strict publication remains a SEPARATE existing ALASS/ffsubsync step.

This initial integration is intentionally NOT auto-started by source cycles.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
from urllib.parse import quote

try:
    from . import ja_first_stage_saved_batch as stage
    from . import ja_first_stage_jellyfin as jelly
    from . import ja_first_publish_staged as publisher
    from . import ja_first_search_pilot as search
    from . import ja_first_srt_normalize as structure
    from . import ja_first_candidate_progress as progress
    from . import subhub_download_ledger as ledger
except ImportError:
    import ja_first_stage_saved_batch as stage
    import ja_first_stage_jellyfin as jelly
    import ja_first_publish_staged as publisher
    import ja_first_search_pilot as search
    import ja_first_srt_normalize as structure
    import ja_first_candidate_progress as progress
    import subhub_download_ledger as ledger

SOURCE="sublarr"
SCHEMA="sublarr-provider-manager-v1"
JID=re.compile(r"[a-f0-9]{32}\Z")
PROVIDER=re.compile(r"[a-z][a-z0-9_-]{1,63}\Z")
MAX_BYTES=2_000_000
OWN_HANDLERS=frozenset({"opensubtitles","subdl","embedded"})
ALLOWED_LANGUAGES={"ja","jpn","japanese"}
MAX_CANDIDATES=4

# Runs ONLY inside already-installed Sublarr container. Query uses catalog
# title/episode identity, never an untrusted URL or host video path. No media
# sidecar write, no translation and no writable output path, even on errors.
CONTAINER_WORKER=r'''
import base64, hashlib, json, sys
from providers import get_provider_manager
from providers.base import VideoQuery

requested=False
try:
    job=json.load(sys.stdin)
    params=job["query"]
    allowed={"title","year","imdb_id","series_title","season","episode"}
    if not isinstance(params,dict) or set(params)-allowed:
        raise ValueError("unsupported_query_fields")
    query=VideoQuery(**params,languages=["ja"],full_only=True)
    manager=get_provider_manager()
    wanted=job["provider"],job["subtitle_id"]
    result=None
    for r in manager.search(query,early_exit=False):
        if (r.provider_name,r.subtitle_id)!=wanted:
            continue
        if (str(r.language).lower() not in ("ja","jpn","japanese")
                or r.forced or r.kind!="full"
                or r.format.value not in ("srt","unknown")
                or str(r.filename or "")!=job["filename"]
                or str(r.release_info or "")!=job["release_info"]):
            continue
        result=r
        break
    if result is None:
        answer={"ok":False,"attempted":False,"reason":"candidate_not_found_or_unusable"}
    else:
        requested=True
        content=manager.download(result,raise_skips=True)
        if type(content) is not bytes or not 0<len(content)<=2000000:
            raise RuntimeError("provider_bytes_invalid")
        answer={"ok":True,"attempted":True,"length":len(content),
                "sha256":hashlib.sha256(content).hexdigest(),
                "content_b64":base64.b64encode(content).decode("ascii")}
except Exception as exc:
    # Never echo private URLs, tokens, subtitle dialogue or API error bodies.
    answer={"ok":False,"attempted":requested,
            "reason":type(exc).__name__}
sys.stdout.write(json.dumps(answer,separators=(",",":")))
'''


def remote_identity(candidate):
    provider=str(candidate.get("provider") or "").strip().lower()
    sid=str(candidate.get("subtitle_id") or "")
    if not PROVIDER.fullmatch(provider) or provider in OWN_HANDLERS:
        raise RuntimeError("sublarr_provider_not_generic")
    if not 2<=len(sid)<=250 or not sid.isprintable():
        raise RuntimeError("invalid_remote_subtitle_id")
    # Full origin identity in the hash: different providers may reuse IDs.
    return jelly.numeric_stage_id("sublarr:"+provider+"\x00"+sid)


def identity_ok(row,candidate):
    """Conservative existing-catalog identity; not final timing approval."""
    if not isinstance(row,dict) or not isinstance(candidate,dict):
        return False
    try:
        remote_identity(candidate)
    except RuntimeError:
        return False
    if (str(candidate.get("language") or "").casefold() not in ALLOWED_LANGUAGES
            or candidate.get("forced") is True
            or str(candidate.get("kind") or "").casefold() in {"forced","signs"}
            or str(candidate.get("format") or "").casefold() not in {"srt","unknown",""}):
        return False
    if row.get("kind")=="Movie":
        return stage.movie_identity_ok(row,candidate)
    if row.get("kind")!="Episode":
        return False
    season,episode=row.get("season"),row.get("episode")
    if type(season) is not int or type(episode) is not int:
        return False
    tags=stage.named_episode(
        str(candidate.get("filename") or "")+" "+
        str(candidate.get("release_info") or ""))
    if tags!={(season,episode)}:
        return False
    series=stage.tokens(row.get("series_title"))
    return bool(series) and any(
        stage.contiguous_words(stage.tokens(value),series)
        for value in (candidate.get("filename"),candidate.get("release_info"))
    )


def source_candidates(row,*,provider=None):
    stage.private_file(stage.SEARCH_DB)
    uri="file:"+quote(str(stage.SEARCH_DB.resolve()),safe="/")+"?mode=ro"
    with sqlite3.connect(uri,uri=True,timeout=15) as db:
        record=db.execute("SELECT results_json FROM searches WHERE jellyfin_id=?",
                          (row["jellyfin_id"],)).fetchone()
    if not record:
        return []
    document=json.loads(record[0])
    if not isinstance(document,dict):
        raise RuntimeError("invalid_saved_search_document")
    unique={}
    for item in document.get("candidates") or []:
        if not identity_ok(row,item):
            continue
        if provider and item["provider"]!=provider:
            continue
        key=(item["provider"],str(item["subtitle_id"]))
        unique[key]=item
    return sorted(unique.values(),key=lambda c:(
        -progress.release_match(row,c),
        -int(c.get("score") or 0),
        str(c["provider"]),str(c["subtitle_id"])
    ))


def worker_query(row):
    saved=search.query_for(row)
    if saved is None:
        raise RuntimeError("media_not_ready_for_provider_search")
    keys=("title","year","imdb_id","series_title","season","episode")
    result={k:saved[k] for k in keys if k in saved}
    if "year" in result:
        result["year"]=int(result["year"])
    return result


def provider_bytes(row,candidate,*,runner=subprocess.run):
    params={"query":worker_query(row),"provider":candidate["provider"],
            "subtitle_id":str(candidate["subtitle_id"]),
            "filename":str(candidate.get("filename") or ""),
            "release_info":str(candidate.get("release_info") or "")}
    command=["docker","exec","-i","-e","PYTHONPATH=/app",
             "sublarr-pilot","python3","-c",CONTAINER_WORKER]
    result=runner(command,input=json.dumps(params),
                  capture_output=True,text=True,timeout=255)
    if result.returncode:
        raise RuntimeError("sublarr_provider_manager_unavailable")
    # If any debug logging contaminates stdout, NEVER treat it as subtitle.
    if len(result.stdout)>3_000_000:
        raise RuntimeError("sublarr_provider_response_oversize")
    try:
        response=json.loads(result.stdout)
    except (ValueError,TypeError):
        raise RuntimeError("sublarr_provider_response_unparseable") from None
    if not isinstance(response,dict) or type(response.get("ok")) is not bool:
        raise RuntimeError("sublarr_provider_response_invalid")
    if response.get("attempted") is True:
        attempt=ledger.begin(candidate["provider"],"sublarr_provider_manager")
        if response["ok"]:
            ledger.finish(attempt,"downloaded",byte_count=int(response.get("length") or 0))
        else:
            code=str(response.get("reason") or "unknown")
            limited=("RateLimit" in code or "RateLimited" in code)
            ledger.finish(attempt,"quota_blocked" if limited else "failed",
                          error_kind=(code if re.fullmatch(r"[A-Za-z0-9_]{1,75}",code)
                                      else "provider_failure"))
    if not response["ok"]:
        reason=str(response.get("reason") or "provider_unavailable")
        if not re.fullmatch(r"[A-Za-z0-9_]{1,75}",reason):
            reason="provider_unavailable"
        raise RuntimeError("sublarr_provider_"+reason)
    try:
        raw=base64.b64decode(response["content_b64"],validate=True)
    except (ValueError,TypeError,KeyError):
        raise RuntimeError("sublarr_provider_base64_invalid") from None
    if (type(response.get("length")) is not int or len(raw)!=response["length"]
            or not 0<len(raw)<=MAX_BYTES
            or hashlib.sha256(raw).hexdigest()!=response.get("sha256")):
        raise RuntimeError("sublarr_provider_bytes_integrity_failed")
    return raw


def stage_metadata(row,candidate,raw,runtime,qa):
    sid,digest=remote_identity(candidate)
    return {
        "provider":SOURCE,"source_schema":SCHEMA,
        "source_jellyfin_id":row["jellyfin_id"],
        "source_remote_provider":candidate["provider"],
        "source_remote_id_sha256":digest,
        "source_filename":str(candidate.get("filename") or "")[:240],
        "source_release":str(candidate.get("release_info") or "")[:240],
        "source_media_kind":row["kind"],
        "source_year":row.get("year"),
        "source_series_title":str(row.get("series_title") or "")[:160],
        "source_season":row.get("season"),"source_episode":row.get("episode"),
        "source_language":str(candidate.get("language") or ""),
        "format":"srt","bytes":len(raw),"sha256":hashlib.sha256(raw).hexdigest(),
        "video_seconds":round(float(runtime),3),
        "cues":qa["cues"],
        "japanese_characters":qa["japanese_characters"],
        "japanese_cue_fraction":qa["japanese_cue_fraction"],
    }


def validate_staged_provenance(row,jid,sid,metrics):
    """Publisher rechecks immutable saved provider identity, never filename alone."""
    if (not isinstance(metrics,dict) or metrics.get("provider")!=SOURCE
            or metrics.get("source_schema")!=SCHEMA
            or metrics.get("source_jellyfin_id")!=jid
            or metrics.get("source_media_kind")!=row.get("kind")
            or metrics.get("source_year")!=row.get("year")
            or metrics.get("source_series_title")!=str(row.get("series_title") or "")[:160]
            or metrics.get("source_season")!=row.get("season")
            or metrics.get("source_episode")!=row.get("episode")):
        raise RuntimeError("sublarr_staged_identity_changed")
    matches=[]
    for c in source_candidates(row):
        csid,cdigest=remote_identity(c)
        if (csid==str(sid) and cdigest==metrics.get("source_remote_id_sha256")
                and c["provider"]==metrics.get("source_remote_provider")
                and str(c.get("filename") or "")[:240]==metrics.get("source_filename")
                and str(c.get("release_info") or "")[:240]==metrics.get("source_release")
                and str(c.get("language") or "")==metrics.get("source_language")):
            matches.append(c)
    if len(matches)!=1:
        raise RuntimeError("sublarr_saved_candidate_not_verified")
    return True


def preserve(row,candidate,raw,runtime,qa):
    """Create-only private file and compatible stage DB row, never video sidecar."""
    sid,digest=remote_identity(candidate)
    jid=row["jellyfin_id"]
    meta=stage_metadata(row,candidate,raw,runtime,qa)
    validate_staged_provenance(row,jid,sid,meta)
    stage.private_root()
    stage.STAGED.mkdir(mode=0o700,exist_ok=True)
    if stage.STAGED.is_symlink() or stage.STAGED.stat().st_mode & 0o077:
        raise RuntimeError("unsafe_staged_subtitle_root")
    dest=stage.STAGED/(jid+".sublarr."+sid+".ja.srt")
    digest_bytes=hashlib.sha256(raw).hexdigest()
    created=False
    if dest.is_symlink():
        raise RuntimeError("unsafe_staged_subtitle_file")
    if dest.exists():
        if not dest.is_file() or hashlib.sha256(dest.read_bytes()).hexdigest()!=digest_bytes:
            raise RuntimeError("conflicting_existing_generic_stage")
    else:
        fd=os.open(str(dest),os.O_WRONLY|os.O_CREAT|os.O_EXCL|
                   getattr(os,"O_NOFOLLOW",0),0o600)
        with os.fdopen(fd,"wb") as f:
            f.write(raw)
        created=True
    try:
        with stage.stage_db() as db:
            previous=db.execute(
                "SELECT host_path,sha256,metrics_json FROM staged "
                "WHERE jellyfin_id=? AND subtitle_id=?",(jid,sid)).fetchone()
            if previous:
                recorded_path,recorded_hash,recorded_metadata=previous
                if (recorded_path!=str(dest) or recorded_hash!=digest_bytes
                        or json.loads(recorded_metadata)!=meta):
                    raise RuntimeError("generic_stage_existing_provenance_collision")
            else:
                db.execute(
                    "INSERT INTO staged "
                    "(jellyfin_id,subtitle_id,host_path,sha256,staged_at,status,metrics_json) "
                    "VALUES(?,?,?,?,strftime('%s','now'),'staged',?)",
                    (jid,sid,str(dest),digest_bytes,json.dumps(meta,sort_keys=True)))
                db.commit()
    except BaseException:
        if created:
            dest.unlink(missing_ok=True)
        raise
    return sid


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jellyfin-id",required=True)
    parser.add_argument("--provider",default=None,
                        help="one exact previously saved provider (e.g. subf2m)")
    parser.add_argument("--max-attempts",type=int,default=2)
    parser.add_argument("--apply",action="store_true",
                        help="only private-stage candidates; never publish")
    args=parser.parse_args(argv)
    if not JID.fullmatch(args.jellyfin_id):
        parser.error("invalid Jellyfin ID")
    if args.provider and not PROVIDER.fullmatch(args.provider):
        parser.error("invalid provider")
    if not 1<=args.max_attempts<=MAX_CANDIDATES:
        parser.error("--max-attempts must be 1..4")
    row=stage.read_inventory().get(args.jellyfin_id)
    if not row or row.get("status")!="ready_ja_search":
        raise RuntimeError("selected_media_not_source_ready")
    candidates=source_candidates(row,provider=args.provider)
    print("=== SAVED OTHER-PROVIDER JAPANESE CANDIDATES ===",flush=True)
    print("Jellyfin ID:",args.jellyfin_id,"| Candidates:",len(candidates),
          "| provider:",args.provider or "other_supported_providers",flush=True)
    print("SUBLARR_GENERIC_MODE:","STAGE_PRIVATE" if args.apply else "READ_ONLY",
          flush=True)
    if not args.apply:
        print("NO PROVIDER CALLS, FILE WRITES, PUBLISHING OR PLaMO",flush=True)
        return
    if not candidates:
        return
    runtime=stage.duration_if_safe(row)
    for candidate in candidates[:args.max_attempts]:
        sid,_=remote_identity(candidate)
        try:
            with stage.stage_db() as db:
                prior=db.execute("SELECT status FROM staged WHERE jellyfin_id=? "
                                 "AND subtitle_id=?",(row["jellyfin_id"],sid)).fetchone()
            if prior:
                print("GENERIC_ALREADY_STAGED:",candidate["provider"],sid,flush=True)
                continue
            raw=provider_bytes(row,candidate)
            # Provider may return SRT with harmless formatting damage, but
            # never infer or invent missing dialogue/timing.
            normalized,report=structure.normalize(raw,trial_release_note=True,
                                                  trial_local_swap=True)
            qa=publisher.validate_srt(normalized,runtime)
            qa["structural_repair"]=report
            numeric=preserve(row,candidate,normalized,runtime,qa)
            print("STAGED_SUBLARR_PRIVATE:",candidate["provider"],numeric,flush=True)
        except (RuntimeError,OSError,ValueError,sqlite3.Error,subprocess.TimeoutExpired) as exc:
            code=str(exc).split(":",1)[0]
            if not re.fullmatch(r"[A-Za-z0-9_]{1,90}",code):
                code=type(exc).__name__
            print("GENERIC_CANDIDATE_REJECTED:",candidate["provider"],code,flush=True)
    print("PRIVATE STAGING ONLY; NO JAPANESE SIDECARS PUBLISHED.",flush=True)


if __name__=="__main__":
    try:main()
    except (RuntimeError,OSError,ValueError,sqlite3.Error,subprocess.TimeoutExpired) as exc:
        print("SUBLARR_GENERIC_STOPPED:",type(exc).__name__,flush=True)
        raise SystemExit(1)
