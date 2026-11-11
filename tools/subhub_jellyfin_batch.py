#!/usr/bin/env python3
"""Reusable owner-initiated Jellyfin Japanese sourcing batch (movies and TV).

Existing Jellyfin library/catalog, existing private staging, existing ALASS /
ffsubsync publisher. NO direct Jellyfin subtitle POST, no translation, no
overwrite. Runs as its own systemd user service, not in the browser.

--series TITLE (optionally --season N and/or --pick SxxExxx) or --movie-id ID.
Per-run cap (default 20 remote searches, max 200) and restartable private JSON
progress. A paced/failed provider PAUSES the job, never silently declares a
missing subtitle or consumes the rest of the catalog.
"""
from __future__ import annotations

import argparse
from collections import Counter
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import signal
import subprocess
import sys
import tempfile
import time

try:
    from . import benchmark_subtitle_search_paths as benchmark
    from . import ja_first_stage_saved_batch as stage
    from . import ja_first_autofill as autofill
except ImportError:
    import benchmark_subtitle_search_paths as benchmark
    import ja_first_stage_saved_batch as stage
    import ja_first_autofill as autofill

SOURCE_DIR = Path(__file__).resolve().parent
STATE = Path.home() / "bruiser-pilot/ja-first-inventory/jellyfin-source-batch.json"
JID = re.compile(r"[0-9a-f]{32}\Z", re.I)
EP = re.compile(r"S(\d{2})E(\d{2,3})\Z", re.I)
MAX_ITEMS = 500
MAX_SEARCHES = 200
COOLDOWN_SEC = 20 * 3600
SEARCH_STRATEGY = "jellyfin-all-providers-plus-sublarr-title-episode-v2"
STOP = False


def stop_requested(signum, frame):
    global STOP
    STOP = True


def item_label(row):
    if row["kind"] == "Episode":
        return (f'S{row["season"]:02d}E{row["episode"]:02d} '
                + str(row.get("title") or "")[:115])
    return str(row.get("title") or "")[:120]


def choose(rows, *, series=None, seasons=(), picks=(), movie_ids=()):
    """The real Jellyfin inventory, not filesystem title searches."""
    if bool(series) == bool(movie_ids):
        raise ValueError("select_exactly_one_series_or_movie_selection")
    selected = []
    if series:
        if not isinstance(series, str) or not (1 <= len(series) <= 160):
            raise ValueError("invalid_series")
        wanted_seasons = set(seasons)
        wanted_picks = set(picks)
        if any(type(n) is not int or not 1 <= n <= 99 for n in wanted_seasons):
            raise ValueError("invalid_seasons")
        if any((type(s) is not int or type(e) is not int or
                not 1 <= s <= 99 or not 1 <= e <= 999) for s,e in wanted_picks):
            raise ValueError("invalid_episode_selection")
        for row in rows:
            if not isinstance(row, dict) or row.get("kind") != "Episode":
                continue
            if row.get("series_title") != series:
                continue
            if wanted_picks and (row.get("season"),row.get("episode")) not in wanted_picks:
                continue
            if wanted_seasons and row.get("season") not in wanted_seasons:
                continue
            selected.append(row)
        if not selected:
            raise ValueError("series_or_episode_selection_not_in_Jellyfin_catalog")
        if wanted_picks - {(r["season"],r["episode"]) for r in selected}:
            raise ValueError("selected_episode_missing_from_Jellyfin_catalog")
    else:
        ids = set(movie_ids)
        if len(ids) != len(movie_ids) or any(
                not isinstance(j,str) or not JID.fullmatch(j) for j in ids):
            raise ValueError("invalid_movie_ids")
        selected = [r for r in rows if isinstance(r,dict) and
                    r.get("kind")=="Movie" and r.get("jellyfin_id") in ids]
        if len(selected) != len(ids):
            raise ValueError("movie_selection_not_in_Jellyfin_catalog")

    if len(selected) > MAX_ITEMS:
        raise ValueError("selection_too_large_split_into_batches")
    seen = set()
    result = []
    for row in sorted(selected,key=lambda r: (
            int(r.get("season") or 0),int(r.get("episode") or 0),
            str(r.get("title") or ""),str(r.get("jellyfin_id") or ""))):
        jid = row.get("jellyfin_id")
        if not isinstance(jid,str) or not JID.fullmatch(jid) or jid in seen:
            raise ValueError("duplicate_or_invalid_Jellyfin_identity")
        seen.add(jid)
        # The current manifest is authoritative for eligibility, but published
        # sidecars are rechecked on disk again immediately before provider use.
        if row.get("status") == "ready_ja_search":
            result.append(row)
    return result


