#!/usr/bin/env python3
"""Read-only, section-aware timing audit of already-published Japanese sidecars.

Reuses ja_first_stage_timing_audit for subtitle decoding, embedded English
reference extraction and approximate bilingual cue alignment. Signals are
diagnostic, NEVER independent proof of correctness or permission to withdraw,
replace, delete or publish a subtitle. No file writes or provider requests.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys

import ja_first_stage_timing_audit as timing

VIDEO_EXTS = timing.VIDEO_EXTS
JA_TOKENS = timing.JA_LANGS
EP_TAG = re.compile(r"(?<![A-Za-z0-9])S\d{2}E\d{2}(?!\d)", re.I)


def japanese_sidecars(video: Path) -> list[Path]:
    """Use only exact media-stem, explicitly JA-tagged sibling sidecars."""
    prefix = video.stem + "."
    found = []
    for path in video.parent.iterdir():
        if path.is_symlink() or not path.is_file():
            continue
        if not path.name.casefold().startswith(prefix.casefold()):
            continue
        if path.suffix.casefold() not in timing.SUB_EXTS:
            continue
        suffix = path.name[len(prefix):-len(path.suffix)]
        tags = [x.casefold() for x in re.split(r"[^A-Za-z0-9]+", suffix) if x]
        if (not any(x in JA_TOKENS for x in tags)
                or any(x in {"forced", "signs"} for x in tags)):
            continue
        found.append(path)
    return sorted(found)


def runtime_seconds(video: Path) -> float:
    process = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(video)],
        capture_output=True, text=True, timeout=40, check=False,
    )
    if process.returncode:
        raise RuntimeError("ffprobe_duration_failed")
    value = float(process.stdout.strip())
    if not 30 <= value <= 8 * 3600:
        raise RuntimeError("invalid_video_runtime")
    return value


def reference_for(video: Path):
    streams, error = timing.ffprobe_streams(video)
    # Only English is a suitable language reference in this audit.
    en_streams = [
        stream for stream in streams
        if str((stream.get("tags") or {}).get("language") or "").casefold()
        in timing.EN_LANGS
    ]
    ref = timing.embedded_reference(video, en_streams)
    if ref is None:
        ref = timing.english_sidecar_reference(video)
    return ref, error


def windows(seconds: float):
    return [
        ("cold_open", 0.0, min(120.0, seconds)),
        ("early_remainder", 120.0, min(300.0, seconds)),
        ("middle", max(0.0, seconds / 2 - 120), min(seconds, seconds / 2 + 120)),
        ("ending", max(0.0, seconds - 240), seconds),
    ]


def section_check(ref: list[float], ja: list[float], seconds: float):
    reports = []
    for name, start, end in windows(seconds):
        if end <= start:
            continue
        r = [t for t in ref if start <= t < end]
        j = [t for t in ja if start <= t < end]
        result = timing.alignment(r, j, min_cues=15)
        reports.append({
            "section": name,
            "from_seconds": round(start, 1),
            "to_seconds": round(end, 1),
            "reference_cues": len(r),
            "japanese_cues": len(j),
            **result,
        })
    # These are possible timing signals, not quality grades or approval gates.
    usable = [
        x for x in reports if x.get("status") in {"fit", "shift_needed"}
        and x.get("matching_start_fraction", 0) >= 0.60
        and x.get("reference_cues", 0) >= 15 and x.get("japanese_cues", 0) >= 15
    ]
    offsets = [float(x["best_offset_seconds"]) for x in usable]
    if len(offsets) < 2:
        verdict = "inconclusive_needs_review"
    elif max(offsets) - min(offsets) > 1.5:
        verdict = "variable_offset_review"
    elif any(abs(x) > 0.75 for x in offsets):
        verdict = "possible_constant_offset_review"
    else:
        verdict = "consistent_timing_signal_not_verified"
    return {"diagnostic": verdict, "regions_with_usable_signal": len(usable),
            "offset_spread_seconds": round(max(offsets)-min(offsets), 2)
            if offsets else None, "sections": reports}


def inspect_video(video: Path):
    video = timing.safe_media_path(str(video))
    result = {"video": str(video), "runtime_seconds": runtime_seconds(video)}
    sidecars = japanese_sidecars(video)
    result["japanese_sidecars"] = []
    if not sidecars:
        result["status"] = "no_japanese_sidecar"
        return result
    reference, probe_error = reference_for(video)
    result["reference"] = reference[1] if reference else None
    result["ffprobe_issue"] = probe_error
    for path in sidecars:
        record = {"path": str(path)}
        if not 0 < path.stat().st_size <= timing.MAX_BYTES:
            record["status"] = "subtitle_size_unavailable"
        else:
            starts = timing.cue_starts(path.read_bytes())
            record["cues"] = len(starts)
            if not timing.MIN_CUES <= len(starts) <= timing.MAX_CUES:
                record["status"] = "subtitle_timestamps_unavailable"
            elif reference is None:
                record["status"] = "unverified_no_english_reference"
            else:
                record.update(section_check(reference[0], starts, result["runtime_seconds"]))
                record["status"] = "audited_signal_only"
        result["japanese_sidecars"].append(record)
    return result


def matching_videos(directory: Path, episodes: list[str]):
    if not directory.is_dir() or directory.is_symlink():
        raise RuntimeError("directory_missing_or_symlinked")
    allowed = {t.upper() for t in episodes}
    found = []
    for path in directory.iterdir():
        if path.is_symlink() or not path.is_file() or path.suffix.casefold() not in VIDEO_EXTS:
            continue
        tags = {m.group(0).upper() for m in EP_TAG.finditer(path.name)}
        if tags & allowed:
            found.append(path)
    return sorted(found)


def self_test():
    ref = [i * 4.3 + ((i * i) % 11) * .17 for i in range(1, 125)]
    good = [t + .3 for t in ref]
    drifted = [t + (4.0 if t < 120 else .3) for t in ref]
    good_result = section_check(ref, good, 550)
    bad_result = section_check(ref, drifted, 550)
    assert good_result["diagnostic"] == "consistent_timing_signal_not_verified", good_result
    assert bad_result["diagnostic"] == "variable_offset_review", bad_result
    assert section_check([], [], 550)["diagnostic"] == "inconclusive_needs_review"
    print("SELF_TEST_OK: constant shift, variable cold-open shift, no-reference uncertainty")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument("--video", type=Path)
    scope.add_argument("--directory", type=Path)
    parser.add_argument("--episodes", nargs="+", default=[],
                        help="Explicit S01E04 S01E05 selections with --directory")
    parser.add_argument("--self-test", action="store_true")
    opts = parser.parse_args()
    if opts.self_test:
        self_test()
        return
    if not opts.video and not opts.directory:
        parser.error("supply --video or --directory")
    if opts.directory and (not opts.episodes or any(
            re.fullmatch(r"S\d{2}E\d{2}", t, re.I) is None for t in opts.episodes)):
        parser.error("--directory requires explicit --episodes S01E04 S01E05")
    videos = [opts.video] if opts.video else matching_videos(opts.directory, opts.episodes)
    print("PUBLISHED_JA_TIMING_AUDIT_READ_ONLY", "videos", len(videos), flush=True)
    if not videos:
        print("NO_MATCHING_VIDEOS", flush=True)
    for video in videos:
        try:
            record = inspect_video(video)
        except (ValueError, OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
            record = {"video": str(video), "status": "audit_error",
                      "error": str(exc)[:160]}
        print(json.dumps(record, ensure_ascii=False, sort_keys=True), flush=True)
    print("AUDIT_DONE: No file changes. Signals do NOT establish dialogue accuracy, "
          "permit automatic unpublication, or prove subtitle quality.", flush=True)


if __name__ == "__main__":
    main()
