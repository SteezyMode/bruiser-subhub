#!/usr/bin/env python3
"""Read-only gate before enabling Japanese-first subtitle acquisition.

Run inside the installed Sublarr 1.18 Docker container with PYTHONPATH=/app.
Uses the running HTTP API; no scans, provider searches, downloads, worker
restarts, configuration changes, file writes, or translation jobs.

Sublarr's /system/budget controls provider-request pacing. It is NOT an
authoritative count of remaining OpenSubtitles subtitle downloads. Do not
equate those values with the remote provider's 5/20/100-download allowances.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from urllib.parse import urlencode
from urllib.request import Request, urlopen

BASE = "http://127.0.0.1:5765"
API_PATHS = {
    "health": "/api/v1/providers/health",
    "budget": "/api/v1/system/budget",
    "config": "/api/v1/config",
    "folders": "/api/v1/standalone/folders",
    "standalone": "/api/v1/standalone/status",
    "wanted_summary": "/api/v1/wanted/summary",
    "wanted_scanner": "/api/v1/wanted/scanner/status",
}
AUTOMATION_FLAGS = (
    "wanted_anime_only",
    "upgrade_enabled",
    "wanted_auto_translate",
    "wanted_scan_on_startup",
    "wanted_search_on_startup",
    "wanted_scan_interval_hours",
    "wanted_search_interval_hours",
    "upgrade_scan_interval_hours",
    "provider_budget_enabled",
)
PROVIDER = "opensubtitles"
MAX_ROWS = 200


def fetch_json(endpoint: str, api_key: str = ""):
    headers = {"X-Api-Key": api_key} if api_key else {}
    req = Request(BASE + endpoint, headers=headers)
    with urlopen(req, timeout=20) as response:
        return json.load(response)


def safe_get(fetch, path: str, errors: dict):
    try:
        return fetch(path)
    except Exception as exc:
        # Missing API is a blocker, but not cause for mutation or hiding it.
        errors[path] = type(exc).__name__ + ": " + str(exc)[:120]
        return None


def items_of(obj, keys: tuple[str, ...]):
    if isinstance(obj, list):
        return obj
    if isinstance(obj, dict):
        for key in keys:
            if isinstance(obj.get(key), list):
                return obj[key]
    return []


def find_provider(health):
    for p in items_of(health, ("providers",)):
        if isinstance(p, dict) and p.get("name") == PROVIDER:
            return p
    return None


def summarize_wanted(pages: list[dict], max_samples: int):
    counts = Counter()
    samples = []
    for page in pages:
        for item in items_of(page, ("items", "data", "results", "wanted")):
            if not isinstance(item, dict):
                continue
            lang = str(item.get("target_language") or item.get("language") or "").lower()
            status = str(item.get("status") or "unknown").lower()
            kind = str(item.get("subtitle_type") or "full").lower()
            counts[(lang or "unknown", status, kind)] += 1
            if lang not in ("ja", "jpn") or status not in ("wanted", "failed") or kind != "full":
                continue
            if len(samples) < max_samples:
                samples.append({
                    "id": item.get("id"),
                    "status": status,
                    "type": item.get("item_type"),
                    "path": str(item.get("file_path") or ""),
                    "title": str(item.get("title") or ""),
                })
    return counts, samples


def analyze(state, pages, row_limit=6):
    health = find_provider(state.get("health"))
    config = state.get("config") if isinstance(state.get("config"), dict) else {}
    budget = items_of(state.get("budget"), ("providers",))
    pool = next((p for p in budget if p.get("name") == PROVIDER), None)
    folders = items_of(state.get("folders"), ("folders", "data", "items"))
    summary = state.get("wanted_summary") if isinstance(state.get("wanted_summary"), dict) else {}
    scanner = state.get("wanted_scanner") if isinstance(state.get("wanted_scanner"), dict) else {}
    counts, samples = summarize_wanted(pages, row_limit)

    blockers = []
    warnings = []
    if not health:
        blockers.append("Native OpenSubtitles not found in Sublarr provider health")
    else:
        if not health.get("initialized") or not health.get("healthy"):
            blockers.append("Native OpenSubtitles is not initialized and healthy")
        if health.get("gate") != "ok":
            blockers.append("OpenSubtitles search gate: " + str(health.get("gate")))
    if not config.get("provider_budget_enabled", True):
        blockers.append("Sublarr provider request budget is disabled")
    if config.get("upgrade_enabled", False):
        warnings.append("Subtitle upgrades enabled; do not start unattended publication")
    if config.get("wanted_auto_translate", False):
        warnings.append("Generic Wanted auto-translation enabled; keep Hy-MT2 fallback separate")
    if config.get("wanted_anime_only", False):
        warnings.append("Wanted search is anime-only; non-anime titles may not enter the queue")
    if not any(str(i.get("target_language", "")).lower() in ("ja", "jpn")
               for page in pages for i in items_of(page, ("items", "data", "results", "wanted"))
               if isinstance(i, dict)):
        warnings.append("No JA-language wanted items in the returned pages")
    if not any(isinstance(f, dict) and f.get("enabled") for f in folders):
        warnings.append("No enabled standalone watched folders; normal scanning may be inactive")
    if any(isinstance(f, dict) and f.get("outside_media_path") for f in folders):
        warnings.append("One or more watched folders are outside the container media root")
    if scanner.get("is_scanning") or scanner.get("is_searching"):
        warnings.append("Sublarr scanner/search currently active; avoid competing manual runs")
    if not pool:
        warnings.append("No live OpenSubtitles provider-budget snapshot")
    return {
        "health": health,
        "budget": pool,
        "config": {k: config.get(k, "<not reported>") for k in AUTOMATION_FLAGS},
        "folders": [{
            "id": f.get("id"), "path": f.get("path"), "enabled": f.get("enabled"),
            "outside_media_path": f.get("outside_media_path")
        } for f in folders if isinstance(f, dict)],
        "standalone": state.get("standalone"),
        "summary": summary,
        "scanner": {k: scanner.get(k) for k in ("is_scanning", "is_searching", "last_scan_at", "last_search_at")},
        "counts": [{"language": k[0], "status": k[1], "subtitle_type": k[2], "count": n}
                   for k, n in sorted(counts.items())],
        "samples": samples,
        "blockers": blockers,
        "warnings": warnings,
    }


def collect(fetch, max_pages: int, row_limit: int):
    errors = {}
    state = {key: safe_get(fetch, path, errors) for key, path in API_PATHS.items()}
    pages = []
    for page in range(1, max_pages + 1):
        qs = urlencode({"page": page, "per_page": MAX_ROWS, "sort_by": "added_at", "sort_dir": "desc"})
        endpoint = "/api/v1/wanted?" + qs
        result = safe_get(fetch, endpoint, errors)
        if result is None:
            break
        pages.append(result)
        count = len(items_of(result, ("items", "data", "results", "wanted")))
        if count < MAX_ROWS:
            break
    report = analyze(state, pages, row_limit)
    report["pages_checked"] = len(pages)
    report["errors"] = errors
    report["download_quota_notice"] = (
        "Sublarr provider-budget usage is API-request pacing, NOT the remaining "
        "OpenSubtitles download allowance. Quota must be learned from provider "
        "download responses; do not infer 100/day from this endpoint."
    )
    return report


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--pages", type=int, default=3,
                     help="maximum 200-row read-only Wanted pages (default: 3)")
    cli.add_argument("--samples", type=int, default=6,
                     help="maximum candidate rows to print (default: 6)")
    args = cli.parse_args()
    if not (1 <= args.pages <= 20 and 0 <= args.samples <= 20):
        cli.error("pages must be 1..20 and samples 0..20")
    from config import get_settings
    settings = get_settings()
    result = collect(lambda path: fetch_json(path, settings.api_key or ""),
                     args.pages, args.samples)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str), flush=True)
    print("\nREAD-ONLY PREFLIGHT COMPLETE: no scans, searches, downloads, changes or GPU work.", flush=True)
    if result["errors"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
