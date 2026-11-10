#!/usr/bin/env python3
"""Finish the isolated Sunny Bazarr trial using Bazarr's supported REST API.

Reads existing Sublarr provider credentials locally where available, prompts on
/dev/tty for missing credentials, disables scheduled searches, then searches
ONE episode (S02E01). No production mounts, downloads or subtitle publication.
Never prints or commits passwords, API keys, or authentication responses.
For a missing OpenSubtitles login, use --stdin-credentials with two lines
of credentials passed over SSH stdin by a local Mac mini prompt.
Do NOT pipe the script itself into python3 -.
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
        ["docker", "exec", "-e", "PYTHONPATH=/app", "sublarr-pilot",
         "python3", "-c", source],
        capture_output=True, text=True, timeout=25)
    if proc.returncode:
        return {}
    try:
        data = json.loads(proc.stdout)
        return data if isinstance(data, dict) else {}
    except ValueError:
        return {}

def terminal_credentials(existing, from_sublarr, supplied=None):
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
    if supplied is not None:
        supplied_user, supplied_pass = supplied
        if supplied_user and supplied_pass:
            osuser, ospass = supplied_user, supplied_pass
            print("OpenSubtitles.com login: received over SSH (not displayed)")
        else:
            print("OpenSubtitles.com login: not supplied (provider stays disabled)")
    elif not ((osuser and ospass) and subdl):
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

def provider_log_diagnostics(key):
    # Report only error categories, not raw logs: providers sometimes log URLs,
    # headers, or account information. Never echo raw exception messages here.
    try:
        log_response = api("/api/system/logs", key)
        log_items = log_response.get("data", []) if isinstance(log_response, dict) else []
        patterns = (
            ("auth-failure", r"unauthori[sz]ed|invalid.?credential|invalid.?key|authentication.?error|\b401\b|\b403\b"),
            ("throttled", r"too.many.requests|rate.?limit|throttl|\b429\b|quota"),
            ("provider-error", r"provider.?error|subdl.*error|opensubtitles.*error|error.*subdl|error.*opensubtitles"),
            ("network-error", r"timeout|connection.?error|ssl.error|proxy.error"),
        )
        flags = []
        for event in log_items[:120]:
            msg = " ".join(str(event.get(k) or "") for k in ("message", "exception"))
            if not re.search(r"subdl|opensubtitles|provider", msg, re.I):
                continue
            for label, pattern in patterns:
                if re.search(pattern, msg, re.I):
                    flags.append(label)
        print("PROVIDER LOG DIAGNOSTICS:", ", ".join(sorted(set(flags))) if flags else "none classified (not proof of success)")
    except SystemExit:
        print("PROVIDER LOG DIAGNOSTICS: unavailable")


def diagnose_only():
    """Read existing Bazarr state/logs; never invoke a provider search."""
    from collections import Counter
    from datetime import datetime, timedelta
    inspect_trial()
    key = bazarr_key()
    cfg = api("/api/system/settings", key)
    general = cfg.get("general", {})
    print("CONFIG: providers =", ", ".join(general.get("enabled_providers", [])) or "none")
    print("CONFIG: scheduled searching =", "Never" if int(
        general.get("wanted_search_frequency", 0)) == 876000 else "NOT Never")
    print("CONFIG: subtitle upgrades =", "enabled" if general.get("upgrade_subs") else "disabled")
    status = api("/api/providers", key)
    for provider in status.get("data", []):
        name = provider.get("name", "")
        if name not in {"subdl", "opensubtitlescom"}:
            continue
        state = re.sub(r"[^A-Za-z0-9 _.-]", "", str(provider.get("status", "?")))[:55]
        retry = re.sub(r"[^A-Za-z0-9 _.:/-]", "", str(provider.get("retry", "?")))[:40]
        print(f"PROVIDER: {name}, status={state}, retry={retry}")
    entries = api("/api/system/logs", key).get("data", [])
    # Logs are already newest first. Use the *server's* time and report source
    # timestamps so previous search failures cannot be mistaken for this one.
    cutoff = datetime.now() - timedelta(hours=3)
    patterns = (
        ("HTTP401", r"(?<!\d)401(?!\d)"),
        ("HTTP403", r"(?<!\d)403(?!\d)"),
        ("HTTP429", r"(?<!\d)429(?!\d)"),
        ("HTTP5xx", r"(?<!\d)5\d\d(?!\d)"),
        ("authentication", r"authenticat|unauthori[sz]ed|invalid.?credential|invalid.?token|invalid.?login|login.failed"),
        ("rate-limit", r"throttl|rate.?limit|too.many.requests|download.limit|quota|api.?limit"),
        ("connection", r"timeout|connection.?error|socket.error|ssl.?error|proxy.error|network.?error"),
        ("provider-error", r"providererror|provider.?error|failed.to.list|error.trying.to.get.subtitle"),
        ("no-matches", r"no subtitles|0 subtitles|nothing found|no results|not found"),
    )
    found = []
    for e in entries[:650]:
        stamp = str(e.get("timestamp") or "")
        try:
            event_time = datetime.strptime(stamp[:19], "%Y-%m-%d %H:%M:%S")
            if event_time < cutoff:
                continue
        except ValueError:
            continue
        msg = str(e.get("message") or "") + " " + str(e.get("exception") or "")
        if not re.search(r"subdl|opensubtitles|provider|subliminal|subtitle", msg, re.I):
            continue
        provider = ("opensubtitlescom" if re.search(r"opensubtitles", msg, re.I)
                    else "subdl" if re.search(r"\bsubdl\b", msg, re.I)
                    else "unspecified")
        categories = [label for label, rx in patterns if re.search(rx, msg, re.I)]
        level = re.sub(r"[^A-Z]", "", str(e.get("type") or "").upper())[:9]
        if not categories and level not in {"WARNING", "ERROR", "CRITICAL"}:
            continue
        # Never print actual log messages/exceptions; they may contain URLs,
        # tokens or credentials.
        found.append((stamp[:19], provider, level, ",".join(categories) or "other"))
    print("LOG WINDOW: last 3 hours, server local time")
    if found:
        for stamp, provider, level, cats in found[:24]:
            print(f"  {stamp} | {provider} | {level} | {cats}")
        count = Counter((p,cat) for _, p, _, cats in found for cat in cats.split(","))
        print("CATEGORY COUNTS:", "; ".join(
            f"{p}:{cat}={n}" for (p,cat), n in sorted(count.items())))
    else:
        print("No classified provider/subtitle errors in the last 3 hours")
    print("READ-ONLY: no provider searches, downloads, or config changes")


def main():
    # Drain the SSH pipe before running any subprocess. In particular,
    # docker exec -i previously consumed credentials before this function.
    supplied = None
    if "--stdin-credentials" in sys.argv:
        supplied = (sys.stdin.readline().rstrip("\r\n"),
                    sys.stdin.readline().rstrip("\r\n"))
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
    username, password, subdl = terminal_credentials(settings, old, supplied=supplied)
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
    status = api("/api/providers", key)
    provider_status = status.get("data", []) if isinstance(status, dict) else []
    for item in provider_status:
        if item.get("name") in chosen:
            state = re.sub(r"[^A-Za-z0-9 _.-]", "", str(item.get("status", "")))[:60]
            retry = re.sub(r"[^A-Za-z0-9 _.:/-]", "", str(item.get("retry", "")))[:40]
            print(f"PROVIDER STATUS: {item['name']} status={state or 'unknown'} retry={retry or 'unknown'}")
    if "opensubtitlescom" not in chosen:
        print("OPEN SUBTITLES: account login absent; skipping a redundant SubDL-only search")
        provider_log_diagnostics(key)
        print("DONE: periodic searches disabled; no new subtitle search or download")
        return
    print("SEARCH: single manual query for S02E01 with enabled providers; NO subtitle download")
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
    provider_log_diagnostics(key)
    print("DONE: search only; provider candidates are not downloaded or published")
    print("NEXT: choose real Japanese candidate; Bazarr/alass hook will process a manual download")

if __name__ == "__main__":
    if "--diagnose-only" in sys.argv:
        diagnose_only()
    else:
        main()
