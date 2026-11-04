#!/usr/bin/env python3
"""Stage exactly one Japanese Always Sunny S01E01 OpenSubtitles result.

Run inside the Sublarr 1.18 Docker container (PYTHONPATH=/app). Uses the
running server for a normally scored search, the real OpenSubtitles API for
one anonymous download, and saves ONLY to private /tmp scratch storage.
No library sidecars, scan, translation, database modifications, model calls,
config changes, or publishing.

Download may consume one OpenSubtitles allowance. If anonymous downloads
aren't authorized, report the response and leave all content unchanged.
"""
from __future__ import annotations

import os
import re
import sqlite3
import urllib.parse
import urllib.request
from pathlib import Path

import requests

from config import get_settings

LOCAL_API = "http://127.0.0.1:5765/api/v1"
REMOTE_API = "https://api.opensubtitles.com/api/v1"
SCRATCH = Path("/tmp/bruiser-subhub-v2-ja-first")


def saved_opensubtitles_key():
    """Read existing encrypted key without creating a new key or changing DB."""
    cfg = get_settings()
    if cfg.database_url and not cfg.database_url.startswith("sqlite"):
        raise RuntimeError("External database not supported by this scratch probe")
    db_file = Path(cfg.db_path).resolve()
    if not db_file.is_file():
        raise RuntimeError("Existing Sublarr DB not found")
    uri = "file:" + urllib.parse.quote(str(db_file), safe="/") + "?mode=ro"
    with sqlite3.connect(uri, uri=True, timeout=10) as con:
        row = con.execute(
            "SELECT value FROM config_entries WHERE key = ?",
            ("opensubtitles_api_key",),
        ).fetchone()
    if not row or not row[0]:
        raise RuntimeError("OpenSubtitles key not saved in Sublarr")
    value = row[0]
    if value.startswith("enc:v1:"):
        keyfile = Path(os.environ.get("SUBLARR_CONFIG_DIR", "/config")) / ".encryption_key"
        if not keyfile.is_file():
            raise RuntimeError("Encryption key unavailable; not creating one")
        from config_crypto import decrypt
        value = decrypt(value)
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError("OpenSubtitles key could not be decrypted")
    return value.strip()


def candidate_from_running_sublarr():
    cfg = get_settings()
    hdr = {"Content-Type": "application/json"}
    if cfg.api_key:
        hdr["X-Api-Key"] = cfg.api_key
    import json
    payload = {
        "series_title": "It's Always Sunny in Philadelphia",
        "season": 1,
        "episode": 1,
        "language": "ja",
    }
    req = urllib.request.Request(
        LOCAL_API + "/providers/search",
        data=json.dumps(payload).encode("utf-8"),
        headers=hdr,
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=150) as response:
        search = json.load(response)
    options = []
    for result in search.get("results", []):
        if result.get("provider") != "opensubtitles":
            continue
        if str(result.get("language", "")).lower() != "ja":
            continue
        if result.get("forced") is True:
            continue
        name = str(result.get("filename") or "")
        normalized = name.lower().replace(".", " ")
        if "sunny" not in normalized or "s01e01" not in name.lower():
            continue
        if not {"series", "season", "episode"}.issubset(set(result.get("matches") or [])):
            continue
        subtitle_id = str(result.get("subtitle_id") or "")
        if not re.fullmatch(r"[1-9]\d{0,14}", subtitle_id):
            continue
        if int(result.get("score") or 0) < 240:
            continue
        options.append(result)
    print("Native JA candidates passing identity gate:", len(options), flush=True)
    if len(options) != 1:
        raise RuntimeError("Expected exactly one verified-identity candidate; no download")
    item = options[0]
    print("Selected filename:", item["filename"])
    print("Match tags:", item.get("matches"), "score:", item.get("score"))
    return item


def is_allowed_url(url):
    parsed = urllib.parse.urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or parsed.username or parsed.password:
        return False
    return any(host == d or host.endswith("." + d)
               for d in ("opensubtitles.com", "opensubtitles.org"))


