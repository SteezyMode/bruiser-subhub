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
    from . import ja_first_autofill as autofill
except ImportError:
    import ja_first_stage_saved_batch as stage
    import ja_first_stage_jellyfin as jelly
    import ja_first_publish_staged as publisher
    import ja_first_search_pilot as search
    import ja_first_srt_normalize as structure
    import ja_first_candidate_progress as progress
    import subhub_download_ledger as ledger
    import ja_first_autofill as autofill

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
import base64, hashlib, json, re, sys
from urllib.parse import urljoin, urlparse
from flask import Flask
from config import get_settings, reload_settings
from extensions import db as sa_db
from db.config import get_all_config_entries
from providers import get_provider_manager
from providers.base import VideoQuery

class SourceEvidenceError(Exception):
    pass

def title_tokens(value):
    value=re.sub(r"(?<=[a-z])['\u2019](?=[a-z])","",
                 str(value or "").casefold())
    return re.findall(r"[a-z]+|[0-9]+",value)

def subf2m_verified_release(manager,job):
    """Only the exact movie YEAR page may verify a historical blank release."""
    from bs4 import BeautifulSoup
    params=job["query"]
    if (job.get("provider")!="subf2m"
            or not params.get("title")
            or type(params.get("year")) is not int
            or not 1900<=params["year"]<=2100):
        raise SourceEvidenceError("movie_title_year_required")
    provider=manager.get_provider("subf2m")
    if provider is None or provider.session is None:
        raise SourceEvidenceError("subf2m_unavailable")
    name=title_tokens(params["title"])
    year=params["year"]
    verified=[]
    for page in provider._search_titles(params["title"]):
        display=str(page.get("name") or "")
        m=re.search(r"\(\s*((?:19|20)\d{2})\s*\)\s*$",display)
        if not m or int(m.group(1))!=year or title_tokens(display[:m.start()])!=name:
            continue
        url=str(page.get("url") or "")
        parsed=urlparse(url)
        if (parsed.scheme!="https" or parsed.hostname!="subf2m.co"
                or not parsed.path.startswith("/subtitles/")
                or parsed.username or parsed.password or parsed.query):
            continue
        verified.append((url,display[:m.start()].strip()))
    if len(verified)!=1:
        raise SourceEvidenceError("unique_title_year_page_not_verified")
    title_url,page_title=verified[0]
    response=provider.session.get(title_url.rstrip("/")+"/japanese",
                                  timeout=provider.timeout)
    if response.status_code!=200:
        raise SourceEvidenceError("japanese_listing_unavailable")
    soup=BeautifulSoup(response.text,"html.parser")
    found=[]
    for li in soup.select("li.item")[:100]:
        link=li.find("a",href=lambda h: h and "/subtitles/" in h)
        if link is None:
            continue
        href=urljoin("https://subf2m.co",link.get("href",""))
        url=urlparse(href)
        if (url.scheme!="https" or url.hostname!="subf2m.co"
                or not url.path.startswith("/subtitles/")
                or url.username or url.password):
            continue
        sub_id=url.path.rstrip("/").rsplit("/",1)[-1]
        if sub_id!=job["subtitle_id"]:
            continue
        text=li.get_text(" ",strip=True)
        text=re.sub(r"^Japanese\s+","",text,flags=re.I)
        text=re.split(r"\s+By\s+",text,maxsplit=1,flags=re.I)[0].strip()
        # Do not replace a blank listing label with the requested title.
        if not 5<=len(text)<=240:
            raise SourceEvidenceError("release_label_unverified")
        words=title_tokens(text)
        # Require exact full title followed by the expected release year,
        # independent of provider's untrusted "matches=title" claim.
        joined=name+[str(year)]
        if not any(words[i:i+len(joined)]==joined
                   for i in range(len(words)-len(joined)+1)):
            raise SourceEvidenceError("release_title_year_unverified")
        if re.search(r"(?i)(?:^|[._ -])(?:forced|signs.only)(?:$|[._ -])",text):
            raise SourceEvidenceError("forced_or_signs_release")
        found.append(text)
    if len(found)!=1:
        raise SourceEvidenceError("candidate_id_not_unique_on_verified_page")
    return {"title":page_title,"year":year,"release":found[0]}

