#!/usr/bin/env python3
"""Stage high-confidence Japanese subtitle candidates from saved search history.

Run on the OptiPlex host. Uses only the existing Jellyfin identity manifest,
the existing Japanese search SQLite history and Sublarr's saved OpenSubtitles
credentials. No new provider searches. Without --apply, no writes/downloads.

--apply stages at most --budget subtitles. Each subtitle may consume ONE
OpenSubtitles download allowance. Validated bytes are copied from container
/tmp into a private, persistent HOST staging directory, never into media.

Staging is NOT publication, content quality approval or timing verification.
"""
from __future__ import annotations

try:
    from . import ja_first_priority as priorities
    from . import subhub_download_ledger as ledger
except ImportError:
    import ja_first_priority as priorities
    import subhub_download_ledger as ledger

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from urllib.parse import quote

ROOT = Path.home() / "bruiser-pilot/ja-first-inventory"
SEARCH_DB = ROOT / "japanese-search.sqlite3"
STAGE_DB = ROOT / "japanese-stage.sqlite3"
STAGED = ROOT / "staged"
VALID_SUBTITLES = {".srt", ".ass", ".ssa", ".vtt"}
JA = {"ja", "jpn", "jp", "japanese"}
ALLOWED_HOST_ROOTS = (
    Path("/mnt/BigDisk/Video"),
    Path("/mnt/2TB/Plex Expansion"),
)
SUPPORTED_VIDEO = {".mkv", ".mp4", ".m4v", ".avi", ".wmv", ".webm", ".ts", ".mov", ".mpg", ".mpeg", ".m2ts"}
SXXEXX = re.compile(r"(?<![a-z0-9])s(\d{1,2})[._ -]*e(\d{1,3})(?!\d)", re.I)
XNUM = re.compile(r"(?<!\d)(\d{1,2})x(\d{1,3})(?!\d)", re.I)
IMDB = re.compile(r"tt\d{5,12}\Z", re.I)

