#!/usr/bin/env python3
"""Read live Sublarr provider *search gates*, safely through the running HTTP API.

Run inside sublarr-pilot with PYTHONPATH=/app. Does not import Subliminal or
start a second ProviderManager, initialize providers, consume search quota,
download subtitles, edit configuration or publish media.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

from config import get_settings

BASE = "http://127.0.0.1:5765"
NAMES = (
    "opensubtitlescom_subliminal",
    "opensubtitles_subliminal",
    "opensubtitles",
    "subdl",
    "jimaku",
    "subf2m",
)


def get_json(path: str):
    cfg = get_settings()
    headers = {"X-Api-Key": cfg.api_key} if cfg.api_key else {}
    request = urllib.request.Request(BASE + path, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        print(f"{path}: HTTP {error.code}", flush=True)
    except (OSError, ValueError, urllib.error.URLError) as error:
        print(f"{path}: {type(error).__name__}", flush=True)
    return None


def show_subset(source: dict, fields: tuple[str, ...]):
    return {
        field: source[field]
        for field in fields
        if field in source and isinstance(source[field], (str, bool, int, float))
    }


def main():
    print("=== SUBLARR LIVE PROVIDER GATES (NO SEARCH) ===", flush=True)
    health = get_json("/api/v1/providers/health")
    statuses = (health or {}).get("providers", [])
    if not isinstance(statuses, list):
        statuses = []
    for name in NAMES:
        item = next((row for row in statuses
                     if isinstance(row, dict) and row.get("name") == name), None)
        if not item:
            print(name, "not present in health response", flush=True)
            continue
        print(json.dumps(show_subset(item, (
            "name", "enabled", "initialized", "healthy", "gate",
            "circuit_breaker_state", "auto_disabled", "throttle_reason",
            "total_searches", "successful_searches", "result_rate",
            "consecutive_failures",
        )), ensure_ascii=False, sort_keys=True), flush=True)

    config = get_json("/api/v1/config")
    if isinstance(config, dict):
        print("\n=== SEARCH CONFIGURATION (ALLOWLISTED) ===", flush=True)
        print(json.dumps(show_subset(config, (
            "provider_budget_enabled", "provider_auto_prioritize",
            "provider_priorities", "provider_cache_ttl_minutes",
            "provider_search_timeout", "provider_search_timeout_seconds",
            "wanted_anime_only", "wanted_search_interval_hours",
            "upgrade_enabled",
        )), ensure_ascii=False, sort_keys=True), flush=True)

    profiles = get_json("/api/v1/language-profiles")
    if isinstance(profiles, dict):
        profiles = profiles.get("profiles", profiles.get("data", []))
    if isinstance(profiles, list):
        print("\n=== JAPANESE PROFILE'S PROVIDER FILTER ===", flush=True)
        for profile in profiles:
            if not isinstance(profile, dict):
                continue
            languages = profile.get("languages", [])
            if isinstance(languages, list) and "ja" not in languages:
                continue
            safe = show_subset(profile, (
                "id", "name", "provider_profile_id", "scoring_preset",
                "cutoff_score", "minimum_score", "min_score",
                "upgrade_enabled",
            ))
            for field in ("providers", "allowed_providers", "provider_names"):
                value = profile.get(field)
                if isinstance(value, list) and all(isinstance(x, str) for x in value):
                    safe[field] = value
            print(json.dumps(safe, ensure_ascii=False, sort_keys=True), flush=True)

    print("\nDONE: no provider searches, downloads, rescans, publishing or model calls.")


if __name__ == "__main__":
    main()
