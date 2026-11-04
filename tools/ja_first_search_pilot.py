#!/usr/bin/env python3
"""Bounded Japanese-first subtitle DISCOVERY against saved Jellyfin intake.

Host-side. Uses the existing Sublarr API via a single docker exec (no new
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
    return TOKENS.findall(str(value or "").casefold())


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
    """Return plausible, review, or reject. This does NOT approve a download."""
    if str(result.get("language") or "").casefold() not in {"ja", "jpn"}:
        return "reject"
    if result.get("forced") is True or result.get("kind") in {"forced", "signs"}:
        return "reject"
    if str(result.get("format") or "").lower() not in {"srt", "ass", "ssa", "vtt"}:
        return "review"
    matches = set(result.get("matches") or [])
    name = str(result.get("filename") or "")
    release = str(result.get("release_info") or "")
    if row["kind"] == "Movie":
        title_tokens = tokens(row.get("title"))
        year = str(row.get("year") or "")
        if not title_tokens or not re.fullmatch(r"\d{4}", year):
            return "review"
        found_title = False
        wrong_year = False
        for text in (name, release):
            words = tokens(text)
            target = title_tokens + [year]
            for i in range(len(words) - len(target) + 1):
                if words[i:i + len(target)] == target:
                    return "plausible"
            for i in range(len(words) - len(title_tokens) + 1):
                if words[i:i + len(title_tokens)] == title_tokens:
                    found_title = True
                    following = words[i + len(title_tokens):]
                    if following and re.fullmatch(r"(?:19|20)\\d{2}", following[0]) and following[0] != year:
                        wrong_year = True
        # Exclude explicit conflicting film years and unrelated search noise.
        # Generic filenames stay in review; they are not automatically valid.
        if wrong_year:
            return "reject"
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
    episode = {"kind": "Episode", "season": 3, "episode": 5}
    good = {"language": "ja", "format": "srt", "filename": "From.S03E05.1080p",
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
    done = {str(r[0]) for r in db.execute(
        "SELECT jellyfin_id FROM searches WHERE searched_at >= ?",
        (int(time.time()) - 30 * 86400,)
    )}
    by_type = {"Movie": [], "Episode": []}
    for r in rows:
        key = str(r.get("jellyfin_id") or "")
        if not key or key in done or r.get("kind") not in by_type:
            continue
        query = query_for(r)
        if query is None:
            continue
        sortkey = hashlib.sha256(key.encode()).hexdigest()
        by_type[r["kind"]].append((sortkey, {"id": key, "row": r, "query": query}))
    for k in by_type:
        by_type[k].sort(key=lambda x: x[0])
    quota = {"Movie": (budget + 1) // 2, "Episode": budget // 2}
    chosen = [v for k in ("Movie", "Episode")
              for _, v in by_type[k][:quota[k]]]
    if len(chosen) < budget:
        known = {x["id"] for x in chosen}
        extras = sorted((t for values in by_type.values() for t in values
                         if t[1]["id"] not in known), key=lambda t: t[0])
        chosen.extend(v for _, v in extras[:budget - len(chosen)])
    return chosen


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--budget", type=int, default=8, help="1..12 provider-search requests")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        checks()
        return
    if not 1 <= args.budget <= 12:
        ap.error("--budget must be 1..12")
    manifests = sorted(ROOT.glob("ja-intake-*.json")) if ROOT.is_dir() else []
    if not manifests:
        raise RuntimeError("No saved Japanese-first intake manifest")
    manifest = manifests[-1]
    data = private_manifest(manifest)
    with open_db() as db:
        chosen = pick(data["items"], db, args.budget)
        print("=== JAPANESE SEARCH PILOT ===", flush=True)
        print("Inventory:", manifest.name)
        print("Search requests planned:", len(chosen), "| budget:", args.budget)
        print("Movie / Episode:", Counter(job["row"]["kind"] for job in chosen))
        if not chosen:
            print("No new eligible items for this run.")
            return
        jobs = [{"id": job["id"], "query": job["query"]} for job in chosen]
        command = ["docker", "exec", "-i", "-e", "PYTHONPATH=/app",
                   "sublarr-pilot", "python3", "-c", CONTAINER_WORKER]
        run = subprocess.run(command, input=json.dumps(jobs), text=True,
                             capture_output=True, timeout=len(jobs) * 100 + 60)
        if run.returncode != 0:
            raise RuntimeError("Sublarr search subprocess failed (no details logged)")
        responses = {}
        for line in run.stdout.splitlines():
            try:
                result = json.loads(line)
                if isinstance(result, dict) and "id" in result:
                    responses[str(result["id"])] = result
            except ValueError:
                pass
        summary = Counter()
        for job in chosen:
            row = job["row"]
            result = responses.get(job["id"])
            if not result or result.get("ok") is not True:
                summary["search_errors"] += 1
                print("ERROR:", row["kind"], row["title"], (result or {}).get("error", "missing_response"))
                continue
            options = result.get("results") or []
            candidates = [r for r in options if isinstance(r, dict) and
                          candidate_grade(row, r) != "reject" and
                          str(r.get("language") or "").lower() in {"ja", "jpn"}]
            rated = [(candidate_grade(row, r), r) for r in candidates]
            plausible = [r for grade, r in rated if grade == "plausible"]
            review = [r for grade, r in rated if grade == "review"]
            outcome = "plausible" if plausible else ("review" if review else "none")
            summary[outcome] += 1
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
            """, (job["id"], int(time.time()), row["kind"], row["title"], outcome,
                  len(candidates), len(plausible), json.dumps({
                      "provider_total": result.get("total"),
                      "candidates": [{"grade": grade, **r} for grade, r in rated],
                  }, ensure_ascii=False)))
            db.commit()
            name = row.get("series_title") if row["kind"] == "Episode" else row["title"]
            suffix = (f' S{row["season"]:02d}E{row["episode"]:02d}'
                      if row["kind"] == "Episode" else f' ({row.get("year")})')
            print(f'{outcome.upper()}: {name}{suffix} | plausible={len(plausible)} review={len(review)} provider_total={result.get("total")}')
            if plausible:
                best = sorted(plausible, key=lambda r: -(r.get("score") or 0))[0]
                print("  example:", json.dumps({
                    "provider": best.get("provider"), "filename": best.get("filename"),
                    "score": best.get("score"), "subtitle_id": best.get("subtitle_id")
                }, ensure_ascii=False))
        print("\n=== RESULT ===")
        for name, n in sorted(summary.items()):
            print(name + ":", n)
        print("Private repeat-safe history:", DB)
        print("DISCOVERY ONLY: no downloads, publication, library changes or GPU work.")
        print("Plausible = filename/episode evidence, NOT verified timing or subtitle quality.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("SEARCH PILOT FAILED:", type(exc).__name__, str(exc)[:120], file=sys.stderr)
        raise SystemExit(1) from None
