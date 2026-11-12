#!/usr/bin/env python3
"""Source-only re-pass of the EXACT saved Finish/PLaMO queued media cohort.

The default is READ-ONLY: reconstruct the owner’s stopped Finish batch from
journal and saved inventory, report now-covered / staged / identity-eligible /
unresolved counts. --apply does a bounded sequential publisher+saved-provider
staging pass. NEVER runs PLaMO, marks source exhaustion, searches providers or
restarts the stopped Finish job. Resumable: sidecars and staged/rejected
provider IDs are re-checked at every title.

The only publishing action delegates to the normal exact-item SubHub publisher
with its existing no-clobber, text/clock-preservation and audio QA gates.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import re
import subprocess
import sys

try:
    from . import subhub_source_failure_audit as history
    from . import ja_first_stage_saved_batch as stage
    from . import ja_first_stage_subdl as subdl
    from . import ja_first_candidate_progress as ranking
except ImportError:
    import subhub_source_failure_audit as history
    import ja_first_stage_saved_batch as stage
    import ja_first_stage_subdl as subdl
    import ja_first_candidate_progress as ranking

HERE=Path(__file__).resolve().parent
JID=re.compile(r"[a-f0-9]{32}\Z")
MAX_SOURCE_ATTEMPTS=100
MAX_PUBLISH_ATTEMPTS=300
SHOW_PREFIXES=(
    "EXACT_JELLYFIN_ITEM_FILTER:","MEDIA:","ALASS_REFERENCE_",
    "  ALASS:","  ALASS HELD:","  FFSUBSYNC HELD:",
    "STAGED:","STAGED_HELD:","STAGED_SUBDL:",
    "BATCH RESULT:","SUBDL_REJECTED:","SUBDL_HELD:",
    "SUBDL_ARCHIVE_CACHE:","HELD:","RESULT:",
    "BRUISER_PUBLISH_ITEM:","QUEUE SUMMARY:",
    "PROVIDER_LIMIT_REACHED:","REJECTED_DOWNLOAD_SKIPPED:",
)


def historical_cohort():
    state=history.read_json(history.STATE)
    inventory=history.manifest()
    searches=history.searches()
    stages=history.stages()
    report=history.analyze(
        state,inventory,searches,stages,history.journal_events(state))
    if not report["journal_complete_for_queue"]:
        raise RuntimeError("historical_plamo_cohort_incomplete_no_batch_launch")
    ids=[item["jellyfin_id"] for item in report["items"]]
    if len(ids)!=len(set(ids)) or any(not JID.fullmatch(jid) for jid in ids):
        raise RuntimeError("historical_plamo_ids_invalid")
    return report,inventory,searches,stages


def eligible_saved(row,doc,staged_ids,held_ids,
                   *,opensub=stage,subdl_adapter=subdl):
    """Only proven same-media provider identities can cause a download."""
    accepted={}
    candidates=(doc.get("results") or {}).get("candidates") or []
    for c in candidates:
        if not isinstance(c,dict):
            continue
        provider=str(c.get("provider") or "")
        remote=str(c.get("subtitle_id") or "")
        if provider=="opensubtitles":
            valid=opensub.identity_ok(row,c)
            sid=remote
        elif provider=="subdl":
            valid=subdl_adapter.identity_ok(row,c)
            sid=subdl_adapter.numeric_id(remote)[0] if valid else ""
        else:
            continue
        if not valid or (row["jellyfin_id"],sid) in (
                set(staged_ids)|set(held_ids)):
            continue
        if provider=="opensubtitles" and opensub.known_rejected_download(row,c):
            continue
        key=(provider,remote)
        accepted[key]=c
    return sorted(accepted.values(),key=lambda c:(
        0 if c.get("grade")=="plausible" else 1,
        -ranking.release_match(row,c),
        -int(c.get("score") or 0),
        str(c.get("provider")),str(c.get("subtitle_id"))))


def _command(args):
    """Visible sequential host execution; no shell, background, or PLaMO."""
    command=[sys.executable,"-B","-u",*map(str,args)]
    child=subprocess.Popen(command,stdin=subprocess.DEVNULL,
                           stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                           text=True,bufsize=1)
    found=[]
    limited=False
    for line in child.stdout:
        line=line.rstrip()
        if line.startswith(SHOW_PREFIXES):
            print("  "+line[:350],flush=True)
        if line.startswith("BRUISER_PUBLISH_ITEM:"):
            try:
                found.append(json.loads(line.split(":",1)[1]))
            except (ValueError,TypeError):
                pass
        if ("PROVIDER_LIMIT_REACHED:" in line or
                "HTTP_429" in line or "quota_blocked" in line or
                "cooling_or_exhausted" in line):
            limited=True
    rc=child.wait()
    return rc,found,limited


def _publisher(jid):
    rc,events,_=_command([
        HERE/"ja_first_publish_queue.py","--jellyfin-id",jid,
        "--max-titles","1","--limit","1","--apply"])
    if rc:
        return "retry"
    if any(x.get("jellyfin_id")==jid and
           x.get("result") in ("published","already_published")
           for x in events):
        return "covered"
    return "held"


def _acquire(jid,candidate):
    provider=str(candidate["provider"])
    sid=str(candidate["subtitle_id"])
    if provider=="opensubtitles":
        cmd=[HERE/"ja_first_stage_saved_batch.py",
             "--jellyfin-id",jid,"--subtitle-id",sid,
             "--kind","all","--budget","1","--exhaustive","--apply"]
    elif provider=="subdl":
        cmd=[HERE/"ja_first_stage_subdl.py",
             "--jellyfin-id",jid,"--subtitle-id",sid,"--apply"]
    else:
        raise RuntimeError("unsupported_acquisition_provider")
    rc,_,limited=_command(cmd)
    return rc,limited


def _safe_apply():
    # Mirror the real installer owner-idle policy. A wrong unit name here
    # would leave two writers competing for provider quota and stage files.
    try:
        from . import install_global_ja_sourcing as installer
    except ImportError:
        import install_global_ja_sourcing as installer
    for name in installer.BUSY_UNITS:
        result=subprocess.run(["systemctl","--user","is-active",name],
                              capture_output=True,text=True,timeout=12)
        if result.stdout.strip() in ("active","activating","reloading"):
            raise RuntimeError("existing_subhub_source_worker_active:"+name)
        if result.returncode not in (0,3,4):
            raise RuntimeError("worker_idle_check_inconclusive:"+name)


def repass(*,apply=False,stage_budget=12,publish_attempt_budget=40):
    report,inventory,searches,historical_stages=historical_cohort()
    if apply:
        _safe_apply()
    ids=[item["jellyfin_id"] for item in report["items"]]
    # Start with saved stages to maximize recovery without provider GETs.
    ids.sort(key=lambda jid:(
        -any(x.get("status")=="staged"
             for x in historical_stages.get(jid,[])),
        str(inventory.get(jid,{}).get("title") or "").casefold(),jid))
    print("=== SOURCE-ONLY RE-PASS OF HISTORICAL PLaMO QUEUE ===",flush=True)
    print("HISTORICAL COHORT:",len(ids),"of",
          report["recorded_plamo_pending"],
          "| complete_journal:",report["journal_complete_for_queue"],
          "| mode:","BOUNDED APPLY" if apply else "READ ONLY",
          "| stage_attempt_budget:",stage_budget,
          "| alignment_attempt_budget:",publish_attempt_budget,flush=True)
    print("NO PLaMO. NO live provider searches. NO source-exhaustion receipts.",
          flush=True)
    counts=Counter()
    attempted_stage=0
    attempted_publish=0
    provider_limits=set()
    known_staged=stage.read_staged()
    held=stage.rejected_duration_candidates()
    for i,jid in enumerate(ids,1):
        row=inventory.get(jid)
        if not row:
            counts["missing_catalog_item"]+=1
            continue
        video=Path(str(row.get("host_path") or ""))
        if (row.get("status") in ("existing_japanese_subtitle","japanese_audio")
                or (video.is_file() and not video.is_symlink()
                    and stage.japanese_sidecar_exists(video))):
            counts["already_covered"]+=1
            continue
        if (row.get("status")!="ready_ja_search" or not video.is_file()
                or video.is_symlink()):
            counts["not_source_ready_or_missing_media"]+=1
            continue
        active=any(x[0]==jid for x in known_staged)
        candidates=eligible_saved(row,searches.get(jid,{}) or {},
                                  known_staged,held)
        print(f"REPASS_PROGRESS: {i}/{len(ids)} | {str(row.get('title') or jid)[:75]} "
              f"| existing_stage={int(active)} saved_stageable={len(candidates)}",
              flush=True)
        counts["uncovered_examined"]+=1
        if not apply:
            counts["has_staged_candidate" if active else
                   "has_stageable_saved_release" if candidates else
                   "no_stageable_saved_release"]+=1
            continue
        # First exhaust known staged bytes through the proven alignment gate.
        if active and attempted_publish<publish_attempt_budget:
            attempted_publish+=1
            if _publisher(jid)=="covered":
                counts["published_or_existing"]+=1
                continue
        if not candidates:
            counts["no_alternate_saved_release"]+=1
            continue
        # A provider's cooldown must not block the other provider. SubDL
        # and OpenSubtitles have independent quotas and stage transports.
        available=[c for c in candidates
                   if c["provider"] not in provider_limits]
        if attempted_stage>=stage_budget or not available:
            counts["candidate_deferred_by_budget_or_quota"]+=1
            continue
        # One ranked saved release per title in a pass. Alternate releases
        # remain saved for the next pass after timing/QA outcome is known.
        chosen=available[0]
        attempted_stage+=1
        rc,limited=_acquire(jid,chosen)
        if limited:
            provider_limits.add(str(chosen["provider"]))
            counts["provider_cooldown_or_quota"]+=1
            continue
        if rc:
            counts["staging_command_failure"]+=1
            continue
        before=known_staged
        known_staged=stage.read_staged()
        held=stage.rejected_duration_candidates()
        if not any(x[0]==jid for x in known_staged):
            counts["stage_failed_or_duration_held"]+=1
            continue
        # Stage found: run real publisher with no trust bypass.
        if attempted_publish<publish_attempt_budget:
            attempted_publish+=1
            if _publisher(jid)=="covered":
                counts["published_or_existing"]+=1
            else:
                counts["aligned_candidate_held"]+=1
        else:
            counts["staged_waiting_for_alignment_budget"]+=1
    print("=== HISTORICAL PLaMO RE-PASS SUMMARY ===",flush=True)
    print("HISTORICAL_JOURNAL_COUNT:",len(ids),
          "| STAGE_ATTEMPTS:",attempted_stage,
          "| ALIGNMENT_ATTEMPTS:",attempted_publish,
          "| PROVIDER_LIMITS:",",".join(sorted(provider_limits)) or "none",flush=True)
    print("RESULT_COUNTS:",json.dumps(dict(sorted(counts.items())),
                                      sort_keys=True),flush=True)
    print("PLaMO NOT RUN. Stopped Finish job NOT RESTARTED.",flush=True)
    if not apply:
        print("READ ONLY: no downloads, alignment publication or state writes.",
              flush=True)
    else:
        print("APPLY: source staging and strict create-only publisher only; "
              "historical Finish state preserved.",flush=True)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply",action="store_true",
                    help="bounded owner-approved staging and create-only publication")
    ap.add_argument("--stage-budget",type=int,default=12)
    ap.add_argument("--publish-attempt-budget",type=int,default=40)
    opts=ap.parse_args()
    if not 0<=opts.stage_budget<=MAX_SOURCE_ATTEMPTS:
        ap.error("stage-budget must be 0..100")
    if not 0<=opts.publish_attempt_budget<=MAX_PUBLISH_ATTEMPTS:
        ap.error("publish-attempt-budget must be 0..300")
    repass(apply=opts.apply,stage_budget=opts.stage_budget,
           publish_attempt_budget=opts.publish_attempt_budget)


if __name__=="__main__":
    main()
