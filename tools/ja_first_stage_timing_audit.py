#!/usr/bin/env python3
"""Read-only timing audit for previously staged Japanese subtitles.

Runs directly on the OptiPlex HOST. Uses Python stdlib plus the already-installed
ffprobe/ffmpeg binaries. Neither the host nor the container needs any Sublarr
Python timing modules. All media reads are restricted to approved local mounts.

References, in preference order:
  1. A non-forced embedded text subtitle from the SAME VIDEO FILE (trusted).
  2. A full, specifically English-tagged sidecar for the SAME VIDEO (untrusted).
No reference -> UNVERIFIED, not FIT. Even FIT is not publication approval.

ffmpeg extracts subtitle text ONLY to stdout. The tool writes no files, opens
no provider connections, does not shift subtitle timings, and never publishes.
"""
from __future__ import annotations

import argparse
import bisect
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
from urllib.parse import quote

ROOT = Path.home() / "bruiser-pilot/ja-first-inventory"
STAGE_DB = ROOT / "japanese-stage.sqlite3"
STAGED = ROOT / "staged"
ALLOWED_ROOTS = (
    Path("/mnt/BigDisk/Video"),
    Path("/mnt/2TB/Plex Expansion"),
)
VIDEO_EXTS = {".mkv", ".mp4", ".m4v", ".avi", ".mov", ".webm", ".ts", ".m2ts"}
SUB_EXTS = {".srt", ".ass", ".ssa", ".vtt"}
TEXT_CODECS = {"subrip", "srt", "ass", "ssa", "webvtt", "mov_text", "text"}
EN_LANGS = {"en", "eng", "english"}
JA_LANGS = {"ja", "jpn", "jp", "japanese"}
ID = re.compile(r"[a-f0-9]{32}\Z")
STAGE_NAME = re.compile(
    r"([a-f0-9]{32})\.opensubtitles\.([1-9][0-9]{3,13})\.ja\.(srt|ass)\Z"
)

# Accept standard SRT/VTT clocks (with optional hours) and ASS Dialogue clocks.
CLOCK_TEXT = r"(?:\d{1,3}:)?\d{2}:\d{2}[,.]\d{2,3}"
SRT_START = re.compile(
    r"(?m)^[ \t]*(" + CLOCK_TEXT + r")[ \t]*-->[ \t]*" + CLOCK_TEXT
)
ASS_DIALOGUE = re.compile(r"(?im)^[ \t]*Dialogue:[ \t]*[^\r\n]+$")
CLOCK_VALUE = re.compile(
    r"(?:(\d{1,3}):)?(\d{2}):(\d{2})[,.](\d{2,3})\Z"
)
MIN_CUES = 40
MAX_CUES = 6000
MAX_BYTES = 2_000_000
MAX_OFFSET_S = 120.0
MAX_PAIRS = 2_000_000
TOLERANCE_S = 0.35


def private_file(path: Path, name: str):
    if not path.is_file() or path.is_symlink() or path.stat().st_mode & 0o077:
        raise RuntimeError(name + "_missing_or_unsafe")


def clock_seconds(value: str):
    match = CLOCK_VALUE.fullmatch(value.strip())
    if not match:
        return None
    hours, mins, secs, ms = match.groups()
    return int(hours or 0) * 3600 + int(mins) * 60 + int(secs) + int(ms) / 10**len(ms)


def cue_starts(raw: bytes):
    """Start timestamps only; never return subtitle text to terminal output."""
    if not raw or len(raw) > MAX_BYTES:
        return []
    for encoding in ("utf-8-sig", "utf-16", "cp932", "shift_jis"):
        try:
            body = raw.decode(encoding)
        except UnicodeError:
            continue
        starts = []
        for match in SRT_START.finditer(body):
            t = clock_seconds(match.group(1))
            if t is not None:
                starts.append(t)
        if not starts:
            for match in ASS_DIALOGUE.finditer(body):
                parts = match.group(0).split(",", 3)
                if len(parts) < 3:
                    continue
                t = clock_seconds(parts[1])
                if t is not None:
                    starts.append(t)
        if starts:
            starts.sort()
            return starts[:MAX_CUES + 1]
    return []


