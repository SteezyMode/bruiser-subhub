#!/usr/bin/env python3
"""Season-ordered, source-first SubHub batch selection using the existing queue.

No second task database, model implementation, or permanent worker. A selected
episode is handed to the installed, checkpointed "subhub-ai" one at a time.
A preview is read-only and shows blocked episodes rather than substituting
unrelated media to reach a requested count.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import time

HOME = Path.home()
DB = HOME / "bruiser-pilot/coverage-queue/coverage.sqlite3"
WORK = HOME / "bruiser-pilot/subhub-translation"
ENGINE = HOME / ".local/bin/subhub-ai"
JELLYFIN_ID = re.compile(r"[0-9a-f]{32}\Z")
READY_ACTION = "validate_english_for_ja_fallback"
MAX_COUNT = 40


def read_queue(path=None):
    path = Path(path or DB)
    if (not path.is_file() or path.is_symlink() or
            path.stat().st_uid != os.getuid() or
            path.stat().st_mode & 0o077):
        raise RuntimeError("private_coverage_queue_unavailable")
    connection = sqlite3.connect(
        "file:" + str(path.resolve()) + "?mode=ro", uri=True, timeout=5)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    return connection


def validate(series, season, count, start):
    if (not isinstance(series, str) or not series.strip() or
            len(series) > 160 or any(ord(ch) < 32 for ch in series)):
        raise ValueError("invalid_series")
    if type(season) is not int or not 1 <= season <= 60:
        raise ValueError("invalid_season")
    if type(count) is not int or not 1 <= count <= MAX_COUNT:
        raise ValueError("invalid_episode_count")
    if type(start) is not int or not 1 <= start <= 999:
        raise ValueError("invalid_start_episode")


def catalog(path=None):
    with read_queue(path) as db:
        rows = db.execute("""
            SELECT series,season FROM media
            WHERE kind='Episode' AND TRIM(series)<>'' GROUP BY series,season
            ORDER BY series COLLATE NOCASE,season
        """).fetchall()
    result = {}
    for row in rows:
        try:
            season = int(row["season"])
        except (ValueError, TypeError):
            continue
        if 1 <= season <= 60:
            result.setdefault(row["series"], set()).add(season)
    return [{"series": s, "seasons": sorted(seasons)}
            for s, seasons in sorted(result.items(), key=lambda a: a[0].casefold())]


def _already_covered(row):
    if row["ja_present"]:
        return True
    # The matrix refresh may lag a successfully published PLaMo sidecar.
    # This is only a skip hint; the underlying engine checks ALL JA sources.
    video = Path(str(row["path"] or ""))
    # Check exact-video JA sidecars, not just our PLaMo output. The queue
    # snapshot may lag a separate human subtitle or successful source publisher.
    try:
        for candidate in video.parent.iterdir():
            if candidate.is_symlink() or not candidate.is_file():
                continue
            if not candidate.name.casefold().startswith(video.stem.casefold() + "."):
                continue
            if candidate.suffix.casefold() not in (".srt", ".ass", ".ssa", ".vtt"):
                continue
            tags = re.findall(r"[a-z0-9]+", candidate.name[len(video.stem):].casefold())
            if (any(x in ("ja", "jp", "jpn", "japanese") for x in tags)
                    and not any(x in ("forced", "signs") for x in tags)
                    and 0 < candidate.stat().st_size <= 2_000_000):
                return True
    except OSError:
        return False
    return False


def plan(series, season, count=20, start=1, *, path=None):
    validate(series, season, count, start)
    with read_queue(path) as db:
        rows = db.execute("""
            SELECT m.path,m.jellyfin_id,m.title,m.series,m.season,m.episode,
                   m.en_text,m.ja_present,t.action,t.state
            FROM media AS m LEFT JOIN tasks AS t
              ON t.path=m.path AND t.target='ja' AND t.active=1
            WHERE m.kind='Episode' AND m.series=? AND m.season=?
            ORDER BY m.path
        """, (series, str(season))).fetchall()
    episodes = {}
    for row in rows:
        try:
            ep = int(row["episode"])
        except (ValueError, TypeError):
            continue
        if start <= ep <= 999:
            episodes.setdefault(ep, []).append(dict(row))
    items = []
    skipped_covered = 0
    for ep in sorted(episodes):
        versions = episodes[ep]
        if any(_already_covered(row) for row in versions):
            skipped_covered += 1
            continue
        if len(versions) != 1:
            item = {"episode": ep, "title": versions[0]["title"],
                    "status": "blocked", "reason": "duplicate_episode_versions"}
        else:
            row = versions[0]
            if (row["action"] == READY_ACTION and row["state"] == "pending"
                    and row["en_text"] and
                    JELLYFIN_ID.fullmatch(str(row["jellyfin_id"] or ""))):
                status, reason = "ready", "verified_english_required_at_runtime"
            else:
                status = "blocked"
                if not row["en_text"]:
                    reason = "english_text_not_ready"
                elif row["action"] in ("search_ja", "download_saved_ja",
                                       "align_existing_staged_ja", "review_saved_ja"):
                    reason = "japanese_source_first"
                else:
                    reason = "not_ready_" + str(row["action"] or "unplanned")[:45]
            item = {"episode": ep, "title": row["title"],
                    "status": status, "reason": reason}
            if status == "ready":
                item["jellyfin_id"] = row["jellyfin_id"]
        items.append(item)
        if len(items) == count:
            break
    ready = sum(x["status"] == "ready" for x in items)
    return {"series": series, "season": season, "start_episode": start,
            "requested": count, "ready": ready, "blocked": len(items)-ready,
            "covered": skipped_covered, "selected": len(items),
            "items": items,
            "note": ("The first missing episodes in season order. Blocked episodes "
                     "are reported, never silently replaced with other seasons.")}


def season_report(series, season, *, path=None):
    """A complete, read-only view of one selected season and its JA outcome.

    Never call providers, never treat a search miss as proof that a human
    subtitle cannot exist, and never infer that unverified timing is correct.
    """
    validate(series, season, MAX_COUNT, 1)
    with read_queue(path) as db:
        rows = db.execute("""
            SELECT m.path,m.jellyfin_id,m.title,m.episode,m.en_text,
                   m.ja_present,t.action,t.state,t.target AS queue_target,
                   t.reason AS queue_reason,t.note AS queue_note
              FROM media AS m LEFT JOIN tasks AS t
                ON t.path=m.path AND t.target IN ('ja','review')
                   AND t.active=1
             WHERE m.kind='Episode' AND m.series=? AND m.season=?
             ORDER BY m.path
        """, (series, str(season))).fetchall()
    # Expose the exact saved provider evidence, without rerunning a paid or
    # quota-limited search. Provider totals are NOT approved subtitle counts.
    evidence = {}
    episode_ids = {str(row["jellyfin_id"]) for row in rows}
    searches = HOME / "bruiser-pilot/ja-first-inventory/japanese-search.sqlite3"
    if (searches.is_file() and not searches.is_symlink()
            and searches.stat().st_uid == os.getuid()
            and not searches.stat().st_mode & 0o077):
        try:
            with sqlite3.connect(
                "file:" + str(searches.resolve()) + "?mode=ro",
                uri=True, timeout=3) as db:
                for rec in db.execute("""
                    SELECT jellyfin_id,outcome,candidate_count,plausible_count,
                           results_json,searched_at FROM searches
                """):
                    jid,outcome,total,plausible,raw,when = rec
                    if jid not in episode_ids:
                        continue
                    try:
                        record = json.loads(raw)
                    except (TypeError, ValueError):
                        record = {}
                    candidates = []
                    for entry in (record.get("candidates") or [])[:12]:
                        if not isinstance(entry, dict):
                            continue
                        candidates.append({
                            "grade":str(entry.get("grade") or "review")[:20],
                            "provider":str(entry.get("provider") or "")[:60],
                            "release":str(entry.get("release_info") or
                                          entry.get("filename") or "")[:160],
                            "score":entry.get("score") if
                                type(entry.get("score")) in (int,float) else None
                        })
                    rejects = []
                    for entry in (record.get("rejected_candidates") or [])[:12]:
                        if isinstance(entry,dict):
                            rejects.append({
                                "provider":str(entry.get("provider") or "")[:60],
                                "release":str(entry.get("release") or "")[:160],
                                "score":entry.get("score") if
                                    type(entry.get("score")) in (int,float) else None})
                    evidence[str(jid)] = {
                        "rejected_count":int(record.get("rejected_count") or 0),
                        "rejected_candidates":rejects,
                        "searched_providers":record.get("searched_providers") or [],
                        "outcome":str(outcome)[:30],
                        "provider_total":record.get("provider_total")
                            if type(record.get("provider_total")) is int else None,
                        "retained_candidates":int(total or 0),
                        "plausible_candidates":int(plausible or 0),
                        "searched_at":int(when or 0),
                        "candidates":candidates
                    }
        except (OSError, sqlite3.Error):
            pass
    versions = {}
    for row in rows:
        try:
            number = int(row["episode"])
        except (TypeError, ValueError):
            continue
        if 1 <= number <= 999:
            versions.setdefault(number, []).append(row)
    if not versions:
        raise RuntimeError("selected_season_not_in_coverage_queue")
    if len(versions) > MAX_COUNT:
        raise RuntimeError("season_exceeds_40_episode_controller_limit")
    items = []
    for number, candidates in sorted(versions.items()):
        if len(candidates) != 1:
            # The queue may include multiple releases, old moved copies, or
            # multiple active task joins for one file. Never silently select
            # one edition for translation or conceal already-covered copies.
            by_path = {}
            for candidate in candidates:
                by_path.setdefault(str(candidate["path"]), candidate)
            editions=list(by_path.values())
            found=sum(bool(_already_covered(row)) for row in editions)
            all_covered=bool(editions) and found==len(editions)
            items.append({
                "episode":number,"title":str(editions[0]["title"]),
                "status":"covered" if all_covered else "review",
                "reason":"duplicate_episode_versions",
                "can_source":False,"can_translate":False,
                "version_count":len(editions),"versions_with_japanese":found,
                "next_action":(
                    "READY · Japanese subtitles present on both versions"
                    if all_covered and len(editions)==2 else
                    "READY · Japanese subtitles present on all versions"
                    if all_covered else
                    f"REVIEW · Japanese on {found}/{len(editions)} editions; choose version")
            })
            continue
        row = candidates[0]
        action, state = str(row["action"] or ""), str(row["state"] or "")
        covered = _already_covered(row)
        jid = str(row["jellyfin_id"] or "")
        if covered:
            status, reason = "covered", "japanese_subtitle_present"
        elif state == "held" or action == "repair_existing_timing":
            status, reason = "review", "timing_or_publication_held"
        elif action == READY_ACTION and state == "pending":
            if row["en_text"] and JELLYFIN_ID.fullmatch(jid):
                status, reason = "ready", "no_accepted_japanese_source_in_saved_search"
            else:
                status, reason = "needs_english", "english_not_verified"
        elif action == "recover_english_for_ja_fallback":
            status, reason = "needs_english", "japanese_search_missed_english_needed"
        elif action in ("search_ja", "download_saved_ja", "align_existing_staged_ja"):
            status, reason = "sourcing", action
        elif action == "review_saved_ja":
            status, reason = "review", "japanese_candidate_needs_review"
        else:
            status, reason = "review", "unresolved_" + action[:42]
        proof = evidence.get(jid)
        searched = bool(proof and proof["outcome"] in ("none","review","plausible")
            and 0 <= time.time()-proof["searched_at"] <= 31*86400)
        # User-requested explicit AI fallback for a reviewed/held source result.
        # Never convert a search error, an unsearched episode, or a duplicate
        # into proof that Japanese is unavailable. English is rechecked by AI.
        # A genuine attempted staged publication can fail timing validation.
        # Do not strand it solely because the snapshot lacks EN text metadata:
        # the exact-file PLaMo handoff will verify a usable English source.
        source_qa_held = bool(state=="held" and
            str(row["queue_note"] or "").startswith(
                "ja_publication_held_after_real_timing_qa:"))
        review_ai = bool(status=="review" and
            (row["en_text"] or source_qa_held) and searched
            and state in ("pending","held")
            and action in ("review_saved_ja", "download_saved_ja",
                           "align_existing_staged_ja", "search_ja")
            and (state=="held" or action=="review_saved_ja")
            and JELLYFIN_ID.fullmatch(jid))
        owner_unlabeled = bool(status=="review" and action=="review_uncertain"
            and row["queue_target"]=="review" and state=="pending"
            and JELLYFIN_ID.fullmatch(jid))
        review_ai = review_ai or owner_unlabeled
        recover_english = bool(status=="needs_english" and
            action=="recover_english_for_ja_fallback" and state=="pending"
            and JELLYFIN_ID.fullmatch(jid))
        retry_source = bool(owner_unlabeled or
            (not covered and JELLYFIN_ID.fullmatch(jid)
             and action in ("search_ja", "download_saved_ja",
                            "align_existing_staged_ja", "review_saved_ja",
                            "validate_english_for_ja_fallback",
                            "recover_english_for_ja_fallback")
             and state in ("pending","held")))
        item = {"episode":number,"title":str(row["title"]),
                "status":status,"reason":reason,
                "queue_reason":str(row["queue_reason"] or "")[:120],
                "queue_note":str(row["queue_note"] or "")[:120],
                "can_source":retry_source,
                "can_translate":status=="ready" or review_ai or recover_english,
                "owner_review_fallback":review_ai,
                "failed_source_qa":source_qa_held,
                "owner_unlabeled_audio":owner_unlabeled,
                "english_indexed":bool(row["en_text"])}
        if owner_unlabeled:
            item["reason"]=("audio_metadata_uncertain_owner_may_choose_verified_english_to_japanese"
                if row["en_text"] else
                "audio_and_english_text_unverified_ai_will_hold_without_real_english")
        elif review_ai:
            item["reason"]="reviewed_source_not_publishable_owner_ai_fallback"
        
        if proof:
            item["search"] = proof
            if status == "ready" and proof["outcome"] == "none":
                item["reason"] = ("search_had_unaccepted_results_review_rejections"
                                  if proof["provider_total"] else
                                  "no_japanese_candidate_found_in_last_search")
        if recover_english:
            item["reason"]="japanese_source_exhausted_english_will_be_searched_and_synced"
        # One explicit next step per episode. Distinguish real Japanese tracks
        # from candidates, provider searches, and translation readiness.
        if covered:
            item["next_action"] = "READY · Japanese subtitles present"
        elif proof and int(proof.get("plausible_candidates") or 0) > 0:
            item["next_action"] = "REPAIR · Japanese candidate found; check timing"
        elif action in ("download_saved_ja", "align_existing_staged_ja",
                        "review_saved_ja"):
            item["next_action"] = "REVIEW · Saved Japanese candidate"
        elif status == "needs_english":
            item["next_action"] = "GET ENGLISH · Search/sync or transcribe with Whisper"
        elif searched and proof["outcome"] == "none" and item["can_translate"]:
            item["next_action"] = "PLAMO OPTION · Last Japanese search had no usable match"
        elif item["can_source"]:
            item["next_action"] = "SEARCH · Japanese subtitles"
        elif item["can_translate"]:
            item["next_action"] = "PLAMO OPTION · Verify Japanese availability first"
        else:
            item["next_action"] = "REVIEW · Media or subtitle status uncertain"
        if item["can_translate"]:
            item["jellyfin_id"] = jid
        items.append(item)
    from collections import Counter
    counts = Counter(item["status"] for item in items)
    return {"series":series, "season":season,"items":items,
            "total":len(items), "covered":counts["covered"],
            "ready":sum(bool(i.get("can_translate")) for i in items),
            "sourcing":counts["sourcing"],
            "needs_english":counts["needs_english"],"review":counts["review"],
            "source_eligible":sum(bool(i.get("can_source")) for i in items),
            "timing_note":"Unverified alignment is never certified accurate."}


def unresolved_plan(series, *, path=None, limit=200):
    """Choose actual source-first fallback tasks without manual episode hunting.

    Do not promote timing-held, partial-provider or unsearched work to PLaMo.
    Only pending JA-exhausted queue actions are eligible; source repair holds
    remain visible in the preview, not silently translated.
    """
    validate(series,1,1,1)
    if type(limit) is not int or not 1<=limit<=200:
        raise ValueError("unresolved_limit_outside_1_to_200")
    with read_queue(path) as db:
        raw=db.execute("""
            SELECT DISTINCT season FROM media WHERE kind='Episode' AND series=?
        """,(series,)).fetchall()
    seasons=sorted({int(row["season"]) for row in raw
                    if str(row["season"] or "").isdigit()
                    and 1<=int(row["season"])<=60})
    ready=[]
    pending=0
    blocked=0
    missing=0
    english_needed=0
    for season in seasons:
        report=season_report(series,season,path=path)
        for item in report["items"]:
            if item["status"]=="covered":
                continue
            missing+=1
            # The owner clicking this batch explicitly authorizes PLaMo
            # for previous real JA timing-QA failures too. Do not silently
            # translate arbitrary reviews, unsearched files, or metadata holds.
            qa_failed = bool(item.get("failed_source_qa") and
                             item.get("owner_review_fallback") and
                             item.get("can_translate"))
            if item.get("can_translate") and (
                    item["status"] in ("ready","needs_english") or qa_failed):
                if len(ready)<limit:
                    ready.append({"season":season,"episode":item["episode"],
                                  "title":item["title"],
                                  "needs_english":item["status"]=="needs_english" or not item.get("english_indexed",False),
                                  "failed_japanese_timing":qa_failed})
                if item["status"]=="needs_english" or not item.get("english_indexed",False):
                    english_needed+=1
            else:
                blocked+=1
                if item.get("can_source") or item["status"] in ("review","sourcing"):
                    pending+=1
    return {"series":series, "total_missing":missing,
            "eligible_total":missing-blocked,
            "selected":len(ready),"needs_english":english_needed,
            "awaiting_japanese_recovery":pending,"blocked":blocked,
            "limit":limit,"picks":ready,
            "note":"Only confirmed source-first fallbacks and real failed Japanese timing QA. Other holds remain in Japanese recovery."}


def selected_episode_plan(series, season, episodes, *, path=None):
    """Require every explicitly requested episode to be source-exhausted and ready."""
    if (not isinstance(episodes, list) or not 1 <= len(episodes) <= MAX_COUNT
            or any(type(n) is not int or not 1 <= n <= 999 for n in episodes)
            or len(set(episodes)) != len(episodes)):
        raise ValueError("invalid_explicit_episode_selection")
    report = season_report(series, season, path=path)
    allowed = {item["episode"]:item for item in report["items"]}
    chosen = []
    for number in sorted(episodes):
        item = allowed.get(number)
        if item is None or not item["can_translate"]:
            raise RuntimeError("selected_episode_not_ready_source_first:E" + str(number))
        chosen.append(item)
    return {"series":series,"season":season,"start_episode":min(episodes),
            "requested":len(episodes),"ready":len(episodes),"blocked":0,
            "covered":report["covered"],"selected":len(episodes),"items":chosen}



def selected_multi_plan(series, selection, *, path=None):
    """Only explicitly selected source-exhausted episodes across seasons."""
    if (not isinstance(selection, list) or not 1 <= len(selection) <= 200
            or any(not isinstance(p,dict) or set(p)!={"season","episode"}
                   or type(p["season"]) is not int or type(p["episode"]) is not int
                   or not 1 <= p["season"] <= 60 or not 1 <= p["episode"] <= 999
                   for p in selection)):
        raise ValueError("invalid_cross_season_selection")
    pairs=[(p["season"],p["episode"]) for p in selection]
    if len(set(pairs))!=len(pairs):
        raise ValueError("duplicate_selected_episode")
    chosen=[]
    for season in sorted({s for s,e in pairs}):
        episodes=[e for s,e in pairs if s==season]
        selected=selected_episode_plan(series,season,episodes,path=path)
        for item in selected["items"]:
            chosen.append(dict(item,season=season))
    chosen.sort(key=lambda r:(r["season"],r["episode"]))
    return {"series":series,"ready":len(chosen),"requested":len(chosen),
            "blocked":0,"selected":len(chosen),"covered":0,"items":chosen,
            "seasons":sorted({s for s,e in pairs})}


def _safe_work_dir():
    if WORK.is_symlink():
        raise RuntimeError("unsafe_translation_workdir")
    WORK.mkdir(parents=True, exist_ok=True, mode=0o700)
    if (WORK.stat().st_uid != os.getuid() or WORK.stat().st_mode & 0o077):
        raise RuntimeError("translation_workdir_not_private")
    return WORK


def run_batch(series, season, count, start, episodes=None, picks=None):
    if not ENGINE.is_file() or ENGINE.is_symlink() or not os.access(ENGINE, os.X_OK):
        raise RuntimeError("subhub_ai_not_installed")
    root = _safe_work_dir()
    lock = root / ".series-batch.lock"
    if lock.is_symlink():
        raise RuntimeError("unsafe_series_batch_lock")
    with lock.open("a+b") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        selected = (selected_multi_plan(series, picks) if picks is not None else
                    selected_episode_plan(series, season, episodes) if episodes is not None else
                    plan(series, season, count, start))
        print("BATCH_BEGIN " + json.dumps({
            k: v for k, v in selected.items() if k not in ("items", "note")},
            ensure_ascii=False), flush=True)
        completed = failed = 0
        for item in selected["items"]:
            tag = f'S{item.get("season",season):02d}E{item["episode"]:02d}'
            if not item.get("can_translate", item["status"]=="ready"):
                print(f'BATCH_BLOCKED {tag} {item["reason"]}', flush=True)
                continue
            print(f'BATCH_ITEM {tag} {item["title"][:120]}', flush=True)
            command = [str(ENGINE), "--apply", "--jellyfin-id",
                       item["jellyfin_id"]]
            if item.get("owner_review_fallback"):
                command.append("--owner-reviewed-source")
            # Existing worker owns the cue checkpoints, thermal safety,
            # English verification, and create-only subtitle publication.
            fatal = False
            with subprocess.Popen(
                    command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT, text=True, bufsize=1) as child:
                for line in child.stdout:
                    print(line, end="", flush=True)
                    if any(marker in line for marker in (
                            "THERMAL_ABORT", "THERMAL_COOLDOWN_TIMEOUT",
                            "GPU_OFFLOAD_NOT_ACTIVE", "GPU_IN_USE",
                            "source_batch_still_running",
                            "CPU_THERMAL_SENSOR_MISSING")):
                        fatal = True
                code = child.wait()
            if code:
                failed += 1
                print(f"BATCH_ITEM_HELD {tag} exit={code}", flush=True)
                if fatal:
                    print("BATCH_STOPPED safety_gate_or_source_conflict", flush=True)
                    return 1
            else:
                completed += 1
                print(f"BATCH_ITEM_OK {tag}", flush=True)
        print(f"BATCH_DONE published={completed} held={failed} "
              f"blocked={selected['blocked']}", flush=True)
        return 1 if failed else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--series", required=True)
    ap.add_argument("--season", type=int, required=True)
    ap.add_argument("--count", type=int, default=20)
    ap.add_argument("--start", type=int, default=1)
    ap.add_argument("--pick", action="append", help="Exact SxxExxx; repeat for other episodes")
    ap.add_argument("--episode", type=int, action="append",
                    help="Exact episode to translate; repeat for explicit selection")
    ap.add_argument("--run", action="store_true",
                    help="Run eligible selected episodes via existing subhub-ai")
    args = ap.parse_args(argv)
    try:
        picks=None
        if args.pick:
            picks=[]
            for value in args.pick:
                match=re.fullmatch(r"S(\d{1,2})E(\d{1,3})",value,re.I)
                if not match:
                    raise ValueError("invalid_pick_sxxexxx")
                picks.append({"season":int(match.group(1)),
                              "episode":int(match.group(2))})
        if args.run:
            return run_batch(args.series,args.season,args.count,args.start,
                             episodes=args.episode,picks=picks)
        print(json.dumps(plan(args.series,args.season,args.count,args.start),
                         ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
        print("BATCH_HELD " + type(exc).__name__ + " " + str(exc)[:180],
              file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
