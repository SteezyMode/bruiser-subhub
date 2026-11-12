#!/usr/bin/env python3
"""Read-only batch triage of the saved Japanese candidates never staged.

Uses the existing 191-title finish-job reconstruction, real installed source
identity rules, the saved search/stage DBs and the coverage queue. No network,
provider download, database writes, ALASS, translation or publication.

Classification is a *current staging blocker*, not proof of subtitle quality.
"""
from __future__ import annotations

from collections import Counter
import argparse
import json
from pathlib import Path
import re
import sys
import time

try:
    from . import subhub_source_failure_audit as history
except ImportError:
    import subhub_source_failure_audit as history

HOST=Path.home()/"bruiser-pilot/subhub-control"
JID=re.compile(r"[a-f0-9]{32}\Z")
AGE_LIMIT_HOURS=72


def installed_stagers(*,policy_local=False):
    """Use actual staging modules, installed or pinned in an audit temp dir.

    --policy-local previews an uninstalled policy *without installing it*.
    Dependencies still resolve from the existing installed worker directory.
    """
    if HOST.is_symlink() or not HOST.is_dir():
        raise RuntimeError("installed_source_dir_unavailable")
    if str(HOST) not in sys.path:
        sys.path.insert(0,str(HOST))
    if policy_local:
        local=Path(__file__).resolve().parent
        required=("ja_first_stage_saved_batch.py","ja_first_stage_subdl.py")
        if any(not (local/file).is_file() or
               (local/file).is_symlink() for file in required):
            raise RuntimeError("pinned_local_staging_modules_missing")
        if str(local) in sys.path:
            sys.path.remove(str(local))
        sys.path.insert(0,str(local))
    import ja_first_stage_saved_batch as opensub
    import ja_first_stage_subdl as subdl
    if policy_local and (Path(opensub.__file__).resolve().parent!=
                         Path(__file__).resolve().parent or
                         Path(subdl.__file__).resolve().parent!=
                         Path(__file__).resolve().parent):
        raise RuntimeError("local_identity_policy_not_loaded")
    return opensub,subdl


def saved_manifest_age_hours():
    manifests=sorted(history.ROOT.glob("ja-intake-*.json"))
    if not manifests or manifests[-1].is_symlink():
        raise RuntimeError("saved_manifest_missing")
    return round(max(0,time.time()-manifests[-1].stat().st_mtime)/3600,1)


def evaluate_candidates(row,candidates,opensub,subdl,stage_records):
    """Categorize each saved provider result, with no downloads or writes."""
    seen=set()
    accepted=[]
    excluded=Counter()
    illustrations=[]
    saved_ids={(str(item.get("subtitle_id")),str(item.get("provider")))
               for item in stage_records}
    for cand in candidates:
        if not isinstance(cand,dict):
            excluded["invalid_saved_result"]+=1
            continue
        provider=str(cand.get("provider") or "unknown")
        sid=str(cand.get("subtitle_id") or "")
        if (provider,sid) in seen:
            excluded["duplicate_provider_result"]+=1
            continue
        seen.add((provider,sid))
        if provider=="opensubtitles":
            suitable=opensub.identity_ok(row,cand)
            if suitable:
                try:
                    failed_download=opensub.known_rejected_download(row,cand)
                except (OSError,RuntimeError,ValueError) as exc:
                    # A cache inspection failure is NOT evidence of an eligible
                    # provider download. Keep the item in manual review.
                    excluded["cached_rejection_check_unavailable"]+=1
                    illustrations.append({
                        "provider":provider,"sid":sid[:70],
                        "reason":type(exc).__name__+":"+str(exc)[:85]})
                    continue
            else:
                failed_download=False
        elif provider=="subdl":
            suitable=subdl.identity_ok(row,cand)
            failed_download=False
        else:
            excluded["provider_not_supported_by_stage"]+=1
            illustrations.append({
                "provider":provider,"sid":sid[:70],
                "reason":"unsupported_stage_transport"})
            continue
        if not suitable:
            excluded["stage_identity_not_established"]+=1
            illustrations.append({
                "provider":provider,"sid":sid[:70],
                "reason":"saved_search_hit_not_stage_identity",
                "release":str(cand.get("filename") or
                              cand.get("release_info") or "")[:130]})
            continue
        if failed_download:
            excluded["previously_downloaded_bytes_rejected"]+=1
            continue
        stage_id=(sid if provider=="opensubtitles" else
                  subdl.numeric_id(sid)[0])
        if any(str(item["subtitle_id"])==stage_id for item in stage_records):
            excluded["saved_release_already_staged"]+=1
            continue
        accepted.append({
            "provider":provider,"subtitle_id":sid,
            "stage_id":stage_id,
            "grade":str(cand.get("grade") or "?"),
            "score":cand.get("score"),
            "release":str(cand.get("filename") or
                          cand.get("release_info") or "")[:145]})
    return accepted,excluded,illustrations[:6]


