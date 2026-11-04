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
import json, sys, time
from urllib.request import Request, urlopen
from config import get_settings

jobs = json.load(sys.stdin)
key = get_settings().api_key
headers = {"Content-Type": "application/json"}
if key:
    headers["X-Api-Key"] = key
url = "http://127.0.0.1:5765/api/v1/providers/search"
for i, job in enumerate(jobs):
    if i:
        time.sleep(3.3)
    payload = job["query"]
    try:
        req = Request(url, data=json.dumps(payload).encode(), headers=headers, method="POST")
        with urlopen(req, timeout=90) as res:
            data = json.load(res)
        results = []
        for r in data.get("results", [])[:50]:
            if not isinstance(r, dict):
                continue
            results.append({k: r.get(k) for k in (
                "provider", "subtitle_id", "filename", "release_info",
                "language", "score", "matches", "format", "forced", "kind"
            )})
        out = {"id": job["id"], "ok": True, "total": data.get("total"),
               "results": results}
    except Exception as exc:
        out = {"id": job["id"], "ok": False, "error": type(exc).__name__}
    print(json.dumps(out, ensure_ascii=False), flush=True)
'''


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
        if conflicting_year:
            return "review" if exact_identity else "reject"
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
        if not IMDB.fullmatch(str(imdb)) or not row.get("title"):
            return None
        return dict(base, title=row["title"], imdb_id=imdb)
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


def pick(rows, db, budget):
    """Sort catalog metadata in memory; touch ONLY a few shortlisted files."""
    now = int(time.time())
    done = {str(r[0]) for r in db.execute(
        """SELECT jellyfin_id FROM searches WHERE
            (outcome = 'in_progress' AND searched_at >= ?)
            OR (outcome = 'error' AND searched_at >= ?)
            OR (outcome NOT IN ('in_progress', 'error') AND searched_at >= ?)""",
        (now - 6 * 3600, now - 86400, now - 30 * 86400)
    )}
    by_type = {"Movie": [], "Episode": []}
    for row in rows:
        kind = row.get("kind")
        key = str(row.get("jellyfin_id") or "")
        if (kind not in by_type or not key or key in done
                or row.get("status") != "ready_ja_search"):
            continue
        # Cheap checks only. Do not stat media or enumerate directories here.
        if not isinstance(row.get("host_path"), str):
            continue
        if Path(row["host_path"]).suffix.lower() not in SUPPORTED:
            continue
        if kind == "Movie":
            if not IMDB.fullmatch(str(row.get("imdb_id") or "")) or not row.get("title"):
                continue
        else:
            season, episode = row.get("season"), row.get("episode")
            if not (row.get("series_title") and type(season) is int
                    and season >= 1 and type(episode) is int and episode >= 1):
                continue
        by_type[kind].append((hashlib.sha256(key.encode()).hexdigest(), row))

    for kind in by_type:
        by_type[kind].sort(key=lambda pair: pair[0])

    quotas = {"Movie": (budget + 1) // 2, "Episode": budget // 2}
    chosen = []
    for kind in ("Movie", "Episode"):
        count = 0
        for _, row in by_type[kind]:
            if count >= quotas[kind]:
                break
            query = query_for(row)  # Only now access the media drive.
            if query is None:
                continue
            chosen.append({"id": str(row["jellyfin_id"]), "row": row, "query": query})
            count += 1
    if len(chosen) < budget:
        known = {item["id"] for item in chosen}
        extras = sorted(
            (pair for values in by_type.values() for pair in values
             if str(pair[1]["jellyfin_id"]) not in known),
            key=lambda pair: pair[0]
        )
        for _, row in extras:
            if len(chosen) >= budget:
                break
            query = query_for(row)
            if query is not None:
                chosen.append({"id": str(row["jellyfin_id"]), "row": row, "query": query})
    return chosen


def save_attempt(db, job, outcome, total=None, rated=None):
    """Write each search result immediately, including interrupted attempts."""
    rated = rated or []
    plausible = [r for grade, r in rated if grade == "plausible"]
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
    """, (job["id"], int(time.time()), job["row"]["kind"],
          job["row"]["title"], outcome, len(rated), len(plausible),
          json.dumps({"provider_total": total,
                      "candidates": [{"grade": grade, **r} for grade, r in rated]},
                     ensure_ascii=False)))
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


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--budget", type=int, default=2, help="1..12 provider-search requests")
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--report", action="store_true", help="print stored results; no provider searches")
    args = ap.parse_args()
    if args.self_test:
        checks()
        return
    if args.report:
        offline_report()
        return
    if not 1 <= args.budget <= 12:
        ap.error("--budget must be 1..12")
    manifests = sorted(ROOT.glob("ja-intake-*.json")) if ROOT.is_dir() else []
    if not manifests:
        raise RuntimeError("No saved Japanese-first intake manifest")
    manifest = manifests[-1]
    data = private_manifest(manifest)
    print("=== JAPANESE SEARCH PILOT (LIVE PROGRESS) ===", flush=True)
    print("Selecting candidates from manifest (in-memory first)...", flush=True)
    with open_db() as db:
        chosen = pick(data["items"], db, args.budget)
        print("Inventory:", manifest.name, flush=True)
        print("Search requests planned:", len(chosen), "| budget:", args.budget, flush=True)
        print("Movie / Episode:", dict(Counter(j["row"]["kind"] for j in chosen)),
              flush=True)
        if not chosen:
            print("No new eligible items for this run.", flush=True)
            return
        summary = Counter()
        for i, job in enumerate(chosen, 1):
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
                                               "query": job["query"]}]),
                    text=True, capture_output=True, timeout=110
                )
                if run.returncode != 0:
                    raise RuntimeError("container_search_failed")
                results = [json.loads(line) for line in run.stdout.splitlines()
                           if line.startswith("{")]
                response = next((r for r in results
                                 if str(r.get("id")) == job["id"]), None)
                if not response or not response.get("ok"):
                    raise RuntimeError((response or {}).get("error", "no_response"))
            except (subprocess.TimeoutExpired, OSError, ValueError, RuntimeError) as exc:
                save_attempt(db, job, "error")
                summary["search_errors"] += 1
                print(f"[{i}/{len(chosen)}] ERROR: {type(exc).__name__} (retry after 1 day)",
                      flush=True)
                continue
            options = response.get("results") or []
            rated = [(grade, r) for r in options if isinstance(r, dict)
                     for grade in [candidate_grade(row, r)] if grade != "reject"]
            plausible = [r for grade, r in rated if grade == "plausible"]
            review = [r for grade, r in rated if grade == "review"]
            outcome = "plausible" if plausible else ("review" if review else "none")
            save_attempt(db, job, outcome, response.get("total"), rated)
            summary[outcome] += 1
            print(f"[{i}/{len(chosen)}] {outcome.upper()}: plausible={len(plausible)} "
                  f"review={len(review)} provider_total={response.get('total')}",
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
            if i < len(chosen):
                time.sleep(3.2)  # Sublarr endpoint is limited to 20 searches/minute.
        print("\n=== RESULT ===", flush=True)
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