WORKER = r'''
import json, os, re, sys
from pathlib import Path
from providers.base import SubtitleFormat, SubtitleResult
from providers.opensubtitles import OpenSubtitlesProvider
from config import get_settings

STAGE = Path("/tmp/bruiser-subhub-ja-first-staged")
STEM_PREFIX = "opensubtitles"
MAX_BYTES = 2_000_000
SRT_TIMING = re.compile(r"(?m)(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2})[,.](\d{3})")
ASS_TIMING = re.compile(r"(?m)^Dialogue:\s*[^,]*,(\d+):(\d{2}):(\d{2})\.(\d{2}),(\d+):(\d{2}):(\d{2})\.(\d{2}),")
JAPANESE = re.compile(r"[\u3040-\u30ff\u3400-\u9fff]")
TAGS = re.compile(r"<[^>]+>|{\\[^}]+}")

def analyze(raw, runtime, *, allow_duration_mismatch=False):
    if not raw or len(raw) > MAX_BYTES:
        raise RuntimeError("subtitle_empty_or_oversize")
    for encoding in ("utf-8-sig", "utf-16", "cp932", "shift_jis"):
        try:
            s = raw.decode(encoding)
        except UnicodeError:
            continue
        if s.count("\ufffd") > 5:
            continue
        srt = list(SRT_TIMING.finditer(s))
        ass = list(ASS_TIMING.finditer(s))
        if srt:
            stamps = [
                (int(m[5])*3600 + int(m[6])*60 + int(m[7]) + int(m[8])/1000)
                for m in srt
            ]
            fmt = "srt"
            n = len(srt)
        elif ass:
            stamps = [
                (int(m[5])*3600 + int(m[6])*60 + int(m[7]) + int(m[8])/100)
                for m in ass
            ]
            fmt = "ass"
            n = len(ass)
        else:
            continue
        ja = len(JAPANESE.findall(TAGS.sub("", s)))
        if n < 75:
            raise RuntimeError("too_few_subtitle_cues")
        if ja < 200:
            raise RuntimeError("too_few_japanese_characters")
        maximum = max(stamps)
        duration_mismatch = maximum > runtime * 1.15 or maximum < runtime * 0.60
        if duration_mismatch and not allow_duration_mismatch:
            raise RuntimeError("subtitle_duration_inconsistent")
        if sum(a <= b for a,b in zip(stamps,stamps[1:])) < (len(stamps)-1)*0.95:
            raise RuntimeError("timing_out_of_order")
        return {
            "format": fmt, "encoding": encoding, "cues": n,
            "japanese_characters": ja,
            "last_end_seconds": round(maximum, 2),
            "video_seconds": round(runtime, 2),
            "last_end_video_ratio": round(maximum/runtime, 3),
            "bytes": len(raw),
            "duration_mismatch": duration_mismatch,
            "timing_note": ("HELD: candidate duration inconsistent with selected video"
                            if duration_mismatch else
                            "Duration plausible only; actual synchronization NOT confirmed"),
        }
    raise RuntimeError("unrecognized_subtitle_timing_or_encoding")

def run(job):
    sid = str(job.get("subtitle_id") or "")
    jellyfin_id = str(job.get("jellyfin_id") or "")
    if (job.get("provider") != "opensubtitles"
            or not re.fullmatch(r"[1-9][0-9]{3,13}", sid)
            or not re.fullmatch(r"[a-f0-9]{32}", jellyfin_id)):
        raise RuntimeError("invalid_or_unsupported_candidate")
    STEM = jellyfin_id + "." + STEM_PREFIX + "." + sid + ".ja"
    runtime = float(job.get("duration") or 0)
    if not 600 <= runtime <= 4*3600:
        raise RuntimeError("unreasonable_video_duration")
    if STAGE.exists() and (not STAGE.is_dir() or STAGE.is_symlink()
                           or STAGE.stat().st_mode & 0o077):
        raise RuntimeError("unsafe_existing_stage_directory")
    if STAGE.exists():
        for ext in ("srt", "ass"):
            path = STAGE / (STEM + "." + ext)
            if path.is_file() and not path.is_symlink():
                data = path.read_bytes()
                meta = analyze(data, runtime, allow_duration_mismatch=True)
                if meta["format"] != ext:
                    raise RuntimeError("cached_subtitle_format_mismatch")
                return {"result": ("held_duration_mismatch"
                                   if meta["duration_mismatch"] else "already_staged"),
                        "stage_path": str(path),
                        "metrics": meta, "new_download": False}

    # The live Sublarr server loads provider UI settings from config_entries
    # during startup. A fresh docker exec Python interpreter does NOT: its
    # get_settings() sees default, blank UISettings. Reuse Sublarr's existing
    # pool/crypto logic rather than inventing another secret store.
    import sqlite3
    from urllib.parse import quote
    from flask import Flask
    from extensions import db as flask_db
    from db.repositories.provider_account_pool import ProviderAccountPoolRepository
    from services.key_selector import get_key_selector

    cfg = get_settings()
    if cfg.database_url and not str(cfg.database_url).startswith("sqlite"):
        raise RuntimeError("external_database_credential_lookup_not_supported")
    db_path = Path(cfg.db_path)
    if not db_path.is_file() or db_path.is_symlink():
        raise RuntimeError("sublarr_database_missing_or_unsafe")
    key_path = Path(os.environ.get("SUBLARR_CONFIG_DIR", cfg.config_dir)) / ".encryption_key"
    if not key_path.is_file() or key_path.is_symlink():
        # Sublarr's decrypt() creates a new master key if the existing one
        # is missing. Refuse before invoking repository decryption.
        raise RuntimeError("existing_encryption_key_missing_or_unsafe")

    # A lightweight, isolated Flask app context enables Sublarr's official
    # repository and key selector. Do not call create_app() — that initializes
    # schedulers, services and migrations. This is DB-read-only.
    app = Flask("bruiser_subhub_credential_reader")
    app.config["SQLALCHEMY_DATABASE_URI"] = cfg.get_database_url()
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    flask_db.init_app(app)
    selected = None
    with app.app_context():
        repo = ProviderAccountPoolRepository()
        # A missing keyfile must not cause config_crypto.decrypt() to
        # CREATE a replacement master encryption key.
        if repo.get_all_for("opensubtitles"):
            if not key_path.is_file():
                raise RuntimeError("existing_encryption_key_missing")
            selector = get_key_selector()
            selected = selector.pick(
                "opensubtitles",
                provider_rate_limits=OpenSubtitlesProvider.rate_limits,
            )
            if selected is None:
                raise RuntimeError("opensubtitles_pool_disabled_cooling_or_exhausted")

    if selected is not None:
        key = str(selected.get("api_key") or "").strip()
        user = str(selected.get("username") or "").strip()
        password = str(selected.get("password") or "").strip()
        credential_source = "existing_account_pool"
    else:
        # Pool-less native providers are supported by Sublarr. Read the same
        # saved config_entries used to initialize the live server. No writes.
        from config_crypto import decrypt, is_encrypted
        uri = "file:" + quote(str(db_path.resolve()), safe="/") + "?mode=ro"
        with sqlite3.connect(uri, uri=True, timeout=10) as connection:
            saved = dict(connection.execute(
                "SELECT key, value FROM config_entries "
                "WHERE key IN ('opensubtitles_api_key', "
                "'opensubtitles_username', 'opensubtitles_password')"
            ).fetchall())
        if any(is_encrypted(value) for value in saved.values()):
            if not key_path.is_file():
                raise RuntimeError("existing_encryption_key_missing")
        key = str(decrypt(saved.get("opensubtitles_api_key")) or "").strip()
        user = str(decrypt(saved.get("opensubtitles_username")) or "").strip()
        password = str(decrypt(saved.get("opensubtitles_password")) or "").strip()
        credential_source = "existing_saved_ui_config"

    if not key:
        raise RuntimeError("native_opensubtitles_key_missing_in_saved_config")
    print("CREDENTIAL SOURCE:", credential_source, "(credentials hidden)", flush=True)
    provider = OpenSubtitlesProvider(api_key=key, username=user, password=password)
    provider.initialize()
    try:
        if not provider.session:
            raise RuntimeError("opensubtitles_initialization_failed")
        candidate = SubtitleResult(
            provider_name="opensubtitles", subtitle_id=sid,
            language="ja", format=SubtitleFormat.UNKNOWN,
            filename=str(job.get("filename") or "")[:240],
            release_info=str(job.get("release_info") or "")[:240],
            matches=set(job.get("matches") or []), provider_data={"file_id": int(sid)},
        )
        # The host ledger records this attempt, including quota refusals.
        # These fixed signals carry no remote IDs, file paths or credentials.
        print("SUBHUB_DOWNLOAD_REQUEST: opensubtitles", flush=True)
        raw = provider.download(candidate)  # At most one /download request.
        print("SUBHUB_DOWNLOAD_RECEIVED:", len(raw), flush=True)
    finally:
        provider.terminate()
    metrics = analyze(raw, runtime, allow_duration_mismatch=True)
    if candidate.format.value not in {"unknown", metrics["format"]}:
        raise RuntimeError("provider_reported_format_conflicts_with_content")
    if not STAGE.exists():
        STAGE.mkdir(mode=0o700)
    if STAGE.is_symlink() or STAGE.stat().st_mode & 0o077:
        raise RuntimeError("unsafe_stage_directory")
    path = STAGE / (STEM + "." + metrics["format"])
    fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY
                 | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(raw)
    except BaseException:
        try: path.unlink()
        except OSError: pass
        raise
    return {"result": ("held_duration_mismatch" if metrics["duration_mismatch"]
                       else "staged_not_published"),
            "stage_path": str(path),
            "metrics": metrics, "new_download": True}

try:
    job = json.load(sys.stdin)
    result = run(job)
    print("STAGE_RESULT_JSON:" + json.dumps(result, ensure_ascii=False), flush=True)
except Exception as exc:
    print("STAGE_RESULT_JSON:" + json.dumps({
        "result": "blocked", "error_type": type(exc).__name__,
        "error": str(exc)[:110]
    }, ensure_ascii=False), flush=True)
    raise SystemExit(1)
'''