def alignment(reference, candidate, *, min_cues=MIN_CUES):
    """Find constant cue offset, or return an explicitly inconclusive verdict.

    A 0.1s difference histogram proposes candidate offsets. Each candidate
    is then verified with a 0.35s nearest-neighbor tolerance. Reports only,
    never rewrites either subtitle. This is deliberately conservative for
    differing-language cue segmentation. Short regional audits can supply a
    smaller min_cues; that signal never by itself authorizes publication.
    """
    if not (min_cues <= len(reference) <= MAX_CUES
            and min_cues <= len(candidate) <= MAX_CUES):
        return {"status": "unverified_insufficient_alignment_data"}

    votes = Counter()
    lower = 0
    pairs = 0
    for t in reference:
        while lower < len(candidate) and candidate[lower] < t - MAX_OFFSET_S:
            lower += 1
        i = lower
        while i < len(candidate) and candidate[i] <= t + MAX_OFFSET_S:
            votes[round((candidate[i] - t) * 10)] += 1
            i += 1
            pairs += 1
            if pairs > MAX_PAIRS:
                return {"status": "unverified_alignment_complexity_limit"}
    if not votes:
        return {"status": "mismatch", "best_offset_seconds": 0.0,
                "matching_start_fraction": 0.0}

    def count_matches(offset):
        hits = 0
        for t in reference:
            position = bisect.bisect_left(
                candidate, t + offset - TOLERANCE_S
            )
            if (position < len(candidate)
                    and candidate[position] <= t + offset + TOLERANCE_S):
                hits += 1
        return hits

    best_offset, best_hits = 0.0, -1
    for bucket, _ in votes.most_common(8):
        for delta in (-2, -1, 0, 1, 2):
            offset = (bucket + delta) / 10.0
            matches = count_matches(offset)
            # When many offsets fall inside the tolerance window, prefer
            # the strongest *exact difference peak*, not the smallest
            # offset in the window (which artificially trims true shifts).
            strength = votes.get(round(offset * 10), 0)
            previous = votes.get(round(best_offset * 10), 0)
            if (matches > best_hits or
                    (matches == best_hits and
                     (strength > previous or
                      (strength == previous and abs(offset) < abs(best_offset))))):
                best_offset, best_hits = offset, matches
    ratio = min(1.0, best_hits / min(len(reference), len(candidate)))
    if ratio >= 0.60:
        status = "fit" if abs(best_offset) <= 0.5 else "shift_needed"
    elif ratio < 0.35:
        status = "mismatch"
    else:
        status = "uncertain"
    return {
        "status": status,
        "best_offset_seconds": round(best_offset, 2),
        "matching_start_fraction": round(ratio, 3),
        "timing_tolerance_seconds": TOLERANCE_S,
    }


def safe_media_path(path_text: str):
    path = Path(path_text)
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise RuntimeError("target_media_missing_or_symlink")
    if path.suffix.casefold() not in VIDEO_EXTS:
        raise RuntimeError("unsupported_media_extension")
    resolved = path.resolve()
    if not any(resolved.is_relative_to(root.resolve()) for root in ALLOWED_ROOTS):
        raise RuntimeError("media_outside_approved_roots")
    return path


def ffprobe_streams(path: Path):
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(path)],
            capture_output=True, timeout=35, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return [], "ffprobe_unavailable_or_timeout"
    if result.returncode:
        return [], "ffprobe_failed"
    try:
        value = json.loads(result.stdout)
    except ValueError:
        return [], "ffprobe_malformed_json"
    return value.get("streams", []), None


def extract_embedded(path: Path, stream_index: int):
    """Reads one existing subtitle track; ffmpeg writes only to stdout."""
    try:
        result = subprocess.run(
            ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
             "-i", str(path), "-map", f"0:{stream_index}",
             "-c:s", "srt", "-f", "srt", "pipe:1"],
            capture_output=True, timeout=65, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode or not 0 < len(result.stdout) <= MAX_BYTES:
        return None
    starts = cue_starts(result.stdout)
    return starts if MIN_CUES <= len(starts) <= MAX_CUES else None


