#!/usr/bin/env python3
"""Exhaustive, source-first recovery for one exact Jellyfin item.

Every *saved, identity-matching* JA release is eligible regardless of provider
score. Probe existing stages, fetch and stage other releases in ranked order,
run normal and intensive alignment, and recheck a complete two-provider search.
No PLaMo launch here; a durable exhaustion receipt permits the queue
controller to dispatch PLaMo automatically. Never overwrite video or subtitles.
A quota limit, incomplete search, timeout or system error is NOT exhaustion.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import tempfile
import time

try:
    from . import benchmark_subtitle_search_paths as inventory
    from . import ja_first_stage_saved_batch as stage
    from . import ja_first_stage_subdl as subdl
    from . import ja_first_candidate_progress as rank
except ImportError:
    import benchmark_subtitle_search_paths as inventory
    import ja_first_stage_saved_batch as stage
    import ja_first_stage_subdl as subdl
    import ja_first_candidate_progress as rank

HERE = Path(__file__).resolve().parent
JID = re.compile(r"[a-f0-9]{32}\Z")
REQUIRED_PROVIDERS = frozenset(("opensubtitles", "subdl"))
MAX_SEARCH_AGE = 31 * 86400
MAX_CANDIDATES = 120
RECEIPTS = Path.home() / "bruiser-pilot/ja-first-inventory/source-exhaustion"


def search_record(jid):
    if not stage.SEARCH_DB.is_file() or stage.SEARCH_DB.is_symlink():
        return None
    stage.private_file(stage.SEARCH_DB)
    with sqlite3.connect("file:" + str(stage.SEARCH_DB.resolve()) + "?mode=ro",
                         uri=True, timeout=10) as db:
        row = db.execute(
            "SELECT outcome,results_json,searched_at FROM searches "
            "WHERE jellyfin_id=?", (jid,)).fetchone()
    if not row:
        return None
    try:
        data = json.loads(row[1])
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    data["_outcome"] = str(row[0])
    data["_searched_at"] = int(row[2] or 0)
    return data


def search_complete(document, now=None):
    """Require affirmative participation of both Japanese providers."""
    if not isinstance(document, dict):
        return False
    now = int(time.time()) if now is None else int(now)
    when = document.get("_searched_at")
    if type(when) is not int or when > now or now-when > MAX_SEARCH_AGE:
        return False
    if document.get("_outcome") not in ("none", "plausible", "review"):
        return False
    gates = document.get("provider_gates")
    if (not isinstance(gates, dict) or
            not REQUIRED_PROVIDERS.issubset(gates) or
            any(gates[name] != "ok" for name in REQUIRED_PROVIDERS) or
            document.get("incomplete_providers")):
        return False
    return True


def candidates_for(row, document):
    """Popularity only orders downloads; identity is checked independently."""
    if not isinstance(document, dict):
        return []
    unique = {}
    for candidate in document.get("candidates") or []:
        if not isinstance(candidate, dict):
            continue
        provider = candidate.get("provider")
        if provider == "opensubtitles":
            valid = stage.identity_ok(row, candidate)
        elif provider == "subdl":
            valid = subdl.identity_ok(row, candidate)
        else:
            valid = False
        if valid:
            unique[(provider, str(candidate["subtitle_id"]))] = candidate
    if len(unique) > MAX_CANDIDATES:
        raise RuntimeError("too_many_saved_candidates_for_exhaustion")
    return sorted(unique.values(), key=lambda c: (
        0 if c.get("grade") == "plausible" else 1,
        -rank.release_match(row, c),
        -int(c.get("score") or 0),
        str(c.get("provider")), str(c.get("subtitle_id"))))


def call(args, *, timeout=1200):
    try:
        run = subprocess.run([sys.executable, "-B", "-u", *map(str, args)],
                             stdin=subprocess.DEVNULL, capture_output=True,
                             text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        return 124, "", "operation_timeout"
    return run.returncode, run.stdout[-20000:], run.stderr[-3000:]


def publish(jid, intensive=False):
    cmd = [HERE/"ja_first_publish_queue.py", "--jellyfin-id", jid,
           "--max-titles", "1", "--limit", "1", "--apply"]
    if intensive:
        cmd.append("--intensive-only")
    rc, out, err = call(cmd, timeout=14*3600)
    for line in out.splitlines():
        if not line.startswith("BRUISER_PUBLISH_ITEM:"):
            continue
        try:
            report = json.loads(line.split(":", 1)[1])
        except (TypeError, ValueError):
            continue
        if report.get("jellyfin_id") == jid and report.get("result") in (
                "published", "already_published"):
            print("DEEP_SOURCE_PUBLISHED:",jid,
                  "intensive" if intensive else "normal",flush=True)
            return "covered"
    if (rc or "QUEUE STOPPED:" in err or
            "TITLE_FAILURE_NOT_CACHED:" in out or
            "intensive_alass_unavailable" in out or
            "alass_command_failed" in out):
        # Incomplete engine attempts, transient audio/docker or absent ALASS
        # are not evidence that this Japanese release cannot be recovered.
        print("DEEP_SOURCE_PUBLISH_RETRY:",jid,(err or
              "incomplete_or_transient_alignment")[:160],flush=True)
        return "retry"
    return "held"


def repair_staged(jid):
    """Normal repairs first; intensive ALASS trials only when still held."""
    first = publish(jid)
    if first != "held":
        return first
    return publish(jid, intensive=True)


def stage_one(jid, candidate):
    provider = candidate["provider"]
    sid = str(candidate["subtitle_id"])
    # Initial repair_staged() already attempted all persisted candidate bytes.
    stage_id = sid if provider == "opensubtitles" else subdl.numeric_id(sid)[0]
    if (jid,stage_id) in stage.read_staged() or (
            provider == "opensubtitles" and
            (jid,stage_id) in stage.rejected_duration_candidates()):
        return "rejected", "previously_staged_or_rejected"
    if provider == "opensubtitles":
        # The saved-batch selector already honors deterministic failed-download
        # cache entries. Check the same cache here so an expected zero-selection
        # result is an exhausted RELEASE, not a permanent retry of this title.
        row=stage.read_inventory().get(jid)
        if row is not None and stage.known_rejected_download(row,candidate):
            print("DEEP_SOURCE_STAGE_SKIPPED:",jid,sid,
                  "cached_malformed_download",flush=True)
            return "rejected", "cached_malformed_download"
        cmd = [HERE/"ja_first_stage_saved_batch.py", "--jellyfin-id",jid,
               "--kind","all","--budget","1","--subtitle-id",sid,
               "--exhaustive","--apply"]
        receipt = "STAGED:"
    else:
        cmd = [HERE/"ja_first_stage_subdl.py", "--jellyfin-id",jid,
               "--subtitle-id",sid,"--apply"]
        receipt = "STAGED_SUBDL:"
    rc,out,err = call(cmd,timeout=900)
    if "PROVIDER_LIMIT_REACHED:" in out or "429" in err or "406" in err:
        return "retry", "provider_quota_or_cooldown"
    if rc and "stage" not in out.lower():
        return "retry", "stage_execution_failed"
    if receipt in out:
        return "staged", "saved_release_acquired"
    if ("STAGED_HELD:" in out or
            "REJECTED_DOWNLOAD_SKIPPED:" in out or
            "SAVED_REJECTED_DOWNLOAD:" in out or
            "STAGE_REJECTED:" in out or
            "SUBDL_REJECTED:" in out):
        return "rejected", "invalid_candidate_bytes"
    # An opaque no-stage result is NOT source exhaustion. Emit actual
    # subprocess evidence so the operator can fix the systemic problem;
    # never spin on a generic message with no diagnostic.
    details=[line.strip() for line in (out+"\n"+err).splitlines()
             if any(tag in line for tag in (
                 "Selected:", "SUBDL_SAVED_CANDIDATES:",
                 "STAGING ERROR:", "SUBDL_HELD:", "SUBDL_STAGE_HELD:",
                 "HELD:", "BATCH RESULT:", "No new high-confidence"))]
    summary=" | ".join(details[-3:])[:450] or "no_stage_receipt_or_error"
    print("DEEP_SOURCE_STAGE_UNRESOLVED:",jid,provider,sid,
          "returncode",rc,summary,flush=True)
    return "retry", provider+":stage_unresolved"


def refresh_search(jid):
    cmd=[HERE/"ja_first_search_pilot.py","--jellyfin-id",jid,"--budget","2"]
    rc,out,err=call(cmd,timeout=500)
    print("DEEP_SOURCE_SEARCH:",jid,"rc",rc,flush=True)
    return rc==0 and "ERROR:" not in out and "DEFERRED:" not in out


def staged_fingerprint(jid):
    """Exact staged bytes/status: a newly staged candidate revokes AI proof."""
    if not stage.STAGE_DB.exists():
        return []
    stage.private_file(stage.STAGE_DB)
    with sqlite3.connect("file:"+str(stage.STAGE_DB.resolve())+"?mode=ro",
                         uri=True,timeout=10) as db:
        rows=db.execute(
            "SELECT subtitle_id,sha256,status FROM staged WHERE jellyfin_id=? "
            "ORDER BY subtitle_id",(jid,)).fetchall()
    return [[str(sid),str(sha),str(status)] for sid,sha,status in rows]


def _secure_dir():
    parent=RECEIPTS.parent
    if (not parent.is_dir() or parent.is_symlink() or
            parent.stat().st_mode & 0o077):
        raise RuntimeError("private_source_root_unavailable")
    RECEIPTS.mkdir(mode=0o700,exist_ok=True)
    if RECEIPTS.is_symlink() or RECEIPTS.stat().st_mode & 0o077:
        raise RuntimeError("unsafe_source_receipts_directory")


def save_exhausted(jid,row,doc,attempted):
    """Proof tied to exact file identity and this completed provider result."""
    video=Path(row["host_path"])
    if not video.is_file() or video.is_symlink():
        raise RuntimeError("source_exhaustion_video_missing")
    _secure_dir()
    target=RECEIPTS/(jid+".json")
    if target.is_symlink():
        raise RuntimeError("unsafe_source_receipt")
    st=video.stat()
    payload={"schema":"bruiser-ja-exhaustion-v1","jellyfin_id":jid,
             "video":str(video),"size":st.st_size,"mtime_ns":st.st_mtime_ns,
             "search_sha256":hashlib.sha256(json.dumps(
                 doc,sort_keys=True,ensure_ascii=False).encode()).hexdigest(),
             "candidate_keys":attempted,
             "stage_records":staged_fingerprint(jid),
             "status":"exhausted",
             "recorded_at":int(time.time())}
    fd,tmp=tempfile.mkstemp(prefix=".source-proof-",dir=RECEIPTS)
    try:
        with os.fdopen(fd,"w",encoding="utf-8") as file:
            os.fchmod(file.fileno(),0o600)
            json.dump(payload,file,sort_keys=True,ensure_ascii=False)
            file.flush();os.fsync(file.fileno())
        os.replace(tmp,target)
    finally:
        Path(tmp).unlink(missing_ok=True)
    return target


def validate_exhausted(jid,row):
    """Revalidate the source decision immediately before any PLaMo handoff."""
    if not JID.fullmatch(str(jid or "")) or not row:
        return False
    file=RECEIPTS/(jid+".json")
    if (not file.is_file() or file.is_symlink() or
            file.stat().st_mode & 0o077):
        return False
    data=json.loads(file.read_text("utf-8"))
    video=Path(str(row.get("host_path") or ""))
    if not video.is_file() or video.is_symlink():
        return False
    st=video.stat()
    saved=search_record(jid)
    if not search_complete(saved):
        return False
    checksum=hashlib.sha256(json.dumps(
        saved,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    return (data.get("schema")=="bruiser-ja-exhaustion-v1"
            and data.get("status")=="exhausted"
            and data.get("jellyfin_id")==jid and data.get("video")==str(video)
            and data.get("size")==st.st_size
            and data.get("mtime_ns")==st.st_mtime_ns
            and data.get("search_sha256")==checksum
            and isinstance(data.get("candidate_keys"),list)
            and data["candidate_keys"]==[
                [c["provider"],str(c["subtitle_id"])]
                for c in candidates_for(row,saved)]
            and data.get("stage_records")==staged_fingerprint(jid))


def run(jid):
    manifest=inventory.load_latest_manifest()
    matches=[r for r in manifest if isinstance(r,dict) and
             r.get("jellyfin_id")==jid]
    if len(matches)!=1:
        raise RuntimeError("exact_jellyfin_item_missing_or_ambiguous")
    row=matches[0]
    if row.get("status") in ("existing_japanese_subtitle","japanese_audio"):
        return {"result":"covered","reason":"inventory_covered"}
    video=Path(str(row.get("host_path") or ""))
    if not video.is_file() or video.is_symlink():
        return {"result":"retry_source","reason":"video_not_available"}
    if stage.japanese_sidecar_exists(video):
        return {"result":"covered","reason":"existing_japanese_sidecar"}
    if row.get("status")!="ready_ja_search":
        return {"result":"retry_source","reason":"inventory_not_source_ready"}
    # Never search/download when a previously staged track may already work.
    existing=repair_staged(jid)
    if existing=="covered":
        return {"result":"covered","reason":"existing_stage_repaired"}
    if existing=="retry":
        return {"result":"retry_source","reason":"existing_stage_transient"}
    search=search_record(jid)
    if not search_complete(search):
        refresh_search(jid)
        search=search_record(jid)
    candidates=candidates_for(row,search)
    tried=[]
    for i,candidate in enumerate(candidates,1):
        provider,sid=candidate["provider"],str(candidate["subtitle_id"])
        tried.append([provider,sid])
        print("DEEP_SOURCE_CANDIDATE:",jid,i,len(candidates),
              provider,sid,flush=True)
        status,reason=stage_one(jid,candidate)
        if status=="retry":
            return {"result":"retry_source","reason":reason,
                    "candidates_examined":i}
        if status=="rejected":
            continue
        outcome=repair_staged(jid)
        if outcome=="covered":
            return {"result":"covered","reason":"source_repaired",
                    "candidates_examined":i}
        if outcome=="retry":
            return {"result":"retry_source","reason":"alignment_transient",
                    "candidates_examined":i}
    # Search can be incomplete while useful saved candidates were recovered.
    if not search_complete(search):
        return {"result":"retry_source","reason":"providers_incomplete_or_deferred",
                "candidates_examined":len(tried)}
    # Trust neither errors nor a silently truncated provider candidate page.
    # Broad provider endpoints sometimes show dozens of unrelated hits.
    # If the provider reports more results than we could retain, unseen,
    # lower-ranked real releases may still exist. Never declare them absent.
    reported=int(search.get("provider_total") or 0)
    retained=len(search.get("candidates") or [])+len(
        search.get("rejected_candidates") or [])
    if (len(search.get("candidates") or [])>=120 or
            reported>100 and retained<reported):
        return {"result":"retry_source","reason":"candidate_search_truncated",
                "candidates_examined":len(tried)}
    # A parallel source search or new Japanese track invalidates the final
    # decision. In that case stay in sourcing rather than dispatching AI.
    if stage.japanese_sidecar_exists(video):
        return {"result":"covered","reason":"japanese_arrived_during_recovery"}
    if search_record(jid)!=search:
        return {"result":"retry_source","reason":"provider_search_changed_during_recovery"}
    save_exhausted(jid,row,search,tried)
    return {"result":"plamo","reason":"all_saved_japanese_candidates_failed",
            "candidates_examined":len(tried)}


def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--jellyfin-id",required=True)
    ap.add_argument("--run",action="store_true")
    args=ap.parse_args(argv)
    if not JID.fullmatch(args.jellyfin_id):
        ap.error("invalid Jellyfin item ID")
    if not args.run:
        print("DEEP_SOURCE_PREFLIGHT: requires --run; no writes performed")
        return 0
    try:
        report=run(args.jellyfin_id)
    except (OSError,RuntimeError,ValueError,sqlite3.Error) as exc:
        report={"result":"retry_source",
                "reason":type(exc).__name__+":"+str(exc)[:120]}
    report["jellyfin_id"]=args.jellyfin_id
    print("DEEP_SOURCE_RESULT:",json.dumps(report,sort_keys=True),flush=True)
    return 0


if __name__=="__main__":
    raise SystemExit(main())
