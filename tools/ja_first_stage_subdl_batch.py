#!/usr/bin/env python3
"""Bounded, general-purpose SubDL staging from the existing Japanese search DB.

Used by the standard source cycle after OpenSubtitles staging. SubDL has its
own allowance: an OpenSubtitles cooldown does not block SubDL ZIP recovery.
No live provider searches, translation, subtitle replacement or media writes.
The normal ALASS/ffsubsync publisher is still the only publication path.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import re
from urllib.error import HTTPError
import zipfile

try:
    from . import ja_first_stage_saved_batch as stage
    from . import ja_first_stage_subdl as subdl
except ImportError:
    import ja_first_stage_saved_batch as stage
    import ja_first_stage_subdl as subdl

MAX_ATTEMPTS=200


def select(inventory, searches, already, budget, scope="all", skipped=None):
    """One saved release per uncovered title, with the normal backlog priority."""
    if not 1<=budget<=MAX_ATTEMPTS:
        raise ValueError("subdl_stage_budget_out_of_range")
    active=stage.priorities.active_coverage_queue()
    already=set(already)|stage.rejected_duration_candidates()
    eligible=[]
    for jid, raw in searches:
        jid=str(jid)
        row=inventory.get(jid)
        if (not isinstance(row,dict) or row.get("status")!="ready_ja_search"
                or row.get("kind") not in ("Movie","Episode")
                or not stage.movie_scope.matches(row,scope)):
            continue
        priority=stage.priorities.queue_position(row,"stage",active)
        if priority is None:
            continue
        try:
            history=json.loads(raw)
        except (ValueError,TypeError):
            continue
        if not isinstance(history,dict):
            continue
        candidates=[]
        for candidate in history.get("candidates") or []:
            if not subdl.identity_ok(row,candidate):
                continue
            sid,_=subdl.numeric_id(str(candidate["subtitle_id"]))
            if (jid,sid) in already:
                continue
            # A cached ZIP already proven malformed with the SAME parser
            # version is not another useful attempt in a broad batch.
            if subdl.known_rejected_cached(row,candidate):
                if skipped is not None:
                    skipped["unchanged_bad_cached_zip"]+=1
                continue
            candidates.append(candidate)
        if not candidates:
            continue
        video=Path(str(row.get("host_path") or ""))
        # Never spend an allowance for a title covered since the last intake.
        if (video.is_file() and not video.is_symlink()
                and stage.japanese_sidecar_exists(video)):
            continue
        # Do not stage a second release before testing the first; a persisted
        # final alignment hold unlocks the alternate on a later source cycle.
        if not stage.alternate_ready(row):
            continue
        candidates.sort(key=lambda item:(
            -stage.candidate_progress.release_match(row,item),
            -int(item.get("score") or 0),
            str(item["subtitle_id"])))
        chosen=candidates[0]
        eligible.append((priority,str(row.get("title") or
                    row.get("series_title") or jid).casefold(),jid,row,chosen))
    eligible.sort(key=lambda entry:(entry[0],entry[1],entry[2]))
    return [(row,candidate) for _,_,_,row,candidate in eligible[:budget]]


def hold_code(error):
    """Stable, bounded category, retaining the actual archive validation gate."""
    parts=str(error).split(":",2)
    first=parts[0]
    if not re.fullmatch(r"[a-zA-Z0-9_]{1,90}",first):
        return type(error).__name__
    if first=="subdl_archive_srt_rejected" and len(parts)>1:
        secondary=parts[1].split(",",1)[0]
        if re.fullmatch(r"[a-zA-Z0-9_]{1,90}",secondary):
            return first+":"+secondary
    return first


def audit_cached(*,scope="all",limit=250):
    """Read-only full-library cached SubDL suitability report.

    Never calls cached_archive/download() and never records failures. A
    structurally acceptable SRT still needs trusted video synchronization
    and create-only publication; this is NOT a subtitle success percentage.
    """
    inventory=stage.read_inventory()
    searches=stage.read_saved_searches()
    totals=Counter()
    sample=defaultdict(list)
    checked=0
    duration_cache={}
    print("=== FULL-LIBRARY CACHED SUBDL AUDIT (READ ONLY) ===",flush=True)
    print("Scope:",scope,"| max inspected cached ZIPs:",limit,flush=True)
    for jid,raw in searches:
        row=inventory.get(str(jid))
        if not isinstance(row,dict) or row.get("kind") not in ("Movie","Episode"):
            continue
        if not stage.movie_scope.matches(row,scope):
            continue
        if row.get("status")!="ready_ja_search":
            continue
        try:
            doc=json.loads(raw)
        except (ValueError,TypeError):
            totals["search_history_unreadable"]+=1
            continue
        if not isinstance(doc,dict):
            continue
        for candidate in doc.get("candidates") or []:
            if not subdl.identity_ok(row,candidate):
                continue
            totals["saved_identity_verified_releases"]+=1
            archive=subdl.cached_zip_path(candidate)
            if not archive.exists() and not archive.is_symlink():
                totals["not_cached_no_download"]+=1
                continue
            totals["cached_releases_found"]+=1
            if checked>=limit:
                totals["cached_not_inspected_limit"]+=1
                continue
            checked+=1
            try:
                if (archive.is_symlink() or not archive.is_file()
                        or archive.stat().st_mode&0o077
                        or not 0<archive.stat().st_size<=subdl.MAX_ARCHIVE):
                    raise RuntimeError("unsafe_cached_zip")
                video=Path(str(row.get("host_path") or ""))
                if video.is_file() and not video.is_symlink() and stage.japanese_sidecar_exists(video):
                    reason="already_covered_not_inspected"
                else:
                    if jid not in duration_cache:
                        try:
                            duration_cache[jid]=stage.duration_if_safe(row)
                        except (RuntimeError,OSError,ValueError) as exc:
                            duration_cache[jid]=exc
                    runtime=duration_cache[jid]
                    if isinstance(runtime,Exception):
                        raise runtime
                    subdl.archive_srt(archive.read_bytes(),row,candidate,runtime)
                    reason="content_valid_sync_not_checked"
            except (RuntimeError,OSError,ValueError,zipfile.BadZipFile) as exc:
                reason=hold_code(exc)
            totals[reason]+=1
            if len(sample[reason])<4:
                sample[reason].append(str(row.get("title") or row.get("series_title") or jid)[:75])
    print("Cached ZIPs actually inspected:",checked,flush=True)
    for reason,num in sorted(totals.items()):
        print("AUDIT:",reason,"=",num,flush=True)
        if reason in sample:
            print("  sample:",sample[reason],flush=True)
    print("Do not use these content results as publication or playback success rate.",flush=True)
    print("ZERO PROVIDER CALLS, ZERO FILES OR DB CHANGED.",flush=True)
    return dict(totals)


def run(*,budget=20,scope="all",apply=False):
    inventory=stage.read_inventory()
    searches=stage.read_saved_searches()
    already=stage.read_staged()
    skipped=Counter()
    chosen=select(inventory,searches,already,budget,scope,skipped)
    print("=== SUBDL SAVED JAPANESE STAGING BATCH ===",flush=True)
    print("Saved searches:",len(searches),"| candidates:",len(chosen),
          "| attempt budget:",budget,"| scope:",scope,
          "| mode:","APPLY" if apply else "READ ONLY",flush=True)
    print("SUBDL_KNOWN_BAD_ZIPS_SKIPPED:",
          skipped["unchanged_bad_cached_zip"],flush=True)
    if not apply:
        print("No provider GET, private stage, or media write.",flush=True)
        return {}
    counts=Counter()
    reasons=Counter()
    for index,(row,candidate) in enumerate(chosen,1):
        label=str(row.get("title") or row.get("series_title") or
                  row["jellyfin_id"])[:100]
        print(f"[{index}/{len(chosen)}] SUBDL STAGING: {label}",flush=True)
        try:
            duration=stage.duration_if_safe(row)
            subdl.stage_one(row,candidate,duration)
            counts["staged_or_cached"]+=1
        except HTTPError as exc:
            if exc.code in (406,429):
                counts["provider_limited"]+=1
                print("SUBDL_PROVIDER_LIMIT_REACHED: HTTP_"+str(exc.code),
                      "| saved stages retained",flush=True)
                break
            counts["held"]+=1
            reasons["HTTP_"+str(exc.code)]+=1
            print("SUBDL_HELD: HTTP_"+str(exc.code),flush=True)
        except (RuntimeError,OSError,ValueError,zipfile.BadZipFile) as exc:
            counts["held"]+=1
            reason=hold_code(exc)
            reasons[reason]+=1
            print("SUBDL_HELD:",reason,flush=True)
    print("SUBDL_BATCH_RESULT:",dict(counts),flush=True)
    print("SUBDL_HOLD_REASONS:",dict(sorted(reasons.items())),flush=True)
    print("PRIVATE STAGING ONLY: published media unchanged.",flush=True)
    return dict(counts)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--budget",type=int,default=20)
    parser.add_argument("--scope",choices=stage.movie_scope.SCOPES,default="all")
    parser.add_argument("--apply",action="store_true")
    parser.add_argument("--audit-cached",action="store_true",
                        help="inspect cached SubDL ZIPs across the selected library scope, no download or write")
    parser.add_argument("--audit-limit",type=int,default=250,
                        help="maximum cached ZIP releases to inspect (1..2000)")
    args=parser.parse_args()
    if args.audit_cached:
        if args.apply:
            parser.error("--audit-cached is read-only; cannot combine with --apply")
        if not 1<=args.audit_limit<=2000:
            parser.error("--audit-limit must be 1..2000")
        audit_cached(scope=args.scope,limit=args.audit_limit)
        return
    if not 1<=args.budget<=MAX_ATTEMPTS:
        parser.error("--budget must be 1..200")
    run(budget=args.budget,scope=args.scope,apply=args.apply)


if __name__=="__main__":
    main()