def private_file(path):
    if (not path.is_file() or path.is_symlink()
            or path.stat().st_mode & 0o077):
        raise RuntimeError("missing_or_insecure_private_state")


def private_root():
    if (not ROOT.is_dir() or ROOT.is_symlink()
            or ROOT.stat().st_mode & 0o077):
        raise RuntimeError("missing_or_insecure_inventory_root")


def read_inventory():
    private_root()
    paths = sorted(ROOT.glob("ja-intake-*.json"))
    if not paths:
        raise RuntimeError("intake_manifest_missing")
    path = paths[-1]
    private_file(path)
    if time.time() - path.stat().st_mtime > 72 * 3600:
        raise RuntimeError("intake_manifest_stale_refresh_before_staging")
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema") != 1 or not isinstance(data.get("items"), list):
        raise RuntimeError("unsupported_inventory_schema")
    return {str(x["jellyfin_id"]): x for x in data["items"]
            if isinstance(x, dict) and x.get("jellyfin_id")}


def read_saved_searches():
    private_file(SEARCH_DB)
    uri = "file:" + quote(str(SEARCH_DB.resolve()), safe="/") + "?mode=ro"
    with sqlite3.connect(uri, uri=True, timeout=15) as db:
        return db.execute(
            """SELECT jellyfin_id,results_json FROM searches
               WHERE outcome IN ('plausible','review','none','partial')"""
        ).fetchall()


def tokens(value):
    # Release filenames normally omit apostrophes: "It's" and "Its" match.
    normalized = re.sub(r"(?<=[a-z])['\u2019](?=[a-z])", "",
                        str(value or "").casefold())
    return re.findall(r"[a-z]+|[0-9]+", normalized)