requested=False
try:
    job=json.load(sys.stdin)
    if job.get("mode") not in (None,"probe","verify_subf2m"):
        raise ValueError("unsupported_operation")
    if job.get("mode")!="probe":
        params=job["query"]
        allowed={"title","year","imdb_id","series_title","season","episode"}
        if not isinstance(params,dict) or set(params)-allowed:
            raise ValueError("unsupported_query_fields")
        provider_name=str(job["provider"])
        query=VideoQuery(**params,languages=["ja"],full_only=True,
                         allowed_providers=[provider_name])
    # Minimal DB-connected Flask context; never run create_app(), whose
    # startup can migrate/seed/rebuild indexes or start extra services.
    bootstrap=get_settings()
    app=Flask("subhub_sublarr_provider_read_context",static_folder=None)
    app.config["SQLALCHEMY_DATABASE_URI"]=bootstrap.get_database_url()
    if not bootstrap.database_url or bootstrap.database_url.startswith("sqlite"):
        app.config["SQLALCHEMY_ENGINE_OPTIONS"]={
            "connect_args":{"check_same_thread":False}}
    sa_db.init_app(app)
    with app.app_context():
        overrides=get_all_config_entries()
        if overrides:
            reload_settings(overrides)
        manager=get_provider_manager()
        if job.get("mode")=="probe":
            answer={"ok":True,"attempted":False,
                    "active_provider_count":len(manager._providers),
                    "subf2m_enabled":"subf2m" in manager._providers}
        else:
            legacy=(job["provider"]=="subf2m" and
                    job.get("filename")==".srt" and
                    not str(job.get("release_info") or "").strip())
            if job.get("mode")=="verify_subf2m" and not legacy:
                raise SourceEvidenceError("blank_source_identity_not_selected")
            proof=subf2m_verified_release(manager,job) if legacy else None
            if job.get("mode")=="verify_subf2m":
                answer={"ok":True,"attempted":False,"source_proof":proof}
            else:
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
                    answer={"ok":False,"attempted":False,
                            "reason":"candidate_not_found_or_unusable"}
                else:
                    requested=True
                    content=manager.download(result,raise_skips=True)
                    if type(content) is not bytes or not 0<len(content)<=2000000:
                        raise RuntimeError("provider_bytes_invalid")
                    answer={"ok":True,"attempted":True,"length":len(content),
                            "sha256":hashlib.sha256(content).hexdigest(),
                            "content_b64":base64.b64encode(content).decode("ascii")}
                    if proof is not None:
                        answer["source_proof"]=proof
except Exception as exc:
    # Never echo private URLs, tokens, subtitle dialogue or API error bodies.
    reason=(str(exc) if isinstance(exc,SourceEvidenceError)
            else type(exc).__name__)
    answer={"ok":False,"attempted":requested,"reason":reason}
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


def subf2m_missing_release(row,candidate):
    """Legacy blank SubF2M entries are UNVERIFIED, not automatically eligible."""
    return (isinstance(row,dict) and row.get("kind")=="Movie"
            and isinstance(candidate,dict)
            and candidate.get("provider")=="subf2m"
            and candidate.get("filename")==".srt"
            and not str(candidate.get("release_info") or "").strip()
            and str(candidate.get("language") or "").casefold() in ALLOWED_LANGUAGES
            and candidate.get("forced") is not True
            and str(candidate.get("kind") or "").casefold() not in {"forced","signs"}
            and str(candidate.get("format") or "").casefold() in {"srt","unknown",""}
            and bool(stage.tokens(row.get("title")))
            and bool(re.fullmatch(r"(?:19|20)\d{2}",str(row.get("year") or "")))
            and bool(PROVIDER.fullmatch(str(candidate.get("provider") or "")))
            and 2<=len(str(candidate.get("subtitle_id") or ""))<=250)


def verify_subf2m_proof(row,candidate,proof):
    """Verify live provider-page evidence without accepting the old blank filename.

    The container reads the verified title page and release label. The host
    independently checks that it actually proves this movie/year, and later
    the publisher re-verifies it against the original saved candidate ID.
    """
    if not subf2m_missing_release(row,candidate) or not isinstance(proof,dict):
        raise RuntimeError("subf2m_source_proof_missing")
    if (type(proof.get("year")) is not int
            or str(proof["year"])!=str(row.get("year"))
            or not isinstance(proof.get("title"),str)
            or stage.tokens(proof["title"])!=stage.tokens(row.get("title"))):
        raise RuntimeError("subf2m_verified_title_or_year_mismatch")
    release=proof.get("release")
    if (not isinstance(release,str) or not 5<=len(release)<=240
            or any(ord(c)<32 for c in release)):
        raise RuntimeError("subf2m_verified_release_invalid")
    if not stage.movie_identity_ok(row,{"filename":release,"release_info":release}):
        raise RuntimeError("subf2m_verified_release_identity_mismatch")
    return True


def source_candidates(row,*,provider=None,include_unverified_subf2m=False):
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
        if not (identity_ok(row,item) or
                include_unverified_subf2m and subf2m_missing_release(row,item)):
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