def obtain_bytes(session, url):
    """Bounded download; refuse redirects to unapproved domains and HTTP."""
    for _ in range(5):
        if not is_allowed_url(url):
            raise RuntimeError("Refused download URL outside OpenSubtitles HTTPS domains")
        with session.get(url, timeout=(8, 40), stream=True, allow_redirects=False) as response:
            if response.status_code in (301, 302, 303, 307, 308):
                location = response.headers.get("Location", "")
                if not location:
                    raise RuntimeError("Redirect without location")
                url = urllib.parse.urljoin(url, location)
                continue
            if response.status_code != 200:
                raise RuntimeError("Subtitle content HTTP " + str(response.status_code))
            chunks, size = [], 0
            for chunk in response.iter_content(chunk_size=16384):
                if not chunk:
                    continue
                size += len(chunk)
                if size > 2_000_000:
                    raise RuntimeError("Subtitle exceeds 2 MB limit")
                chunks.append(chunk)
            return b"".join(chunks)
    raise RuntimeError("Too many redirects")


def inspect(content):
    if not content or b"\x00" in content[:32] and content[:2] not in (b"\xff\xfe", b"\xfe\xff"):
        raise RuntimeError("Subtitle looks empty or binary")
    text = None
    encoding = None
    for enc in ("utf-8-sig", "utf-16", "cp932", "shift_jis"):
        try:
            candidate = content.decode(enc)
        except UnicodeError:
            continue
        if "-->" in candidate or "[Script Info]" in candidate or "Dialogue:" in candidate:
            text, encoding = candidate, enc
            break
    if text is None:
        raise RuntimeError("Unrecognized subtitle encoding or format")
    timings = len(re.findall(r"\d{2}:\d{2}:\d{2}[,.]\d{3}\s*-->", text))
    ass = text.count("\nDialogue:")
    if timings < 20 and ass < 20:
        raise RuntimeError("Too few timed cues for a full episode")
    ja = len(re.findall(r"[\u3040-\u30ff\u3400-\u9fff]", text))
    if ja < 50:
        raise RuntimeError("No substantial Japanese text detected")
    print("Content:", len(content), "bytes; encoding:", encoding,
          "| timed cues:", timings if timings else ass,
          "| Japanese characters:", ja)
    return text, ("srt" if timings else "ass")


def main():
    item = candidate_from_running_sublarr()
    file_id = int(item["subtitle_id"])
    existing = list(SCRATCH.glob(f"sunny-s01e01.opensubtitles.{file_id}.ja.*")) if SCRATCH.exists() else []
    if existing:
        print("Already staged:", existing[0], "(no additional download)")
        return

    api_key = saved_opensubtitles_key()
    session = requests.Session()
    session.headers.update({
        "Api-Key": api_key,
        "User-Agent": "BruiserSubHubDev/0.1",
        "Content-Type": "application/json",
    })
    print("Requesting one anonymous Japanese subtitle download...", flush=True)
    response = session.post(
        REMOTE_API + "/download", json={"file_id": file_id},
        timeout=(8, 25),
    )
    if response.status_code != 200:
        # No secrets or provider-supplied URLs printed.
        print("OpenSubtitles download status:", response.status_code)
        try:
            body = response.json()
            print("Message:", str(body.get("message", ""))[:160])
        except ValueError:
            pass
        print("No subtitle was staged or published.")
        return
    data = response.json()
    url = data.get("link", "")
    if not is_allowed_url(url):
        raise RuntimeError("Unsafe download URL returned; aborting")
    content = obtain_bytes(session, url)
    _, ext = inspect(content)
    SCRATCH.mkdir(mode=0o700, parents=True, exist_ok=True)
    out = SCRATCH / f"sunny-s01e01.opensubtitles.{file_id}.ja.{ext}"
    fd = os.open(out, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(content)
    print("STAGED:", out, flush=True)
    print("NOT PUBLISHED — still requires human Japanese quality and actual-video timing checks.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("PILOT STOPPED:", type(exc).__name__, str(exc)[:200], flush=True)
        raise SystemExit(1) from None