def named_episode(text):
    return {(int(m[1]), int(m[2]))
            for pattern in (SXXEXX, XNUM)
            for m in pattern.finditer(str(text or ""))}


def contiguous_words(full, needle):
    if not needle:
        return False
    return any(full[i:i + len(needle)] == needle
               for i in range(len(full) - len(needle) + 1))


def identity_ok(row, result):
    """Conservative: identity candidate only, never permission to publish."""
    if (result.get("provider") != "opensubtitles"
            or str(result.get("language") or "").casefold() not in {"ja", "jpn"}
            or result.get("forced") is True
            or str(result.get("kind") or "").casefold() in {"forced", "signs"}
            or not re.fullmatch(r"[1-9][0-9]{3,13}",
                                str(result.get("subtitle_id") or ""))):
        return False

    name = str(result.get("filename") or "")
    release = str(result.get("release_info") or "")
    if row.get("kind") == "Movie":
        # Title/year is enough to stage a reviewable candidate; an absent
        # IMDb ID does not mean subtitle files are impossible to match.
        # Keep strict same-title + year checks below, then timing/QA/no-clobber.
        year = str(row.get("year") or "")
        title = tokens(row.get("title"))
        if not re.fullmatch(r"\d{4}", year) or not title:
            return False
        found = False
        for text in (name, release):
            words = tokens(text)
            for i in range(len(words) - len(title) + 1):
                if words[i:i + len(title)] != title:
                    continue
                neighbors = [words[i - 1] if i else "",
                             words[i + len(title)] if i + len(title) < len(words) else ""]
                if any(re.fullmatch(r"(?:19|20)\d{2}", w) and w != year
                       for w in neighbors):
                    return False
                if year in neighbors:
                    found = True
        return found

    if row.get("kind") == "Episode":
        season, number = row.get("season"), row.get("episode")
        if (type(season) is not int or season < 1
                or type(number) is not int or number < 1
                or not row.get("series_title")
                or not (any(row.get(k) for k in
                           ("series_imdb_id", "series_tmdb_id", "series_tvdb_id"))
                        or (row.get("series_identity_source") == "jellyfin"
                            and re.fullmatch(r"[0-9a-fA-F]{32}",
                                str(row.get("series_jellyfin_id") or ""))))):
            return False
        # Explicit episode and named series, plus native Sublarr's match set.
        tags = named_episode(name + " " + release)
        if not tags or tags != {(season, number)}:
            return False
        if not {"series", "season", "episode"}.issubset(
                set(result.get("matches") or [])):
            return False
        return any(contiguous_words(tokens(text), tokens(row["series_title"]))
                   for text in (name, release))
    return False


def stage_name(row, result, extension):
    if not re.fullmatch(r"[a-f0-9]{32}", str(row.get("jellyfin_id") or "")):
        raise RuntimeError("invalid_jellyfin_id")
    if extension not in {"srt", "ass"}:
        raise RuntimeError("unsupported_subtitle_format")
    return (str(row["jellyfin_id"]) + ".opensubtitles."
            + str(result["subtitle_id"]) + ".ja." + extension)


def read_staged():
    if not STAGE_DB.exists():
        return set()
    private_file(STAGE_DB)
    uri = "file:" + quote(str(STAGE_DB.resolve()), safe="/") + "?mode=ro"
    with sqlite3.connect(uri, uri=True, timeout=10) as db:
        entries = db.execute(
            "SELECT jellyfin_id,subtitle_id,host_path FROM staged WHERE status IN ('staged','published')"
        ).fetchall()
    valid = set()
    for jid, sid, path in entries:
        p = Path(path)
        if (p.parent == STAGED and p.is_file()
                and not p.is_symlink() and p.stat().st_size > 0):
            valid.add((str(jid), str(sid)))
    return valid


def rejected_duration_candidates():
    """Previously downloaded wrong-duration tracks; never retry at provider cost."""
    if not STAGE_DB.exists():
        return set()
    private_file(STAGE_DB)
    uri = "file:" + quote(str(STAGE_DB.resolve()), safe="/") + "?mode=ro"
    with sqlite3.connect(uri, uri=True, timeout=10) as db:
        entries = db.execute(
            "SELECT jellyfin_id,subtitle_id,host_path FROM staged "
            "WHERE status='held_duration_mismatch'"
        ).fetchall()
    rejected = set()
    for jid,sid,path in entries:
        p = Path(path)
        if (p.parent == STAGED / "held-duration" and p.is_file()
                and not p.is_symlink() and 0 < p.stat().st_size <= 2_000_000):
            rejected.add((str(jid), str(sid)))
    return rejected


