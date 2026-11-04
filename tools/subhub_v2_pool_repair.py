#!/usr/bin/env python3
"""Safely repair the Sublarr 1.18 OpenSubtitles.com account-pool gate.

Uses ONLY credentials already stored in Sublarr config_entries. Never prints
secrets or invents pool keys. Without --apply: inventory only. With --apply:
create one idempotent pool row via Sublarr's normal encrypted-at-rest API,
only if a complete existing OpenSubtitles credential set is present.

No subtitles are searched, downloaded or published. Does not change budget,
folder scanning, wanted scheduler, or upgrade settings.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from config import get_settings

PROVIDER = "opensubtitlescom_subliminal"
CREDENTIAL_KEYS = (
    "opensubtitles_api_key",
    "opensubtitles_username",
    "opensubtitles_password",
)
BASE = "http://127.0.0.1:5765"


def api(path: str, data: dict | None = None):
    cfg = get_settings()
    headers = {"X-Api-Key": cfg.api_key} if cfg.api_key else {}
    if data is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        BASE + path,
        headers=headers,
        data=json.dumps(data).encode("utf-8") if data is not None else None,
        method="POST" if data is not None else "GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        return error.code, None
    except (OSError, ValueError) as error:
        print("API unavailable:", type(error).__name__, flush=True)
        return None, None


def existing_credentials():
    cfg = get_settings()
    if cfg.database_url and not cfg.database_url.startswith("sqlite"):
        print("External database: automatic credential inventory unsupported.")
        return None
    db_path = Path(cfg.db_path).resolve()
    if not db_path.is_file():
        print("Sublarr SQLite database unavailable at configured path.")
        return None
    uri = "file:" + urllib.parse.quote(str(db_path), safe="/") + "?mode=ro"
    try:
        with sqlite3.connect(uri, uri=True, timeout=10) as conn:
            rows = conn.execute(
                "SELECT key, value FROM config_entries "
                "WHERE key IN (?, ?, ?)", CREDENTIAL_KEYS
            ).fetchall()
    except (sqlite3.Error, OSError) as error:
        print("Cannot inspect config_entries:", type(error).__name__)
        return None

    stored = {key: val for key, val in rows}
    needs_decryption = any(
        isinstance(stored.get(key), str) and stored[key].startswith("enc:v1:")
        for key in CREDENTIAL_KEYS
    )
    # Importing config_crypto and decrypting with a missing key would create a
    # new key. Refuse rather than touch an existing installation unexpectedly.
    if needs_decryption:
        keyfile = Path(os.environ.get("SUBLARR_CONFIG_DIR", "/config")) / ".encryption_key"
        if not keyfile.is_file():
            print("Existing encrypted configuration key file unavailable; no changes.")
            return None
    from config_crypto import decrypt

    values = {}
    for key in CREDENTIAL_KEYS:
        val = stored.get(key)
        if isinstance(val, str) and val.startswith("enc:v1:"):
            val = decrypt(val)
        values[key] = val.strip() if isinstance(val, str) else ""
        print(key, "saved" if values[key] else "missing", flush=True)
    return values


def main():
    apply = sys.argv[1:] == ["--apply"]
    if sys.argv[1:] not in ([], ["--apply"]):
        raise SystemExit("Usage: script.py [--apply]")
    print("=== EXISTING OPENSUBTITLES ACCOUNT / PROVIDER POOL ===", flush=True)
    values = existing_credentials()
    status, listed = api("/api/v1/providers/" + PROVIDER + "/keys")
    if status != 200 or not isinstance(listed, dict):
        print("Cannot read Sublarr pool metadata; no changes made.", flush=True)
        return 1
    keys = listed.get("keys", [])
    if not isinstance(keys, list):
        print("Unexpected account pool response; no changes made.")
        return 1
    print(PROVIDER, "existing pool rows:", len(keys), flush=True)
    print("enabled rows:", sum(row.get("enabled") is True for row in keys
                               if isinstance(row, dict)), flush=True)
    if not apply:
        print("READ-ONLY. To seed one row from saved credentials, use --apply.")
        return 0
    if keys:
        print("No change: pool row(s) already exist; will not overwrite them.")
        return 0
    if values is None or not all(values.get(key) for key in CREDENTIAL_KEYS):
        print("No change: complete authentic OpenSubtitles credentials not saved.")
        print("Do not create placeholders or disable the global provider budget.")
        return 0
    payload = {
        "label": "subhub-existing-credentials",
        "api_key": values["opensubtitles_api_key"],
        "username": values["opensubtitles_username"],
        "password": values["opensubtitles_password"],
        "tier": "free",
        "enabled": True,
    }
    status, response = api("/api/v1/providers/" + PROVIDER + "/keys", payload)
    if status != 201:
        print("Account-pool registration did not succeed; HTTP:", status)
        return 1
    print("Saved one enabled pool row from existing actual credentials.")
    print("Provider budget remains enabled; existing media is unchanged.")
    hs, health = api("/api/v1/providers/health")
    if hs == 200 and isinstance(health, dict):
        for entry in health.get("providers", []):
            if isinstance(entry, dict) and entry.get("name") == PROVIDER:
                print("Now:", entry.get("gate"), "| initialized:",
                      entry.get("initialized"), "| healthy:", entry.get("healthy"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
