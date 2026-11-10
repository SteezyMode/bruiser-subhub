#!/usr/bin/env python3
"""Finish the isolated Sunny Bazarr trial using Bazarr's supported REST API.

Reads existing Sublarr provider credentials locally where available, prompts on
/dev/tty for missing credentials, disables scheduled searches, then searches
ONE episode (S02E01). No production mounts, downloads or subtitle publication.
Never prints or commits passwords, API keys, or authentication responses.
Run interactively on the OptiPlex host (see repo instructions).
"""
from __future__ import annotations

import getpass
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path.home() / "bruiser-pilot/bazarr-trial"
BASE = "http://100.121.156.34:16767"
SERIES = "It's Always Sunny in Philadelphia"
TRIAL_CONTAINERS = ("bruiser-bazarr-trial", "bruiser-sonarr-trial")

def fail(message):
    raise SystemExit("TRIAL BLOCKED: " + message)

def inspect_trial():
    media = ROOT / "media/tv" / SERIES
    if not media.is_dir():
        fail("Five-episode trial media directory not found")
    files = [p for p in media.rglob("*") if p.is_file()
             and p.suffix.casefold() in {".mkv", ".mp4", ".avi", ".m4v", ".webm"}]
    if len(files) != 5:
        fail(f"Expected five copied videos, found {len(files)}")
    for name in TRIAL_CONTAINERS:
        p = subprocess.run(["docker", "inspect", "--format", "{{json .Mounts}}", name],
                           text=True, capture_output=True)
        if p.returncode:
            fail(f"Trial container missing: {name}")
        try:
            mounts = json.loads(p.stdout)
        except ValueError:
            fail(f"Cannot validate {name} mounts")
        if not mounts or any(
            not Path(m.get("Source", "/")).resolve().is_relative_to(ROOT.resolve())
            for m in mounts
        ):
            fail(f"Unexpected mount on {name}; no changes made")
    print("PROTECTED: both containers have only isolated trial mounts")

def bazarr_key():
    config = ROOT / "config/bazarr/config/config.yaml"
    if not config.is_file():
        fail("Bazarr trial config missing")
    text = config.read_text("utf-8")
    match = re.search(
        r"(?m)^auth:\s*\n(?:[ \t]+[^\n]+\n)*?[ \t]+apikey:[ \t]*['\"]?([a-fA-F0-9]{32,128})",
        text)
    if not match:
        fail("Bazarr API key missing")
    return match.group(1)

