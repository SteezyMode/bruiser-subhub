#!/usr/bin/env python3
"""Reusable owner-initiated Jellyfin Japanese sourcing batch (movies and TV).

Existing Jellyfin library/catalog, existing private staging, existing ALASS /
ffsubsync publisher. NO direct Jellyfin subtitle POST, no translation, no
overwrite. Runs as its own systemd user service, not in the browser.

--series TITLE (optionally --season N and/or --pick SxxExxx) or --movie-id ID.
Per-run cap (default 20 remote searches, max 40) and restartable private JSON
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
MAX_SEARCHES = 40
COOLDOWN_SEC = 20 * 3600
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


def read_state(path=STATE):
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


def write_state(doc,path=STATE):
    """Atomic 0600 receipt. Browser refreshes never mutate it."""
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
        # Unavailable Japanese source is not permanent; try again only after
        # the cooldown. Held QA is not blindly reattempted every click.
        if state in ("no_match","deferred") and now-tried >= COOLDOWN_SEC:
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
        "state":"queued","phase":"queued","current":"",
        "items":items,"started_at":now,"updated_at":now,
        "searches_this_run":0,"downloads_this_run":0,
        "events":[],"previous":previous,
    }


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


def call(command,*,timeout):
    """Captured only; never log provider remote IDs, credentials or subtitle text."""
    proc=subprocess.run(command,capture_output=True,text=True,
                        stdin=subprocess.DEVNULL,timeout=timeout,check=False)
    return proc.returncode,proc.stdout[-2500:],proc.stderr[-500:]


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


def execute(rows,doc,*,limit,runner=call,writer=write_state):
    """One budget-limited real-media pass. Never equate no-match with coverage."""
    rows_by_id={row["jellyfin_id"]:row for row in rows}
    writer(doc)
    failures_in_row=0
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
                event(doc,"skip_covered",label,"Existing Japanese sidecar")
                writer(doc)
                continue
        except OSError:
            item["status"]="held";item["reason"]="cannot_inspect_media_directory"
            event(doc,"held",label,item["reason"])
            writer(doc)
            continue
        item["status"]="running"
        item["attempted_at"]=int(time.time())
        event(doc,"search_download",label)
        writer(doc)
        cmd=[sys.executable,"-B",str(SOURCE_DIR/"ja_first_stage_jellyfin.py"),
             "--jellyfin-id",item["id"],"--provider","subbuzz","--apply"]
        try:
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
                pub_code,pub_out,pub_err=runner(p_cmd,timeout=800)
            except subprocess.TimeoutExpired:
                pub_code,pub_out,pub_err=124,"","timed_out"
            expected='"jellyfin_id": "'+item["id"]+'"'
            if (pub_code==0 and expected in pub_out and
                    '"result": "published"' in pub_out):
                item["status"]="published";item["reason"]="Japanese sidecar created"
                failures_in_row=0
            else:
                item["status"]="held";item["reason"]="publication_qa_or_timing_hold"
                failures_in_row+=1
        elif verdict=="no_match":
            item["status"]="no_match";item["reason"]="No exact Japanese result via current Jellyfin provider"
            failures_in_row=0
        elif verdict=="covered":
            item["status"]="covered";item["reason"]="Existing Japanese subtitles"
            failures_in_row=0
        elif verdict=="deferred":
            item["status"]="deferred";item["reason"]="provider_rate_limited"
            event(doc,"provider_deferred",label)
            doc["state"]="paused";writer(doc);return
        else:
            item["status"]="held";item["reason"]="preflight_or_provider_download_failed"
            failures_in_row+=1
        event(doc,item["status"],label,item["reason"])
        writer(doc)
        # Don't hammer a plugin returning non-quota download errors.
        if failures_in_row>=3:
            event(doc,"paused_errors","","Three consecutive download/QA holds")
            doc["state"]="paused";writer(doc);return
        # A small rate gate even for successful searches; upstream Jellyfin
        # provider controls remain authoritative and 429 is a hard stop.
        if doc["searches_this_run"] and doc["searches_this_run"]<limit:
            time.sleep(3)
    doc["state"]="completed" if not progress(doc)["pending"] else "paused"
    event(doc,doc["state"],"","All eligible selected items visited" if
          doc["state"]=="completed" else "More work remains")
    writer(doc)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    exclusive=parser.add_mutually_exclusive_group(required=True)
    exclusive.add_argument("--series")
    exclusive.add_argument("--movie-id",action="append")
    parser.add_argument("--season",action="append",type=int,default=[])
    parser.add_argument("--pick",action="append",default=[])
    parser.add_argument("--max-searches",type=int,default=20)
    parser.add_argument("--run",action="store_true",
                        help="perform real provider requests, staging and guarded publication")
    args=parser.parse_args(argv)
    if not 1<=args.max_searches<=MAX_SEARCHES:
        parser.error("max 40 provider searches per pass")
    if args.movie_id and (args.season or args.pick):
        parser.error("season/pick requires --series")
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
        print(json.dumps({"eligible":len(chosen),"selector":plan,
                          "max_searches_this_run":args.max_searches,
                          "mode":"PREVIEW_NO_PROVIDER_CALLS"},ensure_ascii=False))
        return 0
    fd=autofill.lock()   # Same interprocess lock used by established source jobs
    signal.signal(signal.SIGTERM,stop_requested)
    signal.signal(signal.SIGINT,stop_requested)
    try:
        stage.private_root()
        prior=read_state()
        doc=fresh_state(chosen,plan,prior)
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