def choices(inventory, searches, already, budget, kind):
    queue = priorities.active_coverage_queue()
    already = set(already) | rejected_duration_candidates()
    possible = []
    for jid, text in searches:
        row = inventory.get(str(jid))
        if not row or row.get("status") != "ready_ja_search":
            continue
        if row.get("kind") not in ("Movie", "Episode"):
            continue
        order = priorities.queue_position(row, "stage", queue)
        if order is None:
            continue
        try:
            result = json.loads(text)
        except ValueError:
            continue
        candidates = (result.get("candidates") or []) if isinstance(result, dict) else []
        plausible = [c for c in candidates if isinstance(c, dict)
                     and identity_ok(row, c)
                     and (str(jid), str(c["subtitle_id"])) not in already]
        if not plausible:
            continue
        plausible.sort(key=lambda r: (
            -int(r.get("score") or 0),
            str(r.get("subtitle_id") or "")
        ))
        c = plausible[0]
        label = (str(row.get("series_title")) +
                 f' S{row["season"]:02d}E{row["episode"]:02d}'
                 if row["kind"] == "Episode"
                 else f'{row.get("title")} ({row.get("year")})')
        if kind == "movie" and row["kind"] != "Movie":
            continue
        if kind == "episode" and row["kind"] != "Episode":
            continue
        possible.append((order, -int(c.get("score") or 0), label.casefold(),
                         str(jid), {"row": row, "candidate": c, "label": label}))
    possible.sort(key=lambda x: x[:4])
    # Download saved high-confidence JA sources across BOTH media types in
    # queue order. Never use an arbitrary percentage split.
    return [x[4] for x in possible[:budget]]

def has_embedded_english_reference(streams):
    """Cheap pre-download *potential reference* filter, not a sync verdict.

    A real sync verdict still requires the downstream timing audit to parse
    a meaningful number of English cues and compare them with Japanese.
    """
    codecs = {"subrip", "srt", "ass", "ssa", "webvtt", "mov_text", "text"}
    languages = {"en", "eng", "english"}
    return any(
        isinstance(stream, dict)
        and stream.get("codec_type") == "subtitle"
        and str(stream.get("codec_name") or "").casefold() in codecs
        and str((stream.get("tags") or {}).get("language") or "")
            .casefold().split("-")[0] in languages
        and not (stream.get("disposition") or {}).get("forced")
        for stream in streams
    )


def potential_timing_reference(row):
    """Inspect video metadata only; never download subtitles or write files."""
    video = Path(str(row.get("host_path") or ""))
    if (not video.is_absolute() or video.is_symlink() or not video.is_file()
            or video.suffix.casefold() not in SUPPORTED_VIDEO):
        return False
    try:
        resolved = video.resolve()
        if not any(resolved.is_relative_to(root.resolve())
                   for root in ALLOWED_HOST_ROOTS):
            return False
        run = subprocess.run(
            ["ffprobe", "-v", "error", "-show_streams", "-of", "json",
             str(video)],
            capture_output=True, timeout=20, check=False
        )
        if run.returncode:
            return False
        metadata = json.loads(run.stdout)
        streams = metadata.get("streams") or []
        return isinstance(streams, list) and has_embedded_english_reference(streams)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return False


def japanese_sidecar_exists(video):
    prefix = video.stem.casefold() + "."
    for sibling in video.parent.iterdir():
        if sibling.is_symlink() or not sibling.is_file():
            continue
        if sibling.suffix.casefold() not in VALID_SUBTITLES:
            continue
        if not sibling.name.casefold().startswith(prefix):
            continue
        tags = set(re.findall(r"[a-z0-9]+",
                              sibling.name.casefold()[len(prefix):-len(sibling.suffix)]))
        if tags & JA and not (tags & {"forced", "signs"}):
            return True
    return False