def embedded_reference(video: Path, streams):
    eligible = []
    for stream in streams:
        if stream.get("codec_type") != "subtitle":
            continue
        if str(stream.get("codec_name", "")).casefold() not in TEXT_CODECS:
            continue
        if (stream.get("disposition") or {}).get("forced"):
            continue
        lang = str((stream.get("tags") or {}).get("language") or "").casefold()
        if lang in JA_LANGS:
            continue
        ix = stream.get("index")
        if type(ix) is not int or ix < 0:
            continue
        # English first, then other tagged, then unlabeled release text tracks.
        priority = 0 if lang in EN_LANGS else (1 if lang else 2)
        eligible.append((priority, ix, lang))
    for _, index, lang in sorted(eligible):
        times = extract_embedded(video, index)
        if times:
            return times, {
                "reference_source": "embedded_text_track",
                "reference_stream_index": index,
                "reference_language": lang or "unknown",
                "reference_trust": "trusted_embedded",
            }
    return None


def english_sidecar_reference(video: Path):
    prefix = video.stem.casefold() + "."
    try:
        siblings = list(video.parent.iterdir())
    except OSError:
        return None
    options = []
    for path in siblings:
        if (path.is_symlink() or not path.is_file()
                or path.suffix.casefold() not in SUB_EXTS):
            continue
        full_name = path.name.casefold()
        if not full_name.startswith(prefix):
            continue
        tags = re.findall(
            r"[a-z0-9]+",
            full_name[len(prefix):-len(path.suffix)]
        )
        if (not any(tag in EN_LANGS for tag in tags)
                or any(tag in {"forced", "signs"} for tag in tags)):
            continue
        options.append(path)
    for path in sorted(options, key=lambda p: p.name.casefold()):
        try:
            if not 0 < path.stat().st_size <= MAX_BYTES:
                continue
            times = cue_starts(path.read_bytes())
        except OSError:
            continue
        if MIN_CUES <= len(times) <= MAX_CUES:
            return times, {
                "reference_source": "english_sidecar",
                "reference_name": path.name,
                "reference_language": "en",
                "reference_trust": "untrusted_sidecar",
            }
    return None


def inspect(row, subtitle: bytes):
    times = cue_starts(subtitle)
    if not MIN_CUES <= len(times) <= MAX_CUES:
        return {"status": "unverified_staged_subtitle_unreadable_or_too_short",
                "japanese_cues": len(times)}
    video = safe_media_path(str(row["host_path"]))
    streams, probe_error = ffprobe_streams(video)
    ref = embedded_reference(video, streams) if streams else None
    if ref is None:
        ref = english_sidecar_reference(video)
    if ref is None:
        return {
            "status": "unverified_no_reference",
            "japanese_cues": len(times),
            "ffprobe_status": probe_error or "ok",
        }
    other_times, context = ref
    outcome = alignment(other_times, times)
    return {
        **outcome, **context,
        "japanese_cues": len(times),
        "reference_cues": len(other_times),
        "note": "Timing only; subtitle accuracy and publication are NOT approved",
    }


def load():
    if not ROOT.is_dir() or ROOT.is_symlink() or ROOT.stat().st_mode & 0o077:
        raise RuntimeError("unsafe_private_root")
    private_file(STAGE_DB, "staging_database")
    if not STAGED.is_dir() or STAGED.is_symlink() or STAGED.stat().st_mode & 0o077:
        raise RuntimeError("unsafe_staging_directory")
    manifests = sorted(ROOT.glob("ja-intake-*.json"))
    if not manifests:
        raise RuntimeError("intake_manifest_missing")
    private_file(manifests[-1], "intake_manifest")
    data = json.loads(manifests[-1].read_text(encoding="utf-8"))
    if data.get("schema") != 1:
        raise RuntimeError("unsupported_inventory_schema")
    items = {str(x["jellyfin_id"]): x for x in data.get("items", [])
             if isinstance(x, dict) and x.get("jellyfin_id")}
    uri = "file:" + quote(str(STAGE_DB.resolve()), safe="/") + "?mode=ro"
    with sqlite3.connect(uri, uri=True, timeout=10) as db:
        rows = db.execute(
            """SELECT jellyfin_id,subtitle_id,host_path,sha256,status,metrics_json
               FROM staged WHERE status='staged'
               ORDER BY staged_at,jellyfin_id"""
        ).fetchall()
    return items, rows


