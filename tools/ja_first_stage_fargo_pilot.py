#!/usr/bin/env python3
"""Stage ONE previously discovered Fargo (1996) Japanese subtitle for inspection.

OptiPlex host command. Requires the private Japanese-first inventory/search
history and an already-running Sublarr container. Makes no new searches.
May consume ONE OpenSubtitles download allowance after --apply is supplied.
Never writes media folders, publishes, modifies provider config, or runs AI.

No --apply: read-only preflight. --self-test: no network or writes.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import time

ROOT = Path.home() / "bruiser-pilot/ja-first-inventory"
DB = ROOT / "japanese-search.sqlite3"
CANDIDATE_ID = "8690333"
MOVIE = "Fargo"
YEAR = 1996
JA = {"ja", "jp", "jpn", "japanese"}
SUBS = {".srt", ".ass", ".ssa", ".vtt"}

# Worker runs inside the EXISTING Sublarr process namespace, but is a new
# Python subprocess: it reads configured credentials without printing them.
WORKER = r'''
import json, os, re, sys
from pathlib import Path
from providers.base import SubtitleFormat, SubtitleResult
from providers.opensubtitles import OpenSubtitlesProvider
from config import get_settings

STAGE = Path("/tmp/bruiser-subhub-ja-first-staged")
STEM = "fargo-1996.opensubtitles.8690333.ja"
MAX_BYTES = 2_000_000
SRT_TIMING = re.compile(r"(?m)(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2})[,.](\d{3})")
ASS_TIMING = re.compile(r"(?m)^Dialogue:\s*[^,]*,(\d+):(\d{2}):(\d{2})\.(\d{2}),(\d+):(\d{2}):(\d{2})\.(\d{2}),")
JAPANESE = re.compile(r"[\u3040-\u30ff\u3400-\u9fff]")
TAGS = re.compile(r"<[^>]+>|{\\[^}]+}")

def analyze(raw, runtime):
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
        if maximum > runtime * 1.15 or maximum < runtime * 0.60:
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
            "timing_note": "Duration plausible only; actual synchronization NOT confirmed",
        }
    raise RuntimeError("unrecognized_subtitle_timing_or_encoding")

def run(job):
    if job.get("subtitle_id") != "8690333":
        raise RuntimeError("unapproved_subtitle_id")
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
                meta = analyze(data, runtime)
                if meta["format"] != ext:
                    raise RuntimeError("cached_subtitle_format_mismatch")
                return {"result": "already_staged", "stage_path": str(path),
                        "metrics": meta, "new_download": False}

    cfg = get_settings()
    key = str(getattr(cfg, "opensubtitles_api_key", "") or "").strip()
    if not key:
        raise RuntimeError("opensubtitles_api_key_not_available")
    user = str(getattr(cfg, "opensubtitles_username", "") or "").strip()
    password = str(getattr(cfg, "opensubtitles_password", "") or "").strip()
    provider = OpenSubtitlesProvider(api_key=key, username=user, password=password)
    provider.initialize()
    try:
        if not provider.session:
            raise RuntimeError("opensubtitles_initialization_failed")
        candidate = SubtitleResult(
            provider_name="opensubtitles", subtitle_id="8690333",
            language="ja", format=SubtitleFormat.UNKNOWN,
            filename="1996-_Fargo", release_info="1996- Fargo",
            matches={"title"}, provider_data={"file_id": 8690333},
        )
        raw = provider.download(candidate)  # At most one /download request.
    finally:
        provider.terminate()
    metrics = analyze(raw, runtime)
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
    return {"result": "staged_not_published", "stage_path": str(path),
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


def check_privacy(path):
    if not path.is_file() or path.is_symlink() or path.stat().st_mode & 0o077:
        raise RuntimeError("missing_or_unsafe_private_file")


def latest_manifest():
    if not ROOT.is_dir() or ROOT.is_symlink() or ROOT.stat().st_mode & 0o077:
        raise RuntimeError("unsafe_inventory_directory")
    paths = sorted(ROOT.glob("ja-intake-*.json"))
    if not paths:
        raise RuntimeError("no_intake_manifest")
    path = paths[-1]
    check_privacy(path)
    if time.time() - path.stat().st_mtime > 72*3600:
        raise RuntimeError("inventory_is_stale")
    content = json.loads(path.read_text(encoding="utf8"))
    if content.get("schema") != 1:
        raise RuntimeError("unsupported_manifest_schema")
    return content


def japanese_sidecar_exists(path):
    prefix = path.stem.casefold() + "."
    for other in path.parent.iterdir():
        if other.is_symlink() or not other.is_file():
            continue
        if other.suffix.casefold() not in SUBS or not other.name.casefold().startswith(prefix):
            continue
        suffix = other.name.casefold()[len(prefix):-len(other.suffix)]
        tokens = set(filter(None, re.split(r"[^a-z0-9]+", suffix)))
        if tokens & JA and not tokens & {"forced", "signs"}:
            return True
    return False


def inspect_video(path):
    if path.is_symlink() or not path.is_file():
        raise RuntimeError("movie_path_not_regular_file")
    if japanese_sidecar_exists(path):
        raise RuntimeError("movie_now_has_japanese_sidecar")
    result = subprocess.run(
        ["ffprobe", "-v", "error",
         "-show_entries", "format=duration:stream=codec_type:stream_tags=language",
         "-of", "json", str(path)],
        capture_output=True, text=True, timeout=30
    )
    if result.returncode != 0:
        raise RuntimeError("ffprobe_failed")
    info = json.loads(result.stdout)
    for stream in info.get("streams", []):
        if stream.get("codec_type") == "subtitle" and (
            str(stream.get("tags", {}).get("language") or "").lower().split("-")[0] in JA
        ):
            raise RuntimeError("movie_now_has_embedded_japanese_subtitle")
    duration = float((info.get("format") or {}).get("duration") or 0)
    if not 600 <= duration <= 4 * 3600:
        raise RuntimeError("unreasonable_video_duration")
    return duration


def verify_saved_candidate(db):
    check_privacy(DB)
    with sqlite3.connect("file:" + str(DB) + "?mode=ro", uri=True) as con:
        rows = con.execute(
            "SELECT jellyfin_id,results_json FROM searches WHERE kind='Movie' AND title=?",
            (MOVIE,),
        ).fetchall()
    candidates = []
    for item_id, raw in rows:
        try:
            data = json.loads(raw)
        except ValueError:
            continue
        for candidate in data.get("candidates", []):
            if (candidate.get("provider") == "opensubtitles"
                    and str(candidate.get("subtitle_id")) == CANDIDATE_ID
                    and str(candidate.get("language")).lower() in {"ja", "jpn"}
                    and candidate.get("forced") is not True):
                candidates.append(str(item_id))
    if len(set(candidates)) != 1:
        raise RuntimeError("pinned_candidate_not_found_in_search_history")
    return candidates[0]


def preflight():
    item_id = verify_saved_candidate(DB)
    manifest = latest_manifest()
    entries = [item for item in manifest.get("items", [])
               if str(item.get("jellyfin_id")) == item_id
               and item.get("kind") == "Movie"
               and item.get("title", "").casefold() == MOVIE.casefold()
               and item.get("year") == YEAR
               and item.get("status") == "ready_ja_search"]
    if len(entries) != 1:
        raise RuntimeError("fargo_manifest_identity_not_unique_or_not_eligible")
    row = entries[0]
    path = Path(row["host_path"])
    if not any(path.is_relative_to(root) for root in (
        Path("/mnt/BigDisk/Video/Movies"),
        Path("/mnt/2TB/Plex Expansion/Movies")
    )):
        raise RuntimeError("movie_outside_approved_host_roots")
    duration = inspect_video(path)
    print("TARGET: Fargo (1996) | subtitle ID: 8690333 | OpenSubtitles", flush=True)
    print("MOVIE: %s | %.1f minutes" % (path.name, duration / 60), flush=True)
    print("SAVED CANDIDATE: verified against search history and Jellyfin inventory",
          flush=True)
    return {"subtitle_id": CANDIDATE_ID, "duration": duration}


def self_test():
    assert re.search(r"[^a-z0-9]+", "Fargo.1996")
    assert "ja" in JA and "en" not in JA
    assert "STAGE_RESULT_JSON:" in WORKER
    assert "8690333" in WORKER
    print("SELF-TEST PASSED (no network, downloads or writes)")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true",
                    help="allow exactly one pinned subtitle download into container /tmp")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        self_test()
        return
    payload = preflight()
    if not args.apply:
        print("PREFLIGHT ONLY: no downloads. Add --apply for one private staging.",
              flush=True)
        return
    print("STAGING ONE CANDIDATE: may spend one OpenSubtitles download credit...",
          flush=True)
    command = ["docker", "exec", "-i", "-e", "PYTHONPATH=/app",
               "sublarr-pilot", "python3", "-c", WORKER]
    result = subprocess.run(
        command, input=json.dumps(payload),
        capture_output=True, text=True, timeout=120
    )
    for line in result.stdout.splitlines():
        if line.startswith("STAGE_RESULT_JSON:"):
            print(line[len("STAGE_RESULT_JSON:"):], flush=True)
    if result.returncode != 0:
        raise RuntimeError("staging_failed_or_blocked; see STAGE_RESULT_JSON")
    print("STAGED ONLY: no subtitles published into any media folder.", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("STAGING BLOCKED:", type(exc).__name__, str(exc)[:130], file=sys.stderr)
        raise SystemExit(1) from None
