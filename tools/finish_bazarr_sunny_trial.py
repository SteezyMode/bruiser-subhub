#!/usr/bin/env python3
"""Finish ONLY isolated Bazarr/Sonarr Sunny trial catalog and Japanese profile.

API-based, idempotent, no provider searches/downloads or production-library changes.
The two trial apps must have been bootstrapped already.
"""
import json
import re
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path.home() / "bruiser-pilot/bazarr-trial"
SONARR = "http://100.121.156.34:18989"
BAZARR = "http://100.121.156.34:16767"
TAGS = {"S02E01", "S03E03", "S04E03", "S05E13", "S06E07"}
PROFILE = "Japanese (Sunny trial)"

def fail(message):
    raise SystemExit("TRIAL BLOCKED: " + message)

def call(base, route, key, form=None):
    headers = {"X-Api-Key": key}
    payload = None
    if form is not None:
        payload = urllib.parse.urlencode(form, doseq=True).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    req = urllib.request.Request(base + route, data=payload, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            data = res.read()
            return json.loads(data) if data else None
    except urllib.error.HTTPError as exc:
        fail(f"{route}: HTTP {exc.code}")
    except (OSError, ValueError) as exc:
        fail(f"{route}: {type(exc).__name__}: {exc}")

def main():
    conf = ROOT / "config"
    if not conf.is_dir():
        fail("No Bazarr trial config")
    for name in ("bruiser-sonarr-trial", "bruiser-bazarr-trial"):
        p = subprocess.run(
            ["docker", "inspect", "--format", "{{json .Mounts}}", name],
            text=True, capture_output=True)
        if p.returncode:
            fail(f"{name} not running/installed")
        mounts = json.loads(p.stdout)
        if not mounts or any(not str(x.get("Source", "")).startswith(str(ROOT) + "/")
                             for x in mounts):
            fail(f"Unexpected volume mount on {name}")
    sx = conf / "sonarr/config.xml"
    bx = conf / "bazarr/config/config.yaml"
    if not sx.is_file() or not bx.is_file():
        fail("Sonarr/Bazarr API config unavailable")
    sk = ET.parse(sx).getroot().findtext("ApiKey", "").strip()
    match = re.search(
        r"(?m)^auth:\s*\n(?:[ \t]+[^\n]+\n)*?[ \t]+apikey:[ \t]*['\"]?([a-fA-F0-9]{32,128})",
        bx.read_text("utf-8"))
    if not re.fullmatch(r"[A-Za-z0-9]{20,128}", sk) or not match:
        fail("Unable to obtain locally stored API keys")
    bk = match.group(1)

    series = call(SONARR, "/api/v3/series", sk)
    matches = [x for x in series if x.get("tvdbId") == 75805
               and x.get("path") == "/tv/It's Always Sunny in Philadelphia"]
    if len(matches) != 1 or len(series) != 1:
        fail("Expected exactly the isolated Sunny series in Sonarr")
    sid = matches[0]["id"]
    files = call(SONARR, "/api/v3/episodefile?seriesId=" + str(sid), sk)
    found = set()
    for f in files:
        m = re.search(r"S\d{2}E\d{2}", str(f.get("relativePath", "")), re.I)
        if m:
            found.add(m.group(0).upper())
    print(f"SONARR: indexed {len(files)} episode files, matching IDs {sorted(found)}")
    if found != TAGS:
        fail(f"Sonarr has not identified all five test files yet (missing {sorted(TAGS-found)})")

    cfg = call(BAZARR, "/api/system/settings", bk)
    if not cfg.get("general", {}).get("use_sonarr"):
        fail("Bazarr Sonarr integration not enabled")
    if cfg.get("general", {}).get("enabled_providers"):
        fail("Trial has providers enabled; refusing unexpected provider searches")
    if cfg.get("general", {}).get("use_postprocessing"):
        fail("Trial already has post-processing enabled; inspect before changing")
    print("BAZARR: no providers or post-processing enabled (quota-safe)")

    shows = call(BAZARR, "/api/series", bk)
    data = shows.get("data", []) if isinstance(shows, dict) else []
    if not any(x.get("sonarrSeriesId") == sid for x in data):
        tasks = call(BAZARR, "/api/system/tasks", bk)
        tasklist = tasks.get("data", []) if isinstance(tasks, dict) else []
        if not any(x.get("job_id") == "update_series" for x in tasklist):
            fail("Bazarr sync task unavailable; inspect Sonarr connection in UI")
        call(BAZARR, "/api/system/tasks", bk, {"taskid": "update_series"})
        print("BAZARR: requested built-in Sync with Sonarr")
        for _ in range(12):
            time.sleep(1)
            shows = call(BAZARR, "/api/series", bk)
            data = shows.get("data", []) if isinstance(shows, dict) else []
            if any(x.get("sonarrSeriesId") == sid for x in data):
                break
    if not any(x.get("sonarrSeriesId") == sid for x in data):
        fail("Sunny not yet indexed in Bazarr; check live Sonarr connection")

    episodes = call(BAZARR, "/api/episodes?seriesid%5B%5D=" + str(sid), bk)
    episode_data = episodes.get("data", []) if isinstance(episodes, dict) else []
    matches = {f"S{e.get('season',0):02d}E{e.get('episode',0):02d}"
               for e in episode_data if e.get("path")}
    print(f"BAZARR: sees {len(episode_data)} episode records; indexed media {sorted(matches&TAGS)}")
    if matches & TAGS != TAGS:
        fail(f"Bazarr has not indexed every test episode: missing {sorted(TAGS-matches)}")

    profiles = call(BAZARR, "/api/system/languages/profiles", bk)
    if not isinstance(profiles, list):
        fail("Unexpected Bazarr profile API response")
    current = [x for x in profiles if x.get("name") == PROFILE]
    if len(current) > 1 or (profiles and not current):
        fail("Non-trial language profiles exist; refusing to replace them")
    if current:
        pid = current[0]["profileId"]
        print("BAZARR: existing trial Japanese profile reused")
    else:
        languages = call(BAZARR, "/api/system/languages", bk)
        lang_data = languages.get("data") if isinstance(languages, dict) else languages
        if not any(x.get("code2") == "ja" for x in lang_data):
            fail("Japanese is not available in Bazarr language list")
        profile = {
            "profileId": 1, "name": PROFILE, "tag": None,
            "items": [{"id": 1, "language": "ja", "hi": "False",
                       "forced": "False", "audio_exclude": "False",
                       "audio_only_include": "False"}],
            "cutoff": 1, "mustContain": [], "mustNotContain": [],
            "originalFormat": False,
        }
        call(BAZARR, "/api/system/settings", bk, {
            "languages-enabled": ["ja"],
            "languages-profiles": json.dumps([profile], ensure_ascii=False),
            "settings-sonarr-defer_search_signalr": "true",
            "settings-general-upgrade_subs": "false",
            "settings-subsync-use_subsync": "false",
        })
        updated = call(BAZARR, "/api/system/languages/profiles", bk)
        current = [x for x in updated if x.get("name") == PROFILE]
        if len(current) != 1:
            fail("Japanese profile was not saved")
        pid = current[0]["profileId"]
        print("BAZARR: Japanese-only profile created")
    call(BAZARR, "/api/series", bk, {"seriesid": str(sid), "profileid": str(pid)})
    shows = call(BAZARR, "/api/series", bk)
    items = shows.get("data", []) if isinstance(shows, dict) else []
    item = next((x for x in items if x.get("sonarrSeriesId") == sid), None)
    if not item or item.get("profileId") != pid:
        fail("Series profile assignment was not verified")
    print(f"BAZARR: Sunny assigned Japanese trial profile {pid}")
    print("READY: isolated catalog configured; no subtitle downloads or searches performed")
    print("NEXT: configure providers + alass hook before a controlled manual search")

if __name__ == "__main__":
    main()