def select(jid, sid, host, digest, status, metrics_json, inventory):
    if not ID.fullmatch(str(jid)) or status != "staged":
        raise RuntimeError("not_a_valid_staged_identity")
    path = Path(host)
    name = STAGE_NAME.fullmatch(path.name)
    if (not name or name.group(1) != jid or name.group(2) != str(sid)
            or path.parent != STAGED):
        raise RuntimeError("staged_file_identity_or_directory_mismatch")
    private_file(path, "staged_file")
    if not 0 < path.stat().st_size <= MAX_BYTES:
        raise RuntimeError("staged_file_size_invalid")
    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() != digest:
        raise RuntimeError("staged_file_hash_mismatch")
    metrics = json.loads(metrics_json)
    if metrics.get("format") != name.group(3) or metrics.get("bytes") != len(content):
        raise RuntimeError("staging_metrics_mismatch")
    row = inventory.get(str(jid))
    if not row or row.get("status") != "ready_ja_search":
        raise RuntimeError("staged_media_missing_from_inventory")
    if row.get("kind") not in {"Movie", "Episode"}:
        raise RuntimeError("unexpected_media_type")
    return row, content



def section_timing(reference, japanese, runtime):
    """Independent opening/middle/ending cue-offset hypotheses; READ ONLY.

    Cross-language cues may merge or split dialogue. Even a high matching
    fraction is NOT independent proof of synchronization, publication, or
    grounds to withdraw an already-published file.
    """
    window = min(180, max(120, runtime * 0.12))
    mid = runtime / 2
    windows = (("opening", 0, window),
               ("middle", max(0, mid-window/2), min(runtime, mid+window/2)),
               ("ending", max(0, runtime-window), runtime))
    reports = {}
    offsets = []
    for name, first, last in windows:
        en = [t for t in reference if first <= t < last]
        ja = [t for t in japanese if first-12 <= t < last+12]
        result = alignment(en, ja, min_cues=12)
        reports[name] = {"english_cues": len(en), "japanese_cues": len(ja), **result}
        if (result.get("status") in {"fit", "shift_needed"} and
                result.get("matching_start_fraction", 0) >= 0.60):
            offsets.append(result["best_offset_seconds"])
    spread = round(max(offsets)-min(offsets), 2) if len(offsets) >= 2 else None
    status = ("possible_variable_offset_review" if spread is not None and spread > 1.5
              else "inconclusive_section_evidence" if spread is None
              else "offsets_consistent_not_verified")
    return {"status": status, "offset_spread_seconds": spread, "sections": reports,
            "caution": "Requires dialogue-level and playback checks before repair or ejection"}


def inspect_published_video(video_path):
    """Explicit, read-only check of an existing video and its .ja.srt sidecar."""
    video = safe_media_path(video_path)
    sidecar = video.with_suffix(".ja.srt")
    if sidecar.is_symlink() or not sidecar.is_file():
        return {"video": video.name, "status": "no_matching_ja_srt_sidecar"}
    if not 0 < sidecar.stat().st_size <= MAX_BYTES:
        return {"video": video.name, "status": "invalid_sidecar_size"}
    japanese = cue_starts(sidecar.read_bytes())
    if len(japanese) < MIN_CUES:
        return {"video": video.name, "status": "unreadable_or_short_japanese_sidecar"}
    streams, error = ffprobe_streams(video)
    ref = embedded_reference(video, streams) if streams else None
    if ref is None:
        ref = english_sidecar_reference(video)
    if ref is None:
        return {"video": video.name, "status": "unverified_no_reference",
                "japanese_cues": len(japanese), "ffprobe_error": error}
    english, context = ref
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(video)],
        capture_output=True, text=True, timeout=35, check=False)
    try:
        if probe.returncode:
            raise ValueError("ffprobe failed")
        runtime = float(probe.stdout.strip())
    except ValueError:
        return {"video": video.name, "status": "unverified_video_runtime"}
    if not 300 <= runtime <= 21600:
        return {"video": video.name, "status": "unverified_video_runtime"}
    return {"video": video.name, "subtitle": sidecar.name,
            "japanese_cues": len(japanese), "reference_cues": len(english),
            "runtime_seconds": round(runtime, 2), **context,
            "sections": section_timing(english, japanese, runtime),
            "decision": "DIAGNOSTIC_ONLY_NO_CHANGES"}


