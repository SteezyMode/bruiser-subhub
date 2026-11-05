#!/usr/bin/env python3
"""Single-title Japanese acquisition probe against the INSTALLED Sublarr Wanted queue.

Requires the existing running Sublarr container with PYTHONPATH=/app.
Makes ONE real provider-search dry-run from an existing legitimate Wanted item.
The official dry-run never saves a subtitle, history, or download; it briefly
changes Wanted status during its search and restores it (so it is NOT literally
a read-only database operation). Provider search quota can be consumed.
No downloads, AI translation, library scan, sync apply or config mutation.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = "http://127.0.0.1:5765"
GOOD_LANGS = {"ja", "jpn", "japanese"}
VIDEO_SUFFIXES = {".mkv", ".mp4", ".m4v", ".avi", ".ts", ".mov", ".wmv"}
MAX_PAGES = 3
PER_PAGE = 100


def api(path: str, headers: dict, payload=None, timeout=30):
    h = dict(headers)
    body = None
    if payload is not None:
        h["Content-Type"] = "application/json"
        body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(BASE + path, data=body, headers=h,
                                     method="POST" if body is not None else "GET")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def find_one_wanted(get, is_file=os.path.isfile, allowed_roots=("/media/",)):
    """Pick one exact existing JA full-dialogue Wanted video, never all jobs."""
    examined = 0
    for page in range(1, MAX_PAGES + 1):
        path = ("/api/v1/wanted?status=wanted&per_page=" + str(PER_PAGE)
                + "&page=" + str(page)
                + "&sort_by=search_count&sort_dir=asc")
        document = get(path)
        rows = document.get("items", []) if isinstance(document, dict) else []
        for row in rows:
            examined += 1
            if not isinstance(row, dict):
                continue
            lang = str(row.get("target_language") or "").lower()
            subt = str(row.get("subtitle_type") or "full").lower()
            status = str(row.get("status") or "").lower()
            fp = row.get("file_path")
            ident = row.get("id")
            if lang not in GOOD_LANGS or subt != "full" or status != "wanted":
                continue
            if isinstance(ident, bool) or not isinstance(ident, int) or ident < 1:
                continue
            if not isinstance(fp, str):
                continue
            p = Path(fp)
            if not any(fp.startswith(root) for root in allowed_roots) or p.suffix.lower() not in VIDEO_SUFFIXES:
                continue
            if os.path.islink(fp) or not is_file(fp):
                continue
            # Never run the first provider-search pilot against a file which
            # already has a named JA SRT; sidecar protection is a core policy.
            if any(any(p.parent.glob(p.stem + suffix)) for suffix in (
                ".ja.srt", ".jpn.srt", ".Japanese.ja.srt",
                ".Bruiser Japanese.ja.srt",
                ".Bruiser E4B Review Japanese.ja.srt",
            )):
                continue
            return row, examined, int(document.get("total", 0))
        if len(rows) < PER_PAGE:
            break
    return None, examined, 0


def summary(item, result):
    allowed = ("wanted_id", "status", "dry_run", "provider", "score",
               "format", "reason", "language", "error", "candidate_count")
    display = {k: v for k in allowed if (v := result.get(k)) is not None
               and isinstance(v, (str, int, float, bool))}
    if "output_path" in result:
        display["output_path_file"] = Path(str(result["output_path"])).name
    print("PROBE_WANTED_ID", item["id"], flush=True)
    print("PROBE_VIDEO_FILE", Path(item["file_path"]).name, flush=True)
    print("PROVIDER_DRY_RUN", json.dumps(display, ensure_ascii=False), flush=True)
    return display


def run(get, post, is_file=os.path.isfile, allowed_roots=("/media/",)):
    health = get("/api/v1/providers/health")
    providers = health.get("providers", []) if isinstance(health, dict) else []
    gate = next((p for p in providers if isinstance(p, dict)
                 and str(p.get("name", "")).lower() == "opensubtitles"), None)
    if not gate or not gate.get("enabled") or not gate.get("initialized") or (
            gate.get("gate") != "ok"):
        raise RuntimeError("Native OpenSubtitles is not ready; no search made")
    print("NATIVE_OPENSUBTITLES gate=ok; real provider search permitted", flush=True)

    cfg = get("/api/v1/config")
    if not isinstance(cfg, dict) or cfg.get("wanted_auto_translate") is not False \
            or cfg.get("upgrade_enabled") is not False:
        raise RuntimeError("Automation safety profile unknown or changed; no search")
    print("AUTO_TRANSLATION off, AUTOMATIC_UPGRADE off", flush=True)

    item, seen, total = find_one_wanted(get, is_file=is_file,
                                        allowed_roots=allowed_roots)
    print("WANTED_EXAMINED", seen, "reported_total", total, flush=True)
    if not item:
        print("NO_ELIGIBLE_WANTED_ITEM: nothing searched; check UI/library index",
              flush=True)
        return None
    print("SELECTED", item["id"], Path(item["file_path"]).name,
          "language", item["target_language"], "type",
          item.get("subtitle_type", "full"), flush=True)
    print("BEGIN EXACTLY ONE provider-search DRY RUN; counts against source "
          "provider quota, does not save subtitle or publish.", flush=True)
    reply = post("/api/v1/wanted/dry-run", {"item_ids": [item["id"]]})
    results = reply.get("results") if isinstance(reply, dict) else None
    if not isinstance(results, list) or len(results) != 1 or (
            results[0].get("wanted_id") != item["id"]):
        raise RuntimeError("Unexpected dry-run response: manually inspect only")
    summary(item, results[0])
    print("PILOT_DONE no translation, publication, sync, library scan or "
          "settings change. Wanted status restored by Sublarr's dry-run route.",
          flush=True)
    return results[0]


def main():
    # Only read Sublarr's existing PRIVATE API key in the running container;
    # never print it or include it in output.
    from config import get_settings
    key = get_settings().api_key
    headers = {"X-Api-Key": key} if key else {}
    run(
        lambda path: api(path, headers, timeout=25),
        lambda path, payload: api(path, headers, payload=payload, timeout=180),
    )


if __name__ == "__main__":
    try:
        main()
    except urllib.error.HTTPError as exc:
        print("SUBLARR_PROBE_ERROR HTTP", exc.code, file=sys.stderr, flush=True)
        raise SystemExit(1) from None
    except (ValueError, OSError, RuntimeError) as exc:
        print("SUBLARR_PROBE_ERROR", type(exc).__name__,
              str(exc)[:220], file=sys.stderr, flush=True)
        raise SystemExit(1) from None
