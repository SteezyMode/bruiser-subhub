#!/usr/bin/env python3
"""One-time, guarded deletion of stale German Wanted requests for American Dad.

For use inside the owner's Sublarr 1.18 container with PYTHONPATH=/app.
By default performs only a preview. --apply uses Sublarr's official Wanted
DELETE API, and saves a persistent snapshot of all removed records first.

Never edits video, subtitle, language profile, provider credentials, timers,
worker jobs or Jellyfin. Never clears the Japanese Wanted rows.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

BASE = "http://127.0.0.1:5765/api/v1"
BATCH = 200
BACKUP_DIR = Path("/config/subhub-v2/ja-first-cleanup")
ALLOWED = (
    "/media/american-dad-main/",
    "/media/american-dad-2tb/",
)


def api(path: str, method: str = "GET"):
    from config import get_settings
    key = get_settings().api_key
    headers = {"X-Api-Key": key} if key else {}
    req = Request(BASE + path, headers=headers, method=method)
    with urlopen(req, timeout=30) as response:
        return json.load(response)


def list_all_wanted():
    rows = []
    declared_total = None
    for page_no in range(1, 21):
        query = urlencode({"page": page_no, "per_page": BATCH,
                           "sort_by": "added_at", "sort_dir": "desc"})
        response = api("/wanted?" + query)
        chunk = response.get("items", response.get("data"))
        if not isinstance(chunk, list):
            raise RuntimeError("Unexpected Wanted page response")
        if declared_total is None:
            declared_total = int(response.get("total", -1))
            if declared_total < 0 or declared_total > 4000:
                raise RuntimeError("Wanted total unavailable or outside pilot scope")
        rows.extend(chunk)
        if len(chunk) < BATCH:
            break
    else:
        raise RuntimeError("Wanted pagination exceeded 20 pages")
    if len(rows) != declared_total:
        raise RuntimeError(f"Wanted pagination changed: collected {len(rows)}, expected {declared_total}")
    return rows


def verify_readiness(rows, *, config, profiles, wanted_status, standalone_status):
    # The known 2026-11-04 pilot state is deliberately pinned, so this tool
    # cannot quietly become a general-purpose subtitle deletion utility.
    if len(profiles) != 1 or profiles[0].get("target_languages") != ["ja"]:
        raise RuntimeError("Expected exactly one Japanese-only language profile")
    if any(config.get(k) != expected for k, expected in {
        "source_language": "en",
        "target_language": "ja",
        "wanted_anime_only": False,
        "upgrade_enabled": False,
        "wanted_scan_interval_hours": 0,
        "wanted_search_interval_hours": 0,
    }.items()):
        raise RuntimeError("Live configuration changed; no deletion")
    if wanted_status.get("is_scanning") or wanted_status.get("is_searching"):
        raise RuntimeError("Wanted scanner is active; no deletion")
    if standalone_status.get("scanner_scanning"):
        raise RuntimeError("Standalone scanner is active; no deletion")
    if len({row.get("id") for row in rows}) != len(rows):
        raise RuntimeError("Duplicate or missing Wanted identifiers")

    by_path = defaultdict(dict)
    counts = Counter()
    for row in rows:
        language = str(row.get("target_language") or "").lower()
        path = row.get("file_path") or ""
        if language not in ("ja", "de"):
            raise RuntimeError("Unexpected Wanted language: " + language)
        if row.get("status") != "wanted" or row.get("subtitle_type", "full") != "full":
            raise RuntimeError("Unexpected Wanted state or forced-subtitle row")
        if not any(path.startswith(root) for root in ALLOWED):
            raise RuntimeError("Unexpected Wanted media root")
        if not isinstance(row.get("id"), int):
            raise RuntimeError("Missing integer Wanted ID")
        if language in by_path[path]:
            raise RuntimeError("Repeated Wanted language for one file")
        by_path[path][language] = row
        counts[language] += 1

    if len(by_path) != 407 or counts["ja"] != 407:
        raise RuntimeError("Expected 407 distinct Japanese Wanted episodes")
    for path, languages in by_path.items():
        if "ja" not in languages:
            raise RuntimeError("Episode has no Japanese Wanted row")
    de = [languages["de"] for languages in by_path.values() if "de" in languages]
    de.sort(key=lambda row: int(row["id"]))
    return de, counts


def persist_backup(items, profiles, config):
    BACKUP_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    file = BACKUP_DIR / f"american-dad-de-wanted-{stamp}.json"
    payload = {
        "reason": "Japanese-first: stale DE Wanted rows for American Dad",
        "saved_at_utc": stamp,
        "count": len(items),
        "profile_snapshot": profiles,
        "language_config": {k: config.get(k) for k in (
            "source_language", "target_language", "upgrade_enabled",
            "wanted_anime_only", "wanted_scan_interval_hours",
            "wanted_search_interval_hours",
        )},
        "removed_wanted_rows": items,
    }
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    fd = os.open(str(file), flags, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as out:
        json.dump(payload, out, ensure_ascii=False, indent=2, default=str)
        out.write("\n")
        out.flush()
        os.fsync(out.fileno())
    return file


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="Back up and delete only the duplicated DE rows")
    args = parser.parse_args()

    config = api("/config")
    profiles = api("/language-profiles").get("profiles", [])
    wanted_status = api("/wanted/scanner/status")
    standalone_status = api("/standalone/status")
    rows = list_all_wanted()
    german, counts = verify_readiness(
        rows, config=config, profiles=profiles,
        wanted_status=wanted_status, standalone_status=standalone_status,
    )
    print("=== AMERICAN DAD JAPANESE-FIRST CLEANUP ===", flush=True)
    print("Current profile: ", profiles[0].get("name"), profiles[0].get("target_languages"), flush=True)
    print("Wanted languages:", dict(counts), flush=True)
    print("German rows with matching Japanese rows:", len(german), flush=True)

    if not args.apply:
        print("DRY RUN. No changes. Add --apply to save backup and prune DE rows.", flush=True)
        return

    if not german:
        print("ALREADY CLEAN. No deletion needed.", flush=True)
        return
    file = persist_backup(german, profiles, config)
    print("Saved full pre-deletion record snapshot:", file, flush=True)
    print("Deleting only DE Wanted entries via Sublarr API...", flush=True)
    for count, row in enumerate(german, 1):
        result = api("/wanted/" + str(row["id"]), method="DELETE")
        if result.get("status") != "deleted" or int(result.get("id", -1)) != row["id"]:
            raise RuntimeError(f"Delete API did not confirm row {row['id']}; stop")
        if count % 50 == 0 or count == len(german):
            print(f"  {count}/{len(german)} removed", flush=True)

    remaining = list_all_wanted()
    leftover, final_counts = verify_readiness(
        remaining, config=api("/config"),
        profiles=api("/language-profiles").get("profiles", []),
        wanted_status=api("/wanted/scanner/status"),
        standalone_status=api("/standalone/status"),
    )
    if leftover or final_counts["ja"] != 407:
        raise RuntimeError("Unexpected post-deletion counts; inspect snapshot")
    print("VERIFIED: 407 Japanese Wanted records remain; 0 German records.", flush=True)
    print("No media files, subtitle files or timers changed.", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        raise SystemExit(f"STOPPED SAFELY: {type(exc).__name__}: {exc}") from None