def selector(series=None,seasons=(),picks=(),movie_ids=()):
    if series:
        return {"series":series,"seasons":sorted(set(seasons)),
                "picks":[[a,b] for a,b in sorted(set(picks))]}
    return {"movie_ids":sorted(movie_ids)}


def _safe_state_root(path):
    folder = path.parent
    if (not folder.is_dir() or folder.is_symlink()
            or folder.stat().st_mode & 0o077):
        raise RuntimeError("private_inventory_directory_unsafe")
    if path.is_symlink() or (path.exists() and
            (not path.is_file() or path.stat().st_mode & 0o077)):
        raise RuntimeError("private_batch_state_unsafe")


def read_state(path=None):
    path=path or STATE
    _safe_state_root(path)
    if not path.is_file():
        return None
    raw=path.read_bytes()
    if len(raw)>500_000:
        raise RuntimeError("private_job_state_oversize")
    data=json.loads(raw)
    if not isinstance(data,dict) or data.get("schema")!="jellyfin-source-batch-v1":
        raise RuntimeError("invalid_saved_batch_state")
    return data


def scoped_state_file(selection):
    """One receipt per exact owner scope; a one-episode job must not erase a series."""
    encoded=json.dumps(selection,sort_keys=True,ensure_ascii=False).encode("utf-8")
    if len(encoded)>16_000:
        raise ValueError("source_scope_too_large")
    digest=hashlib.sha256(encoded).hexdigest()[:20]
    return STATE.parent/("jellyfin-source-scope-"+digest+".json")


def read_scoped_state(selection):
    """Resumes old work even after an unrelated episode was sourced separately."""
    path=scoped_state_file(selection)
    prior=read_state(path)
    if prior and prior.get("selector")==selection:
        return prior
    old=read_state()
    return old if old and old.get("selector")==selection else None


def write_state(doc,path=None):
    """Atomic 0600 receipt. Browser refreshes never mutate it."""
    path=path or STATE
    _safe_state_root(path)
    raw=json.dumps(doc,sort_keys=True,ensure_ascii=False).encode("utf-8")
    if len(raw)>500_000:
        raise RuntimeError("batch_state_oversize")
    fd,tmp=tempfile.mkstemp(prefix=".subhub-jellyfin-job-",dir=path.parent)
    try:
        with os.fdopen(fd,"wb") as f:
            os.chmod(tmp,0o600)
            f.write(raw); f.flush(); os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:
        Path(tmp).unlink(missing_ok=True)