def api(route, key, values=None, timeout=60):
    payload = None
    headers = {"X-Api-Key": key}
    if values is not None:
        payload = urllib.parse.urlencode(values, doseq=True).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    req = urllib.request.Request(BASE + route, data=payload, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            body = res.read()
            return json.loads(body) if body else None
    except urllib.error.HTTPError as exc:
        # Never echo the response body: it could contain provider credentials.
        fail(f"{route}: HTTP {exc.code} (response suppressed)")
    except (OSError, ValueError) as exc:
        fail(f"{route}: {type(exc).__name__} (response suppressed)")

def sublarr_credentials():
    """Read only known credentials using Sublarr's own at-rest decryptor.

    Called in the existing Sublarr container; captured output never goes to
    the user's terminal. If absent/incompatible, allow secure prompt instead.
    """
    source = r'''
import json, os, sqlite3
from config_crypto import decrypt
path=os.environ.get("SUBLARR_DB_PATH","/config/sublarr.db")
db=sqlite3.connect("file:"+path+"?mode=ro", uri=True)
wanted=("opensubtitles_username","opensubtitles_password",
        "opensubtitlescom_subliminal_username","opensubtitlescom_subliminal_password",
        "subdl_api_key")
rows=db.execute("SELECT key,value FROM config_entries WHERE key IN ("+
                ",".join("?" for _ in wanted)+")",wanted).fetchall()
values={k:decrypt(v) or "" for k,v in rows}
print(json.dumps(values))
'''
    proc = subprocess.run(
        ["docker", "exec", "-i", "-e", "PYTHONPATH=/app", "sublarr-pilot",
         "python3", "-c", source],
        capture_output=True, text=True, timeout=25)
    if proc.returncode:
        return {}
    try:
        data = json.loads(proc.stdout)
        return data if isinstance(data, dict) else {}
    except ValueError:
        return {}

def terminal_credentials(existing, from_sublarr):
    osuser = (existing.get("opensubtitlescom", {}).get("username")
              or from_sublarr.get("opensubtitles_username")
              or from_sublarr.get("opensubtitlescom_subliminal_username") or "")
    ospass = (existing.get("opensubtitlescom", {}).get("password")
              or from_sublarr.get("opensubtitles_password")
              or from_sublarr.get("opensubtitlescom_subliminal_password") or "")
    subdl = existing.get("subdl", {}).get("api_key") or from_sublarr.get("subdl_api_key") or ""
    if osuser and ospass:
        print("OpenSubtitles.com login: obtained locally (not displayed)")
    if subdl:
        print("SubDL key: obtained locally (not displayed)")
    if not ((osuser and ospass) and subdl):
        try:
            with open("/dev/tty", "r+", encoding="utf-8") as tty:
                if not (osuser and ospass):
                    print("OpenSubtitles.com credentials missing locally.", file=tty)
                    if not osuser:
                        tty.write("OpenSubtitles username (Enter to skip): ")
                        tty.flush()
                        osuser = tty.readline().strip()
                    if osuser and not ospass:
                        ospass = getpass.getpass("OpenSubtitles password (Enter to skip): ", stream=tty)
                if not subdl:
                    subdl = getpass.getpass("SubDL API key (Enter to skip): ", stream=tty)
        except (OSError, EOFError):
            print("No interactive terminal; missing provider credentials skipped")
    if osuser and ospass and (osuser.startswith("enc:v1:") or ospass.startswith("enc:v1:")):
        fail("Sublarr OpenSubtitles credentials could not be decrypted")
    if subdl.startswith("enc:v1:"):
        fail("Sublarr SubDL credential could not be decrypted")
    return osuser, ospass, subdl

def main():
    inspect_trial()
    key = bazarr_key()
    settings = api("/api/system/settings", key)
    general = settings.get("general", {})
    if not general.get("use_sonarr") or general.get("use_radarr"):
        fail("Unexpected Sonarr/Radarr configuration")
    if not general.get("use_postprocessing"):
        fail("Alass postprocessing is not enabled")
    if "/config/scripts/bazarr-subsync" not in str(general.get("postprocessing_cmd", "")):
        fail("Expected alass hook is not configured")
    if settings.get("subsync", {}).get("use_subsync"):
        fail("Native ffsubsync still enabled; inspect before searching")
    enabled = general.get("enabled_providers", [])
    if not isinstance(enabled, list) or set(enabled) - {"opensubtitlescom", "subdl"}:
        fail("Unexpected enabled providers; leave existing configuration alone")

    # Disable recurring search/upgrade BEFORE adding credentials or providers.
    api("/api/system/settings", key, {
        "settings-general-wanted_search_frequency": "876000",
        "settings-general-upgrade_frequency": "876000",
        "settings-general-upgrade_subs": "false",
        "settings-sonarr-defer_search_signalr": "true",
    })
    settings = api("/api/system/settings", key)
    if (int(settings.get("general", {}).get("wanted_search_frequency", 0)) != 876000
        or settings.get("general", {}).get("upgrade_subs")):
        fail("Automatic searching/upgrade was not disabled")
    print("SCHEDULER: periodic missing-subtitle search set to Never; upgrades disabled")

    old = sublarr_credentials()
    if old:
        print("SUBLARR: provider credential settings inspected read-only")
    else:
        print("SUBLARR: no usable credential settings found; local input may be required")
    username, password, subdl = terminal_credentials(settings, old)
    chosen = []
    fields = {
        "settings-general-upgrade_subs": "false",
        "settings-opensubtitlescom-include_ai_translated": "false",
        "settings-opensubtitlescom-include_machine_translated": "false",
        "settings-subdl-ai_translate": "false",
        "settings-subdl-include_ai_translated": "false",
    }
    if username and password:
        fields["settings-opensubtitlescom-username"] = username
        fields["settings-opensubtitlescom-password"] = password
        chosen.append("opensubtitlescom")
    if subdl:
        fields["settings-subdl-api_key"] = subdl
        chosen.append("subdl")
    if not chosen:
        print("NO PROVIDERS: credentials not supplied; nothing to search")
        return
    # Enable only these 1-2 providers, and never echo their credentials.
    fields["settings-general-enabled_providers"] = chosen
    api("/api/system/settings", key, fields)
    after = api("/api/system/settings", key)
    active = after.get("general", {}).get("enabled_providers", [])
    if set(active) != set(chosen):
        fail("Enabled providers were not saved correctly")
    if int(after.get("general", {}).get("wanted_search_frequency", 0)) != 876000:
        fail("Scheduler changed unexpectedly")
    print("PROVIDERS ENABLED:", ", ".join(chosen))
    print("SEARCH: single manual query for S02E01; NO subtitle download")
    shows = api("/api/series", key)
    rows = shows.get("data", []) if isinstance(shows, dict) else []
    matching = [s for s in rows if s.get("tvdbId") == 75805
                and s.get("path", "").startswith("/tv/")]
    if len(matching) != 1 or len(rows) != 1:
        fail("Unexpected Bazarr series catalog; refusing search")
    sid = matching[0]["sonarrSeriesId"]
    ep = api("/api/episodes?seriesid%5B%5D=" + str(sid), key)
    episode_rows = ep.get("data", []) if isinstance(ep, dict) else []
    target = [x for x in episode_rows if x.get("season") == 2
              and x.get("episode") == 1 and x.get("path")]
    if len(target) != 1:
        fail("S02E01 was not uniquely identified")
    eid = target[0]["sonarrEpisodeId"]
    results = api("/api/providers/episodes?episodeid=" + str(eid), key, timeout=180)
    candidates = results.get("data", []) if isinstance(results, dict) else []
    print(f"RESULT: {len(candidates)} subtitle candidates")
    for i, item in enumerate(sorted(candidates, key=lambda x: x.get("score") or 0,
                                    reverse=True)[:15], 1):
        release = item.get("release_info") or []
        if isinstance(release, list):
            release = " | ".join(map(str, release))
        line = str(release).replace("\n", " ")[:110]
        print(f"  {i:02d}. {item.get('provider','?')} / {item.get('language','?')} "
              f"score={item.get('score','?')}  {line}")
    print("DONE: search only; provider candidates are not downloaded or published")
    print("NEXT: choose real Japanese candidate; Bazarr/alass hook will process a manual download")

if __name__ == "__main__":
    main()