def duration_if_safe(row):
    video = Path(str(row["host_path"]))
    if (not video.is_absolute() or video.is_symlink()
            or not video.is_file() or video.suffix.casefold() not in SUPPORTED_VIDEO):
        raise RuntimeError("video_missing_or_not_regular")
    resolved = video.resolve()
    if not any(resolved.is_relative_to(root.resolve())
               for root in ALLOWED_HOST_ROOTS):
        raise RuntimeError("video_outside_approved_media_roots")
    if row["kind"] == "Episode":
        tags = named_episode(video.stem)
        if tags and tags != {(row["season"], row["episode"])}:
            raise RuntimeError("jellyfin_file_episode_numbering_conflict")
    if japanese_sidecar_exists(video):
        raise RuntimeError("japanese_sidecar_already_present")
    result = subprocess.run(
        ["ffprobe", "-v", "error",
         "-show_entries", "format=duration:stream=codec_type:stream_tags=language",
         "-of", "json", str(video)],
        capture_output=True, text=True, timeout=35
    )
    if result.returncode:
        raise RuntimeError("ffprobe_failed")
    metadata = json.loads(result.stdout)
    audio_langs = []
    for stream in metadata.get("streams", []):
        lang = str(stream.get("tags", {}).get("language") or "").casefold().split("-")[0]
        if stream.get("codec_type") == "subtitle" and lang in JA:
            raise RuntimeError("embedded_japanese_subtitle_already_present")
        if stream.get("codec_type") == "audio":
            audio_langs.append(lang)
    if audio_langs and audio_langs[0] in JA:
        raise RuntimeError("japanese_audio_already_present")
    duration = float((metadata.get("format") or {}).get("duration") or 0)
    if not 600 <= duration <= 4 * 3600:
        raise RuntimeError("video_duration_invalid")
    return duration


def stage_db():
    if STAGE_DB.is_symlink() or (STAGE_DB.exists()
                               and STAGE_DB.stat().st_mode & 0o077):
        raise RuntimeError("unsafe_stage_database")
    previous_umask = os.umask(0o077)
    try:
        db = sqlite3.connect(STAGE_DB, timeout=15)
    finally:
        os.umask(previous_umask)
    db.execute("""CREATE TABLE IF NOT EXISTS staged (
        jellyfin_id TEXT NOT NULL,
        subtitle_id TEXT NOT NULL,
        host_path TEXT NOT NULL,
        sha256 TEXT NOT NULL,
        staged_at INTEGER NOT NULL,
        status TEXT NOT NULL,
        metrics_json TEXT NOT NULL,
        PRIMARY KEY(jellyfin_id,subtitle_id)
    )""")
    db.commit()
    return db


def preserve_from_container(row, candidate, report, *, hold_duration=False):
    metrics = report.get("metrics")
    if not isinstance(metrics, dict):
        raise RuntimeError("stage_metrics_missing")
    fmt = metrics.get("format")
    name = stage_name(row, candidate, fmt)
    expected = "/tmp/bruiser-subhub-ja-first-staged/" + name
    if report.get("stage_path") != expected:
        raise RuntimeError("unexpected_container_staging_path")
    STAGED.mkdir(mode=0o700, exist_ok=True)
    if STAGED.is_symlink() or STAGED.stat().st_mode & 0o077:
        raise RuntimeError("unsafe_private_staging_folder")
    destination = STAGED / "held-duration" if hold_duration else STAGED
    destination.mkdir(mode=0o700, exist_ok=True)
    if destination.is_symlink() or destination.stat().st_mode & 0o077:
        raise RuntimeError("unsafe_private_duration_hold_folder")
    target = destination / name
    tempdir = Path(tempfile.mkdtemp(prefix=".copy-", dir=STAGED))
    tmp = tempdir / name
    try:
        copy = subprocess.run(
            ["docker", "cp", "sublarr-pilot:" + expected, str(tmp)],
            capture_output=True, text=True, timeout=35
        )
        if copy.returncode:
            raise RuntimeError("docker_copy_failed")
        if not tmp.is_file() or tmp.is_symlink() or not (0 < tmp.stat().st_size <= 2_000_000):
            raise RuntimeError("copied_subtitle_invalid")
        tmp.chmod(0o600)
        digest = hashlib.sha256(tmp.read_bytes()).hexdigest()
        try:
            os.link(tmp, target)  # O_EXCL-like: never overwrite a staged file.
        except FileExistsError:
            if target.is_symlink() or hashlib.sha256(target.read_bytes()).hexdigest() != digest:
                raise RuntimeError("conflicting_existing_staged_file")
        return target, digest
    finally:
        shutil.rmtree(tempdir)


def record_native_download_attempt(stdout, report, *, path=None):
    """Count a real native GET even when subsequent subtitle QA rejects it.

    A cached stage never sends REQUEST. Recording is based on the worker's
    actual download boundary, not a guessed limit or the final stage verdict.
    """
    if "SUBHUB_DOWNLOAD_REQUEST: opensubtitles" not in stdout:
        return False
    event=ledger.begin("opensubtitles","sublarr_native",path=path)
    received=re.findall(r"(?m)^SUBHUB_DOWNLOAD_RECEIVED: ([0-9]{1,7})$",stdout)
    if len(received)==1 and 0<int(received[0])<=2_000_000:
        ledger.finish(event,"downloaded",byte_count=int(received[0]),path=path)
        return True
    error=str(report.get("error_type") or "")+" "+str(report.get("error") or "")
    if re.search(r"(?i)(?:\b(?:429|406|quota)\b|rate[_ -]?limit|"
                 r"budget[_ -]?exhaust|download[_ -]?limit)",error):
        ledger.finish(event,"quota_blocked",error_kind="provider_limit",path=path)
    else:
        ledger.finish(event,"failed",error_kind="download_no_bytes",path=path)
    return True