def fresh_state(rows,chosen,prior=None,now=None):
    now=now or int(time.time())
    old={}
    if prior and prior.get("selector")==chosen:
        old={x["id"]:x for x in prior.get("items",[]) if
             isinstance(x,dict) and "id" in x}
    items=[]
    for row in rows:
        jid=row["jellyfin_id"]
        prev=old.get(jid,{})
        state=prev.get("status","queued")
        tried=int(prev.get("attempted_at") or 0)
        # One-time recovery sweep when the underlying search strategy changes:
        # old SubBuzz HTTP 500 and single-provider misses never proved absence.
        if prior and prior.get("search_strategy") != SEARCH_STRATEGY and state in (
                "held","no_match","deferred"):
            state="queued"
        elif state in ("no_match","deferred") and now-tried >= COOLDOWN_SEC:
            state="queued"
        if state in ("running","interrupted","paused"):
            state="queued"
        items.append({"id":jid,"label":item_label(row),
                      "status":state,"reason":str(prev.get("reason") or "")[:120],
                      "attempted_at":tried})
    previous=[]
    if prior and prior.get("selector")!=chosen:
        previous=[{
            "selector":prior.get("selector"),"state":prior.get("state"),
            "total":len(prior.get("items",[])),"ended_at":prior.get("updated_at")
        }]+list(prior.get("previous",[]))[:4]
    elif prior:
        previous=list(prior.get("previous",[]))[:5]
    return {
        "schema":"jellyfin-source-batch-v1","selector":chosen,
        "search_strategy":SEARCH_STRATEGY,
        "state":"queued","phase":"queued","current":"",
        "items":items,"started_at":now,"updated_at":now,
        "searches_this_run":0,"downloads_this_run":0,
        # The owner-facing meter is for THIS pass, not the saved lifetime queue.
        "pass_total":sum(x["status"]=="queued" for x in items),
        "pass_processed":0,
        "events":[],"previous":previous,
    }


def mark_processed(doc,item):
    """Advance the single episode meter once, regardless of outcome."""
    if item["status"] in ("queued","running"):
        raise RuntimeError("cannot_count_unfinished_episode")
    if item.get("processed_this_pass"):
        raise RuntimeError("episode_already_counted_this_pass")
    item["processed_this_pass"]=True
    doc["pass_processed"]+=1


def write_job_state(doc):
    """Persist exact-scope history AND the latest-job dashboard display."""
    write_state(doc,scoped_state_file(doc["selector"]))
    write_state(doc)


def event(doc,kind,label="",detail=""):
    doc["phase"]=kind
    doc["current"]=label
    doc["updated_at"]=int(time.time())
    doc["events"]=(doc.get("events",[])+[
        {"phase":kind,"item":label[:135],"detail":detail[:155]}
    ])[-30:]


def progress(doc):
    count=Counter(it["status"] for it in doc["items"])
    total=len(doc["items"])
    finished=sum(n for state,n in count.items() if state not in ("queued","running"))
    return {"total":total,"finished":finished,
            "pending":count["queued"]+count["running"],
            "published":count["published"],"already_covered":count["covered"],
            "no_match":count["no_match"],"held":count["held"],
            "deferred":count["deferred"],"completed_fraction":
                round(finished/total,4) if total else 1}


def _milestone(line):
    """Only sanitized, code-generated stage signals may update owner progress."""
    if line.startswith("MEDIA:"):
        return "video_checked", "Video and subtitle eligibility checked"
    if line.startswith("JELLYFIN_JA_SEARCH_REQUEST:"):
        return "searching_provider", "Searching Japanese subtitle providers"
    if line.startswith("JELLYFIN_JA_MATCHING_CANDIDATES:"):
        return "matching", "Provider search returned; filtering candidates"
    if line.startswith("JELLYFIN_JA_BYTES:"):
        return "download_received", "Subtitle bytes downloaded; validating Japanese"
    if line.startswith("JELLYFIN_PRIVATE_STAGE:"):
        return "staged", "Japanese subtitle validated and staged privately"
    if line.startswith("ALASS HELD:"):
        return "alignment_fallback", "ALASS held; checking alternative sync"
    if line.startswith("FFSUBSYNC:"):
        return "timing_checked", "FFSUBSYNC timing validated"
    if line.startswith("SOURCED_GROSS_QA:"):
        return "quality_checked", "Gross subtitle quality gate completed"
    if line.startswith("PUBLISHED:"):
        return "published_sidecar", "Japanese subtitle created"
    return None


