#!/usr/bin/env python3
"""Bounded Japanese-first subtitle DISCOVERY against saved Jellyfin intake.

Host-side. Uses the existing Sublarr API via bounded sequential docker exec calls (no new
credentials), records private results, and never downloads/publishes media.
Strong-looking results are only candidates, NOT release/timing approval.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import time

try:
    from . import ja_first_priority as priorities
except ImportError:
    import ja_first_priority as priorities

ROOT = Path.home() / "bruiser-pilot/ja-first-inventory"
DB = ROOT / "japanese-search.sqlite3"
EXTS = {".srt", ".ass", ".ssa", ".vtt"}
SUPPORTED = {".mkv", ".mp4", ".avi", ".m4v", ".wmv", ".webm", ".ts", ".mov", ".mpg", ".mpeg", ".m2ts"}
IMDB = re.compile(r"tt\d{5,12}\Z", re.I)
TOKENS = re.compile(r"[a-z0-9]+", re.I)
EP = re.compile(r"(?<![a-z0-9])s(\d{1,2})[. _-]*e(\d{1,3})(?!\d)", re.I)
EP_ALT = re.compile(r"(?<!\d)(\d{1,2})x(\d{1,3})(?!\d)", re.I)
AGE_LIMIT = 72 * 3600

# This runs ONLY inside the already-running Sublarr container. The key never
# leaves the container and is never printed or passed on a command line.
CONTAINER_WORKER = r'''
import json, re, sys, time
from urllib.request import Request, urlopen
from config import get_settings

jobs = json.load(sys.stdin)
key = get_settings().api_key
headers = {"Content-Type": "application/json"}
if key:
    headers["X-Api-Key"] = key
url = "http://127.0.0.1:5765/api/v1/providers/search"
health_url = "http://127.0.0.1:5765/api/v1/providers/health"
core = {"opensubtitles", "subdl"}

class SourceProvidersDeferred(Exception):
    def __init__(self, gates):
        self.gates = gates
        super().__init__(str(gates))

def provider_gates():
    try:
        with urlopen(Request(health_url, headers=headers), timeout=15) as res:
            providers = json.load(res).get("providers")
        if not isinstance(providers, list):
            return {"provider_health": "unavailable"}
        gates = {
            p["name"]: ("not_initialized" if not p.get("initialized")
                        else str(p.get("gate") or "unknown"))
            for p in providers if isinstance(p, dict)
            and p.get("name") in core and p.get("enabled")
        }
        return gates or {"ja_source_providers": "not_enabled"}
    except Exception:
        return {"provider_health": "unavailable"}

def require_sources():
    gates = provider_gates()
    # Do NOT require every provider to be open. Sublarr's long-lived search
    # coordinator already skips providers that are paced, throttled or disabled.
    # Blocking an entire library pass when only SubDL is paced loses valid
    # OpenSubtitles coverage (observed on the Nov 11 OptiPlex run).
    if not any(value == "ok" for value in gates.values()):
        raise SourceProvidersDeferred(gates)
    return gates

def request_search(payload):
    before = require_sources()
    req = Request(url, data=json.dumps(payload).encode(), headers=headers, method="POST")
    with urlopen(req, timeout=90) as res:
        data = json.load(res)
    if not isinstance(data, dict) or not isinstance(data.get("results"), list):
        raise RuntimeError("invalid_sublarr_search_response")
    after = provider_gates()
    # A provider can hit stretch pacing during this request. Be conservative:
    # we did not receive individual-provider participation receipts, so this
    # response cannot establish all enabled providers were searched.
    gates = dict(before)
    for name, state in after.items():
        if state != "ok":
            gates[name] = state
        elif name not in gates:
            gates[name] = state
    return data, gates

def blocked_providers(gates):
    return sorted(name for name, state in gates.items() if state != "ok")

def title_words(value):
    return re.findall(r"[a-z0-9]+", str(value or "").casefold())

def credible_movie_hit(data, title, year):
    """Only suppress the refined query for evidence of the SAME movie.

    This is NOT publication approval. Final identity and timing checks still
    run in the host workflow. A shared title word ("Mad") proves nothing.
    """
    needle = title_words(title)
    if not needle:
        return False
    for result in data.get("results") or []:
        if (not isinstance(result, dict)
                or result.get("language") not in ("ja", "jpn")):
            continue
        for source in (result.get("filename"), result.get("release_info")):
            words = title_words(source)
            for i in range(len(words) - len(needle) + 1):
                if words[i:i+len(needle)] != needle:
                    continue
                before = words[i-1] if i else ""
                after = words[i+len(needle)] if i+len(needle) < len(words) else ""
                years = [int(x) for x in (before, after)
                         if re.fullmatch(r"(?:19|20)\d{2}",x)]
                if (years and any(abs(y-int(year))<=1 for y in years)
                        or not years and "title" in (result.get("matches") or [])):
                    return True
    return False

def unique_results(*replies):
    seen = set()
    out = []
    for data in replies:
        for r in data.get("results") or []:
            if not isinstance(r, dict):
                continue
            key = (str(r.get("provider")), str(r.get("subtitle_id")),
                   str(r.get("filename")))
            if key in seen:
                continue
            seen.add(key)
            out.append({k: r.get(k) for k in (
                "provider", "subtitle_id", "filename", "release_info",
                "language", "score", "matches", "format", "forced", "kind"
            )})
    return out[:100]

for i, job in enumerate(jobs):
    if i:
        time.sleep(3.3)
    payload = dict(job["query"])
    request_limit = job.get("request_limit",2)
    if type(request_limit) is not int or not 1 <= request_limit <= 2:
        raise ValueError("invalid_source_search_request_limit")
    truncated_variant = False
    is_episode = (bool(payload.get("series_title"))
                  and type(payload.get("season")) is int
                  and type(payload.get("episode")) is int)
    original = None
    gates = {}
    replies = []
    variant = "original"
    try:
        series_imdb_id = payload.get("imdb_id") if is_episode else None
        if is_episode:
            # Sublarr 1.18 sends series IMDb as an episode IMDb to
            # OpenSubtitles. Do the reliable title+S/E variant first, then
            # the external-ID+S/E variant when the first has no strong hit.
            payload.pop("imdb_id", None)
            payload["file_path"] = ""
            variant = "series_title_episode"
        elif payload.get("title") and payload.get("year") and not payload.get("imdb_id"):
            # The 1.18 combined endpoint DROPS the year field. Put it into
            # the text query so providers can narrow their own search.
            title = str(payload["title"])
            year = str(payload["year"])
            payload["title"] = title if year in title_words(title) else title+" "+year
            variant = "movie_title_year"

        first, gates = request_search(payload)
        replies.append(first)
        original = first.get("total")
        if is_episode and series_imdb_id:
            exact=any(
                isinstance(hit,dict)
                and {"season","episode"}.issubset(set(hit.get("matches") or []))
                and str(hit.get("language") or "").casefold() in ("ja","jpn")
                for hit in first.get("results") or [])
            if not exact and len(replies) < request_limit:
                id_query=dict(payload,imdb_id=series_imdb_id)
                time.sleep(3.3)
                with_id, gates=request_search(id_query)
                replies.append(with_id)
                variant="title_episode_then_series_imdb_episode"
            elif not exact:
                truncated_variant = True
                variant = "series_title_episode_refinement_budget_deferred"
        if (not is_episode and payload.get("imdb_id")
                and payload.get("title") and payload.get("year")
                and not credible_movie_hit(first, payload["title"], payload["year"])):
            # A full page of unrelated 'Bride', 'Mad' or 'Rainbow' hits is
            # NOT success. Try one year-qualified title lookup, even when the
            # combined provider search returned 50 unrelated subtitles.
            fallback = dict(payload)
            fallback.pop("imdb_id", None)
            fallback["file_path"] = ""
            year = str(fallback["year"])
            title = str(fallback["title"])
            fallback["title"] = title if year in title_words(title) else title+" "+year
            if len(replies) < request_limit:
                time.sleep(3.3)  # Sublarr combined search: 20 requests/minute
                second, gates = request_search(fallback)
                replies.append(second)
                variant = "imdb_then_movie_title_year"
            else:
                truncated_variant = True
                variant = "imdb_movie_title_year_refinement_budget_deferred"

        results = unique_results(*replies)
        missing = blocked_providers(gates)
        out = {
            "id": job["id"], "ok": True,
            "total": sum(int(x.get("total") or 0) for x in replies),
            "initial_total": original,
            "strategy_version": 5, "query_variant": variant,
            "provider_gates": gates, "results": results,
            "partial": bool(missing or truncated_variant),
            "incomplete_providers": missing,
            "requests_made": len(replies),
        }
    except SourceProvidersDeferred as exc:
        # Preserve results from a successful first call if the last provider
        # closed before an optional movie fallback. That is a PARTIAL search,
        # not a total deferral or a fabricated zero-result outcome.
        out = {
            "id": job["id"], "ok": True,
            "deferred": not bool(replies), "partial": bool(replies),
            "total": sum(int(x.get("total") or 0) for x in replies),
            "initial_total": original, "strategy_version": 5,
            "query_variant": "provider_gate_deferred" if not replies else variant,
            "provider_reason": str(exc), "provider_gates": exc.gates,
            "incomplete_providers": blocked_providers(exc.gates),
            "results": unique_results(*replies),
            "requests_made": len(replies),
        }
    except Exception as exc:
        out = {"id": job["id"], "ok": False, "error": type(exc).__name__}
    print(json.dumps(out, ensure_ascii=False), flush=True)
'''


try:
    from . import ja_first_movie_scope as movie_scope
except ImportError:
    import ja_first_movie_scope as movie_scope

def tokens(value):
    return re.findall(r"[a-z]+|[0-9]+", str(value or "").casefold())


def episode_tags(value):
    return [(int(m[1]), int(m[2])) for pattern in (EP, EP_ALT)
            for m in pattern.finditer(str(value or ""))]


def sidecar_present(video):
    prefix = video.stem.casefold() + "."
    try:
        for path in video.parent.iterdir():
            if path.is_symlink() or path.suffix.casefold() not in EXTS:
                continue
            name = path.name.casefold()
            if not name.startswith(prefix):
                continue
            suffix = name[len(prefix):-len(path.suffix)]
            parts = TOKENS.findall(suffix)
            if any(t in {"ja", "jp", "jpn", "japanese"} for t in parts) and (
                "forced" not in parts and "signs" not in parts
            ):
                return True
    except OSError:
        return True  # Fail closed on an unreadable directory
    return False


def candidate_grade(row, result):
    """Grade identity evidence only. Never approve a subtitle download.

    The provider may have a perfectly valid SRT while reporting format=unknown
    (e.g. an extensionless OpenSubtitles filename). Format must be checked
    separately using subtitle bytes after an authorized staging download.
    """
    if str(result.get("language") or "").casefold() not in {"ja", "jpn"}:
        return "reject"
    if result.get("forced") is True or result.get("kind") in {"forced", "signs"}:
        return "reject"
    matches = set(result.get("matches") or [])
    name = str(result.get("filename") or "")
    release = str(result.get("release_info") or "")

    if row["kind"] == "Movie":
        title_tokens = tokens(row.get("title"))
        year = str(row.get("year") or "")
        if not title_tokens or not re.fullmatch(r"\d{4}", year):
            return "review"
        found_title, conflicting_year, exact_identity = False, False, False
        near_year_conflict = False
        for text in (name, release):
            words = tokens(text)
            for i in range(len(words) - len(title_tokens) + 1):
                if words[i:i + len(title_tokens)] != title_tokens:
                    continue
                found_title = True
                preceding = words[i - 1] if i else ""
                following = words[i + len(title_tokens)] if i + len(title_tokens) < len(words) else ""
                if year in (preceding, following):
                    exact_identity = True
                for neighbor in (preceding, following):
                    if re.fullmatch(r"(?:19|20)\d{2}", neighbor) and neighbor != year:
                        conflicting_year = True
                        # A festival-premiere year and theatrical-release year
                        # can legitimately differ by one. Retain the candidate
                        # for REVIEW, never automatic staging/publication.
                        near_year_conflict |= abs(int(neighbor) - int(year)) == 1
        if conflicting_year:
            return "review" if exact_identity or (found_title and near_year_conflict) else "reject"
        if exact_identity:
            return "plausible"
        # Search score alone cannot prove that the candidate is the right film.
        return "review" if found_title or "title" in matches else "reject"

    if row["kind"] == "Episode":
        expected = (row.get("season"), row.get("episode"))
        tags = episode_tags(name + " " + release)
        if tags and any(tag != expected for tag in tags):
            return "reject"
        if {"series", "season", "episode"}.issubset(matches) and expected in tags:
            return "plausible"
        return "review"
    return "reject"


def checks():
    friday = {"kind": "Movie", "title": "Friday", "year": 1995}
    result = {"language": "ja", "format": "srt", "filename": "Friday.1995.1080p"}
    assert candidate_grade(friday, result) == "plausible"
    assert candidate_grade(friday, dict(result, filename="Next.Friday.2000.1080p")) == "reject"
    assert candidate_grade(friday, dict(result, filename="Friday.2010.1080p")) == "reject"
    release_year = {"kind":"Movie","title":"Late Night with the Devil","year":2024}
    premiere = dict(result, filename="Late.Night.with.the.Devil.2023.WEB-DL.ja-JP",
                   matches=["title"])
    assert candidate_grade(release_year, premiere) == "review"
    assert candidate_grade(release_year, dict(premiere, filename="Late.Night.with.the.Devil.2013.WEB-DL")) == "reject"
    assert candidate_grade(release_year, dict(premiere, filename="Late.Night.with.the.Demons.2023.WEB-DL", matches=[])) == "reject"
    assert candidate_grade(friday, dict(result, filename=".srt", matches=["title"])) == "review"
    fargo = {"kind": "Movie", "title": "Fargo", "year": 1996}
    assert candidate_grade(fargo, dict(result, filename="1996-_Fargo",
                                       format="unknown")) == "plausible"
    eastern = {"kind": "Movie", "title": "Eastern Promises", "year": 2007}
    assert candidate_grade(eastern, dict(result, filename="Eastern.Promises.2007.2160p",
                                         format="unknown")) == "plausible"
    lethal = {"kind": "Movie", "title": "Lethal Weapon 2", "year": 1989}
    assert candidate_grade(lethal, dict(result, filename="2_Lethal_Weapon2_1989_Ja-Sub",
                                        format="unknown")) == "plausible"
    smile = {"kind": "Movie", "title": "Smile", "year": 2022}
    assert candidate_grade(smile, dict(result, filename="Smile.2022.Netflix",
                                       format="unknown")) == "plausible"
    episode = {"kind": "Episode", "season": 3, "episode": 5}
    good = {"language": "ja", "format": "unknown", "filename": "From.S03E05.1080p",
            "matches": ["series", "season", "episode"]}
    assert candidate_grade(episode, good) == "plausible"
    assert candidate_grade(episode, dict(good, filename="From.S03E06.1080p")) == "reject"
    assert candidate_grade(episode, dict(good, matches=["season", "episode"])) == "review"
    assert episode_tags("S03E05") == [(3, 5)]
    print("SELF-TEST PASSED (no network or writes)")


def private_manifest(path):
    if not ROOT.is_dir() or ROOT.is_symlink() or ROOT.stat().st_mode & 0o077:
        raise RuntimeError("Unsafe inventory directory")
    if not path.is_file() or path.is_symlink() or path.stat().st_mode & 0o077:
        raise RuntimeError("Missing or unsafe manifest")
    if path.parent != ROOT:
        raise RuntimeError("Manifest must be in the approved private inventory directory")
    if time.time() - path.stat().st_mtime > AGE_LIMIT:
        raise RuntimeError("Manifest is older than 72 hours; regenerate intake")
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema") != 1 or not isinstance(data.get("items"), list):
        raise RuntimeError("Unsupported intake manifest")
    return data


def query_for(row):
    if row.get("status") != "ready_ja_search":
        return None
    # Unknown audio-language tags are not proof a title lacks Japanese
    # subtitles. Search is safe; downstream identity, embedded-track and
    # no-overwrite gates still decide whether publication is allowed.
    audio = str(row.get("audio_language") or "").casefold().strip()
    audio = audio.replace("_", "-").split("-", 1)[0]
    if audio in {"ja", "jp", "jpn", "japanese"}:
        return None
    path = row.get("host_path")
    if not isinstance(path, str) or not path.startswith("/"):
        return None
    video = Path(path)
    if (video.suffix.lower() not in SUPPORTED or video.is_symlink()
            or not video.is_file() or sidecar_present(video)):
        return None
    base = {"file_path": "", "language": "ja"}
    if row.get("kind") == "Movie":
        imdb = row.get("imdb_id", "")
        if not row.get("title") or not re.fullmatch(r"(?:19|20)\d{2}",str(row.get("year") or "")):
            return None
        query=dict(base, title=row["title"], year=row["year"])
        if IMDB.fullmatch(str(imdb)):
            query["imdb_id"]=imdb
        return query
    if row.get("kind") == "Episode":
        series = row.get("series_title")
        season, ep = row.get("season"), row.get("episode")
        if not series or type(season) is not int or season < 1 or type(ep) is not int or ep < 1:
            return None
        # Do not trust a Jellyfin episode ID when its filename explicitly says
        # a different S/E. Such files need independent catalog correction.
        path_tags = episode_tags(video.stem)
        if path_tags and any(tag != (season, ep) for tag in path_tags):
            return None
        q = dict(base, series_title=series, season=season, episode=ep)
        imdb = row.get("series_imdb_id", "")
        if IMDB.fullmatch(str(imdb)):
            q["imdb_id"] = imdb
        return q
    return None


def open_db():
    if DB.is_symlink() or (DB.exists() and DB.stat().st_mode & 0o077):
        raise RuntimeError("Unsafe search state DB")
    old = os.umask(0o077)
    try:
        db = sqlite3.connect(DB, timeout=30)
    finally:
        os.umask(old)
    db.execute("""CREATE TABLE IF NOT EXISTS searches (
        jellyfin_id TEXT PRIMARY KEY,
        searched_at INTEGER NOT NULL,
        kind TEXT NOT NULL,
        title TEXT NOT NULL,
        outcome TEXT NOT NULL,
        candidate_count INTEGER NOT NULL,
        plausible_count INTEGER NOT NULL,
        results_json TEXT NOT NULL
    )""")
    db.commit()
    return db


def pick(rows, db, budget, scope='all', retry_none_after_days=None,
         rescan_missing=False):
    """Sort catalog metadata in memory; touch ONLY a few shortlisted files."""
    now = int(time.time())
    if rescan_missing and (type(rescan_missing) is not bool
                           or retry_none_after_days is not None
                           or not scope.startswith("movies-")):
        raise ValueError("rescan_missing_requires_explicit_movie_scope")
    if (retry_none_after_days is not None and
            (type(retry_none_after_days) is not int
             or not 1 <= retry_none_after_days <= 30
             or scope == "all")):
        raise ValueError("retry_none_requires_explicit_movie_scope_and_days_1_to_30")
    done=set()
    history_timestamps={}
    # Read legacy search DBs too; absence of strategy metadata simply means
    # a no-result entry needs one recheck, not a database migration failure.
    columns={str(col[1]) for col in db.execute("PRAGMA table_info(searches)")}
    projection=("results_json" if "results_json" in columns
                else "NULL AS results_json")
    for jid,outcome,when,raw in db.execute(
        "SELECT jellyfin_id,outcome,searched_at,"+projection+" FROM searches"):
        if rescan_missing:
            # Preserve chronological priority across allowance resets:
            # unfinished films (older history) before movies already
            # rechecked during this owner's interrupted fresh pass.
            history_timestamps[str(jid)]=int(when or 0)
            # Owner-selected genre refresh: one completed provider lookup
            # per missing movie per 20-hour allowance window. Preserve all
            # old candidate evidence; never touch already-covered media.
            if when >= now-20*3600:
                done.add(str(jid))
            elif outcome == "error" and when >= now-86400:
                done.add(str(jid))
            continue
        if outcome == "in_progress" and when >= now-6*3600:
            done.add(str(jid))
        elif outcome == "error" and when >= now-86400:
            done.add(str(jid))
        elif outcome in ("partial","deferred") and when >= now-20*3600:
            # An unavailable provider or rate limit is not a completed search.
            # But retrying the same film in the same allowance window wastes
            # API requests and prevents progress through other movies.
            done.add(str(jid))
        elif outcome not in ("in_progress","error","deferred","partial") and when >= now-30*86400:
            # Zero-result entries made before provider-gate verification are
            # inconclusive and may be retried once with the improved
            # strategy. Existing positive candidates
            # are left untouched; their staging queue already owns them.
            legacy_zero=(outcome=="none")
            if legacy_zero:
                try:
                    legacy_zero=int(json.loads(raw).get("strategy_version") or 0)<4
                except (TypeError,ValueError):
                    legacy_zero=True
            if not legacy_zero:
                # Explicit, bounded owner retry for completed *movie* misses.
                # This does NOT bypass recent provider limits or stage held
                # candidates, and is never enabled in the daily source timer.
                retry_none = (outcome == "none" and
                              retry_none_after_days is not None and
                              when <= now-retry_none_after_days*86400)
                if not retry_none:
                    done.add(str(jid))
    # The persistent coverage queue ranks missing Japanese subtitle work;
    # never burn provider calls on titles already staged, held or headed to AI.
    # A new library item not yet in the last matrix is eligible only AFTER
    # known pending queue items. No arbitrary Movie/Episode quota.
    queue = None if rescan_missing else priorities.active_coverage_queue()
    choices = []
    for row in rows:
        if not movie_scope.matches(row, scope):
            continue
        kind = row.get("kind")
        key = str(row.get("jellyfin_id") or "")
        if (kind not in ("Movie", "Episode") or not key or key in done
                or row.get("status") != "ready_ja_search"):
            continue
        if not isinstance(row.get("host_path"), str):
            continue
        if Path(row["host_path"]).suffix.lower() not in SUPPORTED:
            continue
        if kind == "Movie":
            if not row.get("title") or not re.fullmatch(r"(?:19|20)\d{2}",str(row.get("year") or "")):
                continue
        else:
            season, episode = row.get("season"), row.get("episode")
            if not (row.get("series_title") and type(season) is int
                    and season >= 1 and type(episode) is int and episode >= 1):
                continue
        if rescan_missing:
            # This is an explicit owner-selected fresh provider scan, not
            # coverage-queue work selection. Old held/staged/review outcomes
            # are irrelevant to *search eligibility*, though they remain
            # protected by the downstream staging and no-overwrite gates.
            order = (0, priorities.priority(row))
        else:
            order = priorities.queue_position(row, "search", queue)
            if order is None:
                continue
        age = history_timestamps.get(key,-1) if rescan_missing else 0
        choices.append((order, age, hashlib.sha256(key.encode()).hexdigest(), row))
    choices.sort(key=lambda item: (item[0], item[1], item[2]))
    chosen = []
    for _, _, _, row in choices:
        if len(chosen) >= budget:
            break
        query = query_for(row)  # Only short-listed files get media access.
        if query is not None:
            chosen.append({"id": str(row["jellyfin_id"]), "row": row,
                           "query": query})
    return chosen

def save_attempt(db, job, outcome, total=None, rated=None, *, strategy_version=None, query_variant=None, provider_gates=None, incomplete_providers=None):
    """Retain Japanese discoveries across later misses and failed searches.

    Provider rejects remain review-only; only positively verified candidates
    can pass the independently strict staging and publication code.
    """
    rated = rated or []
    previous = db.execute(
        "SELECT kind,title,outcome,results_json FROM searches WHERE jellyfin_id=?",
        (job["id"],)).fetchone()
    if (previous and outcome in ("in_progress", "error", "deferred")
            and previous[2] not in ("in_progress", "error", "deferred", "none")):
        # Never replace completed evidence with an empty/error attempt,
        # but allow a new initial in_progress record to become error.
        return
    prior = {}
    if previous and previous[0] == job["row"]["kind"] and previous[1] == job["row"]["title"]:
        try:
            prior = json.loads(previous[3])
            if not isinstance(prior,dict):
                prior = {}
        except (ValueError,TypeError):
            prior = {}
    def key(item):
        return (str(item.get("provider") or "").casefold(),
                str(item.get("subtitle_id") or ""),
                str(item.get("filename") or ""))
    kept = {}
    for item in prior.get("candidates",[]):
        if isinstance(item,dict) and item.get("grade") in ("plausible","review"):
            kept[key(item)] = item
    rejected = {}
    for item in prior.get("rejected_candidates",[]):
        if isinstance(item,dict):
            rejected[key(item)] = item
    for grade,item in rated:
        if not isinstance(item,dict):
            continue
        candidate = dict(item,grade=grade)
        if grade in ("plausible","review"):
            kept[key(candidate)] = candidate
            rejected.pop(key(candidate),None)
        elif grade=="reject":
            rejected[key(candidate)] = candidate
    candidates=list(kept.values())[:120]
    rejected_candidates=list(rejected.values())[:120]
    plausible=sum(item["grade"]=="plausible" for item in candidates)
    final=("plausible" if plausible else "review" if candidates else outcome)
    payload={"provider_total":total,"candidates":candidates,
             "rejected_candidates":rejected_candidates,
             "rejected_count":len(rejected_candidates),
             "strategy_version":(strategy_version if isinstance(strategy_version,int)
                                 else prior.get("strategy_version",0)),
             "query_variant":query_variant or prior.get("query_variant","unknown"),
             "provider_gates":provider_gates if isinstance(provider_gates,dict) else prior.get("provider_gates",{}),
             "incomplete_providers":incomplete_providers if isinstance(incomplete_providers,list) else prior.get("incomplete_providers",[]),
             "searched_providers":sorted({str(item.get("provider"))
                 for item in candidates+rejected_candidates if item.get("provider")})}
    db.execute("""INSERT INTO searches (
        jellyfin_id,searched_at,kind,title,outcome,candidate_count,
        plausible_count,results_json
    ) VALUES (?,?,?,?,?,?,?,?)
    ON CONFLICT(jellyfin_id) DO UPDATE SET
        searched_at=excluded.searched_at,
        kind=excluded.kind,title=excluded.title,outcome=excluded.outcome,
        candidate_count=excluded.candidate_count,
        plausible_count=excluded.plausible_count,
        results_json=excluded.results_json
    """,(job["id"],int(time.time()),job["row"]["kind"],
         job["row"]["title"],final,len(candidates),plausible,
         json.dumps(payload,ensure_ascii=False)))
    db.commit()


def offline_report(limit=10):
    """Re-grade saved evidence with current rules. Never rewrite saved history."""
    if not DB.is_file() or DB.is_symlink() or DB.stat().st_mode & 0o077:
        raise RuntimeError("Missing or unsafe search history database")
    # Report mode deliberately permits old inventory manifests: no search
    # happens, so staleness does not expose the live media library to action.
    manifests = sorted(ROOT.glob("ja-intake-*.json"))
    if not manifests:
        raise RuntimeError("No inventory manifest for offline identity lookup")
    manifest = manifests[-1]
    if not manifest.is_file() or manifest.is_symlink() or manifest.stat().st_mode & 0o077:
        raise RuntimeError("Unsafe inventory manifest")
    inventory = json.loads(manifest.read_text(encoding="utf-8"))
    identities = {str(x.get("jellyfin_id")): x
                  for x in inventory.get("items", []) if isinstance(x, dict)}
    with sqlite3.connect("file:" + str(DB) + "?mode=ro", uri=True, timeout=10) as db:
        rows = db.execute(
            """SELECT jellyfin_id,kind,title,outcome,candidate_count,plausible_count,
                      results_json,searched_at FROM searches
               WHERE outcome NOT IN ('in_progress')
               ORDER BY searched_at DESC, title LIMIT ?""",
            (limit,),
        ).fetchall()
    print("=== OFFLINE JAPANESE CANDIDATE RE-GRADE ===", flush=True)
    print("Saved records:", len(rows), "| inventory:", manifest.name, flush=True)
    totals = Counter()
    for id_, kind, title, old_outcome, count, old_plausible, body, when in rows:
        identity = identities.get(str(id_), {})
        name = identity.get("series_title") if kind == "Episode" else identity.get("title")
        label = (f'{name} S{identity.get("season"):02d}E{identity.get("episode"):02d}'
                 if kind == "Episode" and type(identity.get("season")) is int
                 and type(identity.get("episode")) is int
                 else f'{name} ({identity.get("year")})' if name and kind == "Movie"
                 else title)
        try:
            data = json.loads(body)
        except ValueError:
            print("INVALID saved result:", title, flush=True)
            totals["invalid_record"] += 1
            continue
        entries = data.get("candidates") or []
        updated = []
        for result in entries:
            if not isinstance(result, dict) or not identity:
                continue
            grade = candidate_grade(identity, result)
            if grade != "reject":
                updated.append((grade, result))
        good = sum(grade == "plausible" for grade, _ in updated)
        review = sum(grade == "review" for grade, _ in updated)
        fresh_outcome = "plausible" if good else ("review" if review else "none")
        totals[fresh_outcome] += 1
        print(f"\n{label} | original={old_outcome} -> current={fresh_outcome}"
              f" | plausible={good} review={review}", flush=True)
        for grade, result in updated[:10]:
            print(" ", json.dumps({
                "identity": grade, "format_status": result.get("format"),
                "provider": result.get("provider"), "filename": result.get("filename"),
                "release_info": result.get("release_info"),
                "matches": result.get("matches"), "score": result.get("score"),
                "subtitle_id": result.get("subtitle_id")
            }, ensure_ascii=False), flush=True)
    print("\nRE-GRADED SUMMARY:", dict(totals), flush=True)
    print("READ ONLY: no providers contacted, no database changes, no downloads.", flush=True)
    print("Identity plausibility is NOT approval to download or publish.", flush=True)



def recover_saved_reviews(*, apply=False, scope="all"):
    """Reclassify saved Japanese movie evidence; NEVER contact providers.

    Exact-title subtitles differing by one calendar year (festival premiere
    vs theatrical release) are review-only. The original search timestamp is
    retained; a local re-grade is NOT a new provider search.
    """
    if (not ROOT.is_dir() or ROOT.is_symlink() or ROOT.stat().st_mode & 0o077
            or not DB.is_file() or DB.is_symlink() or DB.stat().st_mode & 0o077
            or DB.stat().st_uid != os.getuid()):
        raise RuntimeError("unsafe_private_search_history")
    manifests = sorted(ROOT.glob("ja-intake-*.json"))
    if not manifests:
        raise RuntimeError("no_saved_jellyfin_manifest")
    manifest = manifests[-1]
    if (not manifest.is_file() or manifest.is_symlink()
            or manifest.stat().st_mode & 0o077
            or manifest.stat().st_uid != os.getuid()):
        raise RuntimeError("unsafe_saved_jellyfin_manifest")
    catalog = json.loads(manifest.read_text(encoding="utf-8"))
    identities = {
        str(x.get("jellyfin_id")):x for x in catalog.get("items", [])
        if isinstance(x, dict) and x.get("kind") == "Movie"
    }
    lock_fd = None
    if apply:
        # The live source controller and selected-show jobs share this lock.
        try:
            from . import ja_first_autofill as autofill
        except ImportError:
            import ja_first_autofill as autofill
        lock_fd = autofill.lock()

    try:
        mode = "rw" if apply else "ro"
        with sqlite3.connect("file:" + str(DB) + "?mode=" + mode,
                             uri=True, timeout=30) as db:
            rows = db.execute("""
                SELECT jellyfin_id, title, outcome, candidate_count,
                       plausible_count, results_json
                FROM searches WHERE kind='Movie' AND outcome!='in_progress'
            """).fetchall()
            pending = []
            for jid, title, outcome, count, plausible, raw in rows:
                identity = identities.get(str(jid))
                if not identity or identity.get("title") != title:
                    continue
                if (scope != "all" and
                        (identity.get("status") != "ready_ja_search"
                         or not movie_scope.matches(identity,scope))):
                    continue
                try:
                    data = json.loads(raw)
                except (ValueError, TypeError):
                    continue
                if not isinstance(data, dict):
                    continue
                candidates = list(data.get("candidates") or [])
                rejected = list(data.get("rejected_candidates") or [])
                if not all(isinstance(c,dict) for c in candidates + rejected):
                    continue
                remaining = []
                recovered = []
                for candidate in rejected:
                    if (len(candidates) + len(recovered) < 120 and
                            candidate_grade(identity, candidate) == "review"):
                        recovered.append(dict(candidate,grade="review",
                                              review_reason="title_year_disagreement"))
                    else:
                        remaining.append(candidate)
                if not recovered:
                    continue
                data["candidates"] = candidates + recovered
                data["rejected_candidates"] = remaining
                data["rejected_count"] = len(remaining)
                # Any retained match remains review-only; no publication decision.
                new_outcome = "plausible" if int(plausible) > 0 else "review"
                pending.append((new_outcome, len(data["candidates"]),
                                json.dumps(data,ensure_ascii=False), str(jid), raw,
                                title, identity.get("year"), len(recovered)))
            print("=== SAVED JAPANESE MOVIE REVIEW RECOVERY ===")
            print("Checked:", len(rows), "| Titles recoverable:", len(pending),
                  "| Candidates:", sum(x[-1] for x in pending))
            for item in pending[:20]:
                print("REVIEW:", item[-3], "library year", item[-2],
                      "| retained candidates", item[-1])
            if apply and pending:
                stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                backup = ROOT / ("japanese-search.before-review-recovery-" + stamp + ".sqlite3")
                fd = os.open(backup, os.O_CREAT | os.O_EXCL | os.O_WRONLY |
                             getattr(os,"O_NOFOLLOW",0), 0o600)
                os.close(fd)
                with sqlite3.connect(backup) as saved:
                    db.backup(saved)
                with db:
                    for updated in pending:
                        outcome, count, body, jid, before = updated[:5]
                        cursor = db.execute("""
                            UPDATE searches SET outcome=?, candidate_count=?,
                                results_json=?
                            WHERE jellyfin_id=? AND results_json=?
                        """,(outcome,count,body,jid,before))
                        if cursor.rowcount != 1:
                            raise RuntimeError("saved_search_changed_during_recovery")
                print("BACKUP:", backup)
                print("RECOVERED: review-only candidates; original searched_at preserved")
            else:
                print("READ ONLY: no provider requests, no DB writes, no downloads.")
    finally:
        if lock_fd is not None:
            os.close(lock_fd)


MAX_SEARCHES_PER_RUN = 600


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--budget", type=int, default=12, help="1..600 provider-search requests")
    ap.add_argument("--jellyfin-id",default="",help="search one real catalog item by its external title/season/episode identity")
    ap.add_argument("--scope",choices=movie_scope.SCOPES,default="all",
                    help="filter searches to specified existing movie categories")
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--report", action="store_true", help="print stored results; no provider searches")
    ap.add_argument("--recover-saved", action="store_true",
                    help="audit recoverable saved Japanese movie candidates; no provider requests")
    ap.add_argument("--retry-none-after-days", type=int, default=None,
                    help="OWNER ONLY: retry movie no-result searches after N days (1..30),"
                         " only with a specific movie scope; not a blanket rescan")
    ap.add_argument("--rescan-missing", action="store_true",
                    help="OWNER ONLY: one missing-Japanese movie-category search"
                         " refresh; prior attempts within 20 hours stay skipped")
    ap.add_argument("--apply", action="store_true",
                    help="with --recover-saved, backup and save review-only candidates")
    args = ap.parse_args()
    if args.apply and not args.recover_saved:
        ap.error("--apply requires --recover-saved")
    if args.rescan_missing and (
            args.retry_none_after_days is not None or args.recover_saved
            or args.report or args.self_test or args.jellyfin_id
            or not args.scope.startswith("movies-")):
        ap.error("--rescan-missing requires a selected movies-* scope and no other override")
    if args.retry_none_after_days is not None and (
            args.recover_saved or args.report or args.self_test
            or args.jellyfin_id or args.scope == "all"
            or not 1 <= args.retry_none_after_days <= 30):
        ap.error("--retry-none-after-days requires scoped movie discovery, 1..30")
    if args.self_test:
        checks()
        return
    if args.report:
        offline_report()
        return
    if args.recover_saved:
        recover_saved_reviews(apply=args.apply, scope=args.scope)
        return
    if not 1 <= args.budget <= MAX_SEARCHES_PER_RUN:
        ap.error("--budget must be 1..600")
    manifests = sorted(ROOT.glob("ja-intake-*.json")) if ROOT.is_dir() else []
    if not manifests:
        raise RuntimeError("No saved Japanese-first intake manifest")
    manifest = manifests[-1]
    data = private_manifest(manifest)
    if args.jellyfin_id and not re.fullmatch(r"[a-f0-9]{32}",args.jellyfin_id):
        ap.error("--jellyfin-id must be an exact Jellyfin item ID")
    print("=== JAPANESE SEARCH PILOT (LIVE PROGRESS) ===", flush=True)
    print("Selecting candidates from manifest (in-memory first)...", flush=True)
    with open_db() as db:
        if args.jellyfin_id:
            matches=[r for r in data["items"] if isinstance(r,dict)
                     and r.get("jellyfin_id")==args.jellyfin_id
                     and r.get("kind") in ("Movie","Episode")]
            if len(matches)!=1:
                raise RuntimeError("explicit_source_item_missing_or_ambiguous")
            row=matches[0]
            if not movie_scope.matches(row,args.scope):
                raise RuntimeError("explicit_item_outside_requested_scope")
            query=query_for(row)
            if query is None:
                raise RuntimeError("explicit_item_not_source_ready")
            chosen=[{"id":args.jellyfin_id,"row":row,"query":query}]
        else:
            chosen = pick(data["items"], db, args.budget, scope=args.scope,
                          retry_none_after_days=args.retry_none_after_days,
                          rescan_missing=args.rescan_missing)
        print("Inventory:", manifest.name, "| scope:", args.scope, flush=True)
        print("Movie jobs eligible:", len(chosen),
              "| backend search-request budget:", args.budget,
              "| missing-movie refresh:", args.rescan_missing,
              "| no-result retry days:",
              args.retry_none_after_days if args.retry_none_after_days is not None
              else "normal cooldown", flush=True)
        print("Movie / Episode:", dict(Counter(j["row"]["kind"] for j in chosen)),
              flush=True)
        if not chosen:
            print("No new eligible items for this run.", flush=True)
            return
        summary = Counter()
        requests_used = 0
        for i, job in enumerate(chosen, 1):
            if requests_used >= args.budget:
                print("BACKEND_SEARCH_REQUEST_BUDGET_REACHED:",
                      requests_used, "/", args.budget, flush=True)
                break
            request_cap = min(2, args.budget - requests_used)
            row = job["row"]
            name = row.get("series_title") if row["kind"] == "Episode" else row["title"]
            suffix = (f' S{row["season"]:02d}E{row["episode"]:02d}'
                      if row["kind"] == "Episode" else f' ({row.get("year")})')
            print(f"[{i}/{len(chosen)}] SEARCHING: {name}{suffix}", flush=True)
            save_attempt(db, job, "in_progress")
            command = ["docker", "exec", "-i", "-e", "PYTHONPATH=/app",
                       "sublarr-pilot", "python3", "-c", CONTAINER_WORKER]
            try:
                run = subprocess.run(
                    command, input=json.dumps([{"id": job["id"],
                                               "query": job["query"],
                                               "request_limit": request_cap}]),
                    text=True, capture_output=True, timeout=225
                )
                if run.returncode != 0:
                    raise RuntimeError("container_search_failed")
                results = [json.loads(line) for line in run.stdout.splitlines()
                           if line.startswith("{")]
                response = next((r for r in results
                                 if str(r.get("id")) == job["id"]), None)
                if not response or not response.get("ok"):
                    raise RuntimeError((response or {}).get("error", "no_response"))
                counted = response.get("requests_made")
                if (type(counted) is not int or
                        not 0 <= counted <= request_cap):
                    raise RuntimeError("unverifiable_backend_search_request_count")
                requests_used += counted
            except (subprocess.TimeoutExpired, OSError, ValueError, RuntimeError) as exc:
                # A failed/timeout request can still have reached providers.
                # Charge the full possible per-film cap rather than risk
                # silently exceeding the user-requested source budget.
                requests_used += request_cap
                save_attempt(db, job, "error")
                summary["search_errors"] += 1
                print(f"[{i}/{len(chosen)}] ERROR: {type(exc).__name__} (retry after 1 day)"
                      f" backend_requests_budgeted={requests_used}/{args.budget}",
                      flush=True)
                continue
            if response.get("deferred"):
                print(f"BACKEND_SEARCH_REQUESTS_USED: {requests_used}/{args.budget}",
                      flush=True)
                partial = [(candidate_grade(row, r), r)
                           for r in response.get("results") or []
                           if isinstance(r, dict)]
                save_attempt(db, job, "deferred", response.get("total"), partial,
                             strategy_version=response.get("strategy_version"),
                             query_variant=response.get("query_variant"),
                             provider_gates=response.get("provider_gates"),
                             incomplete_providers=response.get("incomplete_providers"))
                summary["deferred"] += 1
                print(f"[{i}/{len(chosen)}] DEFERRED: {response.get('provider_reason')} "
                      "(remaining items not queried)", flush=True)
                break
            options = response.get("results") or []
            rated = [(candidate_grade(row, r), r)
                     for r in options if isinstance(r, dict)]
            plausible = [r for grade, r in rated if grade == "plausible"]
            review = [r for grade, r in rated if grade == "review"]
            # A zero-candidate result is NOT a complete miss when even one
            # configured Japanese provider was unavailable or participation
            # cannot be established. Keep it eligible for later recovery.
            outcome = ("plausible" if plausible else "review" if review
                       else "partial" if response.get("partial") else "none")
            save_attempt(db, job, outcome, response.get("total"), rated,
                         strategy_version=response.get("strategy_version"),
                         query_variant=response.get("query_variant"),
                         provider_gates=response.get("provider_gates"),
                         incomplete_providers=response.get("incomplete_providers"))
            summary[outcome] += 1
            print(f"[{i}/{len(chosen)}] {outcome.upper()}: plausible={len(plausible)} "
                  f"review={len(review)} provider_total={response.get('total')}"
                  f" strategy={response.get('query_variant')} requests={response.get('requests_made')}"
                  f" incomplete={','.join(response.get('incomplete_providers') or [])}",
                  flush=True)
            if plausible:
                best = sorted(plausible, key=lambda r: -(r.get("score") or 0))[0]
                print("  example:", json.dumps({
                    "provider": best.get("provider"), "filename": best.get("filename"),
                    "score": best.get("score"), "subtitle_id": best.get("subtitle_id")
                }, ensure_ascii=False), flush=True)
            elif review:
                print("  Review examples (NOT approved for downloading):", flush=True)
                for candidate in review[:3]:
                    print(" ", json.dumps({
                        "provider": candidate.get("provider"),
                        "filename": candidate.get("filename"),
                        "release_info": candidate.get("release_info"),
                        "score": candidate.get("score"), "matches": candidate.get("matches")
                    }, ensure_ascii=False), flush=True)
            print(f"BACKEND_SEARCH_REQUESTS_USED: {requests_used}/{args.budget}",
                  flush=True)
            if i < len(chosen) and requests_used < args.budget:
                time.sleep(3.2)  # Sublarr endpoint is limited to 20 searches/minute.
        print("\n=== RESULT ===", flush=True)
        print("BACKEND_SEARCH_REQUESTS_CHARGED:",requests_used,
              "| hard maximum:",args.budget,flush=True)
        for name, n in sorted(summary.items()):
            print(name + ":", n, flush=True)
        print("Private repeat-safe history:", DB, flush=True)
        print("DISCOVERY ONLY: no downloads, publication, library changes or GPU work.",
              flush=True)
        print("Plausible = filename/episode evidence, NOT verified timing or quality.",
              flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("SEARCH PILOT FAILED:", type(exc).__name__, str(exc)[:120], file=sys.stderr)
        raise SystemExit(1) from None