def run_one(job, database):
    row, candidate = job["row"], job["candidate"]
    runtime = duration_if_safe(row)
    payload = {
        "jellyfin_id": row["jellyfin_id"],
        "subtitle_id": str(candidate["subtitle_id"]),
        "provider": "opensubtitles",
        "filename": candidate.get("filename"),
        "release_info": candidate.get("release_info"),
        "matches": candidate.get("matches") or [],
        "duration": runtime
    }
    command = ["docker", "exec", "-i", "-e", "PYTHONPATH=/app",
               "sublarr-pilot", "python3", "-c", WORKER]
    result = subprocess.run(command, input=json.dumps(payload),
                            text=True, capture_output=True, timeout=120)
    lines = [x for x in result.stdout.splitlines()
             if x.startswith("STAGE_RESULT_JSON:")]
    report = json.loads(lines[-1][len("STAGE_RESULT_JSON:"):]) if lines else {}
    # Account BEFORE interpreting the final worker outcome: a downloaded file
    # still consumes allowance if its Japanese text or timing later fails QA.
    record_native_download_attempt(result.stdout,report)
    if not lines:
        raise RuntimeError("container_staging_result_missing")
    if result.returncode or report.get("result") not in (
        "staged_not_published", "already_staged", "held_duration_mismatch"
    ):
        raise RuntimeError("container_staging_blocked:" +
                           str(report.get("error") or report.get("error_type") or "unknown")[:70])
    held = report["result"] == "held_duration_mismatch"
    target, digest = preserve_from_container(
        row, candidate, report, hold_duration=held)
    database.execute("""INSERT INTO staged
        (jellyfin_id,subtitle_id,host_path,sha256,staged_at,status,metrics_json)
        VALUES (?,?,?,?,?,?,?)
        ON CONFLICT(jellyfin_id,subtitle_id) DO UPDATE SET
          host_path=excluded.host_path,sha256=excluded.sha256,
          staged_at=excluded.staged_at,status=excluded.status,
          metrics_json=excluded.metrics_json
    """, (str(row["jellyfin_id"]), str(candidate["subtitle_id"]),
          str(target), digest, int(time.time()),
          "held_duration_mismatch" if held else "staged",
          json.dumps({**report["metrics"],
                      "provider":"opensubtitles",
                      "source_filename":str(candidate.get("filename") or "")[:240],
                      "source_release":str(candidate.get("release_info") or "")[:240]},
                     ensure_ascii=False)))
    database.commit()
    print("STAGED_HELD:" if held else "STAGED:", target, flush=True)
    print("METRICS:", json.dumps(report["metrics"], ensure_ascii=False), flush=True)
    if held:
        raise RuntimeError("subtitle_duration_inconsistent_saved_private:"
                           + str(report["metrics"].get("last_end_video_ratio")))
    return str(report["result"])


