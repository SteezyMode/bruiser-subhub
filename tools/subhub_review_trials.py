#!/usr/bin/env python3
"""Review-grade Japanese MOVIE subtitle acquisition and private QA.

No new provider SEARCHES. Only previously saved JA review-grade movie results
are eligible. Download into owner-only quarantine, inspect/repair temporary
bytes, trial ALASS, and report. Never write stage DB or media or run publisher.
No episodes, no PLaMO. Successful ALASS alone cannot prove movie identity.
"""
from __future__ import annotations

import argparse
import base64
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import zipfile
from urllib.error import HTTPError

try:
    from . import ja_first_stage_saved_batch as stage
    from . import ja_first_stage_subdl as subdl
    from . import ja_first_movie_scope as scope
    from . import ja_first_srt_normalize as normalize
    from . import ja_first_publish_staged as publisher
    from . import ja_first_ffsubsync as ff
    from . import ja_first_alass as alass
    from . import subhub_deep_source as history
    from . import subhub_saved_movie_recovery as saved
except ImportError:
    import ja_first_stage_saved_batch as stage
    import ja_first_stage_subdl as subdl
    import ja_first_movie_scope as scope
    import ja_first_srt_normalize as normalize
    import ja_first_publish_staged as publisher
    import ja_first_ffsubsync as ff
    import ja_first_alass as alass
    import subhub_deep_source as history
    import subhub_saved_movie_recovery as saved

QUARANTINE = stage.STAGED / "review-trial-cache"
MAX_RAW_BYTES = 2_000_000
MAX_REPORT_BYTES = 12_000
PROVIDERS = ("subdl", "opensubtitles")
TRIAL_GATE_VERSION = "1"  # Bump when trial/QA policy changes.


def acceptable(row, candidate):
    """Admit unknown names for quarantine ONLY, never publication."""
    if not isinstance(row, dict) or not isinstance(candidate, dict):
        return False
    if row.get("kind") != "Movie" or row.get("status") != "ready_ja_search":
        return False
    if candidate.get("grade") != "review" or candidate.get("provider") not in PROVIDERS:
        return False
    if (str(candidate.get("language") or "").casefold() not in ("ja", "jpn")
            or candidate.get("forced") is True
            or str(candidate.get("kind") or "").casefold() in ("forced", "signs")):
        return False
    remote = str(candidate.get("subtitle_id") or "")
    if candidate["provider"] == "subdl":
        return bool(subdl.SUBDL_ID.fullmatch(remote))
    return bool(saved.OPEN_ID.fullmatch(remote))


def audit_candidates(rows, reader=history.search_record, *, provider="both"):
    """Select once per (Jellyfin ID, provider, remote ID), without identity gate."""
    jobs=[]
    counts=Counter()
    seen=set()
    for row in sorted(rows,key=lambda r:(str(r.get("kind")),str(r.get("title") or
                               r.get("series_title") or "").casefold(),
                               str(r.get("jellyfin_id") or ""))):
        if row.get("status")!="ready_ja_search" or row.get("kind")!="Movie":
            continue
        if not scope.matches(row,"movies-all"):
            # Use approved Jellyfin movie-library roots, never TV paths.
            continue
        jid=str(row.get("jellyfin_id") or "")
        if not history.JID.fullmatch(jid):
            continue
        document=reader(jid)
        if not isinstance(document,dict):
            continue
        candidates=document.get("candidates") or []
        for candidate in candidates:
            if not isinstance(candidate,dict) or candidate.get("grade")!="review":
                continue
            counts["saved_review_hits"]+=1
            if candidate.get("provider") not in PROVIDERS:
                counts["other_provider_review_hits"]+=1
                continue
            if provider!="both" and candidate.get("provider")!=provider:
                continue
            if not acceptable(row,candidate):
                counts["invalid_or_nonja_review_hits"]+=1
                continue
            remote=str(candidate["subtitle_id"])
            key=(jid,candidate["provider"],remote)
            if key in seen:
                counts["duplicate_saved_hit"]+=1
                continue
            seen.add(key)
            jobs.append((row,candidate))
            counts["eligible_"+candidate["provider"]]+=1
    counts["candidate_jobs"]=len(jobs)
    return jobs,counts


