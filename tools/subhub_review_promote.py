#!/usr/bin/env python3
"""Promote identity-verified cached movie JA after cross-engine timing QA.

Uses cached originals, existing stage provenance, and the same create-only
publisher. Prefer ALASS English-text+audio cross-reference; if no English
reference exists, require ALASS and ffsubsync AUDIO alignment to agree in all
three film thirds, with unchanged ffsubsync shift/coverage guards. Never
override a disagreeing English reference. No new searches or PLaMo.
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
    from . import ja_first_movie_scope as movie_scope
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
    import ja_first_movie_scope as movie_scope

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
        if not movie_scope.matches(row, movie_scope.MOVIES_NO_ANIME):
            counts["outside_non_anime_movie_scope"]+=1
            continue
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


def audio_consensus(video,text,runtime):
    """No-English fallback: independently run both established AUDIO aligners.

    Two audio aligners are not independent dialogue/identity evidence: exact
    film identity was checked by the cached review selector. This method only
    checks whether both different timing engines converge across the opening,
    middle AND ending. It is never used to override a disagreeing English
    text reference or accept a large ffsubsync timing correction.
    """
    original_health=gate.validate_srt(text,runtime)

    def alass_trial(candidate):
        corrected=ff.keep_source_dialogue(text,candidate)
        if gate.validate_srt(corrected,runtime)!=original_health:
            raise RuntimeError("audio_consensus_alass_japanese_health_changed")
        alass.assess(text,corrected,runtime)
        return corrected

    aligned,reference=alass.align(video,text,validator=alass_trial)
    # An English reference newly appearing during this pass is not audio
    # consensus. Resume the more informative two-reference route instead.
    if reference!="video_audio":
        raise RuntimeError("audio_consensus_reference_changed")

    synced=ff.align_in_container(video,text)
    synced=ff.keep_source_dialogue(text,synced)
    synced,_=ff.repair_minor_overlaps(synced,runtime)
    if gate.validate_srt(synced,runtime)!=original_health:
        raise RuntimeError("audio_consensus_ffsubsync_japanese_health_changed")
    # Retain all of ffsubsync's existing safety rules: max 30-s absolute shift,
    # max 5-s variation, cue identity, audio coverage and overlap health.
    ff.check_alignment(text,synced,runtime)
    thirds=alass._intensive_agreement(aligned,synced)
    if thirds is None:
        raise RuntimeError("audio_consensus_alass_ffsubsync_disagree")
    return aligned,{
        "alignment_reference":"video_audio",
        "audio_engine_consensus":"ffsubsync_video_audio",
        "audio_consensus_thirds":thirds,
        "audio_consensus_limitations":"timing_only_not_dialogue_or_identity_proof",
    }


def cross_check(row,candidate,text,runtime):
    """Match exact-media Japanese against independent timing references.

    Prefer a verified EN text and audio comparison. Only when the exact
    movie has NO available English reference, compare the existing ALASS
    and ffsubsync video-audio aligners. If either comparison fails, hold;
    no stage DB or media write occurs here.
    """
    video=gate.safe_media_path(str(row.get("host_path") or ""))
    actual=gate.subprocess_duration(video)
    if abs(actual-runtime)>0.5:
        raise RuntimeError("movie_duration_changed")
    streams,error=gate.ffprobe_streams(video)
    if error or not isinstance(streams,list):
        raise RuntimeError("movie_subtitle_probe_failed")
    gate.check_no_existing_ja(video,streams)
    try:
        aligned,evidence=alass.intensive_align(
            video,text,jid=row["jellyfin_id"])
    except RuntimeError as exc:
        if str(exc)!="alass_intensive_missing_english_reference":
            # A reference that exists but disagrees with the video is a
            # substantive QA signal. Never bypass it via audio-only fallback.
            raise
        aligned,evidence=audio_consensus(video,text,runtime)
    dual_reference=(
        evidence.get("intensive_cross_reference")=="video_audio"
        and evidence.get("alignment_reference")!="video_audio"
        and len(evidence.get("intensive_agreement_thirds") or [])==3
    )
    audio_reference=(
        evidence.get("alignment_reference")=="video_audio"
        and evidence.get("audio_engine_consensus")=="ffsubsync_video_audio"
        and len(evidence.get("audio_consensus_thirds") or [])==3
    )
    if not (dual_reference or audio_reference):
        raise RuntimeError("no_independent_timing_agreement")
    corrected=ff.keep_source_dialogue(text,aligned)
    metrics=alass.assess(text,corrected,runtime,
                         independently_verified_tail=dual_reference)
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
        independently_verified_tail=(
            evidence.get("intensive_cross_reference")=="video_audio"))
    if ready["chosen"]!=aligned:
        raise RuntimeError("review_alignment_changed_after_staging")
    ready["assessment"].update(evidence)
    ready["assessment"]["engine"]=(
        "review_cross_verified_alass_v1"
        if evidence.get("intensive_cross_reference")=="video_audio"
        else "review_alass_ffsubsync_audio_consensus_v1")
    # All on-disk publication uses pre-existing create-only primitives.
    alass.preserve(ready)
    gate.publish(ready["row"],ready["video"],ready["target"],ready["chosen"])
    try:
        queue.mark_completed(jid)
    except (OSError,ValueError,RuntimeError,sqlite3.Error):
        print("REVIEW_PUBLISHED_STAGE_STATUS_PENDING:",jid,flush=True)
    return "published",evidence



def audit_references(row,candidate):
    """Read-only evidence audit for the film's exact same-video references.

    No ALASS runs, no provider calls, no published stage writes. An existing
    EN track is only *available*, not yet independently synchronized.
    """
    runtime=stage.duration_if_safe(row)
    text,_=cached_source(row,candidate,runtime)
    cues=ff.parse_cues(text)
    last=max(c["end"] for c in cues)/1000
    video=gate.safe_media_path(str(row.get("host_path") or ""))
    embedded=alass._embedded_english(video)
    sidecar=alass._intensive_external_english(video)
    indexed=alass._intensive_jellyfin_english(video,row["jellyfin_id"])
    return {
        "jellyfin_id_prefix":row["jellyfin_id"][:8],
        "movie":str(row.get("title") or "")[:90],
        "year":row.get("year"),
        "provider":candidate["provider"],
        "original_cues":len(cues),
        "original_subtitle_ends_pct":round(100*last/runtime,1),
        "english_embedded":embedded is not None,
        "english_sidecar":sidecar is not None,
        "english_jellyfin_indexed":indexed is not None,
        "cross_reference_available":any(x is not None
                                      for x in (embedded,sidecar,indexed)),
    }


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
        if args.reference_audit:
            print("=== CACHED MOVIE REFERENCE AUDIT (NO ALASS, NO WRITES) ===")
            for row,candidate,receipt in chosen:
                try:
                    report=audit_references(row,candidate)
                    print("REFERENCE_AUDIT:",json.dumps(
                        report,sort_keys=True,ensure_ascii=False),flush=True)
                except (OSError,ValueError,RuntimeError,sqlite3.Error) as exc:
                    print("REFERENCE_AUDIT_HELD:",row["jellyfin_id"][:8],
                          str(row.get("title") or "")[:72],
                          str(exc).split(":",1)[0][:85],flush=True)
            print("END REFERENCE AUDIT: no provider downloads or media writes.")
            return 0
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
    parser.add_argument("--reference-audit",action="store_true",
                        help="read-only audit of actual same-video English references"
                             " and original Japanese subtitle coverage; no ALASS")
    parser.add_argument("--limit",type=int,default=200)
    args=parser.parse_args(argv)
    if args.reference_audit and args.apply:
        parser.error("--reference-audit and --apply are mutually exclusive")
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