def self_test():
    compile(WORKER, "<sublarr-ja-staging-worker>", "exec")
    movie = {"kind": "Movie", "title": "Fargo", "year": 1996,
             "imdb_id": "tt0116282"}
    fargo = {"provider": "opensubtitles", "subtitle_id": "8690333",
             "language": "ja", "filename": "1996-_Fargo", "release_info": "1996- Fargo",
             "score": 60, "matches": ["title"]}
    assert identity_ok(movie, fargo)
    assert not identity_ok(movie, dict(fargo, filename="Fargo.1999",
                                      release_info="Fargo 1999"))
    episode = {"kind": "Episode", "season": 22, "episode": 1,
               "series_title": "American Dad!", "series_imdb_id": "tt0397306"}
    american_dad = {"provider": "opensubtitles", "subtitle_id": "11947715",
                    "language": "ja", "filename": "American.Dad.S22E01.ja",
                    "matches": ["series", "season", "episode"]}
    assert identity_ok(episode, american_dad)
    assert not identity_ok(episode, dict(american_dad,
                                        filename="American.Dad.S22E02.ja"))
    assert not identity_ok(episode, dict(american_dad, matches=["season", "episode"]))
    assert stage_name({"jellyfin_id": "a"*32}, fargo, "srt").endswith(
        ".opensubtitles.8690333.ja.srt")
    assert has_embedded_english_reference([{
        "codec_type": "subtitle", "codec_name": "subrip",
        "tags": {"language": "eng"}, "disposition": {"forced": 0}
    }])
    assert not has_embedded_english_reference([{
        "codec_type": "subtitle", "codec_name": "hdmv_pgs_subtitle",
        "tags": {"language": "eng"}, "disposition": {"forced": 0}
    }])
    assert not has_embedded_english_reference([{
        "codec_type": "subtitle", "codec_name": "subrip",
        "tags": {"language": "eng"}, "disposition": {"forced": 1}
    }])
    print("SELF-TEST PASSED: identity and reference filters; no network or writes",
          flush=True)


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--budget", type=int, default=3,
                     help="maximum staged OpenSubtitles downloads: 1..200")
    cli.add_argument("--kind", choices=("all", "movie", "episode"),
                     default="all")
    cli.add_argument("--require-embedded-en", action="store_true",
                     help="select only candidates with an embedded English text track, "
                          "to prioritize later trusted timing comparison")
    cli.add_argument("--apply", action="store_true",
                     help="permit downloading and durable private staging")
    cli.add_argument("--self-test", action="store_true")
    opts = cli.parse_args()
    if opts.self_test:
        self_test()
        return
    if not 1 <= opts.budget <= 200:
        cli.error("--budget must be 1..200")
    inventory = read_inventory()
    history = read_saved_searches()
    already = read_staged()
    if opts.require_embedded_en:
        # Search at most 24 manifest-confirmed candidate rows. Never probe
        # thousands of media files for a small acquisition budget.
        pool = choices(inventory, history, already, 24, opts.kind)
        selected = []
        considered = 0
        for option in pool:
            considered += 1
            print(f'  REFERENCE CHECK [{considered}/{len(pool)}]: '
                  f'{option["label"]}', flush=True)
            found = potential_timing_reference(option["row"])
            print("    embedded English text:",
                  "found" if found else "not found / not verifiable", flush=True)
            if found:
                selected.append(option)
                if len(selected) >= opts.budget:
                    break
        print("EMBEDDED ENGLISH REFERENCE FILTER:",
              f"{len(selected)} eligible among {considered} assessed"
              f" (pool capped at {len(pool)} candidates)", flush=True)
        print("Reference presence is not a verified synchronization fit.",
              flush=True)
    else:
        selected = choices(inventory, history, already, opts.budget, opts.kind)
    print("=== JAPANESE SUBTITLE STAGING BATCH ===", flush=True)
    print("Available saved search entries:", len(history), flush=True)
    print("Selected:", len(selected), "| budget:", opts.budget, flush=True)
    for i, job in enumerate(selected, 1):
        print(f'  [{i}] {job["label"]} | OpenSubtitles ID '
              f'{job["candidate"]["subtitle_id"]}', flush=True)
    if not selected:
        if opts.require_embedded_en:
            print("No candidate with a confirmed embedded English text track "
                  "in the checked pool; other discovery results are retained.",
                  flush=True)
        else:
            print("No new high-confidence candidates to stage.", flush=True)
        return
    if not opts.apply:
        print("PREFLIGHT ONLY: No downloads, database writes, or media changes.",
              flush=True)
        return
    with stage_db() as database:
        completed = Counter()
        for i, job in enumerate(selected, 1):
            print(f'[{i}/{len(selected)}] STAGING: {job["label"]}', flush=True)
            try:
                result = run_one(job, database)
                completed[result] += 1
            except (RuntimeError, OSError, ValueError, subprocess.TimeoutExpired) as exc:
                message = str(exc).lower()
                completed["held"] += 1
                print("HELD:", job["label"], type(exc).__name__,
                      str(exc)[:135], flush=True)
                # Respect the existing API account's actual download allowance.
                # Do not send hundreds of further download attempts after
                # the native provider reports exhaustion/cooldown/HTTP 429.
                if any(text in message for text in (
                    "quota", "rate_limit", "ratelimit", "cooling",
                    "exhausted", "download_limit", "download limit",
                    "allowed subtitles", "429", "406",
                )):
                    print("PROVIDER_LIMIT_REACHED: stop further downloads "
                          "for this cycle; staged files retained", flush=True)
                    completed["provider_limited"] += 1
                    break
        print("BATCH RESULT:", dict(completed), flush=True)
        print("Files preserved privately under:", STAGED, flush=True)
        print("NOT PUBLISHED: media folders and Jellyfin remain unchanged.", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("STAGING ERROR:", type(exc).__name__, str(exc)[:140], file=sys.stderr)
        raise SystemExit(1) from None