def quarantine_root():
    stage.private_root()
    QUARANTINE.mkdir(mode=0o700,parents=False,exist_ok=True)
    if (QUARANTINE.is_symlink() or not QUARANTINE.is_dir()
            or QUARANTINE.stat().st_mode & 0o077):
        raise RuntimeError("unsafe_review_quarantine")
    return QUARANTINE


def key_path(row,candidate):
    raw=json.dumps([row["jellyfin_id"],candidate["provider"],
                    str(candidate["subtitle_id"])],separators=(",",":"),ensure_ascii=True)
    digest=hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return QUARANTINE/(digest+".bin"),QUARANTINE/(digest+".json")


def read_cached(path):
    if path.is_symlink():
        raise RuntimeError("review_cache_symlink")
    if not path.exists():
        return None
    if (not path.is_file() or path.stat().st_mode & 0o077
            or not 0<path.stat().st_size<=MAX_RAW_BYTES):
        raise RuntimeError("unsafe_review_cache")
    return path.read_bytes()


def cache_raw(path,raw):
    if not isinstance(raw,bytes) or not 0<len(raw)<=MAX_RAW_BYTES:
        raise RuntimeError("review_raw_invalid_size")
    old=read_cached(path)
    if old is not None:
        if old!=raw:
            raise RuntimeError("review_cached_source_conflict")
        return
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|
               getattr(os,"O_NOFOLLOW",0),0o600)
    try:
        with os.fdopen(fd,"wb") as target:
            target.write(raw)
            target.flush()
            os.fsync(target.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def already_inspected(row,candidate):
    """Advance across backlog if the same bytes passed through trial before."""
    raw,receipt=key_path(row,candidate)
    if receipt.is_symlink():
        raise RuntimeError("review_receipt_symlink")
    if not receipt.is_file():
        return False
    if receipt.stat().st_mode & 0o077 or receipt.stat().st_size>MAX_REPORT_BYTES:
        raise RuntimeError("unsafe_review_receipt")
    try:
        doc=json.loads(receipt.read_text("utf-8"))
    except (ValueError,UnicodeError):
        return False
    if not isinstance(doc,dict) or any((
        doc.get("schema")!="bruiser-review-trial-v1",
        doc.get("trial_gate_version")!=TRIAL_GATE_VERSION,
        doc.get("jellyfin_id")!=row["jellyfin_id"],
        doc.get("provider")!=candidate["provider"],
        doc.get("subtitle_id_sha256")!=hashlib.sha256(
            str(candidate["subtitle_id"]).encode()).hexdigest(),
    )):
        return False
    if candidate["provider"]=="subdl":
        archive=subdl.cached_zip_path(candidate)
        if archive.is_symlink():
            raise RuntimeError("review_archive_symlink")
        if not archive.is_file() or not 0<archive.stat().st_size<=subdl.MAX_ARCHIVE:
            return False
        with archive.open("rb") as stream:
            digest=hashlib.file_digest(stream,"sha256").hexdigest()
    else:
        content=read_cached(raw)
        if content is None:
            return False
        digest=hashlib.sha256(content).hexdigest()
    return digest==doc.get("source_sha256")


def cache_receipt(path,row,candidate,source_hash,assessment):
    # Quarantine report only; NO database record in the publishable staging DB.
    doc={
        "schema":"bruiser-review-trial-v1",
        "trial_gate_version":TRIAL_GATE_VERSION,
        "jellyfin_id":row["jellyfin_id"],
        "provider":candidate["provider"],
        "subtitle_id_sha256":hashlib.sha256(
            str(candidate["subtitle_id"]).encode()).hexdigest(),
        "source_sha256":source_hash,
        "status":assessment.get("status"),
        "reason":assessment.get("reason"),
        "cues":assessment.get("cues"),
        "japanese_characters":assessment.get("japanese_characters"),
        "alignment_reference":assessment.get("alignment_reference"),
        "timing_shift_range_seconds":assessment.get("timing_shift_range_seconds"),
        "metadata_identity_verified":assessment.get("metadata_identity_verified"),
    }
    data=(json.dumps(doc,sort_keys=True,ensure_ascii=False)+"\n").encode()
    if len(data)>MAX_REPORT_BYTES:
        raise RuntimeError("review_receipt_oversize")
    if path.is_symlink():
        raise RuntimeError("review_receipt_symlink")
    tmp=path.with_suffix(".json.tmp")
    if tmp.is_symlink() or tmp.exists():
        raise RuntimeError("review_receipt_conflict")
    fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    try:
        with os.fdopen(fd,"wb") as target:
            target.write(data)
            target.flush()
            os.fsync(target.fileno())
        os.replace(tmp,path)
    finally:
        tmp.unlink(missing_ok=True)


def download_opensubtitles(row,candidate,runtime):
    """Reuse the established Sublarr credential reader, no stage DB writes."""
    payload={"jellyfin_id":row["jellyfin_id"],
             "subtitle_id":str(candidate["subtitle_id"]),
             "provider":"opensubtitles",
             "filename":str(candidate.get("filename") or "")[:240],
             "release_info":str(candidate.get("release_info") or "")[:240],
             "matches":candidate.get("matches") or [],
             "duration":runtime,
             "trial_only":True}
    proc=subprocess.run(["docker","exec","-i","-e","PYTHONPATH=/app",
                         "sublarr-pilot","python3","-c",stage.WORKER],
                        input=json.dumps(payload),capture_output=True,text=True,
                        timeout=150,check=False)
    marker="STAGE_RESULT_JSON:"
    chunks=[line[len(marker):] for line in proc.stdout.splitlines()
            if line.startswith(marker)]
    report=json.loads(chunks[-1]) if chunks else {}
    # Count real downloads even if content later fails QA; no second GET.
    stage.record_native_download_attempt(proc.stdout,report)
    if proc.returncode or report.get("result")!="private_trial_bytes":
        # Never print raw provider exception text or entire worker stdout:
        # exceptions may contain credentials, URLs and account details.
        detail=str(report.get("error") or "")
        kind=str(report.get("error_type") or "")
        if (saved.QUOTA.search(detail) or
                "cooling_or_exhausted" in detail or
                "rate_limit" in detail.casefold() or
                re.search(r"\b(?:406|429)\b",detail)):
            raise RuntimeError("provider_download_limit")
        match=re.search(r"(?<![0-9])(?:40[0134]|41[0-9]|50[0-9])(?![0-9])",detail)
        if match:
            raise RuntimeError("opensubtitles_http_"+match.group()) from None
        if kind in {"RuntimeError","ValueError"} and re.fullmatch(
                r"[a-z][a-z0-9_]{2,85}",detail):
            raise RuntimeError("opensubtitles_"+detail) from None
        safe_kind=(kind if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{1,40}",kind)
                   else "no_worker_response")
        raise RuntimeError("opensubtitles_worker_"+safe_kind) from None
    raw=base64.b64decode(report.get("content_b64") or "",validate=True)
    if type(report.get("length")) is not int or len(raw)!=report["length"]:
        raise RuntimeError("review_download_length_mismatch")
    if not 0<len(raw)<=MAX_RAW_BYTES:
        raise RuntimeError("review_download_size_invalid")
    # The native Sublarr worker can reuse a pre-existing private provider
    # stage without another HTTP GET. Preserve that distinction in reports.
    source=("reused_container_stage" if report.get("new_download") is False
            else "downloaded")
    return raw,source


def inspect_srt(raw,runtime):
    """Decode text, mechanically normalize; no semantic rewriting."""
    issues=[]
    for encoding in ("utf-8-sig","utf-16","cp932","shift_jis"):
        try:
            original=raw.decode(encoding)
        except UnicodeError:
            continue
        if original.count("\ufffd")>5:
            continue
        try:
            text,repairs=normalize.normalize(original.encode("utf-8"),
                                            trial_release_note=True,
                                            trial_local_swap=True)
            qa=publisher.validate_srt(text,runtime)
            return text,qa,repairs
        except (ValueError,RuntimeError) as exc:
            issues.append(str(exc).split(":",1)[0][:85])
    raise RuntimeError("review_srt_rejected:"+
                       (issues[0] if issues else "undecodable"))


def inspect_subdl(blob,row,candidate,runtime):
    raw,qa,_=subdl.archive_srt(blob,row,candidate,runtime)
    return raw,qa,qa.get("structural_repair") or {}


def trial_alignment(row,text,runtime):
    if not alass.available():
        raise RuntimeError("alass_unavailable")
    video=Path(str(row.get("host_path") or ""))
    def validate(output):
        aligned=ff.keep_source_dialogue(text,output)
        alass.assess(text,aligned,runtime)
        return aligned
    aligned,reference=alass.align(video,text,validator=validate)
    assessment=alass.assess(text,aligned,runtime)
    return {"alignment_reference":reference,
            "timing_shift_range_seconds":[assessment["shift_min_s"],
                                          assessment["shift_max_s"]]}



def download_to_private_cache(row,candidate,*,download_subdl=subdl.cached_archive,
                              download_os=download_opensubtitles):
    """Acquire one saved JA review source. No normalization, ALASS or publishing.

    Original bytes are retained in the same cache already used by private
    trials. This function is safe for a broad, resumable download-only sweep.
    """
    if not acceptable(row,candidate):
        raise RuntimeError("invalid_movie_review_candidate")
    runtime=stage.duration_if_safe(row)
    quarantine_root()
    path,_=key_path(row,candidate)
    provider=candidate["provider"]
    if provider=="subdl":
        archive=subdl.cached_zip_path(candidate)
        if archive.is_symlink():
            raise RuntimeError("review_archive_symlink")
        existed=archive.is_file()
        blob=download_subdl(candidate)  # native owner-only ZIP cache, no re-GET
        if not isinstance(blob,bytes) or not 0<len(blob)<=subdl.MAX_ARCHIVE:
            raise RuntimeError("review_subdl_archive_invalid")
        return ("cached" if existed else "downloaded"),len(blob)
    raw=read_cached(path)
    if raw is not None:
        return "cached",len(raw)
    acquired=download_os(row,candidate,runtime)
    if isinstance(acquired,tuple) and len(acquired)==2:
        raw,source=acquired
    else:
        raw,source=acquired,"downloaded"
    cache_raw(path,raw)
    return source,len(raw)


def private_bytes_present(row,candidate):
    """No provider call; used to build offline processing queue."""
    path,_=key_path(row,candidate)
    if candidate["provider"]=="opensubtitles":
        return read_cached(path) is not None
    archive=subdl.cached_zip_path(candidate)
    if archive.is_symlink():
        raise RuntimeError("review_archive_symlink")
    if not archive.is_file():
        return False
    meta=archive.stat()
    return 0<meta.st_size<=subdl.MAX_ARCHIVE and not (meta.st_mode & 0o077)


def cached_subdl_only(candidate):
    path=subdl.cached_zip_path(candidate)
    if path.is_symlink() or not path.is_file():
        raise RuntimeError("review_source_not_cached")
    meta=path.stat()
    if not 0<meta.st_size<=subdl.MAX_ARCHIVE or meta.st_mode & 0o077:
        raise RuntimeError("review_cached_archive_unsafe")
    return path.read_bytes()


def cached_opensubtitles_only(row,candidate,runtime):
    raise RuntimeError("review_source_not_cached")


def trial(row,candidate,*,download_subdl=subdl.cached_archive,
          download_os=download_opensubtitles):
    """Return a private receipt; even a perfect sync cannot publish."""
    provider=candidate["provider"]
    runtime=stage.duration_if_safe(row)  # Before quota or any provider call.
    quarantine_root()
    path,receipt=key_path(row,candidate)
    identity=(subdl.identity_ok(row,candidate) if provider=="subdl"
              else stage.identity_ok(row,candidate))
    report={"metadata_identity_verified":bool(identity)}
    origin="cached"
    source_hash=None
    try:
        if provider=="subdl":
            archive=subdl.cached_zip_path(candidate)
            if archive.is_symlink():
                raise RuntimeError("review_archive_symlink")
            origin="cached" if archive.is_file() else "downloaded"
            # The already existing SubDL ZIP cache accepts larger bounded ZIPs
            # and preserves rejected originals without a second provider GET.
            blob=download_subdl(candidate)
            if not isinstance(blob,bytes):
                raise RuntimeError("review_zip_invalid")
            source_hash=hashlib.sha256(blob).hexdigest()
            raw,qa,repairs=inspect_subdl(blob,row,candidate,runtime)
        else:
            raw=read_cached(path)
            if raw is None:
                origin="downloaded"
                retrieved=download_os(row,candidate,runtime)
                if isinstance(retrieved,tuple) and len(retrieved)==2:
                    raw,origin=retrieved
                else:
                    raw=retrieved
                cache_raw(path,raw)
            source_hash=hashlib.sha256(raw).hexdigest()
            raw,qa,repairs=inspect_srt(raw,runtime)
        report.update({
            "cues":qa["cues"],
            "japanese_characters":qa["japanese_characters"],
            "repair":repairs,
            "status":"japanese_qa_pass",
        })
        try:
            report.update(trial_alignment(row,raw,runtime))
            report["status"]=("timing_trial_pass_identity_eligible"
                              if identity else "timing_trial_pass_identity_unverified")
        except (OSError,RuntimeError,ValueError,subprocess.TimeoutExpired) as exc:
            report["status"]="timing_trial_held"
            report["reason"]=str(exc).split(":",1)[0][:85]
    except (RuntimeError,OSError,ValueError,zipfile.BadZipFile) as exc:
        report["status"]="held_source_or_structure"
        if isinstance(exc,HTTPError) and exc.code in (406,429):
            report["reason"]="provider_download_limit"
        else:
            report["reason"]=str(exc).split(":",1)[0][:85]
    if source_hash is not None:
        cache_receipt(receipt,row,candidate,source_hash,report)
    elif report["status"]=="held_source_or_structure":
        # Do not cache transient network/credential failures as rejected bytes.
        raise RuntimeError(report["reason"]) from None
    return origin,report


def run(args):
    """Two explicit movie-wide passes: acquisition, then local inspection.

    Download-only never calls ALASS. Process-cache never calls any provider.
    Both skip TV, stage DB, media publication and PLaMO by construction.
    """
    saved.check_idle()
    fd=saved.autofill.lock()
    try:
        records=list(stage.read_inventory().values())
        jobs,counts=audit_candidates(records,provider=args.provider)
        phase=("DOWNLOAD TO PRIVATE CACHE" if args.download_only else
               "PROCESS CACHED SOURCES" if args.process_cache else
               "LEGACY INLINE PRIVATE TRIAL")
        print("=== ALL MOVIES:",phase,"(NO TV) ===")
        for key,n in sorted(counts.items()):
            print(key+":",n)
        print("Saved candidates:",len(jobs),"| phase:",phase,
              "| max attempts:",args.limit,
              "| provider:",args.provider,"| TV skipped: yes")
        if not args.apply:
            cached=0
            for row,candidate in jobs:
                try:
                    if private_bytes_present(row,candidate):
                        cached+=1
                except (OSError,ValueError,RuntimeError):
                    continue
            print("Private original files already cached:",cached)
            print("PREVIEW ONLY; use --apply to run the selected phase")
            return 0
        tally=Counter()
        attempted=0
        blocked=set()
        skipped_prior=0
        skipped_uncached=0
        for row,candidate in jobs:
            if attempted>=args.limit:
                break
            provider=candidate["provider"]
            if provider in blocked:
                continue
            if stage.japanese_sidecar_exists(Path(str(row.get("host_path") or ""))):
                tally["skipped_already_covered"]+=1
                continue
            if args.process_cache:
                if not private_bytes_present(row,candidate):
                    skipped_uncached+=1
                    continue
                if not args.retry and already_inspected(row,candidate):
                    skipped_prior+=1
                    continue
            elif not args.retry and already_inspected(row,candidate):
                if args.download_only:
                    # Already cached and inspected. Avoid re-downloading even
                    # if the original quarantine entry later disappeared.
                    skipped_prior+=1
                    continue
                skipped_prior+=1
                continue
            attempted+=1
            title=str(row.get("title") or row["jellyfin_id"])[:88]
            print(f"[{attempted}/{args.limit}] {title} [{provider}]",flush=True)
            try:
                if args.download_only:
                    origin,n=download_to_private_cache(row,candidate)
                    tally["source_"+origin]+=1
                    print(" ",origin,"source_bytes="+str(n),flush=True)
                else:
                    origin,result=(trial(row,candidate,
                        download_subdl=cached_subdl_only,
                        download_os=cached_opensubtitles_only)
                        if args.process_cache else trial(row,candidate))
                    status=result["status"]
                    tally[status]+=1
                    print(" ",origin,status,
                          "cues="+str(result.get("cues")),
                          "Japanese_chars="+str(result.get("japanese_characters")),
                          "identity_verified="+str(result.get("metadata_identity_verified")),
                          "ALASS="+str(result.get("alignment_reference") or "held"),
                          "reason="+str(result.get("reason") or "-"),
                          flush=True)
            except (OSError,ValueError,RuntimeError,subprocess.TimeoutExpired) as exc:
                reason=str(exc).split(":",1)[0][:85]
                tally["download_or_trial_held"]+=1
                print("  HELD:",reason,flush=True)
                if saved.QUOTA.search(reason) or reason=="provider_download_limit":
                    blocked.add(provider)
                    print("  DOWNLOAD QUOTA/COLDOWN:",provider,
                          "remaining candidates postponed",flush=True)
                elif reason in ("opensubtitles_http_401","opensubtitles_http_403",
                                "opensubtitles_worker_HTTPError",
                                "opensubtitles_native_opensubtitles_key_missing_in_saved_config"):
                    blocked.add(provider)
                    print("  PROVIDER ERROR:",provider,
                          "remaining candidates postponed",flush=True)
        print("=== MOVIE REVIEW",phase,"SUMMARY ===")
        print("Attempted:",attempted)
        print("Skipped prior verified cache/receipts:",skipped_prior)
        print("Skipped not yet cached:",skipped_uncached)
        for key,n in sorted(tally.items()):
            print(key+":",n)
        if blocked:
            print("Providers paused:",", ".join(sorted(blocked)))
        print("Publishable-stage DB writes: ZERO | sidecars published: ZERO")
        print("TV work: ZERO | new searches: ZERO | PLaMo: ZERO")
        return 0
    finally:
        os.close(fd)


def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--provider",choices=("both",*PROVIDERS),default="both")
    phases=ap.add_mutually_exclusive_group()
    phases.add_argument("--download-only",action="store_true",
                        help="acquire all saved movie reviews to private cache, no ALASS")
    phases.add_argument("--process-cache",action="store_true",
                        help="run lossless repair and ALASS only on cached bytes; no provider calls")
    ap.add_argument("--limit",type=int,default=250,
                    help="maximum candidate attempts this invocation, not an artificial daily quota")
    ap.add_argument("--apply",action="store_true")
    ap.add_argument("--retry",action="store_true",
                    help="reinspect previously processed cached originals")
    args=ap.parse_args(argv)
    if not 1<=args.limit<=500:
        ap.error("--limit must be 1..500")
    return run(args)


if __name__=="__main__":
    try:
        raise SystemExit(main())
    except (OSError,RuntimeError,ValueError,subprocess.TimeoutExpired) as exc:
        print("REVIEW_TRIAL_STOPPED:",type(exc).__name__,
              str(exc).split(":",1)[0][:95],file=sys.stderr,flush=True)
        raise SystemExit(1)