def list_candidates():
    """Single read-only saved-search census; no API requests or provider GET."""
    from collections import Counter
    inventory=stage.read_inventory()
    counts=Counter()
    titles=set()
    examples=[]
    for jid,raw in stage.read_saved_searches():
        row=inventory.get(str(jid))
        if not row or row.get("status")!="ready_ja_search":
            continue
        try:
            document=json.loads(raw)
        except (TypeError,ValueError):
            continue
        if not isinstance(document,dict):
            continue
        matches=[c for c in document.get("candidates") or []
                 if identity_ok(row,c)]
        if not matches:
            continue
        titles.add(str(jid))
        for candidate in matches:
            counts[candidate["provider"]]+=1
        if len(examples)<12:
            examples.append((str(jid),str(row.get("title")
                             or row.get("series_title") or "Untitled")[:65],
                             sorted(set(c["provider"] for c in matches))))
    print("=== SAVED OTHER-PROVIDER JAPANESE STAGING CANDIDATES ===")
    print("Titles with eligible saved candidates:",len(titles))
    print("Releases by provider:",dict(sorted(counts.items())))
    for jid,title,providers in examples:
        print("EXAMPLE:",jid,"|",title,"|",",".join(providers))
    print("READ ONLY: no provider search, downloads, video writes or PLaMO")


def exclusion_reason(row,candidate):
    """Explain the exact existing staging filter, without relaxing it."""
    if not isinstance(candidate,dict):
        return "invalid_record"
    try:
        remote_identity(candidate)
    except RuntimeError:
        return "not_generic_or_invalid_provider_id"
    if str(candidate.get("language") or "").casefold() not in ALLOWED_LANGUAGES:
        return "language_not_japanese"
    if candidate.get("forced") is True or str(
            candidate.get("kind") or "").casefold() in {"forced","signs"}:
        return "forced_or_signs_only"
    if str(candidate.get("format") or "").casefold() not in {"srt","unknown",""}:
        return "unsupported_format"
    if not isinstance(row,dict) or row.get("status")!="ready_ja_search":
        return "media_not_pending_japanese"
    if identity_ok(row,candidate):
        return "eligible"
    if row.get("kind")=="Movie":
        return "unverified_movie_title_or_year"
    if row.get("kind")=="Episode":
        return "unverified_series_or_episode"
    return "unsupported_media_kind"


def is_animation(row):
    """Genre indicator for pilot ordering, not a claim about original audio."""
    genres=row.get("genres") or []
    return any(str(g).casefold().strip() in {"anime","animation"}
               for g in genres)


def exclusion_audit():
    """Full saved-results audit, no provider calls, no filesystem mutation.

    Count candidate-level evidence separately from unique titles.
    Rejected search hits are never silently promoted into stage eligibility.
    """
    from collections import Counter,defaultdict
    inventory=stage.read_inventory()
    state=Counter()
    by_provider=defaultdict(Counter)
    examples=defaultdict(list)
    viable_titles=set()
    live_action_examples=[]
    seen=set()
    for jid,raw in stage.read_saved_searches():
        row=inventory.get(str(jid))
        if not row:
            state["search_not_in_current_inventory"]+=1
            continue
        try:
            doc=json.loads(raw)
        except (TypeError,ValueError):
            state["invalid_saved_json"]+=1
            continue
        if not isinstance(doc,dict):
            state["invalid_saved_json"]+=1
            continue
        for source in ("candidates","rejected_candidates"):
            for c in doc.get(source) or []:
                if not isinstance(c,dict):
                    state["invalid_candidate_entry"]+=1
                    continue
                provider=str(c.get("provider") or "").casefold()
                if provider in OWN_HANDLERS:
                    continue
                # Do not turn repeated legacy records into artificial evidence.
                key=(str(jid),provider,str(c.get("subtitle_id") or ""),
                     str(c.get("filename") or ""),str(c.get("format") or ""),
                     str(c.get("language") or ""),str(c.get("forced") or ""),
                     str(c.get("kind") or ""),source)
                if key in seen:
                    continue
                seen.add(key)
                reason=exclusion_reason(row,c)
                # Discovery rejects may happen for reasons our simpler stage
                # filter cannot infer. NEVER call one of those stage-eligible.
                bucket=reason if source=="candidates" else "discovery_rejected_"+reason
                summary=by_provider[provider or "missing_provider"]
                summary[source+"_total"]+=1
                summary[bucket]+=1
                state["releases_examined"]+=1
                if source=="candidates" and reason=="eligible":
                    viable_titles.add(str(jid))
                    summary["unique_title_"+str(jid)]=1
                if bucket!="eligible" and len(examples[(provider,bucket)])<2:
                    examples[(provider,bucket)].append(
                        (str(row.get("title") or row.get("series_title") or "Untitled")[:64],
                         str(row.get("kind") or "unknown")))
                if (source=="candidates" and
                        row.get("status")=="ready_ja_search" and
                        not is_animation(row) and
                        len(live_action_examples)<14 and
                        reason in ("eligible","unverified_movie_title_or_year",
                                   "unverified_series_or_episode","unsupported_format")):
                    live_action_examples.append((
                        str(jid),str(row.get("title") or row.get("series_title") or "")[:60],
                        provider,reason,str(c.get("format") or "unknown"),
                        str(c.get("grade") or "unknown")))
    print("=== SAVED NON-CORE PROVIDER FILTER AUDIT ===")
    print("Retained/rejected are distinct saved-search classes, not provider failures.")
    print("No actual provider participation or recent availability is proven.")
    print("Release records examined:",state["releases_examined"])
    print("Titles with eligible saved non-core releases:",len(viable_titles))
    for provider,c in sorted(by_provider.items()):
        unique=sum(1 for name in c if name.startswith("unique_title_"))
        print("PROVIDER:",provider,
              "| retained:",c["candidates_total"],
              "| rejected_by_discovery:",c["rejected_candidates_total"],
              "| eligible:",c["eligible"],
              "| unique_eligible_titles:",unique)
        for reason,n in sorted(c.items()):
            if reason in ("eligible","candidates_total","rejected_candidates_total"
                          ) or reason.startswith("unique_title_"):
                continue
            print("  EXCLUDED:",reason,n,
                  "| examples:",examples.get((provider,reason),[]))
    print("NON-ANIMATION GENRE PILOT REVIEW (not verified live-action):")
    for jid,title,provider,reason,fmt,grade in live_action_examples:
        print("PILOT:",jid,title,"|",provider,
              "|",reason,"| format:",fmt,"| prior grade:",grade)
    print("READ ONLY: ZERO searches, downloads, stages, AI, or publication.")


