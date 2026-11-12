#!/usr/bin/env python3
"""One owner-selected TV scope: source Japanese, then translate proven gaps.

This is one foreground systemd job, not a second provider engine. The existing
Jellyfin source batch owns provider quotas/ALASS/ffsubsync; the existing PLaMo
batch owns EN verification, translation checkpoints, QA and create-only writes.
A failed or quota-paused search is NOT proof Japanese subtitles do not exist.
Unverified duplicate versions are never sent to PLaMo automatically.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time

try:
    from . import subhub_translation_batch as batch
except ImportError:
    import subhub_translation_batch as batch

SOURCE = Path.home() / "bruiser-pilot/subhub-control/subhub_jellyfin_batch.py"
DEEP_SOURCE = SOURCE.with_name("subhub_deep_source.py")
AUTO_PLAMO = Path.home() / "bruiser-pilot/plamo3-ab/subhub_plamo_handoff.py"
INTENSIVE = SOURCE.with_name("ja_first_publish_queue.py")
TRANSLATOR = Path(__file__).with_name("subhub_translation_batch.py")
STATE = Path.home() / "bruiser-pilot/ja-first-inventory/finish-scope.json"
MAX_TRANSLATION_PICKS = 200
MAX_SEARCHES = 200


def scope_seasons(series, seasons=()):
    records = next((x for x in batch.catalog()
                    if x["series"] == series), None)
    if not records:
        raise ValueError("series_not_in_saved_jellyfin_queue")
    available = set(records["seasons"])
    requested = sorted(set(seasons)) if seasons else sorted(available)
    if not requested or not set(requested).issubset(available):
        raise ValueError("selected_season_not_in_jellyfin_queue")
    return requested


def plan(series, seasons=()):
    selected = scope_seasons(series, seasons)
    items = []
    for season in selected:
        report = batch.season_report(series, season)
        for row in report["items"]:
            items.append(dict(row, season=season))
    missing = [x for x in items if x["status"] != "covered"]
    # PLaMo only after a recorded Japanese miss or actual timing-QA failure.
    # A plausible candidate still awaiting repair is NOT exhausted.
    def may_translate(x):
        proof = x.get("search") or {}
        plausible = int(proof.get("plausible_candidates") or 0)
        return (bool(x.get("can_translate")) and
                (plausible == 0 or bool(x.get("failed_source_qa"))) and
                x.get("reason") != "duplicate_episode_versions")
    eligible = [x for x in missing if may_translate(x)]
    return {"series":series,"seasons":selected,"total":len(items),
            "covered":len(items)-len(missing),"missing":len(missing),
            "source_first":len(missing)-len(eligible),
            "plamo_ready":len(eligible),
            "duplicate_versions":sum(
                x.get("reason") == "duplicate_episode_versions" for x in missing),
            "picks":[{"season":x["season"],"episode":x["episode"]}
                     for x in eligible[:MAX_TRANSLATION_PICKS]]}


def write_state(payload):
    parent=STATE.parent
    if (not parent.is_dir() or parent.is_symlink() or
            parent.stat().st_mode & 0o077):
        raise RuntimeError("private_state_directory_unavailable")
    if STATE.is_symlink() or (STATE.exists() and
            (not STATE.is_file() or STATE.stat().st_mode & 0o077)):
        raise RuntimeError("unsafe_existing_finish_state")
    value=dict(payload,updated_utc=datetime.now(timezone.utc).isoformat())
    raw=json.dumps(value,ensure_ascii=False,sort_keys=True).encode("utf-8")
    if len(raw)>15_000:
        raise RuntimeError("finish_state_too_large")
    fd,temp=tempfile.mkstemp(prefix=".finish-",dir=parent)
    try:
        with os.fdopen(fd,"wb") as f:
            os.fchmod(f.fileno(),0o600)
            f.write(raw);f.flush();os.fsync(f.fileno())
        os.replace(temp,STATE)
    finally:
        Path(temp).unlink(missing_ok=True)


def command(args, label, on_line=None):
    if not args[0].is_file() or args[0].is_symlink():
        raise RuntimeError(label+"_worker_not_installed")
    print("FINISH_STEP",label,flush=True)
    with subprocess.Popen([sys.executable,"-B","-u",*map(str,args)],
            stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,text=True,bufsize=1) as p:
        assert p.stdout is not None
        for line in p.stdout:
            print(line,end="",flush=True)
            if on_line is not None:
                on_line(line)
        return p.wait()


def selected_media(series=None, seasons=(), *, movie_ids=(), movie_scope=None,
                   item_ids=(), library_folder=None, library_group=None,
                   library_genre=None, library_kind=None):
    """Select every exact Jellyfin file; duplicate episode versions remain separate."""
    # Dashboard controller runs from a different installation directory
    # than the canonical host source engine; resolve it explicitly.
    try:
        from . import subhub_deep_source as deep
    except ImportError:
        if str(SOURCE.parent) not in sys.path:
            sys.path.insert(0,str(SOURCE.parent))
        import subhub_deep_source as deep
    chosen=[]
    seen=set()
    if not series and sum(bool(x) for x in (
            movie_ids,movie_scope,item_ids,library_folder,library_group,library_genre))!=1:
        raise ValueError("choose_one_library_or_exact_item_selection")
    if library_group and library_group not in ("Movie","Episode"):
        raise ValueError("invalid_library_group")
    if library_genre:
        if (library_kind not in ("Movie","Episode") or
                not isinstance(library_genre,str) or
                not 1<=len(library_genre)<=60 or
                any(ord(c)<32 for c in library_genre)):
            raise ValueError("invalid_library_genre")
    elif library_kind:
        raise ValueError("library_kind_requires_genre")
    if library_folder:
        try:
            from . import subhub_library_browser as browser
        except ImportError:
            import subhub_library_browser as browser
        rows,_=browser.snapshot()
        roots={r["root"] for r in rows}
        if (library_folder not in roots and not any(
                browser.within(r["folder"],library_folder) and
                browser.within(library_folder,r["root"])
                for r in rows)):
            raise ValueError("library_folder_not_in_saved_inventory")
    if movie_scope and movie_scope not in deep.stage.movie_scope.SCOPES:
        raise ValueError("invalid_movie_scope")
    ids=set(movie_ids or item_ids)
    if (len(ids)!=len(movie_ids or item_ids) or
            len(ids)>300 or any(
            not isinstance(jid,str) or not re.fullmatch(r"[a-f0-9]{32}",jid)
            for jid in ids)):
        raise ValueError("invalid_item_selection")
    for row in deep.inventory.load_latest_manifest():
        if not isinstance(row,dict):
            continue
        if series:
            if (row.get("kind")!="Episode" or row.get("series_title")!=series
                    or row.get("season") not in seasons):
                continue
        elif movie_ids or movie_scope:
            if (row.get("kind")!="Movie" or
                    (ids and str(row.get("jellyfin_id") or "") not in ids) or
                    (movie_scope and not deep.stage.movie_scope.matches(row,movie_scope))):
                continue
        elif item_ids:
            if str(row.get("jellyfin_id") or "") not in ids:
                continue
        elif library_group:
            if row.get("kind")!=library_group:
                continue
        elif library_genre:
            if (row.get("kind")!=library_kind or
                    library_genre.casefold() not in
                    {str(g).casefold() for g in row.get("genres") or []}):
                continue
        elif library_folder:
            if (not isinstance(row.get("host_path"),str) or
                    not browser.within(row["host_path"],library_folder)):
                continue
        # An unverified catalog entry is not proven missing. Never send it
        # into an automatic provider/AI loop. It remains visibly unverified
        # in the library browser until classification can be corrected.
        if row.get("status") not in (
                "ready_ja_search","existing_japanese_subtitle",
                "japanese_audio"):
            continue
        jid=str(row.get("jellyfin_id") or "")
        if not re.fullmatch(r"[a-f0-9]{32}",jid) or jid in seen:
            raise RuntimeError("duplicate_or_invalid_selected_jellyfin_id")
        seen.add(jid)
        chosen.append((int(row["season"] or 0),int(row["episode"] or 0),jid)
                      if row.get("kind")=="Episode" else (0,0,jid))
    chosen.sort()
    if ids and len(chosen)!=len(ids):
        raise RuntimeError("selected_media_missing_or_inventory_unverified")
    # A whole library/genre with nothing missing is not an error.
    if not chosen and (series or movie_ids or item_ids):
        raise RuntimeError("selected_scope_not_in_jellyfin_inventory")
    return chosen


def movie_plan(movie_ids=(), movie_scope=None, *, item_ids=(),
               library_folder=None, library_group=None,
               library_genre=None, library_kind=None):
    """Read-only exact movie coverage preview; no provider calls or AI."""
    selected=selected_media(movie_ids=movie_ids,movie_scope=movie_scope,
                            item_ids=item_ids,library_folder=library_folder,
                            library_group=library_group,
                            library_genre=library_genre,library_kind=library_kind)
    try:
        from . import subhub_deep_source as deep
    except ImportError:
        if str(SOURCE.parent) not in sys.path:
            sys.path.insert(0,str(SOURCE.parent))
        import subhub_deep_source as deep
    rows={str(row.get("jellyfin_id")):row for row in
          deep.inventory.load_latest_manifest() if isinstance(row,dict)}
    covered=sum(rows[jid].get("status") in
                ("existing_japanese_subtitle","japanese_audio")
                or deep.stage.japanese_sidecar_exists(
                    Path(str(rows[jid].get("host_path") or "")))
                for _,_,jid in selected)
    return {"series":"","seasons":[],"total":len(selected),
            "covered":covered,"missing":len(selected)-covered,
            "source_first":len(selected)-covered,"plamo_ready":0,
            "picks":[]}


def initial_covered(selection):
    """Exclude existing Japanese tracks before building a work queue."""
    try:
        from . import subhub_deep_source as deep
    except ImportError:
        if str(SOURCE.parent) not in sys.path:
            sys.path.insert(0,str(SOURCE.parent))
        import subhub_deep_source as deep
    ids={jid for _,_,jid in selection}
    rows={str(row.get("jellyfin_id")):row for row in
          deep.inventory.load_latest_manifest() if isinstance(row,dict)
          and str(row.get("jellyfin_id")) in ids}
    covered=set()
    for jid in ids:
        row=rows.get(jid)
        if not row:
            continue
        if row.get("status") in ("existing_japanese_subtitle","japanese_audio"):
            covered.add(jid)
            continue
        video=Path(str(row.get("host_path") or ""))
        if video.is_file() and not video.is_symlink() and deep.stage.japanese_sidecar_exists(video):
            covered.add(jid)
    return covered


def valid_source_exhaustion(jid):
    """Revalidate exact video and completed provider search before model use."""
    try:
        from . import subhub_deep_source as deep
    except ImportError:
        if str(SOURCE.parent) not in sys.path:
            sys.path.insert(0,str(SOURCE.parent))
        import subhub_deep_source as deep
    matches=[r for r in deep.inventory.load_latest_manifest()
             if isinstance(r,dict) and r.get("jellyfin_id")==jid]
    return len(matches)==1 and deep.validate_exhausted(jid,matches[0])


def selected_title_metadata(selection):
    """Only names are needed for live progress; never mutate media or queue."""
    try:
        from . import subhub_deep_source as deep
    except ImportError:
        if str(SOURCE.parent) not in sys.path:
            sys.path.insert(0,str(SOURCE.parent))
        import subhub_deep_source as deep
    ids={jid for _,_,jid in selection}
    return {str(row.get("jellyfin_id")):row for row in
            deep.inventory.load_latest_manifest() if isinstance(row,dict)
            and str(row.get("jellyfin_id")) in ids}


def run(series=None, seasons=(), *, movie_ids=(), movie_scope=None,
        item_ids=(), library_folder=None, library_group=None,
        library_genre=None, library_kind=None):
    """One owner action: source every selected file, auto PLaMO proven misses.

    Incomplete providers and temporary errors stay in SOURCE, with autonomous
    paced retry. The operator may stop the job, but no per-title review is
    required. PLaMO can start only with an exact validated source receipt.
    """
    before=(plan(series,seasons) if series else
            movie_plan(movie_ids,movie_scope,item_ids=item_ids,
                       library_folder=library_folder,library_group=library_group,
                       library_genre=library_genre,library_kind=library_kind))
    selection=(selected_media(series,before["seasons"]) if series else
               selected_media(movie_ids=movie_ids,movie_scope=movie_scope,
                              item_ids=item_ids,library_folder=library_folder,
                              library_group=library_group,
                              library_genre=library_genre,library_kind=library_kind))
    finished=initial_covered(selection)
    by_id=selected_title_metadata(selection)
    pending={jid:(season,episode) for season,episode,jid in selection
             if jid not in finished}
    total=len(selection)
    receipt={"schema":"subhub-finish-scope-v1","series":series or "",
             "seasons":before["seasons"],"phase":"source",
             "state":"running","before":{k:v for k,v in before.items()
                                         if k!="picks"},
             "total_exact_files":total,"covered_exact_files":len(finished),
             "source_pending":len(pending),"plamo_pending":0,
             "round":0,"source_attempts":0,"plamo_attempts":0,
             "started_at":int(time.time()),"item_started_at":0,
             "current":"","detail":"","last_event_at":0,"last_issue":""}
    write_state(receipt)
    print("FINISH_BEGIN",json.dumps({"total_exact_files":total,
          "series":series or "","seasons":before["seasons"],
          "movie_scope":movie_scope or "",
          "movie_ids":len(movie_ids),"item_ids":len(item_ids),
          "library_folder":library_folder or "",
          "library_group":library_group or "",
          "library_genre":library_genre or ""},ensure_ascii=False),
          flush=True)
    # Dict retains state for this process; source-exhaustion receipts and
    # PLaMO checkpoints are independently durable across a restarted job.
    plamo=set()
    while pending or plamo:
        receipt["round"]+=1
        for jid in list(pending):
            season,ep=pending[jid]
            row=by_id.get(jid) or {}
            title=(str(row.get("series_title") or "")+" " if season else "")+(
                   f"S{season:02d}E{ep:03d} " if season else "")+str(
                   row.get("title") or jid)
            receipt.update(phase="source",state="running",
                           current=title[:160],detail="Checking existing Japanese subtitles",
                           item_started_at=int(time.time()),last_event_at=int(time.time()),
                           source_attempts=receipt["source_attempts"]+1)
            write_state(receipt)
            result={}
            def accept(line):
                if line.startswith("DEEP_SOURCE_RESULT:"):
                    try:
                        result.update(json.loads(line.split(":",1)[1]))
                    except (TypeError,ValueError):
                        pass
                elif line.startswith(("DEEP_SOURCE_CANDIDATE:",
                                      "DEEP_SOURCE_SEARCH:",
                                      "DEEP_SOURCE_PUBLISHED:",
                                      "DEEP_SOURCE_PUBLISH_RETRY:")):
                    receipt["detail"]=line[:160]
                    receipt["last_event_at"]=int(time.time())
                    write_state(receipt)
            rc=command([DEEP_SOURCE,"--jellyfin-id",jid,"--run"],
                       "deep_source_"+jid[:8],on_line=accept)
            decision=result.get("result") if not rc else "retry_source"
            if decision=="covered":
                finished.add(jid)
                del pending[jid]
                print("FINISH_COVERED:",jid,flush=True)
            elif decision=="plamo":
                del pending[jid]
                plamo.add(jid)
                print("FINISH_PLAMO_QUEUE:",jid,"Japanese sources exhausted",
                      flush=True)
            else:
                receipt["last_issue"]=str(result.get("reason") or
                                          "source_worker_failed")[:150]
                print("FINISH_SOURCE_RETRY:",jid,receipt["last_issue"],
                      flush=True)
            receipt.update(covered_exact_files=len(finished),
                           source_pending=len(pending),
                           plamo_pending=len(plamo))
            write_state(receipt)
        for jid in list(plamo):
            # A refreshed provider search or changed media invalidates a
            # former exhaustion proof. Re-route automatically to sourcing.
            if not valid_source_exhaustion(jid):
                plamo.remove(jid)
                pending[jid]=next(((sn,number) for sn,number,mid in selection
                                   if mid==jid),(0,0))
                receipt["last_issue"]="source_proof_invalidated_retry_japanese"
                print("FINISH_SOURCE_REQUEUE:",jid,flush=True)
                continue
            season,ep=next(((sn,number) for sn,number,mid in selection
                            if mid==jid),(0,0))
            row=by_id.get(jid) or {}
            title=(str(row.get("series_title") or "")+" " if season else "")+(
                   f"S{season:02d}E{ep:03d} " if season else "")+str(
                   row.get("title") or jid)
            receipt.update(phase="translation",state="running",
                           current=title[:160],detail="Running PLaMO fallback",
                           item_started_at=int(time.time()),
                           plamo_attempts=receipt["plamo_attempts"]+1)
            write_state(receipt)
            rc=command([AUTO_PLAMO,"--jellyfin-id",jid,
                        "--source-exhausted-auto","--apply"],
                       "plamo_"+jid[:8])
            if rc==0:
                plamo.remove(jid)
                finished.add(jid)
                print("FINISH_PLAMO_PUBLISHED:",jid,flush=True)
            else:
                receipt["last_issue"]="plamo_attempt_held_"+jid[:8]
                print("FINISH_PLAMO_RETRY:",jid,flush=True)
            receipt.update(covered_exact_files=len(finished),
                           source_pending=len(pending),
                           plamo_pending=len(plamo))
            write_state(receipt)
        if pending or plamo:
            # One click may span quota resets or a slow/thermally limited AI
            # job. Never classify a paused provider as "no Japanese". A long
            # sleep prevents busy loops; systemd stop cancels the whole group.
            delay=7200 if pending else 900
            receipt.update(state="waiting_retry",phase="source" if pending
                           else "translation",current="Awaiting next automatic retry")
            write_state(receipt)
            print("FINISH_WAITING_RETRY:",delay,"seconds",
                  "source",len(pending),"plamo",len(plamo),flush=True)
            time.sleep(delay)
    receipt.update(state="completed",phase="done",current="",
                   remaining=0,covered_exact_files=len(finished),
                   source_pending=0,plamo_pending=0)
    write_state(receipt)
    print("FINISH_RESULT",json.dumps({"remaining":0,
         "covered":len(finished),"total":total,"state":"completed"}),flush=True)
    return 0

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    one=p.add_mutually_exclusive_group(required=True)
    one.add_argument("--series")
    one.add_argument("--movie-id",action="append",default=[])
    one.add_argument("--movie-scope")
    one.add_argument("--item-id",action="append",default=[])
    one.add_argument("--library-folder")
    one.add_argument("--library-group",choices=("Movie","Episode"))
    one.add_argument("--library-genre")
    p.add_argument("--library-kind",choices=("Movie","Episode"))
    p.add_argument("--season",type=int,action="append",default=[])
    p.add_argument("--run",action="store_true")
    opts=p.parse_args(argv)
    if opts.series and (len(opts.series)>160 or any(
            ord(ch)<32 for ch in opts.series)):
        p.error("invalid series")
    if len(opts.season)>60 or len(set(opts.season))!=len(opts.season) or any(
            not 1<=s<=60 for s in opts.season):
        p.error("invalid seasons")
    if not opts.series and opts.season:
        p.error("--season requires --series")
    if opts.movie_scope and opts.movie_scope not in (
            "all","movies-no-anime","horror-drama-folders"):
        p.error("invalid movie scope")
    if opts.run:
        return run(opts.series,opts.season,movie_ids=opts.movie_id,
                   movie_scope=opts.movie_scope,item_ids=opts.item_id,
                   library_folder=opts.library_folder,
                   library_group=opts.library_group,
                   library_genre=opts.library_genre,library_kind=opts.library_kind)
    preview=(plan(opts.series,opts.season) if opts.series else
             movie_plan(opts.movie_id,opts.movie_scope,item_ids=opts.item_id,
                        library_folder=opts.library_folder,
                        library_group=opts.library_group,
                        library_genre=opts.library_genre,
                        library_kind=opts.library_kind))
    print(json.dumps(preview,ensure_ascii=False))
    return 0


if __name__=="__main__":
    try:
        raise SystemExit(main())
    except (OSError,ValueError,RuntimeError) as e:
        print("FINISH_HELD",type(e).__name__,str(e)[:160],file=sys.stderr)
        raise SystemExit(1)