def self_test():
    srt = (
        b"1\n00:00:01,100 --> 00:00:02,400\nTest\n\n"
        b"2\n00:00:04,250 --> 00:00:05,200\nTest\n"
    )
    ass = (
        b"[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        b"Dialogue: 0,0:00:01.20,0:00:02.40,Default,,0,0,0,,Test\n"
        b"Dialogue: 0,0:00:04.30,0:00:05.40,Default,,0,0,0,,Test\n"
    )
    assert cue_starts(srt) == [1.1, 4.25]
    assert cue_starts(ass) == [1.2, 4.3]
    assert cue_starts(b"WEBVTT\n\n00:01.200 --> 00:03.500\nTest") == [1.2]
    a = [i * 3.57 + 0.13 * ((i * i) % 17) for i in range(1, 110)]
    fit = alignment(a, a)
    shifted = alignment(a, [x + 5.0 for x in a])
    assert fit["status"] == "fit" and fit["matching_start_fraction"] > 0.99, fit
    assert shifted["status"] == "shift_needed", shifted
    assert abs(shifted["best_offset_seconds"] - 5.0) <= 0.2, shifted
    ref = [i * 3.9 + (i*i % 11) * .071 for i in range(1, 360)]
    drift = [t + (3 if t < 150 else .5 if 560 < t < 740
                  else -1 if t > 1250 else 0) for t in ref]
    report = section_timing(ref, drift, 1440)
    assert report["status"] == "possible_variable_offset_review", report
    constant = section_timing(ref, [t + .75 for t in ref], 1440)
    assert constant["status"] == "offsets_consistent_not_verified", constant
    assert STAGE_NAME.fullmatch("a" * 32 + ".opensubtitles.11947715.ja.srt")
    print("SELF-TEST PASSED: SRT/VTT/ASS parsers and timing alignment; no file or network access")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--video", action="append", default=[],
                        help="Read-only timing comparison for this existing video; repeatable")
    parser.add_argument("--limit", type=int, default=2, help="1..5 staged files")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    if args.video:
        if len(args.video) > 8:
            parser.error("maximum eight explicit videos per diagnostic")
        for video in args.video:
            try:
                print("PUBLISHED_TIMING:", json.dumps(
                    inspect_published_video(video), ensure_ascii=False), flush=True)
            except (ValueError, OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
                print("PUBLISHED_TIMING_HELD:", type(exc).__name__, str(exc)[:160], flush=True)
        print("READ_ONLY_DIAGNOSTIC_DONE; NO SUBTITLE CHANGES OR PROVIDER REQUESTS")
        return
    if not 1 <= args.limit <= 5:
        parser.error("--limit must be 1..5")
    inventory, records = load()
    print("=== HOST-NATIVE JAPANESE SUBTITLE TIMING AUDIT ===", flush=True)
    print("Durably staged entries:", len(records), flush=True)
    for number, record in enumerate(records[:args.limit], 1):
        try:
            row, subtitle = select(*record, inventory)
            name = (str(row.get("series_title")) +
                    f' S{row["season"]:02d}E{row["episode"]:02d}'
                    if row["kind"] == "Episode" else
                    f'{row.get("title")} ({row.get("year")})')
            print(f"[{number}/{min(args.limit, len(records))}] CHECKING: {name}", flush=True)
            report = inspect(row, subtitle)
            print("TIMING:", json.dumps(report, ensure_ascii=False), flush=True)
        except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
            print("TIMING HELD:", type(exc).__name__, str(exc)[:120], flush=True)
    print("AUDIT COMPLETE: No provider requests, subtitle downloads, file writes or publication.")
    print("FIT means timings are compatible, not that Japanese text or publication is approved.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("TIMING AUDIT BLOCKED:", type(exc).__name__, str(exc)[:120],
              file=sys.stderr)
        raise SystemExit(1) from None