def call(command,*,timeout,progress=None):
    """Stream safe milestones every few seconds; enforce the original timeout.

    No subtitle text, secret-bearing URLs, provider candidate IDs or entire
    stdout/stderr are written to persistent job state. Tests can inject a runner.
    """
    proc=subprocess.Popen(command,stdin=subprocess.DEVNULL,
                          stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    watch=selectors.DefaultSelector()
    collected={"out":bytearray(),"err":bytearray()}
    lines={"out":bytearray(),"err":bytearray()}
    start=time.monotonic()
    next_heartbeat=start+10
    try:
        watch.register(proc.stdout,selectors.EVENT_READ,"out")
        watch.register(proc.stderr,selectors.EVENT_READ,"err")
        while watch.get_map():
            now=time.monotonic()
            if now-start>=timeout:
                raise subprocess.TimeoutExpired(command,timeout)
            for key,_ in watch.select(timeout=min(1,max(.01,timeout-(now-start)))):
                kind=key.data
                chunk=os.read(key.fileobj.fileno(),8192)
                if not chunk:
                    watch.unregister(key.fileobj)
                    continue
                collected[kind].extend(chunk)
                if len(collected[kind])>12000:
                    del collected[kind][:-12000]
                if kind=="out" and progress:
                    lines[kind].extend(chunk)
                    while b"\n" in lines[kind]:
                        entry,_,remaining=lines[kind].partition(b"\n")
                        lines[kind]=bytearray(remaining)
                        signal=_milestone(entry.decode("utf-8","replace"))
                        if signal:
                            progress(*signal)
                    if len(lines[kind])>8192:
                        lines[kind].clear()
            if progress and time.monotonic()>=next_heartbeat:
                progress("working","Still processing this episode")
                next_heartbeat=time.monotonic()+10
        proc.wait(timeout=max(.01,timeout-(time.monotonic()-start)))
        return (proc.returncode,
                collected["out"].decode("utf-8","replace")[-2500:],
                collected["err"].decode("utf-8","replace")[-1500:])
    except BaseException:
        if proc.poll() is None:
            proc.kill()
        proc.wait()
        raise
    finally:
        watch.close()
        proc.stdout.close()
        proc.stderr.close()


def classify_stage(code,stdout,stderr):
    if code==0 and "JELLYFIN_PRIVATE_STAGE:" in stdout:
        return "staged"
    if code==0 and "HELD: no exactly matching Japanese SRT" in stdout:
        return "no_match"
    if re.search(r"(?:HTTP[_ ](?:Error[_ ]?)?429|rate.limited|budget_exhausted)",stderr+stdout,re.I):
        return "deferred"
    if "japanese_sidecar_already_present" in stderr or "embedded_japanese_subtitle_already_present" in stderr:
        return "covered"
    return "held"


def safe_failure_reason(stdout,stderr):
    """Explain individual holds without persisting secrets, URLs or raw subtitles."""
    raw=(stderr or "")[-2500:]
    match=re.search(r"HTTP(?:Error| Error|_Error)?[: _]*(4[0-9]{2}|5[0-9]{2})",raw,re.I)
    if match:
        return "provider_http_"+match.group(1)
    # RuntimeError tokens are generated by OUR stage gates; never expose
    # arbitrary provider messages or full paths in dashboard/job files.
    lines=[line.strip() for line in raw.splitlines()[-8:]]
    for line in reversed(lines):
        match=re.search(r"(?:RuntimeError|ValueError):\s*([a-z][a-z0-9_]{3,95})\s*$",line)
        if match and "_" in match.group(1):
            return match.group(1)
    if "JELLYFIN_JA_BYTES:" in stdout:
        return "subtitle_validation_failed"
    if "JELLYFIN_JA_MATCHING_CANDIDATES:" in stdout:
        return "provider_download_failed"
    if "JELLYFIN_JA_SEARCH_REQUEST:" in stdout:
        return "provider_search_failed"
    if "MEDIA:" in stdout:
        return "preflight_or_credentials_failed"
    return "media_preflight_failed"


def is_upstream_failure(stdout,reason):
    """Pause only if requests reached the provider but no bytes came back.

    Individual media preflight failures and invalid subtitle QA (bytes already
    downloaded) are independent item holds, not evidence provider is down.
    """
    return ("JELLYFIN_JA_SEARCH_REQUEST:" in stdout and
            "JELLYFIN_JA_BYTES:" not in stdout)


def recover_via_sublarr(row, *, remaining_searches, checkpoint):
    """Use the EXISTING Sublarr OpenSubtitles/SubDL discovery, then its saved
    candidate stage and the SAME ALASS/ffsubsync publication gate. No AI.
    A Jellyfin/one-provider 500 never prevents this independent route.
    """
    jid=str(row["jellyfin_id"])
    label=item_label(row)
    kind="episode" if row["kind"]=="Episode" else "movie"
    publish=[sys.executable,"-B","-u",
             str(SOURCE_DIR/"ja_first_publish_queue.py"),
             "--jellyfin-id",jid,"--max-titles","1","--limit","1","--apply"]
    stage_cmd=[sys.executable,"-B","-u",
               str(SOURCE_DIR/"ja_first_stage_saved_batch.py"),
               "--jellyfin-id",jid,"--kind",kind,"--budget","1","--apply"]
    def step(command, timeout):
        try:
            return call(command,timeout=timeout,progress=checkpoint)
        except subprocess.TimeoutExpired:
            return 124,"","step_timeout"
    def try_saved():
        checkpoint("sublarr_candidate_stage","Checking saved Japanese candidates")
        rc,out,err=step(stage_cmd,180)
        if "PROVIDER_LIMIT_REACHED:" in out or re.search(
                r"(?i)(?:HTTP[ _]?429|budget_exhausted|rate.limit)",err):
            return "deferred",0
        if not re.search(r"(?m)^STAGED:\\s",out):
            return "unavailable",0
        checkpoint("sublarr_sync_publish","Repairing timing with ALASS/ffsubsync")
        pc,po,pe=step(publish,850)
        expected='"jellyfin_id": "'+jid+'"'
        if pc==0 and expected in po and '"result": "published"' in po:
            return "published",1
        return "held",1

    # First consume saved OpenSubtitles search evidence; zero new searches.
    state,downloads=try_saved()
    if state in ("published","deferred"):
        return state, "sublarr_saved_candidate" if state=="published" else "sublarr_provider_limited",0,downloads
    if remaining_searches<=0:
        return "deferred","search_budget_reached_before_title_search",0,downloads

    checkpoint("sublarr_search","Searching OpenSubtitles and SubDL by series/title and season/episode")
    cmd=[sys.executable,"-B","-u",str(SOURCE_DIR/"ja_first_search_pilot.py"),
         "--jellyfin-id",jid,"--budget","1"]
    search_rc,search_out,search_err=step(cmd,270)
    search_used=1
    if search_rc:
        return "held","sublarr_title_search_failed",search_used,downloads
    if "DEFERRED:" in search_out:
        return "deferred","sublarr_provider_deferred",search_used,downloads
    # The search results are persisted by the existing search pilot; stage
    # them with its existing identity and no-overwrite guards, not raw API IDs.
    stage_state,new_downloads=try_saved()
    downloads+=new_downloads
    if stage_state=="published":
        return "published","sublarr_title_candidate",search_used,downloads
    if stage_state=="deferred":
        return "deferred","sublarr_download_limited",search_used,downloads
    return "held","sublarr_candidates_unavailable_or_timing_hold",search_used,downloads


def execute(rows,doc,*,limit,runner=call,writer=write_job_state):
    """One budget-limited real-media pass. Never equate no-match with coverage."""
    rows_by_id={row["jellyfin_id"]:row for row in rows}
    writer(doc)
    for item in doc["items"]:
        if STOP:
            event(doc,"interrupted","","Owner stopped job")
            doc["state"]="interrupted";writer(doc);return
        if item["status"]!="queued":
            continue
        if doc["searches_this_run"]>=limit:
            event(doc,"paused_limit","","Per-run provider-search limit reached")
            doc["state"]="paused";writer(doc);return
        row=rows_by_id[item["id"]]
        label=item["label"]
        path=Path(str(row.get("host_path") or ""))
        try:
            if path.is_file() and stage.japanese_sidecar_exists(path):
                item["status"]="covered"
                mark_processed(doc,item)
                event(doc,"skip_covered",label,"Existing Japanese sidecar")
                writer(doc)
                continue
        except OSError:
            item["status"]="held";item["reason"]="cannot_inspect_media_directory"
            mark_processed(doc,item)
            event(doc,"held",label,item["reason"])
            writer(doc)
            continue
        item["status"]="running"
        item["attempted_at"]=int(time.time())
        event(doc,"search_download",label)
        writer(doc)
        cmd=[sys.executable,"-B",str(SOURCE_DIR/"ja_first_stage_jellyfin.py"),
             "--jellyfin-id",item["id"],"--provider","any","--apply"]
        def checkpoint(phase,detail):
            event(doc,phase,label,detail)
            writer(doc)
        try:
            if runner is call:
                code,out,err=runner(cmd,timeout=320,progress=checkpoint)
            else:
                code,out,err=runner(cmd,timeout=320)
        except subprocess.TimeoutExpired:
            code,out,err=124,"","timed_out"
        verdict=classify_stage(code,out,err)
        if ("JELLYFIN_JA_SEARCH_REQUEST:" in out or
                "JELLYFIN_JA_MATCHING_CANDIDATES:" in out):
            doc["searches_this_run"]+=1
        # The operation can still have spent a request if it errored after
        # remote SEARCH started but before it printed matching candidates.
        elif code!=0 and ("HTTP" in err or "remote_search" in err.lower()):
            doc["searches_this_run"]+=1
        if verdict=="staged":
            doc["downloads_this_run"]+=1
            event(doc,"sync_publish",label,"Private stage validated; checking timing")
            writer(doc)
            p_cmd=[sys.executable,"-B",str(SOURCE_DIR/"ja_first_publish_queue.py"),
                   "--jellyfin-id",item["id"],"--max-titles","1","--limit","1","--apply"]
            try:
                if runner is call:
                    pub_code,pub_out,pub_err=runner(
                        p_cmd,timeout=800,progress=checkpoint)
                else:
                    pub_code,pub_out,pub_err=runner(p_cmd,timeout=800)
            except subprocess.TimeoutExpired:
                pub_code,pub_out,pub_err=124,"","timed_out"
            expected='"jellyfin_id": "'+item["id"]+'"'
            if (pub_code==0 and expected in pub_out and
                    '"result": "published"' in pub_out):
                item["status"]="published";item["reason"]="Japanese sidecar created"
            else:
                item["status"]="held";item["reason"]="publication_qa_or_timing_hold"
                # This media's QA hold is not a failure of the provider, and
                # must not prevent the next 75 unrelated episodes being tried.
        elif verdict=="no_match":
            item["status"]="no_match";item["reason"]="No exact Japanese result via current Jellyfin provider"
        elif verdict=="covered":
            item["status"]="covered";item["reason"]="Existing Japanese subtitles"
        elif verdict=="deferred":
            item["status"]="deferred";item["reason"]="provider_rate_limited"
            mark_processed(doc,item)
            event(doc,"provider_deferred",label)
            # A verified 429/budget limit pauses further requests; other
            # episode failures belong in the exception pile, not a global stop.
            doc["state"]="paused";writer(doc);return
        else:
            item["status"]="held"
            item["reason"]=safe_failure_reason(out,err)
        # The original ID/one-provider route is NOT the verdict on Japanese
        # subtitle availability. For any unresolved item, really search the
        # existing OpenSubtitles/SubDL coordinator by title + S/E, and stage
        # recoverable saved OpenSubtitles candidates before moving on.
        if runner is call and item["status"] in ("held","no_match"):
            fallback_status,reason,searched,downloaded=recover_via_sublarr(
                row,remaining_searches=max(0,limit-doc["searches_this_run"]),
                checkpoint=checkpoint)
            doc["searches_this_run"]+=searched
            doc["downloads_this_run"]+=downloaded
            if fallback_status=="published":
                item["status"]="published"
                item["reason"]="Japanese sidecar created via "+reason
            elif fallback_status=="deferred":
                item["status"]="deferred"
                item["reason"]=reason
                mark_processed(doc,item)
                event(doc,"provider_deferred",label,reason)
                doc["state"]="paused";writer(doc);return
            elif reason:
                item["reason"]=reason
        mark_processed(doc,item)
        event(doc,item["status"],label,item["reason"])
        writer(doc)
        # HTTP 500 and episode QA failures are recorded and skipped. The
        # existing per-pass request cap and pacing still bound this pass.
        # A small rate gate even for successful searches; upstream Jellyfin
        # provider controls remain authoritative and 429 is a hard stop.
        if doc["searches_this_run"] and doc["searches_this_run"]<limit:
            time.sleep(3)
    doc["state"]="completed" if not progress(doc)["pending"] else "paused"
    event(doc,doc["state"],"",
          "Pass finished; review exceptions separately" if
          doc["state"]=="completed" else "More items remain for another pass")
    writer(doc)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    exclusive=parser.add_mutually_exclusive_group(required=True)
    exclusive.add_argument("--series")
    exclusive.add_argument("--movie-id",action="append")
    parser.add_argument("--season",action="append",type=int,default=[])
    parser.add_argument("--pick",action="append",default=[])
    parser.add_argument("--max-searches",type=int,default=20)
    parser.add_argument("--job-id",default="",help="dashboard-issued run ID for exact progress correlation")
    parser.add_argument("--run",action="store_true",
                        help="perform real provider requests, staging and guarded publication")
    args=parser.parse_args(argv)
    if not 1<=args.max_searches<=MAX_SEARCHES:
        parser.error("max 200 provider searches per pass")
    if args.movie_id and (args.season or args.pick):
        parser.error("season/pick requires --series")
    if args.job_id and not re.fullmatch(r"[a-f0-9]{16}",args.job_id):
        parser.error("invalid dashboard job ID")
    picks=[]
    for raw in args.pick:
        m=EP.fullmatch(raw)
        if not m:
            parser.error("invalid SxxExxx selection")
        picks.append((int(m.group(1)),int(m.group(2))))
    rows=benchmark.load_latest_manifest()
    options={"series":args.series,"seasons":args.season,
             "picks":picks,"movie_ids":args.movie_id or []}
    chosen=choose(rows,**options)
    plan=selector(**options)
    if not chosen:
        print(json.dumps({"eligible":0,"reason":"all selected media already covered or held",
                          "selector":plan},ensure_ascii=False))
        return 0
    if not args.run:
        # The dashboard should show 0/47, not 0/78, on a resumed pass:
        # completed/held items remain saved but are not re-attempted.
        prior=read_scoped_state(plan)
        pending=fresh_state(chosen,plan,prior)["pass_total"]
        print(json.dumps({"eligible":pending,"selected":len(chosen),
                          "selector":plan,
                          "max_searches_this_run":args.max_searches,
                          "mode":"PREVIEW_NO_PROVIDER_CALLS"},ensure_ascii=False))
        return 0
    fd=autofill.lock()   # Same interprocess lock used by established source jobs
    signal.signal(signal.SIGTERM,stop_requested)
    signal.signal(signal.SIGINT,stop_requested)
    try:
        stage.private_root()
        prior=read_scoped_state(plan)
        doc=fresh_state(chosen,plan,prior)
        doc["job_id"]=args.job_id
        doc["search_cap"]=args.max_searches
        print("JELLYFIN_BATCH_BEGIN",json.dumps({
            "selected":len(chosen),"selector":plan,
            "max_searches":args.max_searches},ensure_ascii=False),flush=True)
        execute(chosen,doc,limit=args.max_searches)
        print("JELLYFIN_BATCH_DONE",json.dumps({
            "state":doc["state"],"progress":progress(doc),
            "searches_this_run":doc["searches_this_run"]},
            ensure_ascii=False),flush=True)
    finally:
        os.close(fd)
    return 0


if __name__=="__main__":
    try:raise SystemExit(main())
    except (OSError,RuntimeError,ValueError,subprocess.TimeoutExpired) as exc:
        print("JELLYFIN_BATCH_HELD",type(exc).__name__,str(exc)[:140],
              file=sys.stderr,flush=True)
        raise SystemExit(1)
