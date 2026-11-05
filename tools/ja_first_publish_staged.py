#!/usr/bin/env python3
"""Create-only publication of ONE verified, staged Japanese subtitle.

Uses the existing SubHub stage database, Japanese search evidence, Jellyfin
identity manifest, and host-native timing audit. No downloads or AI work.
Default action is read-only preflight. --apply adds exactly one .ja.srt beside
the identified video; refuses to overwrite any existing subtitle file.

Requires sibling repo modules:
  ja_first_stage_saved_batch.py  (candidate identity check)
  ja_first_stage_timing_audit.py (trusted embedded timing check)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import tempfile
from urllib.parse import quote

from ja_first_stage_saved_batch import identity_ok
from ja_first_stage_timing_audit import (
    ROOT, STAGED, STAGE_DB, STAGE_NAME,
    private_file, safe_media_path, inspect, ffprobe_streams,
)

SEARCH_DB = ROOT / "japanese-search.sqlite3"
JA = {"ja", "jp", "jpn", "japanese"}
SUB_EXT = {".srt", ".ass", ".ssa", ".vtt"}
KANA_KANJI = re.compile(r"[\u3040-\u30ff\u3400-\u9fff]")
SRT = re.compile(
    r"(?m)^[ \t]*(\d{1,3}:)?\d{2}:\d{2}[,.]\d{2,3}[ \t]*-->"
    r"[ \t]*(\d{1,3}:)?\d{2}:\d{2}[,.]\d{2,3}"
)
TIMING_THRESHOLD = 0.75
EXPECTED_ID_PATTERN = re.compile(r"[a-f0-9]{32}\Z")


def db_uri(path):
    private_file(path, path.name)
    return "file:" + quote(str(path.resolve()), safe="/") + "?mode=ro"


def video_target(video):
    return video.with_name(video.stem + ".ja.srt")


def read_inventory(jid):
    if not ROOT.is_dir() or ROOT.is_symlink() or ROOT.stat().st_mode & 0o077:
        raise RuntimeError("unsafe_inventory_root")
    manifests = sorted(ROOT.glob("ja-intake-*.json"))
    if not manifests:
        raise RuntimeError("inventory_missing")
    manifest = manifests[-1]
    private_file(manifest, "inventory")
    data = json.loads(manifest.read_text(encoding="utf-8"))
    if data.get("schema") != 1:
        raise RuntimeError("unsupported_inventory_schema")
    matches = [x for x in data.get("items", [])
               if isinstance(x, dict) and str(x.get("jellyfin_id")) == jid]
    if len(matches) != 1 or matches[0].get("status") != "ready_ja_search":
        raise RuntimeError("jellyfin_identity_not_unique_or_no_longer_eligible")
    return matches[0]


def read_staging(jid, sid):
    uri = db_uri(STAGE_DB)
    with sqlite3.connect(uri, uri=True, timeout=10) as connection:
        records = connection.execute(
            """SELECT host_path,sha256,status,metrics_json FROM staged
               WHERE jellyfin_id=? AND subtitle_id=?""", (jid, sid)
        ).fetchall()
    if len(records) != 1 or records[0][2] != "staged":
        raise RuntimeError("not_in_successfully_staged_database")
    filename, digest, _, metrics_text = records[0]
    if not STAGED.is_dir() or STAGED.is_symlink() or STAGED.stat().st_mode & 0o077:
        raise RuntimeError("unsafe_private_staging_directory")
    staged = Path(filename)
    match = STAGE_NAME.fullmatch(staged.name)
    if (not match or match.group(1) != jid or match.group(2) != sid
            or match.group(3) != "srt" or staged.parent != STAGED):
        raise RuntimeError("staged_filename_or_path_mismatch")
    private_file(staged, "staged_subtitle")
    if not 0 < staged.stat().st_size <= 2_000_000:
        raise RuntimeError("staged_subtitle_size_invalid")
    data = staged.read_bytes()
    if hashlib.sha256(data).hexdigest() != digest:
        raise RuntimeError("staged_sha256_mismatch")
    metrics = json.loads(metrics_text)
    if metrics.get("format") != "srt" or metrics.get("bytes") != len(data):
        raise RuntimeError("staging_format_or_size_mismatch")
    return staged, data, metrics


def verify_search_identity(row, jid, sid):
    uri = db_uri(SEARCH_DB)
    with sqlite3.connect(uri, uri=True, timeout=10) as db:
        records = db.execute(
            "SELECT results_json FROM searches WHERE jellyfin_id=?", (jid,)
        ).fetchall()
    if len(records) != 1:
        raise RuntimeError("saved_search_identity_missing")
    search = json.loads(records[0][0])
    candidates = [candidate for candidate in search.get("candidates", [])
                  if isinstance(candidate, dict)
                  and candidate.get("provider") == "opensubtitles"
                  and str(candidate.get("subtitle_id")) == sid
                  and identity_ok(row, candidate)]
    if len(candidates) != 1:
        raise RuntimeError("candidate_not_safely_identified_in_search_history")


def check_no_existing_ja(video, streams):
    # Stop for ANY matching Japanese sidecar, including .forced or SDH,
    # rather than risking overwriting a separate curated Japanese track.
    prefix = video.stem.casefold() + "."
    for sibling in video.parent.iterdir():
        if sibling.is_symlink() and sibling.name.casefold().startswith(prefix):
            raise RuntimeError("symlinked_subtitle_neighbor")
        if sibling.suffix.casefold() not in SUB_EXT:
            continue
        text = sibling.name.casefold()
        if not text.startswith(prefix):
            continue
        tags = set(re.findall(r"[a-z0-9]+",
                   text[len(prefix):-len(sibling.suffix)]))
        if tags & JA:
            raise RuntimeError("japanese_sidecar_already_exists")
    if streams is None:
        raise RuntimeError("cannot_verify_embedded_subtitles")
    audio_languages = []
    for stream in streams:
        kind = stream.get("codec_type")
        lang = str((stream.get("tags") or {}).get("language") or "").casefold().split("-")[0]
        if kind == "subtitle" and lang in JA:
            raise RuntimeError("japanese_embedded_subtitle_already_exists")
        if kind == "audio":
            audio_languages.append(lang)
    if audio_languages and audio_languages[0] in JA:
        raise RuntimeError("primary_audio_is_japanese")
    target = video_target(video)
    if target.is_symlink() or target.exists():
        raise RuntimeError("publication_target_already_exists")
    return target


def validate_srt(content, runtime):
    if not 0 < len(content) <= 2_000_000:
        raise RuntimeError("invalid_srt_byte_size")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeError:
        raise RuntimeError("srt_not_valid_utf8") from None
    if "\ufffd" in text or "\x00" in text:
        raise RuntimeError("srt_contains_invalid_text")
    blocks = re.split(r"\r?\n[ \t]*\r?\n", text.strip())
    timed = []
    japanese_blocks = 0
    chars = 0
    for block in blocks:
        if not block.strip():
            continue
        lines = block.splitlines()
        # Each SRT cue can have an optional numeric index followed by its
        # full time arrow and dialogue. Reject unparseable blocks.
        arrow_index = 1 if lines[0].strip().isdigit() else 0
        if len(lines) < arrow_index + 2:
            raise RuntimeError("empty_or_malformed_srt_cue")
        timing = lines[arrow_index].strip()
        if not SRT.fullmatch(timing):
            raise RuntimeError("unparseable_srt_timestamp")
        dialogue = "\n".join(lines[arrow_index + 1:]).strip()
        if not dialogue:
            raise RuntimeError("empty_srt_dialogue")
        n = len(KANA_KANJI.findall(dialogue))
        chars += n
        if n:
            japanese_blocks += 1
        timed.append(timing)
    if len(timed) < 75 or len(timed) > 6000:
        raise RuntimeError("unreasonable_srt_cue_count")
    if chars < 200 or japanese_blocks / len(timed) < 0.70:
        raise RuntimeError("japanese_text_density_insufficient")
    if len(timed) < runtime / 20:  # e.g. 21min / 20 => 65 cues minimum
        raise RuntimeError("subtitle_too_sparse_for_full_dialogue")
    return {
        "cues": len(timed),
        "japanese_characters": chars,
        "japanese_cue_fraction": round(japanese_blocks / len(timed), 3)
    }


def metadata_label(row):
    if row["kind"] == "Episode":
        return f'{row["series_title"]} S{row["season"]:02d}E{row["episode"]:02d}'
    return f'{row.get("title")} ({row.get("year")})'


def preflight(jid, sid):
    if not EXPECTED_ID_PATTERN.fullmatch(jid) or not sid.isdigit():
        raise RuntimeError("invalid_requested_identity")
    row = read_inventory(jid)
    if row.get("kind") not in {"Movie", "Episode"}:
        raise RuntimeError("unsupported_media_type")
    if row["kind"] == "Episode" and not (
        row.get("series_title") and type(row.get("season")) is int
        and row["season"] > 0 and type(row.get("episode")) is int
        and row["episode"] > 0
    ):
        raise RuntimeError("missing_series_identity_or_episode_number")
    verify_search_identity(row, jid, sid)
    staged, content, metrics = read_staging(jid, sid)
    video = safe_media_path(str(row.get("host_path") or ""))
    if row["kind"] == "Episode":
        from ja_first_stage_saved_batch import named_episode
        filename_tags = named_episode(video.stem)
        if filename_tags and filename_tags != {(row["season"], row["episode"])}:
            raise RuntimeError("episode_filename_conflicts_with_jellyfin_identity")
    target = video_target(video)
    streams, probe_error = ffprobe_streams(video)
    if probe_error or not isinstance(streams, list):
        raise RuntimeError("ffprobe_cannot_verify_existing_subtitles")
    check_no_existing_ja(video, streams)

    timing = inspect(row, content)
    if (timing.get("status") != "fit"
            or timing.get("reference_trust") != "trusted_embedded"
            or timing.get("matching_start_fraction", 0) < TIMING_THRESHOLD
            or abs(timing.get("best_offset_seconds", 999)) > 0.2):
        raise RuntimeError("trusted_embedded_timing_gate_not_met:" + timing.get("status", "unknown"))
    # Staging validator established the media duration from ffprobe.
    runtime = float(metrics.get("video_seconds") or 0)
    if not 600 <= runtime <= 4 * 3600:
        raise RuntimeError("invalid_staged_video_duration")
    # New ffprobe reading avoids publishing against a replaced video file.
    duration_probe = subprocess_duration(video)
    if abs(duration_probe - runtime) > 0.5:
        raise RuntimeError("video_duration_changed_since_staging")
    qa = validate_srt(content, runtime)
    if abs(qa["cues"] - int(metrics.get("cues") or 0)) > 0:
        raise RuntimeError("srt_cue_count_changed_since_staging")
    # Lightweight sourcing gate: reject only unmistakable garbage, not
    # unreviewed phrasing or natural Japanese paraphrases.
    from ja_first_obvious_quality import require_not_garbage
    require_not_garbage(content)
    print("=== JAPANESE SUBTITLE PUBLICATION PREFLIGHT ===", flush=True)
    print("MEDIA:", metadata_label(row), flush=True)
    print("TARGET:", target, flush=True)
    print("STAGING:", staged, flush=True)
    print("TEXT CHECK:", json.dumps(qa, ensure_ascii=False), flush=True)
    print("TIMING:", json.dumps(timing, ensure_ascii=False), flush=True)
    print("EXISTING JAPANESE TRACKS: none detected", flush=True)
    print("STATUS: eligible for create-only publication; quality not editorially reviewed",
          flush=True)
    return row, video, target, content


def subprocess_duration(video):
    import subprocess
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(video)],
        capture_output=True, text=True, timeout=35
    )
    if result.returncode:
        raise RuntimeError("ffprobe_duration_failed")
    return float(result.stdout.strip())


def publish(row, video, target, content):
    # Enforce the same low-threshold source sanity gate for every route
    # (audio ffsubsync, trusted embedded alignment, and corrected fallback).
    from ja_first_obvious_quality import require_not_garbage
    gross_qa = require_not_garbage(content)
    print("SOURCED_GROSS_QA:", gross_qa["verdict"],
          "warnings", ",".join(gross_qa["warnings"]) or "none",
          "(not a translation-quality grade)", flush=True)
    # Final existence check just before atomic create; the actual hard-link
    # creation is also no-clobber, even if another process races this run.
    streams, probe_error = ffprobe_streams(video)
    if probe_error:
        raise RuntimeError("final_embedded_track_verification_failed")
    check_no_existing_ja(video, streams)
    fd, temporary = tempfile.mkstemp(
        prefix="." + target.name + ".staging-", suffix=".tmp",
        dir=str(target.parent)
    )
    temp = Path(temporary)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        temp.chmod(0o644)
        try:
            os.link(temp, target, follow_symlinks=False)
        except FileExistsError:
            raise RuntimeError("target_appeared_concurrently_refusing_overwrite") from None
        # The created file is now complete and immutable-by-this-tool.
        folder_fd = os.open(video.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(folder_fd)
        finally:
            os.close(folder_fd)
    finally:
        temp.unlink(missing_ok=True)
    print("PUBLISHED:", target, flush=True)
    print("SHA256:", hashlib.sha256(content).hexdigest(), flush=True)
    print("CREATE ONLY: source video and existing subtitle tracks unchanged.",
          flush=True)


def self_test():
    sample = (
        "1\n00:00:01,000 --> 00:00:02,000\nこんにちは\n\n"
        "2\n00:00:03,000 --> 00:00:04,000\nありがとう\n"
    ).encode("utf-8")
    # The sample is intentionally too short for publication.
    try:
        validate_srt(sample, 1300)
        raise AssertionError("short Japanese track should be refused")
    except RuntimeError as exc:
        assert str(exc) == "unreasonable_srt_cue_count", exc
    assert video_target(Path("/mnt/BigDisk/Video/TV/Show.S22E01.mkv")).name == "Show.S22E01.ja.srt"
    assert TIMING_THRESHOLD == 0.75
    print("SELF-TEST PASSED: SRT gate and create-only target naming; no files or network",
          flush=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--jellyfin-id", required=False, default="")
    ap.add_argument("--subtitle-id", required=False, default="")
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        self_test()
        return
    if not args.jellyfin_id or not args.subtitle_id:
        ap.error("--jellyfin-id and --subtitle-id are required")
    row, video, target, content = preflight(args.jellyfin_id, args.subtitle_id)
    if not args.apply:
        print("DRY RUN: No files or configuration changed. Add --apply to publish.",
              flush=True)
        return
    publish(row, video, target, content)
    print("Jellyfin may need a subtitle/library refresh to discover the new track.",
          flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("PUBLICATION HELD:", type(exc).__name__, str(exc)[:160],
              file=sys.stderr)
        raise SystemExit(1) from None
