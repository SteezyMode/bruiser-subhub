#!/usr/bin/env python3
"""One-time API bootstrap for the isolated 5-episode Sunny Sonarr/Bazarr trial.

No production media mounts, providers, subtitle searches or downloads.
Run ON the OptiPlex host via: python3 - < this_file.py
Reads existing locally generated API keys; never prints them.
"""
import json
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path.home() / "bruiser-pilot/bazarr-trial"
SERIES = "It's Always Sunny in Philadelphia"
TEST_DIR = ROOT / "media/tv" / SERIES
SONARR = "http://100.121.156.34:18989"
BAZARR = "http://100.121.156.34:16767"
EXPECTED = {"S02E01", "S03E03", "S04E03", "S05E13", "S06E07"}

def stop(message):
    raise SystemExit("TRIAL BLOCKED: " + message)

def request(base, path, key, data=None, form=False):
    payload = None
    headers = {"X-Api-Key": key}
    if data is not None:
        if form:
            payload = urllib.parse.urlencode(data, doseq=True).encode("utf-8")
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        else:
            payload = json.dumps(data).encode("utf-8")
            headers["Content-Type"] = "application/json"
    target = base + path
    req = urllib.request.Request(target, data=payload, headers=headers,
                                 method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=25) as res:
            body = res.read()
            return json.loads(body) if body else None
    except urllib.error.HTTPError as exc:
        # Avoid echoing sensitive API or config content.
        stop(f"{path}: server returned HTTP {exc.code}; no further changes made")
    except (OSError, ValueError) as exc:
        stop(f"{path}: {type(exc).__name__}: {exc}")

def main():
    if not TEST_DIR.is_dir():
        stop("Trial video-copy directory not found")
    tags = set()
    for p in TEST_DIR.rglob("*"):
        if p.is_file() and p.suffix.lower() in {".mkv", ".mp4", ".avi", ".m4v", ".webm"}:
            match = re.search(r"S\d{2}E\d{2}", p.name, re.I)
            if match:
                tags.add(match.group(0).upper())
    if tags != EXPECTED:
        stop(f"Test files do not match the five expected episodes: {sorted(tags)}")
    # Check exact containers; no attempt to change Docker or media mounts.
    for name in ("bruiser-sonarr-trial", "bruiser-bazarr-trial"):
        proc = subprocess.run(["docker", "inspect", "--format",
                               "{{json .Mounts}}", name],
                              text=True, capture_output=True)
        if proc.returncode:
            stop(f"Trial container is missing: {name}")
        mounts = json.loads(proc.stdout)
        actual = [str(m.get("Source", "")) for m in mounts]
        if not actual or any(not x.startswith(str(ROOT) + "/") for x in actual):
            stop(f"Unexpected mount in {name}; refusing to configure")

    sx = ROOT / "config/sonarr/config.xml"
    bx = ROOT / "config/bazarr/config/config.yaml"
    if not sx.is_file() or not bx.is_file():
        stop("App first-run configuration missing; ensure both containers have initialized")
    sonarr_key = ET.parse(sx).getroot().findtext("ApiKey", default="").strip()
    if not re.fullmatch(r"[A-Za-z0-9]{20,128}", sonarr_key):
        stop("Cannot read Sonarr API key")
    bazarr_cfg = bx.read_text("utf-8")
    match = re.search(r"(?m)^auth:\s*\n(?:[ \t]+[^\n]+\n)*?[ \t]+apikey:[ \t]*['\"]?([a-fA-F0-9]{32,128})", bazarr_cfg)
    if not match:
        stop("Cannot read Bazarr API key under 'auth'; no key printed")
    bazarr_key = match.group(1)

    print("CHECK: both trial apps respond to their local APIs")
    status = request(SONARR, "/api/v3/system/status", sonarr_key)
    print("SONARR", str(status.get("version", "unknown")))

    existing = request(SONARR, "/api/v3/series", sonarr_key)
    if not isinstance(existing, list):
        stop("Unexpected Sonarr library response")
    matching = [s for s in existing if s.get("tvdbId") == 75805]
    others = [s for s in existing if s.get("tvdbId") != 75805]
    if others:
        stop("Trial Sonarr already contains other series; leave it untouched")
    if matching:
        series = matching[0]
        if series.get("path") != "/tv/" + SERIES:
            stop("Existing Sunny entry has a different media path")
        print("SONARR: existing Sunny catalog entry reused")
    else:
        roots = request(SONARR, "/api/v3/rootfolder", sonarr_key)
        if not any(x.get("path") == "/tv" for x in roots):
            request(SONARR, "/api/v3/rootfolder", sonarr_key, {"path": "/tv"})
            print("SONARR: registered /tv as trial root")
        quality = request(SONARR, "/api/v3/qualityprofile", sonarr_key)
        if not quality or not isinstance(quality, list):
            stop("No Sonarr quality profile available")
        found = request(SONARR,
                        "/api/v3/series/lookup?term=tvdb%3A75805", sonarr_key)
        candidates = [x for x in found if x.get("tvdbId") == 75805]
        if len(candidates) != 1:
            stop("Sonarr TVDB lookup did not identify Sunny uniquely")
        series = dict(candidates[0])
        series.update({
            "path": "/tv/" + SERIES,
            "rootFolderPath": "/tv",
            "qualityProfileId": quality[0]["id"],
            "seasonFolder": True,
            "monitored": False,
            "addOptions": {
                "monitor": "none",
                "searchForMissingEpisodes": False,
                "searchForCutoffUnmetEpisodes": False
            }
        })
        series = request(SONARR, "/api/v3/series", sonarr_key, series)
        if not series or not series.get("id"):
            stop("Sonarr series registration not confirmed")
        print("SONARR: registered Sunny (UNMONITORED; no downloads)")
    sid = series["id"]
    request(SONARR, "/api/v3/command", sonarr_key,
            {"name": "RefreshSeries", "seriesId": sid})
    print("SONARR: requested media rescan for copied episodes")

    config = request(BAZARR, "/api/system/settings", bazarr_key)
    if not isinstance(config, dict):
        stop("Bazarr settings API not ready")
    if config.get("general", {}).get("use_radarr"):
        stop("Bazarr trial unexpectedly has Radarr enabled")
    request(BAZARR, "/api/system/settings", bazarr_key, {
        "settings-general-use_sonarr": "true",
        "settings-sonarr-ip": "sonarr",
        "settings-sonarr-port": "8989",
        "settings-sonarr-base_url": "",
        "settings-sonarr-ssl": "false",
        "settings-sonarr-apikey": sonarr_key,
        "settings-general-upgrade_subs": "false",
        "settings-general-use_radarr": "false",
    }, form=True)
    config = request(BAZARR, "/api/system/settings", bazarr_key)
    if not config.get("general", {}).get("use_sonarr"):
        stop("Bazarr did not report Sonarr enabled")
    if str(config.get("sonarr", {}).get("ip")) != "sonarr":
        stop("Bazarr Sonarr host was not saved")
    print("BAZARR: Sonarr connection settings saved")
    print("PROTECTED: no provider accounts, auto-downloads, language profiles or alass hooks configured")
    print("NEXT: verify Sunny appears in Bazarr, then configure JA profile and provider/alass workflow")

if __name__ == "__main__":
    main()
