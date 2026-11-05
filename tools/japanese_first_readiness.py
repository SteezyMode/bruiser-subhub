#!/usr/bin/env python3
"""No-write Japanese-first acquisition preflight for installed Sublarr 1.18.

Prints only allowlisted status/metadata. No provider searches, DB writes,
file downloads, model calls or media edits. API key stays inside container.
"""
import json
import os
import shutil
import urllib.error
import urllib.parse
import urllib.request

from config import get_settings

BASE = "http://127.0.0.1:5765"
settings = get_settings()
HEADERS = {"X-Api-Key": settings.api_key} if settings.api_key else {}
TARGETS = ("opensubtitles", "subdl", "jimaku", "addic7ed")


def read(path):
    request = urllib.request.Request(BASE + path, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.load(response)


def collection(result, *keys):
    if isinstance(result, list):
        return result
    if isinstance(result, dict):
        for key in keys:
            if isinstance(result.get(key), list):
                return result[key]
        for key in ("results", "items", "data", "profiles", "providers", "folders"):
            if isinstance(result.get(key), list):
                return result[key]
    return []


def safe_call(path):
    try:
        return read(path)
    except (urllib.error.URLError, ValueError, TimeoutError, OSError) as exc:
        print(f"  {path}: unavailable ({type(exc).__name__})", flush=True)
        return None


def scalar(obj, names):
    for name in names:
        value = obj.get(name)
        if isinstance(value, (str, bool, int, float)):
            return value
    return "unknown"


print("=== JAPANESE-FIRST: SUBLARR LIVE READ-ONLY PREFLIGHT ===", flush=True)

status = safe_call("/api/v1/health")
if isinstance(status, dict):
    print("\nHealth status:", scalar(status, ("status", "state", "health")))
    print("Application version:", scalar(status, ("version", "app_version")))

print("\nSync binaries INSIDE container:")
for binary in ("ffsubsync", "ffs", "ffmpeg", "ffprobe", "alass"):
    print(" ", binary, "=", "present" if shutil.which(binary) else "not found")

engines = safe_call("/api/v1/sync/engines")
print("\nSync engine status (read-only):")
if isinstance(engines, dict):
    for key in ("sanity_threshold_ms", "auto_sync_enabled", "engine_order", "enabled"):
        val = engines.get(key)
        if isinstance(val, (str, bool, int, float, list)):
            print(" ", key, "=", val)
elif engines is None:
    print("  status endpoint unavailable")
for entry in collection(engines, "engines"):
    if isinstance(entry, dict):
        print("  engine:", scalar(entry, ("name", "engine", "id")),
              "| available:", scalar(entry, ("available", "is_available")),
              "| timeout_s:", scalar(entry, ("timeout_s", "timeout")))



providers = collection(safe_call("/api/v1/providers"), "providers")
print("\nProvider inventory:", len(providers))
for entry in providers:
    if not isinstance(entry, dict):
        continue
    name = str(scalar(entry, ("name", "provider_name", "id")))
    if any(target in name.lower().replace("_", "") for target in TARGETS):
        print(" ", name,
              "| enabled:", scalar(entry, ("enabled", "is_enabled")),
              "| configured:", scalar(entry, ("configured", "is_configured")),
              "| status:", scalar(entry, ("status", "health_status")))

health = collection(safe_call("/api/v1/providers/health"), "providers")
print("\nObserved provider health:")
for entry in health:
    if not isinstance(entry, dict):
        continue
    name = str(scalar(entry, ("name", "provider", "provider_name", "id")))
    if any(target in name.lower().replace("_", "") for target in TARGETS):
        print(" ", name,
              "| enabled:", scalar(entry, ("enabled", "is_enabled")),
              "| initialized:", scalar(entry, ("initialized",)),
              "| healthy:", scalar(entry, ("healthy", "is_healthy")),
              "| gate:", scalar(entry, ("gate", "search_gate", "reason")),
              "| status:", scalar(entry, ("status", "health", "state")))

profiles = collection(safe_call("/api/v1/language-profiles"), "profiles")
print("\nLanguage profiles:", len(profiles))
for entry in profiles[:20]:
    if not isinstance(entry, dict):
        continue
    print(" ", "id:", scalar(entry, ("id", "profile_id")),
          "| name:", scalar(entry, ("name",)),
          "| languages:", entry.get("languages", entry.get("target_languages", "unknown")),
          "| cutoff:", scalar(entry, ("cutoff", "cutoff_score", "minimum_score")),
          "| upgrade:", scalar(entry, ("upgrade_enabled", "upgrade")))

folders = collection(safe_call("/api/v1/standalone/folders"), "folders")
print("\nStandalone folders:", len(folders))
for item in folders[:20]:
    if not isinstance(item, dict):
        continue
    print(" ", "id:", scalar(item, ("id",)),
          "| path:", scalar(item, ("path", "folder_path")),
          "| enabled:", scalar(item, ("enabled", "scan_enabled", "active")))
    mount_path = item.get("path") or item.get("folder_path")
    if isinstance(mount_path, str) and mount_path.startswith("/") and "\\n" not in mount_path:
        print("    container_path_exists:", os.path.isdir(mount_path),
              "| readable:", os.access(mount_path, os.R_OK))

config = safe_call("/api/v1/config")
if isinstance(config, dict):
    keys = (
        "wanted_anime_only", "wanted_anime_movies_only",
        "wanted_scan_interval_hours", "wanted_search_interval_hours",
        "wanted_auto_translate", "wanted_auto_extract",
        "wanted_search_on_startup", "wanted_scan_on_startup",
        "source_language", "target_language", "upgrade_enabled",
        "auto_sync_enabled", "sync_sanity_threshold_ms",
        "auto_sync_after_download", "wanted_auto_search",
        "wanted_scan_enabled", "wanted_scan_on_startup",
        "wanted_upgrade_enabled", "provider_budget_enabled",
    )
    print("\nSelected automation settings:")
    for key in keys:
        v = config.get(key)
        if isinstance(v, (str, bool, int, float)) and len(str(v)) < 100:
            print(" ", key, "=", v)

wanted = safe_call("/api/v1/wanted?limit=250")
items = collection(wanted, "items", "wanted", "results")
print("\nCurrent Wanted view:", len(items), "items in returned page")
if isinstance(wanted, dict):
    for key in ("total", "page", "page_size", "limit", "has_next"):
        if isinstance(wanted.get(key), (str, int, bool)):
            print(" ", key, "=", wanted[key])
hits = []
for item in items:
    if not isinstance(item, dict):
        continue
    identity = " ".join(str(item.get(k, "")) for k in (
        "title", "series_title", "movie_title", "name", "filename", "path",
    ))
    if "smile 2" not in identity.lower() and "always sunny" not in identity.lower():
        continue
    hits.append(item)
print("Smile 2 / Always Sunny candidate rows:", len(hits))
for row in hits[:10]:
    print(" ", "id:", scalar(row, ("id", "item_id")),
          "| title:", scalar(row, ("title", "series_title", "movie_title", "name")),
          "| language:", scalar(row, ("language", "target_language", "lang")),
          "| status:", scalar(row, ("status",)))

spec = safe_call("/api/v1/openapi.json")
if isinstance(spec, dict):
    operation = spec.get("paths", {}).get("/api/v1/wanted/dry-run", {}).get("post", {})
    schema = operation.get("requestBody", {}).get("content", {}).get("application/json", {}).get("schema", {})
    print("\nDry-run request schema (for a later 1–2 title search):")
    if isinstance(schema, dict):
        print(" ", json.dumps(schema, ensure_ascii=False)[:1500])
    else:
        print("  unavailable")
print("\nDONE: No searches, sync jobs, subtitle downloads, configuration changes or translation started.")
