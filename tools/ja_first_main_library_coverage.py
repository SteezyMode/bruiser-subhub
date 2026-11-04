#!/usr/bin/env python3
"""Small Japanese-only subtitle availability survey for registered main library mounts.

Sublarr 1.18, run via "docker exec -i -e PYTHONPATH=/app sublarr-pilot python3 -".
Uses Sublarr's existing guessit parser and /providers/search HTTP endpoint.
Does NOT download, save, sync, publish, change Wanted, start a worker or
alter library configuration. By default only PRINTS the candidate manifest.
Add --search to spend up to 12 provider search requests (NOT download credits).

Caveats: provider searches can have their own request limits/cache and may
record provider-search statistics. The simple /providers/search route accepts
movie TITLE but not year, so movie scores are only survey evidence, never
release-verified publication approval. Production intake needs authoritative
Jellyfin/standalone IDs and exact release verification.
"""
from __future__ import annotations

import argparse
from collections import Counter
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import sys
from urllib.request import Request, urlopen

ROOTS = (
    ("/media/bigdisk-video/Movies", "movie"),
    ("/media/expansion-video/Movies", "movie"),
    ("/media/bigdisk-video/Television", "episode"),
    ("/media/expansion-video/Television", "episode"),
)
VIDEO_EXTS = frozenset({".mkv", ".mp4", ".avi", ".m4v", ".wmv", ".webm", ".ts"})
JUNK_NAMES = ("sample", "trailer", "featurette", "behind the scenes", "deleted scene")
SEASON_DIR = re.compile(r"^(?:season|series)[ ._-]*\d{1,3}$|^S\d{1,3}$", re.I)
API = "http://127.0.0.1:5765/api/v1"


def known_series_folder(root: str, path: str) -> str:
    """A folder immediately before 'Season XX' is a stronger series hint than a filename."""
    try:
        folders = Path(path).parent.relative_to(Path(root)).parts
    except ValueError:
        return ""
    for i, name in enumerate(folders):
        if i and SEASON_DIR.match(name):
            return folders[i - 1].strip()
    return ""


def parse_candidate(path: str, root: str, expected_type: str, parsed: dict):
    """Conservative metadata gate: skip ambiguities rather than invent identities."""
    if Path(path).suffix.lower() not in VIDEO_EXTS:
        return None
    if any(s in Path(path).stem.lower() for s in JUNK_NAMES):
        return None
    if parsed.get("type") != expected_type or parsed.get("is_special") or parsed.get("is_ova"):
        return None

    if expected_type == "movie":
        title = str(parsed.get("title") or "").strip()
        try:
            year = int(parsed.get("year") or 0)
        except (TypeError, ValueError):
            return None
        if not title or not 1950 <= year <= 2026 or len(title) > 110:
            return None
        identity = ("movie", title.casefold(), year)
        payload = {"title": title, "language": "ja", "file_path": ""}
        label = f"{title} ({year})"
        return {"path": path, "label": label, "identity": identity,
                "kind": "movie", "payload": payload, "year": year}

    try:
        season, episode = int(parsed.get("season")), int(parsed.get("episode"))
    except (TypeError, ValueError):
        return None
    if not (0 < season < 100 and 0 < episode < 999):
        return None
    if len(parsed.get("episodes") or []) > 1:
        return None
    series = known_series_folder(root, path) or str(parsed.get("title") or "").strip()
    if not series or len(series) > 110:
        return None
    identity = ("episode", series.casefold())
    payload = {
        "series_title": series, "season": season, "episode": episode,
        "language": "ja", "file_path": "",
    }
    return {"path": path, "label": f"{series} S{season:02d}E{episode:02d}",
            "identity": identity, "kind": "episode", "payload": payload}