def current_status(row,selected,stage_rows,opensub,queue,inventory_old):
    """Exactly one high-level reason; preserve lower-level clues separately."""
    if not row:
        return "catalog_identity_missing","not_in_latest_manifest"
    if str(row.get("status") or "") in (
            "japanese_audio","existing_japanese_subtitle"):
        return "already_covered_in_inventory","catalog_covered"
    if str(row.get("status") or "")!="ready_ja_search":
        return "catalog_no_longer_source_ready","status:"+str(row.get("status"))
    video=Path(str(row.get("host_path") or ""))
    if not video.is_absolute() or video.is_symlink() or not video.is_file():
        return "media_unavailable","video_path_missing_or_unreadable"
    if stage_rows:
        return "staging_progress_changed","stage_record_now_present"
    try:
        if opensub.japanese_sidecar_exists(video):
            return "already_covered_by_sidecar","local_ja_sidecar_present"
    except OSError as exc:
        return "media_preflight_failed","directory_unreadable:"+type(exc).__name__
    if not selected:
        return "no_stageable_saved_candidate","all_saved_candidates_filtered"
    try:
        # Same gate as the real generic staging selector (read-only).
        queue_pos=opensub.priorities.queue_position(row,"stage",queue)
    except (ValueError,RuntimeError,KeyError) as exc:
        return "queue_gate_unavailable",str(exc)[:100]
    if queue_pos is None:
        return "coverage_queue_not_selectable","inactive_or_path_action_mismatch"
    try:
        if not opensub.alternate_ready(row):
            return "prior_staged_alignment_pending","do_not_duplicate_download"
    except (OSError,RuntimeError,ValueError) as exc:
        return "stage_state_check_failed",type(exc).__name__+":"+str(exc)[:90]
    try:
        # This is ffprobe/metadata only. It never touches the provider.
        opensub.duration_if_safe(row)
    except (OSError,RuntimeError,ValueError) as exc:
        return "media_preflight_failed",type(exc).__name__+":"+str(exc)[:110]
    sources={c["provider"] for c in selected}
    if sources=={"subdl"}:
        return "stageable_subdl_separate_route","not_selected_by_opensubtitles_batch"
    if sources=={"opensubtitles"}:
        return "stageable_opensubtitles","saved_provider_release_can_be_staged"
    return "stageable_both_providers","candidate_routes_both_available"


