#!/usr/bin/env python3
"""Promote independently cross-aligned, identity-verified cached movie JA.

This is deliberately NOT the source-review experiment. It uses originals
cached by subhub_review_trials, existing stage provenance, ALASS's intensive
cross-reference (audio AND an English text reference), and the existing
create-only publisher. Default audit never writes anything. No downloads,
new provider searches, episodes or PLaMO. Unverified film identities HELD.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import time

try:
    from . import subhub_review_trials as review
    from . import subhub_saved_movie_recovery as recovery
    from . import ja_first_stage_saved_batch as stage
    from . import ja_first_stage_subdl as subdl
    from . import ja_first_publish_staged as gate
    from . import ja_first_alass as alass
    from . import ja_first_publish_queue as queue
    from . import ja_first_obvious_quality as quality
    from . import ja_first_ffsubsync as ff
    from . import ja_first_candidate_progress as progress
except ImportError:
    import subhub_review_trials as review
    import subhub_saved_movie_recovery as recovery
    import ja_first_stage_saved_batch as stage
    import ja_first_stage_subdl as subdl
    import ja_first_publish_staged as gate
    import ja_first_alass as alass
    import ja_first_publish_queue as queue
    import ja_first_obvious_quality as quality
    import ja_first_ffsubsync as ff
    import ja_first_candidate_progress as progress

# Never interpret a preliminary ALASS pass as film-identity evidence.
TRIAL_PASS=("timing_trial_pass_identity_eligible",
            "timing_trial_pass_identity_unverified")


def identity_ok(row,candidate):
    if row.get("kind")!="Movie":
        return False
    if candidate.get("provider")=="subdl":
        return subdl.identity_ok(row,candidate)
    if candidate.get("provider")=="opensubtitles":
        return stage.identity_ok(row,candidate)
    return False


def read_receipt(row,candidate):
    """Authenticate a prior private trial against the current exact bytes."""
    if not review.already_inspected(row,candidate):
        return None
    _,receipt=review.key_path(row,candidate)
    try:
        return json.loads(receipt.read_text("utf-8"))
    except (OSError,UnicodeError,ValueError):
        return None


def cached_source(row,candidate,runtime):
    """Return the bytes previously checked, never fetch an external source."""
    if candidate["provider"]=="subdl":
        blob=review.cached_subdl_only(candidate)
        text,qa,_=review.inspect_subdl(blob,row,candidate,runtime)
    elif candidate["provider"]=="opensubtitles":
        path,_=review.key_path(row,candidate)
        raw=review.read_cached(path)
        if raw is None:
            raise RuntimeError("private_review_source_missing")
        text,qa,_=review.inspect_srt(raw,runtime)
    else:
        raise RuntimeError("unsupported_cached_provider")
    # Exact Japanese content constraints used in the publisher itself.
    verified=gate.validate_srt(text,runtime)
    if verified!={
        "cues":qa["cues"],
        "japanese_characters":qa["japanese_characters"],
        "japanese_cue_fraction":qa["japanese_cue_fraction"],
    }:
        raise RuntimeError("review_source_qa_changed")
    quality.require_not_garbage(text)
    return text,qa


def rank(row,candidate,receipt):
    # Prefer trial success, then release/edition fit and provider score.
    successful=receipt.get("status") in TRIAL_PASS
    try:
        score=int(candidate.get("score") or 0)
    except (TypeError,ValueError):
        score=0
    return (not successful,-progress.release_match(row,candidate),
            -score,str(candidate.get("provider")),str(candidate.get("subtitle_id")))


def select(rows, *, source_reader=review.audit_candidates,
           receipt_reader=read_receipt, identity_check=identity_ok):
    """One strongest eligible, cached, VERIFIED-metadata source per movie."""
    entries,catalog=source_reader(rows)
    by_movie=defaultdict(list)
    counts=Counter()
    examples=[]
    ids_with_cached=set()
    for row,candidate in entries:
        if not review.private_bytes_present(row,candidate):
            counts["not_cached"]+=1
            continue
        jid=row["jellyfin_id"]
        ids_with_cached.add(jid)
        receipt=receipt_reader(row,candidate)
        if not receipt:
            counts["not_yet_tested"]+=1
            continue
        if receipt.get("status") not in (*TRIAL_PASS,"timing_trial_held"):
            counts["structural_or_quality_hold"]+=1
            continue
        if not identity_check(row,candidate):
            counts["unverified_movie_identity"]+=1
            if len(examples)<8:
                examples.append((str(row.get("title") or "")[:60],
                                 "unverified_title_year"))
            continue
        if receipt.get("metadata_identity_verified") is False:
            # The current, independently repeated source identity predicate
            # must agree with the trial's recorded identity. A changed
            # predicate requires reinspection and an explicit new receipt.
            counts["metadata_verdict_changed_recheck"]+=1
            continue
        by_movie[jid].append((row,candidate,receipt))
        counts["identity_and_cached_eligible"]+=1

    selected=[]
    for jid,candidates in by_movie.items():
        candidates.sort(key=lambda x:rank(*x))
        selected.append(candidates[0])
        counts["alternate_cached_deferred"]+=len(candidates)-1
    selected.sort(key=lambda x:(str(x[0].get("title") or "").casefold(),
                                x[0]["jellyfin_id"]))
    counts["unique_movies_with_cached_review"]=len(ids_with_cached)
    counts["distinct_movies_eligible"]=len(selected)
    counts["saved_review_candidates"]=catalog.get("candidate_jobs",len(entries))
    return selected,counts,examples


def stage_cached_opensubtitles(row,candidate,text,runtime,qa):
    """Reuse the original stage database and naming, without Docker or GET.

    Must be called ONLY after cross-reference proof; otherwise an unrelated
    worker might publish this staged file with weaker alignment checks.
    """
    jid=row["jellyfin_id"]
    sid=str(candidate["subtitle_id"])
    if not stage.identity_ok(row,candidate):
        raise RuntimeError("review_movie_identity_no_longer_verified")
    stage.private_root()
    stage.STAGED.mkdir(mode=0o700,exist_ok=True)
    if stage.STAGED.is_symlink() or stage.STAGED.stat().st_mode & 0o077:
        raise RuntimeError("unsafe_staged_subtitle_directory")
    target=stage.STAGED/stage.stage_name(row,candidate,"srt")
    digest=hashlib.sha256(text).hexdigest()
    if target.is_symlink():
        raise RuntimeError("review_staged_symlink")
    if target.exists():
        stage.private_file(target)
        if target.read_bytes()!=text:
            raise RuntimeError("review_existing_staged_content_conflict")
        created=False
    else:
        fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL|
                   getattr(os,"O_NOFOLLOW",0),0o600)
        created=True
        with os.fdopen(fd,"wb") as target_stream:
            target_stream.write(text)
            target_stream.flush()
            os.fsync(target_stream.fileno())
    metrics={
        "provider":"opensubtitles","format":"srt","bytes":len(text),
        "video_seconds":round(float(runtime),3),
        "cues":qa["cues"],
        "japanese_characters":qa["japanese_characters"],
        "japanese_cue_fraction":qa["japanese_cue_fraction"],
        "source_filename":str(candidate.get("filename") or "")[:240],
        "source_release":str(candidate.get("release_info") or "")[:240],
        "source_review_verified":"cross_reference_before_staging",
    }
    try:
        with stage.stage_db() as db:
            old=db.execute(
                "SELECT host_path,sha256,status FROM staged "
                "WHERE jellyfin_id=? AND subtitle_id=?",(jid,sid)).fetchone()
            if old is not None:
                if (old[0],old[1])!=(str(target),digest):
                    raise RuntimeError("review_stage_id_conflict")
                if old[2] not in ("staged","published"):
                    raise RuntimeError("review_existing_stage_held")
            else:
                db.execute(
                    "INSERT INTO staged "
                    "(jellyfin_id,subtitle_id,host_path,sha256,staged_at,"
                    "status,metrics_json) VALUES (?,?,?,?,?,?,?)",
                    (jid,sid,str(target),digest,int(time.time()),"staged",
                     json.dumps(metrics,sort_keys=True,ensure_ascii=False)))
                db.commit()
    except BaseException:
        if created:
            target.unlink(missing_ok=True)
        raise
    return sid


def cross_check(row,candidate,text,runtime):
    """Independent same-video English/audio ALASS references must agree.

    Critically this runs BEFORE touching the live publication stage database.
    This accepts neither metadata alone nor a single ALASS fit as proof.
    """
    video=gate.safe_media_path(str(row.get("host_path") or ""))
    actual=gate.subprocess_duration(video)
    if abs(actual-runtime)>0.5:
        raise RuntimeError("movie_duration_changed")
    streams,error=gate.ffprobe_streams(video)
    if error or not isinstance(streams,list):
        raise RuntimeError("movie_subtitle_probe_failed")
    gate.check_no_existing_ja(video,streams)
    aligned,evidence=alass.intensive_align(
        video,text,jid=row["jellyfin_id"])
    corrected=ff.keep_source_dialogue(text,aligned)
    metrics=alass.assess(text,corrected,runtime,
                         independently_verified_tail=True)
    if not (evidence.get("intensive_cross_reference")=="video_audio"
            and evidence.get("alignment_reference")!="video_audio"
            and len(evidence.get("intensive_agreement_thirds") or [])==3):
        raise RuntimeError("no_independent_audio_english_agreement")
    return corrected,evidence,metrics


def promote(row,candidate,*,dry_run=False):
    """Prove -> stage from original cache -> rerun gates -> create-only publish."""
    jid=row["jellyfin_id"]
    if not review.acceptable(row,candidate) or not identity_ok(row,candidate):
        raise RuntimeError("review_identity_not_sufficient")
    receipt=read_receipt(row,candidate)
    if receipt is None or receipt.get("metadata_identity_verified") is not True:
        raise RuntimeError("prior_trial_identity_not_verified")
    if receipt.get("status") not in (*TRIAL_PASS,"timing_trial_held"):
        raise RuntimeError("cached_trial_not_japanese_qa_passed")
    runtime=stage.duration_if_safe(row)
    # This independent QA and dual-reference ALASS validation can be lengthy.
    text,qa=cached_source(row,candidate,runtime)
    aligned,evidence,metrics=cross_check(row,candidate,text,runtime)
    if dry_run:
        return "verified_dry_run",evidence
    if candidate["provider"]=="subdl":
        # Existing SubDL transport checks the original private ZIP SHA,
        # and stage_one strictly refuses an unknown/colliding stage.
        subdl.stage_one(row,candidate,runtime)
        sid=subdl.numeric_id(str(candidate["subtitle_id"]))[0]
    else:
        sid=stage_cached_opensubtitles(row,candidate,text,runtime,qa)
    # Recheck staged SHA, source-search identity, media/JA presence, content QA
    # and duration with the shared, existing ALASS publication preparation.
    ready=alass.prepare(
        jid,sid,aligner=lambda video,source:aligned,
        independently_verified_tail=True)
    if ready["chosen"]!=aligned:
        raise RuntimeError("review_alignment_changed_after_staging")
    ready["assessment"].update(evidence)
    ready["assessment"]["engine"]="review_cross_verified_alass_v1"
    # All on-disk publication uses pre-existing create-only primitives.
    alass.preserve(ready)
    gate.publish(ready["row"],ready["video"],ready["target"],ready["chosen"])
    try:
        queue.mark_completed(jid)
    except (OSError,ValueError,RuntimeError,sqlite3.Error):
        print("REVIEW_PUBLISHED_STAGE_STATUS_PENDING:",jid,flush=True)
    return "published",evidence


def run(args):
    recovery.check_idle()
    fd=recovery.autofill.lock()
    try:
        rows=list(stage.read_inventory().values())
        chosen,counts,examples=select(rows)
        print("=== CACHED MOVIE REVIEW -> JELLYFIN ===",flush=True)
        for key,n in sorted(counts.items()):
            print(key+":",n,flush=True)
        print("Other review candidates remain private; TV and PLaMO untouched.")
        for title,reason in examples:
            print("HOLD_EXAMPLE:",title,reason,flush=True)
        if not args.apply:
            print("AUDIT ONLY: 0 media writes, 0 downloads.")
            print("Pass --apply for dual-reference validation and safe publication.")
            return 0
        counters=Counter()
        attempted=0
        for row,candidate,receipt in chosen:
            if attempted>=args.limit:
                break
            attempted+=1
            label=str(row.get("title") or "")[:90]
            print(f"[{attempted}/{min(args.limit,len(chosen))}] {label}",flush=True)
            try:
                result,evidence=promote(row,candidate)
                counters[result]+=1
                print("  REVIEW_RESULT:",result,
                      "cross_reference="+str(evidence.get("alignment_reference")),
                      flush=True)
            except (OSError,ValueError,RuntimeError,sqlite3.Error) as exc:
                counters["held"]+=1
                print("  REVIEW_HELD:",str(exc).split(":",1)[0][:100],
                      flush=True)
        print("=== REVIEW MOVIE PROMOTION SUMMARY ===")
        for key,n in sorted(counters.items()):
            print(key+":",n)
        print("Unverified film identities never published.")
        return 0
    finally:
        os.close(fd)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply",action="store_true")
    parser.add_argument("--limit",type=int,default=200)
    args=parser.parse_args(argv)
    if not 1<=args.limit<=200:
        parser.error("limit must be 1..200")
    return run(args)


if __name__=="__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError,OSError,ValueError,sqlite3.Error) as exc:
        print("REVIEW_PROMOTION_STOPPED:",str(exc).split(":",1)[0][:100],
              file=sys.stderr,flush=True)
        raise SystemExit(1)