def probe_manager(*,runner=subprocess.run):
    """Read-only provider manager initialization test; no remote searches."""
    command=["docker","exec","-i","-e","PYTHONPATH=/app",
             "sublarr-pilot","python3","-c",CONTAINER_WORKER]
    result=runner(command,input='{"mode":"probe"}',text=True,
                  capture_output=True,timeout=75)
    if result.returncode or len(result.stdout)>4000:
        raise RuntimeError("sublarr_probe_process_failed")
    try:
        payload=json.loads(result.stdout)
    except (TypeError,ValueError):
        raise RuntimeError("sublarr_probe_output_invalid") from None
    if not isinstance(payload,dict) or payload.get("ok") is not True:
        reason=str(payload.get("reason") or "unavailable") if isinstance(payload,dict) else "unavailable"
        if not re.fullmatch(r"[A-Za-z0-9_]{1,75}",reason):
            reason="unavailable"
        raise RuntimeError("sublarr_probe_"+reason)
    providers=payload.get("active_provider_count")
    if type(providers) is not int or not 0<=providers<=150:
        raise RuntimeError("sublarr_probe_provider_count_invalid")
    print("SUBLARR_MANAGER_APP_CONTEXT: PASS")
    print("Active providers initialized:",providers)
    print("SubF2M enabled:",bool(payload.get("subf2m_enabled")))
    print("No provider searches, subtitle downloads or media writes.")


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jellyfin-id",default="")
    parser.add_argument("--list-candidates",action="store_true",
                        help="read-only saved candidate census across media catalog")
    parser.add_argument("--audit-exclusions",action="store_true",
                        help="read-only per-provider candidate rejection causes and non-animation pilots")
    parser.add_argument("--probe-manager",action="store_true",
                        help="read-only minimal Flask provider manager initialization, no searches")
    parser.add_argument("--provider",default=None,
                        help="one exact previously saved provider (e.g. subf2m)")
    parser.add_argument("--max-attempts",type=int,default=2)
    parser.add_argument("--apply",action="store_true",
                        help="only private-stage candidates; never publish")
    args=parser.parse_args(argv)
    if args.probe_manager:
        if args.apply or args.jellyfin_id or args.provider or args.list_candidates or args.audit_exclusions:
            parser.error("--probe-manager cannot be combined with stage options")
        probe_manager()
        return
    if args.audit_exclusions:
        if args.apply or args.jellyfin_id or args.provider or args.list_candidates:
            parser.error("--audit-exclusions cannot be combined with stage options")
        exclusion_audit()
        return
    if args.list_candidates:
        if args.apply or args.jellyfin_id or args.provider:
            parser.error("--list-candidates cannot be combined with stage options")
        list_candidates()
        return
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
    # The standard source cycle owns this same lock; never spend provider
    # credits concurrently with another owner/automatic run.
    fd=autofill.lock()
    try:
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
    finally:
        os.close(fd)


if __name__=="__main__":
    try:main()
    except (RuntimeError,OSError,ValueError,sqlite3.Error,subprocess.TimeoutExpired) as exc:
        print("SUBLARR_GENERIC_STOPPED:",type(exc).__name__,flush=True)
        raise SystemExit(1)