def audit_saved_unstaged(*,limit=100,full=False,policy_local=False):
    state=history.read_json(history.STATE)
    latest=history.manifest()
    search=history.searches()
    stages=history.stages()
    report=history.analyze(
        state,latest,search,stages,history.journal_events(state))
    cohort=[x for x in report["items"]
            if x["reason"]=="japanese_candidates_found_not_staged"]
    opensub,subdl=installed_stagers(policy_local=policy_local)
    queue=opensub.priorities.active_coverage_queue()
    age=saved_manifest_age_hours()
    print("=== SAVED JAPANESE CANDIDATES NOT STAGED: READ-ONLY TRIAGE ===")
    print("Historical PLaMO pending reconstructed:",
          report["plamo_ids_reconstructed"],"/",
          report["recorded_plamo_pending"],
          "| journal_complete:",report["journal_complete_for_queue"])
    print("Saved search classified as plausible but unstaged:",
          len(cohort),"| manifest_age_hours:",age,
          "| safe_stage_manifest_age_limit_hours:",AGE_LIMIT_HOURS)
    if not report["journal_complete_for_queue"]:
        print("WARNING: incomplete journal. These are observed cases only; "
              "do not claim entire historical cohort has been reconstructed.")
    if age>AGE_LIMIT_HOURS:
        print("WARNING: generic staging currently rejects the stale manifest "
              "until it is refreshed, regardless of per-title identity.")
    print("Staging identity policy:",
          "PINNED LOCAL PREVIEW (NOT INSTALLED)" if policy_local else
          "CURRENTLY INSTALLED WORKER")
    print("Actual OpenSubtitles and SubDL identity rules used.")
    results=[]
    for item in cohort[:limit]:
        jid=item["jellyfin_id"]
        row=latest.get(jid)
        rec=search.get(jid,{})
        candidates=[c for c in (rec.get("results") or {}).get("candidates",[])
                    if isinstance(c,dict)]
        staged=stages.get(jid,[])
        if row:
            usable,excluded,examples=evaluate_candidates(
                row,candidates,opensub,subdl,staged)
        else:
            usable,excluded,examples=[],Counter(),[]
        status,detail=current_status(row,usable,staged,opensub,queue,item)
        titlestr=item["title"]+(f' ({item["year"]})' if item["year"] else "")
        result={"jid":jid,"title":titlestr,"reason":status,"detail":detail,
                "candidate_count":len(candidates),
                "stageable":usable,"excluded":dict(excluded),
                "examples":examples,
                "queue":None if queue is None else
                         list(queue.get(jid,("not_in_queue",))),
                "existing_stage_count":len(staged)}
        results.append(result)
    groups=Counter(row["reason"] for row in results)
    print("\nCURRENT GATE CLASSIFICATION (not a publication verdict):")
    for key,n in groups.most_common():
        print(f"  {n:3} {key}")
    totals=Counter()
    for item in results:
        totals.update(item["excluded"])
    print("\nSAVED CANDIDATE FILTER REASONS:")
    for key,n in totals.most_common():
        print(f"  {n:3} {key}")
    print("\nALL TRIAGED TITLES:")
    for row in results:
        print(f'  {row["title"]} [{row["jid"]}] '
              f'saved={row["candidate_count"]} '
              f'eligible={len(row["stageable"])} '
              f'gate={row["reason"]} detail={row["detail"]}')
        for cand in row["stageable"][:4]:
            print(f'    ELIGIBLE {cand["provider"]}:{cand["subtitle_id"]} '
                  f'grade={cand["grade"]} name={cand["release"]}')
        if full:
            for ex in row["examples"][:6]:
                print("    REJECTED:",json.dumps(ex,ensure_ascii=False))
            if row["queue"]:
                print("    QUEUE:",json.dumps(row["queue"],ensure_ascii=False))
            if row["excluded"]:
                print("    FILTERS:",json.dumps(row["excluded"],ensure_ascii=False))
    print("\nNothing downloaded, staged, translated or published. "
          "Read-only saved inventory/search DB, queue, media metadata.")
    print("Identity-eligible means worth trying acquisition; it is NOT proof "
          "that the Japanese subtitle matches the exact video.")
    return results


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--full",action="store_true",
                    help="show individual identity rejects, queue state")
    ap.add_argument("--policy-local",action="store_true",
                    help="preview downloaded staging modules alongside this script; "
                         "never installs or modifies host source")
    ap.add_argument("--limit",type=int,default=100,
                    help="maximum historical cohort titles to inspect (1..1000)")
    opts=ap.parse_args()
    if not 1<=opts.limit<=1000:
        ap.error("--limit must be 1..1000")
    audit_saved_unstaged(limit=opts.limit,full=opts.full,
                         policy_local=opts.policy_local)


if __name__=="__main__":
    main()
