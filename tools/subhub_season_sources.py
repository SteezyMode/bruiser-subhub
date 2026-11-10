#!/usr/bin/env python3
"""Season-scoped JA source-first pass using the existing SubHub workers.

The only automatic work is Japanese-provider discovery, high-confidence
staging, verified create-only JA publication, and queue reconciliation.
No English ASR, AI inference, torrent actions, directory creation in media,
or media replacement. A single transient systemd unit owns each run.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from contextlib import closing, contextmanager
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time

try:
    from . import subhub_translation_batch as batch
except ImportError:
    import subhub_translation_batch as batch

SOURCE_CODE = Path.home() / "bruiser-pilot/subhub-control"
SOURCE_UNIT = "bruiser-subhub-season-sources.service"
SOURCE_ACTIONS = frozenset({
    "search_ja", "download_saved_ja", "align_existing_staged_ja"
})
MAX_EPISODES = 40


def scope(series, season, *, path=None):
    """Existing private coverage queue is the authoritative season identity."""
    batch.validate(series, season, MAX_EPISODES, 1)
    with batch.read_queue(path) as db:
        rows = db.execute("""
            SELECT m.path,m.jellyfin_id,m.title,m.episode,m.ja_present,
                   t.action,t.state
              FROM media AS m LEFT JOIN tasks AS t
                ON t.path=m.path AND t.target='ja' AND t.active=1
             WHERE m.kind='Episode' AND m.series=? AND m.season=?
        """, (series, str(season))).fetchall()
    episodes = defaultdict(list)
    for item in rows:
        try:
            ep = int(item["episode"])
        except (TypeError, ValueError):
            continue
        if 1 <= ep <= 999:
            episodes[ep].append(item)
    selected = {}
    held = Counter()
    for ep in sorted(episodes):
        versions = episodes[ep]
        if any(batch._already_covered(row) for row in versions):
            held["already_covered"] += 1
            continue
        if len(versions) != 1:
            held["duplicate_episode"] += 1
            continue
        row = versions[0]
        if row["state"] != "pending" or row["action"] not in SOURCE_ACTIONS:
            held["not_source_ready"] += 1
            continue
        jid = str(row["jellyfin_id"] or "")
        if not batch.JELLYFIN_ID.fullmatch(jid) or jid in selected:
            held["invalid_identity"] += 1
            continue
        selected[jid] = str(row["path"])
        if len(selected) > MAX_EPISODES:
            raise RuntimeError("season_exceeds_safe_episode_limit")
    return {"series": series, "season": season, "ids": selected,
            "eligible": len(selected), "skipped": dict(held)}



RECHECK_ACTIONS = SOURCE_ACTIONS | frozenset({
    "review_saved_ja", "validate_english_for_ja_fallback",
    "recover_english_for_ja_fallback"
})


def selected_scope(series, picks, *, recheck=False, path=None):
    """Fail closed unless every requested episode is in exactly this series."""
    batch.validate(series, 1, MAX_EPISODES, 1)
    if (not isinstance(picks, list) or not 1 <= len(picks) <= 200
            or any(not isinstance(p,dict) or set(p)!={"season","episode"}
                   or type(p["season"]) is not int or type(p["episode"]) is not int
                   or not 1 <= p["season"] <= 60 or not 1 <= p["episode"] <= 999
                   for p in picks)):
        raise ValueError("invalid_source_episode_selection")
    wanted = {(p["season"],p["episode"]) for p in picks}
    if len(wanted) != len(picks):
        raise ValueError("duplicate_source_episode_selection")
    allowed = RECHECK_ACTIONS if recheck else SOURCE_ACTIONS
    selected = {}
    reviewed = []
    with batch.read_queue(path) as db:
        rows = db.execute("""
            SELECT m.path,m.jellyfin_id,m.season,m.episode,m.ja_present,
                   t.target,t.action,t.state
              FROM media m LEFT JOIN tasks t
                ON t.path=m.path AND t.target IN ('ja','review') AND t.active=1
             WHERE m.kind='Episode' AND m.series=?
        """, (series,)).fetchall()
    by_episode = defaultdict(list)
    for row in rows:
        try:
            tag = (int(row["season"]),int(row["episode"]))
        except (TypeError,ValueError):
            continue
        if tag in wanted:
            by_episode[tag].append(row)
    if set(by_episode) != wanted:
        raise RuntimeError("selected_episode_missing_from_exact_series")
    for tag in sorted(wanted):
        versions = by_episode[tag]
        if len(versions)!=1:
            raise RuntimeError("duplicate_episode_requires_review")
        row=versions[0]
        manual_review = bool(recheck and row["target"]=="review"
            and row["action"]=="review_uncertain" and row["state"]=="pending")
        state_ok = (row["state"]=="pending" or
                    (recheck and row["state"]=="held" and
                     row["action"] in RECHECK_ACTIONS))
        if (batch._already_covered(row)
                or not (manual_review or
                        (row["target"]=="ja" and state_ok
                         and row["action"] in allowed))
                or not batch.JELLYFIN_ID.fullmatch(str(row["jellyfin_id"] or ""))):
            raise RuntimeError("selected_episode_not_eligible_for_source:"+
                               "S%02dE%03d"%tag)
        jid=str(row["jellyfin_id"])
        selected[jid] = str(row["path"])
        if manual_review:
            reviewed.append(jid)
    return {"series":series, "ids":selected,"eligible":len(selected),
            "reviewed":sorted(reviewed),
            "seasons":sorted({sn for sn,ep in wanted}),"skipped":{}}


def native():
    """Import existing installed search/stage/publish components, unchanged."""
    path = SOURCE_CODE
    expected = (
        "ja_first_autofill.py", "ja_first_search_pilot.py",
        "ja_first_stage_saved_batch.py", "ja_first_publish_queue.py",
        "ja_first_priority.py", "ja_first_catalog_manifest.py"
    )
    if not path.is_dir() or path.is_symlink() or any(
        not (path / name).is_file() or (path / name).is_symlink()
        for name in expected
    ):
        raise RuntimeError("existing_source_controller_not_installed")
    if str(path) not in sys.path:
        # Preserve this dashboard's pinned coverage-queue helper ahead of the
        # separately installed source-tool directory.
        sys.path.append(str(path))
    import ja_first_autofill as autofill
    import ja_first_search_pilot as search
    import ja_first_stage_saved_batch as stage
    import ja_first_publish_queue as publish
    return autofill, search, stage, publish


def container_video_paths(rows):
    """Use live Docker mount mapping; never guess a container media path."""
    run=subprocess.run(
        ["docker","inspect","--format","{{json .Mounts}}","sublarr-pilot"],
        capture_output=True,text=True,timeout=12,check=False)
    if run.returncode:
        print("SEASON_JA_PATH_MATCH unavailable_metadata_search_only",flush=True)
        return {}
    mounts=json.loads(run.stdout)
    if not isinstance(mounts,list):
        raise RuntimeError("unexpected_sublarr_mount_metadata")
    result={}
    for row in rows:
        path=Path(str(row.get("host_path") or ""))
        for mount in sorted(mounts,key=lambda x:len(str(x.get("Source") or "")),
                            reverse=True):
            source=str(mount.get("Source") or "")
            target=str(mount.get("Destination") or "")
            if not source.startswith("/") or not target.startswith("/"):
                continue
            if path.is_relative_to(Path(source)):
                result[str(row["jellyfin_id"])]=str(
                    Path(target)/path.relative_to(Path(source)))
                break
    print("SEASON_JA_PATH_MATCH",len(result),"of",len(rows),
          "using_installed_sublarr_mounts",flush=True)
    return result


def manual_source_query(row, search):
    """Exact episode search for an explicitly selected, file-probed unlabeled audio.

    This does not assign an English audio tag to the media. The existing
    publication gate still performs independent same-file safety and sync QA.
    """
    video=Path(str(row.get("host_path") or ""))
    season,episode=row.get("season"),row.get("episode")
    if (row.get("kind")!="Episode" or row.get("status")!="ready_ja_search"
            or type(season) is not int or type(episode) is not int
            or season<1 or episode<1 or not row.get("series_title")
            or not video.is_file() or video.is_symlink()
            or search.sidecar_present(video)):
        return None
    tags=search.episode_tags(video.stem)
    if tags and any(tag!=(season,episode) for tag in tags):
        return None
    query={"file_path":"","language":"ja",
           "series_title":row["series_title"],"season":season,"episode":episode}
    imdb=str(row.get("series_imdb_id") or "")
    if search.IMDB.fullmatch(imdb):
        query["imdb_id"]=imdb
    return query


@contextmanager
def scoped_audio_review(ids, reviewed, search, stage, publish):
    """In-memory exact-ID approval of an owner-selected untagged-audio episode.

    No catalog, database or media identity is modified. The normal Japanese
    source publisher still verifies language, identity, timing and no overwrite.
    """
    if not reviewed:
        yield {}, {}
        return
    from unittest.mock import patch
    manifests=sorted(search.ROOT.glob("ja-intake-*.json"))
    if not manifests:
        raise RuntimeError("review_source_manifest_unavailable")
    original_manifest=search.private_manifest
    base=original_manifest(manifests[-1])
    items={str(row.get("jellyfin_id")):row for row in base["items"]
           if isinstance(row,dict)}
    approved={}
    blocked={}
    for jid in reviewed:
        row=items.get(jid)
        allowed={"review_audio_language_unverified","review_missing_media_streams",
                 "ready_ja_search"}
        if (not row or row.get("status") not in allowed
                or row.get("host_path")!=ids[jid]
                or row.get("kind")!="Episode"):
            state=str(row.get("status") or "missing") if row else "missing"
            same_path=bool(row and row.get("host_path")==ids[jid])
            blocked[jid]="manifest="+state+" path_matches="+str(same_path)
            continue
        try:
            # Existing stage code probes the ACTUAL video. It rejects
            # Japanese-audio tags, embedded Japanese, sidecars and wrong paths.
            stage.duration_if_safe(row)
        except (OSError,ValueError,RuntimeError,subprocess.TimeoutExpired) as exc:
            blocked[jid]=type(exc).__name__ + ":" + str(exc)[:80]
            continue
        approved[jid]=dict(row,status="ready_ja_search")
    for jid,reason in blocked.items():
        print("SEASON_JA_REVIEW_HELD",jid,reason,flush=True)
    print("SEASON_JA_AUDIO_REVIEW",len(approved),"eligible",
          len(blocked),"held",flush=True)
    original_inventory=stage.read_inventory
    original_direct=publish.direct.read_inventory
    def patched_manifest(path):
        doc=original_manifest(path)
        return dict(doc,items=[approved.get(str(row.get("jellyfin_id")),row)
                               for row in doc["items"]])
    def patched_inventory():
        rows=original_inventory()
        rows.update(approved)
        return rows
    def patched_direct(jid,*,allow_existing_ja=False):
        return approved.get(jid) or original_direct(
            jid,allow_existing_ja=allow_existing_ja)
    with (patch.object(search,"private_manifest",side_effect=patched_manifest),
          patch.object(stage,"read_inventory",side_effect=patched_inventory),
          patch.object(publish.direct,"read_inventory",side_effect=patched_direct)):
        yield approved, blocked


def saved_duration_rejections(stage):
    """Compatibility with older installed source controllers, read-only.

    A host may predate the convenience function but have the same staging DB.
    Do not re-download a known wrong-duration subtitle just to retry a title.
    """
    method=getattr(stage,"rejected_duration_candidates",None)
    if callable(method):
        return method()
    db_path=Path(stage.STAGE_DB)
    if not db_path.exists():
        return set()
    if (not db_path.is_file() or db_path.is_symlink()
            or db_path.stat().st_uid!=os.getuid()
            or db_path.stat().st_mode & 0o077):
        raise RuntimeError("unsafe_existing_stage_database")
    with sqlite3.connect("file:"+str(db_path)+"?mode=ro",
                         uri=True,timeout=10) as db:
        return {(str(jid),str(sid)) for jid,sid in db.execute(
            "SELECT jellyfin_id,subtitle_id FROM staged "
            "WHERE status='held_duration_mismatch'")}


def find_japanese(ids, search, budget, *, recheck=False, approved_reviews=None, stage=None):
    """Existing Sublarr provider endpoint and existing result classification.

    The ordinary source script does not yet offer season filtering; select the
    exact approved IDs in memory, but reuse its eligibility, scoring, history
    and native Sublarr API worker without changing its installed behavior.
    """
    approved_reviews=approved_reviews or {}
    paths = sorted(search.ROOT.glob("ja-intake-*.json"))
    if not paths:
        raise RuntimeError("source_manifest_unavailable")
    manifest = search.private_manifest(paths[-1])
    indexed = {str(row["jellyfin_id"]): row for row in manifest["items"]
               if isinstance(row, dict) and row.get("jellyfin_id")}
    holds = Counter()
    rows = []
    for jid, path in ids.items():
        row = indexed.get(jid)
        if row is None:
            holds["not_in_source_manifest"] += 1
        elif row.get("host_path") != path:
            holds["manifest_path_mismatch"] += 1
        else:
            rows.append(row)
            if row.get("status") != "ready_ja_search":
                holds[str(row.get("status") or "unknown_source_status")] += 1
    print("SEASON_JA_SOURCE_INVENTORY",json.dumps({
        "matched":len(rows), "eligible_from_manifest":sum(
            row.get("status") == "ready_ja_search" for row in rows),
        "held":dict(holds)},sort_keys=True),flush=True)
    counts = Counter()
    with closing(search.open_db()) as db:
        if recheck:
            jobs = []
            mapped=container_video_paths(rows)
            queue=search.priorities.active_coverage_queue()
            saved={}
            previous=set()
            if approved_reviews and stage is not None:
                for known_jid,raw in stage.read_saved_searches():
                    try:
                        saved[str(known_jid)]=json.loads(raw)
                    except (ValueError,TypeError):
                        pass
                previous=stage.read_staged() | saved_duration_rejections(stage)
            for row in rows:
                jid=str(row["jellyfin_id"])
                saved_action=(queue.get(jid) or ("",))[0]
                if saved_action in ("download_saved_ja","align_existing_staged_ja"):
                    print("SEASON_JA_REUSE_SAVED",jid,saved_action,flush=True)
                    continue  # Prefer quota-free staging/publication before re-search.
                if jid in approved_reviews and stage is not None:
                    prior=saved.get(jid) or {}
                    matched=any(isinstance(c,dict)
                        and stage.identity_ok(row,c)
                        and (jid,str(c.get("subtitle_id"))) not in previous
                        for c in prior.get("candidates",[]))
                    if matched:
                        print("SEASON_JA_REUSE_SAVED",jid,
                              "manual_review_release_match",flush=True)
                        continue
                query=(manual_source_query(row,search) if jid in approved_reviews
                       else search.query_for(row))
                if query is not None:
                    path=mapped.get(jid)
                    if path:
                        query["file_path"]=path
                    jobs.append({"id":jid,"row":row,"query":query})
            jobs=jobs[:budget]
        else:
            jobs = search.pick(rows, db, budget)
        print("SEASON_JA_SEARCH_PLANNED",len(jobs),
              "mode","explicit_recheck" if recheck else "saved_history",flush=True)
        for idx, job in enumerate(jobs, 1):
            row = job["row"]
            label = str(row.get("series_title") or "") + (
                f' S{row["season"]:02d}E{row["episode"]:02d}')
            print("SEASON_JA_SEARCH",idx,len(jobs),label,flush=True)
            search.save_attempt(db, job, "in_progress")
            try:
                run = subprocess.run(
                    ["docker", "exec", "-i", "-e", "PYTHONPATH=/app",
                     "sublarr-pilot", "python3", "-c", search.CONTAINER_WORKER],
                    input=json.dumps([{"id":job["id"],"query":job["query"],
                                       "retry_by_title":bool(recheck)}]),
                    capture_output=True, text=True, timeout=225, check=False)
                if run.returncode:
                    raise RuntimeError("native_container_search_failed")
                messages = [json.loads(line) for line in run.stdout.splitlines()
                            if line.startswith("{")]
                result = next((x for x in messages
                               if str(x.get("id")) == job["id"]), None)
                if not result or not result.get("ok"):
                    category = str((result or {}).get("error") or "")
                    # A provider HTTP error may indicate an exhausted allowance.
                    # Do not spray additional queries against a possible 429.
                    if category == "HTTPError":
                        search.save_attempt(db,job,"error")
                        counts["provider_unavailable"] += 1
                        print("PROVIDER_LIMIT_REACHED stop_search_on_http_error",
                              flush=True)
                        break
                    raise RuntimeError("native_provider_search_failed")
                if result.get("deferred"):
                    # No usable OpenSubtitles/SubDL call: this is NOT "none".
                    # Stop spending requests; later eligible runs can retry.
                    search.save_attempt(
                        db, job, "deferred", result.get("total"),
                        strategy_version=result.get("strategy_version"),
                        query_variant=result.get("query_variant"),
                        provider_gates=result.get("provider_gates"))
                    counts["deferred"] += 1
                    print("SEASON_JA_DEFERRED", label,
                          str(result.get("provider_reason") or "provider_gate_unavailable")[:180],
                          flush=True)
                    break
                options = result.get("results") or []
                if result.get("query_variant") == "title_only_fallback":
                    print("SEASON_JA_TITLE_FALLBACK",label,
                          "initial_total",result.get("initial_total"),
                          "title_total",result.get("total"),flush=True)
                # Keep ALL provider results, even identity rejects, as
                # review-only evidence. The source helper owns durable history.
                rated = [(search.candidate_grade(row,r),r)
                         for r in options if isinstance(r,dict)]
                plausible = sum(grade=="plausible" for grade,_ in rated)
                review = sum(grade=="review" for grade,_ in rated)
                rejected = sum(grade=="reject" for grade,_ in rated)
                status = ("plausible" if plausible else
                          "review" if review else "none")
                search.save_attempt(db,job,status,result.get("total"),rated,
                                    strategy_version=result.get("strategy_version"),
                                    query_variant=result.get("query_variant"),
                                    provider_gates=result.get("provider_gates"))
                print("SEASON_JA_CANDIDATES",label,
                      "provider_total",result.get("total"),
                      "plausible",plausible,"review",review,
                      "rejected_for_review",rejected,flush=True)
                counts[status] += 1
                print("SEASON_JA_RESULT",label,status,
                      "plausible",plausible,"review",review,flush=True)
            except (OSError,RuntimeError,ValueError,subprocess.TimeoutExpired) as exc:
                search.save_attempt(db,job,"error")
                counts["error"] += 1
                print("SEASON_JA_HELD",label,type(exc).__name__,flush=True)
            if idx < len(jobs):
                time.sleep(3.2)  # Keep Sublarr's existing 20 searches/minute pace.
    return counts


def stage_japanese(ids, stage, budget, *, recheck=False):
    inventory = {jid:row for jid,row in stage.read_inventory().items()
                 if jid in ids and row.get("host_path") == ids[jid]}
    saved = [row for row in stage.read_saved_searches()
             if str(row[0]) in inventory]
    if recheck:
        already=stage.read_staged() | saved_duration_rejections(stage)
        chosen=[]
        for jid,raw in saved:
            jid=str(jid)
            row=inventory.get(jid)
            if not row or row.get("status")!="ready_ja_search":
                continue
            try:
                document=json.loads(raw)
            except (TypeError,ValueError):
                continue
            candidates=[c for c in document.get("candidates",[])
                        if isinstance(c,dict)
                        and str(c.get("provider") or "").casefold()
                            in ("opensubtitles","opensubtitlescom")
                        and stage.identity_ok(row,c)
                        and (jid,str(c.get("subtitle_id"))) not in already]
            candidates.sort(key=lambda c:-int(c.get("score") or 0))
            if candidates:
                chosen.append({"row":row,"candidate":candidates[0],
                    "label":str(row.get("series_title"))+
                      " S%02dE%03d"%(row["season"],row["episode"])})
        chosen=chosen[:budget]
    else:
        chosen = stage.choices(inventory,saved,stage.read_staged(),budget,"episode")
    counts = Counter()
    print("SEASON_JA_STAGE_PLANNED",len(chosen),flush=True)
    if not chosen:
        return counts
    with closing(stage.stage_db()) as db:
        for idx,job in enumerate(chosen,1):
            print("SEASON_JA_STAGE",idx,len(chosen),job["label"],flush=True)
            try:
                result = stage.run_one(job,db)
                counts[result] += 1
            except (OSError,RuntimeError,ValueError,subprocess.TimeoutExpired) as exc:
                counts["held"] += 1
                detail = str(exc).lower()
                print("SEASON_JA_HELD",job["label"],type(exc).__name__,
                      str(exc)[:100],flush=True)
                if any(word in detail for word in (
                    "quota","rate_limit","ratelimit","cooling",
                    "exhausted","download_limit","download limit",
                    "allowed subtitles","429","406"
                )):
                    counts["provider_limited"] += 1
                    print("PROVIDER_LIMIT_REACHED",flush=True)
                    break
    return counts


def mark_publication_held(jid, reason):
    """A real staged subtitle failed the publisher's independent timing gate.

    Retain the saved candidate. Queue the failed JA publication as a hold so
    owner-selected PLaMo can preflight English instead of hiding the episode.
    """
    try:
        from . import bruiser_coverage_queue as coverage
    except ImportError:
        import bruiser_coverage_queue as coverage
    note="ja_publication_held_after_real_timing_qa:"+str(reason)[:255]
    try:
        with coverage.queue_db() as db:
            result=coverage.update_task_state(db,jid,"ja","held",note)
        print("SEASON_JA_FALLBACK_AVAILABLE",jid,result["action"],flush=True)
    except (OSError,ValueError,RuntimeError,sqlite3.Error) as exc:
        # Review-target episodes are controlled by another queue task. Never
        # create a fake JA task or invent a successful publication.
        print("SEASON_JA_FALLBACK_NOT_RECORDED",jid,
              type(exc).__name__,str(exc)[:90],flush=True)


def publish_japanese(ids, publish, limit):
    # The established publisher enforces timing identity and never overwrites.
    rows = [row for row in publish.stages() if str(row[0]) in ids]
    grouped = publish.unique_titles(rows,MAX_EPISODES)
    counts = Counter()
    print("SEASON_JA_PUBLISH_PLANNED",len(grouped),flush=True)
    for jid,candidates in grouped.items():
        if counts["published_new"] >= limit:
            break
        print("SEASON_JA_PUBLISH",jid,flush=True)
        try:
            kind,row,chosen = publish.choose(jid,candidates)
            if kind.startswith("published_"):
                publish.mark_completed(jid)
                counts["already_published"] += 1
            elif kind.startswith("ready_"):
                publish.publish_selected(jid,kind,chosen)
                publish.mark_completed(jid)
                counts["published_new"] += 1
            else:
                counts["held"] += 1
                mark_publication_held(jid,"unpublishable_candidate:"+str(kind))
        except (OSError,RuntimeError,ValueError,KeyError,sqlite3.Error) as exc:
            counts["held"] += 1
            print("SEASON_JA_HELD",jid,type(exc).__name__,
                  str(exc)[:100],flush=True)
            mark_publication_held(jid,str(exc))
    return counts


def reconcile():
    try:
        from . import bruiser_coverage_queue as coverage
    except ImportError:
        import bruiser_coverage_queue as coverage
    return coverage.main(["init"])


def run(series,season,picks=None,recheck=False):
    selection = (selected_scope(series,picks,recheck=recheck)
                 if picks is not None else scope(series,season))
    ids = selection["ids"]
    print("SEASON_JA_BEGIN",json.dumps({
        "series":series,"season":season,"eligible":len(ids),
        "skipped":selection["skipped"]},ensure_ascii=False),flush=True)
    if not ids:
        print("SEASON_JA_DONE no_eligible_source_tasks",flush=True)
        return 0
    autofill,search,stage,publish = native()
    fd = autofill.lock()  # same inter-process lock as the daily source worker
    try:
        autofill.ensure_installed()
        settings = autofill.config()
        autofill.safe_source_settings(settings)
        if not autofill.native_search_disabled(settings):
            raise RuntimeError("native_provider_search_still_active")
        autofill.check_scheduler_idle()
        autofill.refresh_manifest()
        # Recheck scope after obtaining the shared source lock.
        current=(selected_scope(series,picks,recheck=recheck)
                 if picks is not None else scope(series,season))
        if current["ids"] != ids:
            raise RuntimeError("source_scope_changed_repreview_required")
        budget=min(MAX_EPISODES,len(ids))
        reviewed=current.get("reviewed",[])
        with scoped_audio_review(ids,reviewed,search,stage,publish) as (approved,blocked):
            effective={jid:path for jid,path in ids.items() if jid not in blocked}
            if not effective:
                raise RuntimeError("all_selected_audio_reviews_held_see_job_log")
            searched=find_japanese(effective,search,budget,recheck=recheck,
                                   approved_reviews=approved,stage=stage)
            staged=stage_japanese(effective,stage,budget,recheck=recheck)
            published=publish_japanese(effective,publish,budget)
        # Re-plan from the existing inventory after new provider evidence.
        # This transitions 'search_ja' -> fallback ONLY after a real no-match.
        reconcile()
        if not (searched or staged or published):
            print("SEASON_JA_NO_WORK",json.dumps({
                "reason": "no_provider_search_or_saved_candidates_eligible",
                "selected":len(ids)},sort_keys=True),flush=True)
            raise RuntimeError("season_source_no_operations_performed_check_manifest_or_search_history")
        print("SEASON_JA_DONE",json.dumps({
            "searched":dict(searched),"staged":dict(staged),
            "published":dict(published)
        },sort_keys=True),flush=True)
    finally:
        os.close(fd)
    return 0


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--series",required=True)
    parser.add_argument("--season",type=int)
    parser.add_argument("--pick",action="append",
                        help="Explicit SxxExxx; multiple selections permitted")
    parser.add_argument("--recheck",action="store_true")
    parser.add_argument("--run",action="store_true")
    args=parser.parse_args(argv)
    if args.pick:
        picks=[]
        for value in args.pick:
            match=batch.re.fullmatch(r"S(\d{1,2})E(\d{1,3})",value,batch.re.I)
            if not match:
                raise ValueError("invalid_pick_sxxexxx")
            picks.append({"season":int(match.group(1)),
                          "episode":int(match.group(2))})
        preview=selected_scope(args.series,picks,recheck=args.recheck)
        if args.run:
            failed=[]
            for season in preview["seasons"]:
                part=[p for p in picks if p["season"]==season]
                try:
                    run(args.series,season,part,recheck=args.recheck)
                except Exception as exc:
                    failed.append(season)
                    print("SEASON_JA_SEASON_HELD",season,type(exc).__name__,
                          str(exc)[:160],flush=True)
                    # Includes unexpected developer errors (e.g. a stale
                    # installed helper). Report a failed overall job, but do
                    # not suppress later explicitly selected seasons.
            print("SEASON_JA_SELECTION_DONE",
                  json.dumps({"attempted_seasons":preview["seasons"],
                              "held_seasons":failed}),flush=True)
            return 1 if failed else 0
        result=preview
    else:
        if args.season is None:
            parser.error("--season or --pick required")
        if args.recheck:
            parser.error("--recheck requires explicit episode selection")
        if args.run:
            return run(args.series,args.season)
        result=scope(args.series,args.season)
    print(json.dumps({k:v for k,v in result.items() if k!="ids"},
                     ensure_ascii=False))
    return 0


if __name__=="__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError,ValueError,OSError,sqlite3.Error) as exc:
        print("SEASON_JA_BLOCKED",type(exc).__name__,str(exc)[:140],
              file=sys.stderr,flush=True)
        raise SystemExit(1)
