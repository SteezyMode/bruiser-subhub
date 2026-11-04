#!/usr/bin/env python3
"""Inspect Japanese candidates from two installed Sublarr provider adapters.

Run inside sublarr-pilot, PYTHONPATH=/app. No subtitle downloads, configs,
publishing, media edits or model calls. Remote searches may use provider quota.
This is a diagnostic, NOT an automatic subtitle acceptance tool.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path

from config import get_settings
from providers import get_provider_manager
from providers.base import VideoQuery
from providers.subliminal_adapter import _to_subliminal_video

PROVIDERS = ("opensubtitlescom_subliminal", "opensubtitles_subliminal")
MOVIE = Path(
    "/media/expansion-video/Movies/Horror/"
    "Smile 2 (2024) [1080p] [WEBRip] [5.1] [YTS.MX]/"
    "Smile.2.2024.1080p.WEBRip.x264.AAC5.1-[YTS.MX].mp4"
)


def fetch_health():
    settings = get_settings()
    request = urllib.request.Request(
        "http://127.0.0.1:5765/api/v1/providers/health",
        headers={"X-Api-Key": settings.api_key} if settings.api_key else {},
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as res:
            data = json.load(res)
    except (OSError, ValueError, urllib.error.URLError) as exc:
        print("Running server health unavailable:", type(exc).__name__, flush=True)
        return
    print("=== RUNNING SERVER PROVIDER GATES ===", flush=True)
    for row in data.get("providers", []):
        if row.get("name") not in PROVIDERS:
            continue
        safe = {}
        for name in ("name", "enabled", "healthy", "initialized",
                     "active_gate", "gate", "gate_reason", "total_searches",
                     "result_rate", "consecutive_failures", "auto_disabled"):
            value = row.get(name)
            if isinstance(value, (str, bool, int, float)):
                safe[name] = value
        print(json.dumps(safe, sort_keys=True), flush=True)


def upstream_matches(result, video):
    source = getattr(result, "provider_data", None)
    original = source.get("subliminal_subtitle") if isinstance(source, dict) else None
    if original is None:
        return []
    try:
        return sorted(str(item) for item in original.get_matches(video))
    except Exception:
        return ["unavailable"]


def candidate_relevance(result, title):
    candidate = " ".join((
        str(getattr(result, "filename", "") or ""),
        str(getattr(result, "release_info", "") or ""),
    )).lower()
    if title == "smile":
        return int("smile" in candidate and ("2" in candidate or "2024" in candidate))
    return int(("sunny" in candidate or "philadelphia" in candidate) and
               ("s01e01" in candidate or "1x01" in candidate))


def inspect_one(manager, label, query, title):
    print("\n===", label, "===", flush=True)
    for name in PROVIDERS:
        provider = manager._providers.get(name)
        if provider is None:
            print(name, "not registered", flush=True)
            continue
        print("\n", name, "searching", flush=True)
        try:
            video = _to_subliminal_video(
                query, required_hashes=getattr(provider, "required_hashes", frozenset())
            )
            results = provider.search(query)
        except Exception as exc:
            print("Error:", type(exc).__name__, str(exc)[:160], flush=True)
            continue
        relevant = [r for r in results if candidate_relevance(r, title)]
        print("Raw results:", len(results),
              "| Filename/release plausible:", len(relevant),
              "| video hash types:", sorted(video.hashes.keys()), flush=True)
        sample = relevant[:8] or results[:3]
        for r in sample:
            print(" FILE:", str(r.filename or "")[:145], flush=True)
            print(" RELEASE:", str(r.release_info or "")[:145], flush=True)
            print(" LANGUAGE:", r.language,
                  "| provider_matches:", sorted(str(x) for x in r.matches),
                  "| upstream_matches:", upstream_matches(r, video),
                  "| forced:", r.forced, "| HI:", r.hearing_impaired,
                  flush=True)
        if not sample:
            print(" No candidates returned", flush=True)


def main():
    fetch_health()
    manager = get_provider_manager()
    if not MOVIE.is_file():
        print("\nSmile 2 video not visible in container; no movie provider searches.")
    else:
        query = VideoQuery(
            file_path=str(MOVIE),
            file_size=MOVIE.stat().st_size,
            title="Smile 2",
            year=2024,
            release_group="YTS.MX",
            source="WEBRip",
            resolution="1080p",
            video_codec="x264",
            languages=["ja"],
        )
        inspect_one(manager, "SMILE 2 / complete metadata", query, "smile")

    sunny = VideoQuery(
        series_title="It's Always Sunny in Philadelphia",
        season=1,
        episode=1,
        year=2005,
        languages=["ja"],
    )
    inspect_one(manager, "ALWAYS SUNNY S01E01 / metadata ONLY",
                sunny, "sunny")
    print("\nDONE: candidates only; no download, sync, publish, scan or translation.")


if __name__ == "__main__":
    main()
