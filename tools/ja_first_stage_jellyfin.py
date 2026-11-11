#!/usr/bin/env python3
"""Stage exactly one Jellyfin remote Japanese SRT in SubHub's EXISTING private store.

No new provider implementation, no media writes, no Jellyfin POST. Uses
Jellyfin's item-scoped remote search and read-only subtitle GET, then normal
SubHub stage DB, duration/identity/SRT QA, ALASS publisher and no-clobber gates.
Default preview is zero provider requests. --apply is explicitly ONE search,
at most ONE subtitle download and (on success) a private create-only stage.

The existing publisher can then process it through its normal dry-run and
explicit --apply modes. No automatic publication is started here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import time
from urllib.error import HTTPError

try:
    from . import benchmark_subtitle_search_paths as benchmark
    from . import probe_jellyfin_remote_subtitle as probe
    from . import ja_first_stage_saved_batch as stage
    from . import ja_first_publish_staged as publisher
    from . import ja_first_catalog_manifest as catalog
    from . import subhub_download_ledger as ledger
except ImportError:
    import sys
    sys.path.insert(0,str(Path.home()/"bruiser-pilot/subhub-control"))
    import benchmark_subtitle_search_paths as benchmark
    import probe_jellyfin_remote_subtitle as probe
    import ja_first_stage_saved_batch as stage
    import ja_first_publish_staged as publisher
    import ja_first_catalog_manifest as catalog
    import subhub_download_ledger as ledger

JID = re.compile(r"[a-f0-9]{32}\Z")
SOURCE = "jellyfin"
METADATA_VERSION = "jellyfin-remote-stage-v1"
MIN_ID = 1_000_000_000_000
ID_RANGE = 9_000_000_000_000


def numeric_stage_id(remote_id):
    """Nonreversible stable numeric ID; OpenSubtitles numeric IDs unaffected."""
    if not isinstance(remote_id,str) or not 2<=len(remote_id)<=512:
        raise RuntimeError("invalid_remote_candidate_id")
    digest=hashlib.sha256(remote_id.encode("utf-8")).hexdigest()
    # 13 digits. Different providers use distinct source filenames, but the
    # old staging DB primary key is (jellyfin_id, subtitle_id), so verify
    # stored provenance on every collision, never overwrite it.
    return str(MIN_ID+int(digest,16)%ID_RANGE), digest


def stage_filename(jid,sid):
    if not JID.fullmatch(str(jid)) or not re.fullmatch(r"[1-9][0-9]{12}",str(sid)):
        raise RuntimeError("invalid_private_stage_identity")
    return f"{jid}.jellyfin.{sid}.ja.srt"


def stage_metadata(row,candidate,sid,digest,raw,runtime,qa):
    if row.get("status")!="ready_ja_search":
        raise RuntimeError("media_already_covered_or_not_eligible")
    jid=str(row.get("jellyfin_id") or "")
    if not JID.fullmatch(jid):
        raise RuntimeError("invalid_jellyfin_id")
    if not isinstance(candidate,dict) or not probe.relevant(row,candidate):
        raise RuntimeError("candidate_does_not_match_exact_Jellyfin_media")
    if numeric_stage_id(candidate.get("Id"))!=(str(sid),str(digest)):
        raise RuntimeError("candidate_id_or_hash_changed")
    provider=str(candidate.get("ProviderName") or "")
    if not provider or len(provider)>80 or any(ord(c)<32 for c in provider):
        raise RuntimeError("invalid_provider")
    if candidate.get("Format") not in ("srt","SRT"):
        raise RuntimeError("only_srt_supported_by_existing_publisher")
    if not (0 < len(raw) <= probe.MAX_SUB_BYTES):
        raise RuntimeError("subtitle_empty_or_oversize")
    expected=publisher.validate_srt(raw,runtime)
    if expected!=qa:
        raise RuntimeError("japanese_subtitle_validation_changed")
    return {
        "provider": SOURCE, "source_schema": METADATA_VERSION,
        "source_jellyfin_id": jid,
        "source_remote_provider":provider,
        "source_remote_id_sha256":digest,
        "source_filename":str(candidate.get("Name") or "")[:240],
        "source_language":str(candidate.get("ThreeLetterISOLanguageName") or ""),
        "source_format":"srt",
        "source_media_kind":row.get("kind"),
        "source_year":row.get("year"),
        "source_series_title":str(row.get("series_title") or "")[:160],
        "source_season":row.get("season"),"source_episode":row.get("episode"),
        "format":"srt","bytes":len(raw),
        "sha256":hashlib.sha256(raw).hexdigest(),
        "video_seconds":round(float(runtime),3),
        "cues":qa["cues"],
        "japanese_characters":qa["japanese_characters"],
        "japanese_cue_fraction":qa["japanese_cue_fraction"],
    }


def validate_staged_provenance(row,jid,sid,metrics):
    """Source attestation for shared publisher, never trust a filename alone."""
    if not isinstance(metrics,dict):
        raise RuntimeError("invalid_source_metadata")
    if (not JID.fullmatch(str(jid))
        or metrics.get("source_schema")!=METADATA_VERSION
        or metrics.get("provider")!=SOURCE
        or metrics.get("source_jellyfin_id")!=jid
        or metrics.get("source_media_kind")!=row.get("kind")
        or metrics.get("source_year")!=row.get("year")
        or not re.fullmatch(r"[a-f0-9]{64}",
                            str(metrics.get("source_remote_id_sha256") or ""))):
        raise RuntimeError("jellyfin_source_identity_invalid")
    expected_sid=str(MIN_ID+int(metrics["source_remote_id_sha256"],16)%ID_RANGE)
    if str(sid)!=expected_sid:
        raise RuntimeError("jellyfin_source_candidate_id_mismatch")
    provider=str(metrics.get("source_remote_provider") or "")
    if not provider or len(provider)>80 or any(ord(c)<32 for c in provider):
        raise RuntimeError("jellyfin_source_provider_missing")
    candidate={
        "Name":metrics.get("source_filename"),
        "ThreeLetterISOLanguageName":metrics.get("source_language"),
    }
    if (metrics.get("source_format")!="srt" or
        not probe.relevant(row,candidate)):
        raise RuntimeError("jellyfin_source_media_match_not_proven")
    if row.get("kind")=="Episode" and any([
        metrics.get("source_season")!=row.get("season"),
        metrics.get("source_episode")!=row.get("episode"),
        metrics.get("source_series_title")!=str(row.get("series_title") or "")[:160],
    ]):
        raise RuntimeError("jellyfin_source_episode_identity_changed")
    return True


def preserve(row,candidate,raw,metrics,database):
    """Create-only in existing 0700 private stage; never rewrite old records."""
    jid=str(row["jellyfin_id"])
    sid,digest=numeric_stage_id(candidate["Id"])
    validate_staged_provenance(row,jid,sid,metrics)
    if stage.STAGED.is_symlink() or (stage.STAGED.exists() and
            (not stage.STAGED.is_dir() or stage.STAGED.stat().st_mode & 0o077)):
        raise RuntimeError("unsafe_private_staging_root")
    stage.STAGED.mkdir(mode=0o700,exist_ok=True)
    if stage.STAGED.is_symlink() or stage.STAGED.stat().st_mode & 0o077:
        raise RuntimeError("unsafe_private_staging_root")
    target=stage.STAGED/stage_filename(jid,sid)
    if target.is_symlink():
        raise RuntimeError("staged_subtitle_symlink")
    created=False
    if target.exists():
        if (not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest()
                 != hashlib.sha256(raw).hexdigest()):
            raise RuntimeError("conflicting_existing_private_stage")
    else:
        fd=os.open(str(target),os.O_WRONLY|os.O_CREAT|os.O_EXCL|
                   getattr(os,"O_NOFOLLOW",0),0o600)
        try:
            with os.fdopen(fd,"wb") as output:
                output.write(raw)
            created=True
        except BaseException:
            try:target.unlink()
            except OSError:pass
            raise
    try:
        db_record=database.execute(
            "SELECT host_path,sha256,metrics_json FROM staged "
            "WHERE jellyfin_id=? AND subtitle_id=?",(jid,sid)).fetchone()
        encoded=json.dumps(metrics,ensure_ascii=False,sort_keys=True)
        hexdigest=hashlib.sha256(raw).hexdigest()
        if db_record:
            old_path,old_hash,old_metrics=db_record
            if (old_path!=str(target) or old_hash!=hexdigest
                or json.loads(old_metrics).get("source_remote_id_sha256")!=digest
                or json.loads(old_metrics).get("provider")!=SOURCE):
                raise RuntimeError("staging_database_identity_collision")
            return {"status":"already_staged","jellyfin_id":jid,
                    "subtitle_id":sid,"bytes":len(raw),"cues":metrics["cues"]}
        database.execute(
            "INSERT INTO staged"
            " (jellyfin_id,subtitle_id,host_path,sha256,staged_at,status,metrics_json)"
            " VALUES(?,?,?,?,?,?,?)",
            (jid,sid,str(target),hexdigest,int(time.time()),"staged",encoded))
        database.commit()
    except BaseException:
        if created:
            try:target.unlink()
            except OSError:pass
        raise
    return {"status":"staged_not_published","jellyfin_id":jid,
            "subtitle_id":sid,"bytes":len(raw),"cues":metrics["cues"]}


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    chosen=ap.add_mutually_exclusive_group(required=True)
    chosen.add_argument("--movie",metavar="EXACT TITLE")
    chosen.add_argument("--episode",metavar="SERIES SxxExxx")
    chosen.add_argument("--jellyfin-id",metavar="32-HEX-ID",
                        help="exact existing catalog identity, preferred for batch jobs")
    ap.add_argument("--provider",default="subbuzz",help="Jellyfin provider label")
    ap.add_argument("--apply",action="store_true",help="ONE search + one GET + create-only private stage; no publication")
    opts=ap.parse_args()
    if opts.jellyfin_id:
        if not benchmark.ITEM_ID.fullmatch(opts.jellyfin_id):
            raise ValueError("invalid_Jellyfin_ID")
        matches=[entry for entry in benchmark.load_latest_manifest()
                 if isinstance(entry,dict) and
                 entry.get("jellyfin_id")==opts.jellyfin_id and
                 entry.get("kind") in ("Movie","Episode")]
        if len(matches)!=1:
            raise ValueError("Jellyfin_item_not_unique_in_catalog")
        row=matches[0]
    else:
        row=benchmark.select(benchmark.load_latest_manifest(),
                             [opts.movie] if opts.movie else [],
                             [opts.episode] if opts.episode else [],1)[0]
    title=(str(row.get("title")) if row["kind"]=="Movie" else
           f'{row["series_title"]} S{row["season"]:02d}E{row["episode"]:02d}')
    if row.get("status")!="ready_ja_search":
        raise RuntimeError("not_eligible_for_new_JA_staging")
    stage.private_root()
    # Full host path, duration, embedded Japanese subtitles and sidecar gates
    # before spending any provider credits.
    runtime=stage.duration_if_safe(row)
    print("MEDIA:",title,"| runtime_seconds:",round(runtime,2),flush=True)
    if not opts.apply:
        print("PREFLIGHT ONLY: zero remote searches or downloads, zero writes.")
        return
    auth=catalog.load_auth()
    opener=probe.build_opener(probe.NoRedirect())
    print("JELLYFIN_JA_SEARCH_REQUEST:",row["jellyfin_id"],flush=True)
    candidates=probe.request_candidates(row,auth,opener)
    matching=[x for x in candidates
              if probe.relevant(row,x)
              and str(x.get("ProviderName") or "").casefold()==opts.provider.casefold()
              and str(x.get("Format") or "").casefold()=="srt"]
    print("JELLYFIN_JA_MATCHING_CANDIDATES:",len(matching),
          "| provider:",opts.provider,flush=True)
    if not matching:
        print("HELD: no exactly matching Japanese SRT from requested provider.")
        return
    candidate=matching[0]
    sid,digest=numeric_stage_id(candidate["Id"])
    # Count ACTUAL remote subtitle GETs in the owner-private ledger,
    # independently of whether the downloaded Japanese text passes QA.
    source_name=ledger.jellyfin_provider(candidate)
    route=("jellyfin_subbuzz" if str(candidate.get("ProviderName") or "")
           .casefold()=="subbuzz" else "jellyfin_native")
    attempt=ledger.begin(source_name,route)
    try:
        raw,content_type=probe.get_remote_bytes(candidate,auth,opener)
    except Exception as exc:
        code=int(exc.code) if isinstance(exc,HTTPError) else None
        outcome="quota_blocked" if code in (406,429) else "failed"
        ledger.finish(attempt,outcome,error_kind=(
            f"HTTP_{code}" if code else type(exc).__name__))
        raise
    ledger.finish(attempt,"downloaded",byte_count=len(raw))
    summary=probe.characterize(raw,content_type)
    print("JELLYFIN_JA_BYTES:",json.dumps(summary),flush=True)
    metrics=stage_metadata(row,candidate,sid,digest,raw,runtime,
                           publisher.validate_srt(raw,runtime))
    with stage.stage_db() as database:
        outcome=preserve(row,candidate,raw,metrics,database)
    print("JELLYFIN_PRIVATE_STAGE:",json.dumps(outcome,sort_keys=True),flush=True)
    print("NO MEDIA CHANGES. ALASS and publisher NOT launched.")


if __name__=="__main__":
    main()