def sample_one_root(root: str, kind: str, per_root: int):
    """Deterministic, distinct-title sample; walks folders without opening videos."""
    from standalone.parser import parse_media_file

    candidates = {}
    encountered = 0
    for directory, subdirs, files in os.walk(root, followlinks=False):
        # Keep traversal deterministic and ignore hidden/system staging folders.
        subdirs[:] = sorted(d for d in subdirs if not d.startswith("."))
        for name in files:
            if not name.lower().endswith(tuple(VIDEO_EXTS)):
                continue
            path = os.path.join(directory, name)
            encountered += 1
            try:
                candidate = parse_candidate(path, root, kind, parse_media_file(path))
            except (OSError, TypeError, ValueError):
                continue
            if candidate is None:
                continue
            # Deterministic pseudo-random selection, avoiding multiple
            # episodes of one series and multiple releases of one movie.
            key = sha256(candidate["path"].encode("utf-8")).hexdigest()
            identity = candidate["identity"]
            current = candidates.get(identity)
            if current is None or key < current[0]:
                candidates[identity] = (key, candidate)

    chosen = [pair[1] for pair in sorted(candidates.values(), key=lambda x: x[0])[:per_root]]
    return chosen, encountered, len(candidates)


def search(query, api_key: str):
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["X-Api-Key"] = api_key
    req = Request(API + "/providers/search",
                  data=json.dumps(query).encode("utf-8"),
                  headers=headers, method="POST")
    with urlopen(req, timeout=90) as resp:
        return json.load(resp)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--per-root", type=int, default=3,
                        help="distinct titles sampled from each root (default 3)")
    parser.add_argument("--search", action="store_true",
                        help="explicitly run Japanese-only provider searches")
    args = parser.parse_args()
    if not (1 <= args.per_root <= 3):
        parser.error("per-root must be 1..3 (up to 12 searches)")

    print("=== MAIN LIBRARY JAPANESE AVAILABILITY SURVEY ===", flush=True)
    sample = []
    for root, kind in ROOTS:
        if not Path(root).is_dir():
            print(f"ROOT MISSING (SKIPPED): {root}", flush=True)
            continue
        selected, encountered, unique = sample_one_root(root, kind, args.per_root)
        print(f"\nROOT {root}: {encountered} media candidates scanned; "
              f"{unique} distinct parseable identities; {len(selected)} sampled", flush=True)
        for item in selected:
            print(" SELECTED:", item["label"], "|", item["path"], flush=True)
        sample.extend(selected)

    if not sample:
        raise SystemExit("No parseable media in registered mounts; nothing searched.")
    if not args.search:
        print("\nMANIFEST ONLY: no provider search. Add --search for JA-only lookup.", flush=True)
        return

    from config import get_settings
    settings = get_settings()
    print(f"\n=== SEARCHING {len(sample)} TITLES, JAPANESE ONLY ===", flush=True)
    summary = Counter()
    for item in sample:
        print("\n" + item["label"], flush=True)
        try:
            data = search(item["payload"], settings.api_key or "")
        except Exception as exc:
            summary["search_error"] += 1
            print(" ERROR:", type(exc).__name__, str(exc)[:180], flush=True)
            continue
        results = [r for r in data.get("results", [])
                   if str(r.get("language") or "").lower() in ("ja", "jpn")]
        if not results:
            summary["no_ja_candidates"] += 1
            print(" Japanese candidates: 0", flush=True)
            continue
        summary["ja_candidates_present"] += 1
        print(" Japanese candidates:", len(results), flush=True)
        results.sort(key=lambda r: -(r.get("score") or 0))
        for r in results[:3]:
            print(json.dumps({
                "provider": r.get("provider"), "score": r.get("score"),
                "matches": r.get("matches"), "filename": r.get("filename"),
                "subtitle_id": r.get("subtitle_id"),
            }, ensure_ascii=False), flush=True)

    print("\n=== RESULTS (CANDIDATE PRESENCE, NOT VERIFIED QUALITY) ===", flush=True)
    print(dict(summary), flush=True)
    print("No subtitle downloads, output files, Wanted changes or translations requested.", flush=True)
    print("Movie searches on this API are title-based; film/year/release confirmation is still required.", flush=True)


if __name__ == "__main__":
    main()
