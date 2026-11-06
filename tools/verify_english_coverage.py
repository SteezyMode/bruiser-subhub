#!/usr/bin/env python3
"""Read-only second pass for Bruiser's English text / no-Japanese census.

Checks *actual* video streams of every Jellyfin metadata English candidate using
existing ffprobe helper, then optionally validates a small film/TV balanced
sample by extracting subtitle text into memory using ffmpeg. No subtitle/media
sidecars are written. Provider APIs and translation are never contacted.

Only writes immutable private JSON+CSV reports under coverage-audits/ (0600).
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import csv
import hashlib
import json
import os
import subprocess
from pathlib import Path
import sys
import time

try:
    import daily_japanese as intake
except ModuleNotFoundError:
    from tools import daily_japanese as intake

DEFAULT_REPORT_DIR = Path.home() / "bruiser-pilot" / "coverage-audits"
MAX_EXTRACT = 100
FIELDS = (
    "kind", "series", "season", "episode", "title", "video_path",
    "english_stream_is_external", "english_stream_codec",
    "english_stream_index", "japanese_status", "audio_language",
    "ffprobe_status", "extracted_cues", "extraction_status",
    "next_action",
)


def manifest_path(folder, chosen=None):
    folder = Path(folder)
    if folder.is_symlink() or not folder.is_dir() or folder.stat().st_mode & 0o077:
        raise RuntimeError("Unsafe private audit report directory")
    if chosen:
        path = Path(chosen)
        if (not path.is_file() or path.is_symlink() or path.parent.resolve() != folder.resolve()
                or not path.name.startswith("en-no-ja-") or path.suffix != ".json"):
            raise RuntimeError("Unrecognized manifest path")
        return path
    paths = sorted(
        (x for x in folder.glob("en-no-ja-20*.json")
         if x.is_file() and not x.is_symlink()),
        key=lambda x: x.name)
    if not paths:
        raise RuntimeError("No English-without-Japanese audit found")
    return paths[-1]


def load_manifest(path):
    if path.stat().st_size > 60_000_000 or path.stat().st_mode & 0o077:
        raise RuntimeError("Unsafe private manifest")
    doc = json.loads(path.read_text("utf-8"))
    if (doc.get("schema") != "bruiser-english-without-japanese-v1"
            or not isinstance(doc.get("items"), list)):
        raise RuntimeError("Wrong manifest schema")
    return doc


def approved_video(row, roots):
    video = Path(str(row.get("video_path") or ""))
    if (not video.is_absolute() or video.is_symlink() or not video.is_file()
            or video.suffix.casefold() not in intake.VIDEO):
        return None
    if not any(video.resolve().is_relative_to(root.resolve()) for root in roots):
        return None
    return video


def probe_media(video):
    """Inspect only real video headers; don't mistake forced JA for dialogue."""
    cmd = ['ffprobe', '-v', 'error',
           '-show_entries',
           'stream=index,codec_type,codec_name:stream_tags=language:stream_disposition=default,forced',
           '-of', 'json', str(video)]
    result = subprocess.run(cmd, capture_output=True, timeout=25)
    if result.returncode:
        raise RuntimeError('ffprobe_failed')
    parsed = json.loads(result.stdout)
    tracks = parsed.get('streams')
    if not isinstance(tracks, list):
        raise RuntimeError('ffprobe_invalid_streams')
    en = []
    ja = False
    for track in tracks:
        if not isinstance(track, dict) or track.get('codec_type') != 'subtitle':
            continue
        forced = track.get('disposition', {}).get('forced') == 1
        if forced:
            continue
        language = str(track.get('tags', {}).get('language') or '').casefold()
        codec = str(track.get('codec_name') or '').casefold()
        if language in intake.JA:
            ja = True
        if (language in intake.EN and codec in intake.TEXT_CODECS
                and type(track.get('index')) is int):
            en.append((track.get('disposition', {}).get('default') != 1,
                       codec != 'subrip', track['index']))
    en.sort()
    return {'ja': ja, 'embedded_en': en[0][2] if en else None}


def inspect(row, roots, prober=probe_media):
    """Verify declared English stream using *real media bytes/header*.

    A non-Japanese, unforced English text stream is exposed as ffprobe's
    embedded_en index; source() later validates actual SRT text.
    """
    video = approved_video(row, roots)
    if video is None:
        return {"ffprobe_status": "video_unavailable", "next_action": "review_media_path"}
    if row.get("english_source") != "jellyfin_text_stream":
        return {"ffprobe_status": "other_source", "next_action": "separate_source_validation"}
    try:
        info = prober(video)
    except (OSError, RuntimeError, ValueError, TimeoutError):
        return {"ffprobe_status": "probe_failed", "next_action": "review_probe_error"}
    if info.get("ja"):
        return {"ffprobe_status": "japanese_detected_on_video",
                "next_action": "skip_already_has_japanese"}
    index = info.get("embedded_en")
    if type(index) is int and index >= 0:
        return {"ffprobe_status": "embedded_english_text_verified",
                "actual_stream_index": index,
                "next_action": "extract_and_check_text"}
    if row.get("english_stream_is_external") is True:
        return {"ffprobe_status": "jellyfin_external_text_unresolved",
                "next_action": "inspect_jellyfin_external_subtitle_location"}
    return {"ffprobe_status": "jellyfin_track_not_in_video",
            "next_action": "inspect_jellyfin_metadata_mismatch"}


def sample_order(rows, sample_count):
    """Deterministic, roughly film/TV-balanced set of genuinely embedded tracks."""
    eligible = [row for row in rows
                if row["ffprobe_status"] == "embedded_english_text_verified"]
    by_kind = {"Movie": [], "Episode": []}
    for row in eligible:
        by_kind["Episode" if row.get("kind") == "Episode" else "Movie"].append(row)
    for arr in by_kind.values():
        arr.sort(key=lambda row: hashlib.sha256(
            row["video_path"].encode("utf-8")).hexdigest())
    quotas = {"Movie": sample_count // 2, "Episode": sample_count - sample_count // 2}
    selected = by_kind["Movie"][:quotas["Movie"]] + by_kind["Episode"][:quotas["Episode"]]
    used = {r["video_path"] for r in selected}
    if len(selected) < sample_count:
        extra = sorted(
            (r for r in eligible if r["video_path"] not in used),
            key=lambda r: hashlib.sha256(r["video_path"].encode()).hexdigest())
        selected += extra[:sample_count - len(selected)]
    return selected


def extract_sample(rows, roots, sample_count, reader=intake.source):
    selected = sample_order(rows, sample_count)
    summary = Counter()
    print("EXTRACTION_PHASE_START", "sample", len(selected), flush=True)
    for num, row in enumerate(selected, 1):
        started = time.monotonic()
        print("EXTRACTION_START", num, "of", len(selected),
              "kind", row.get("kind", "unknown"), flush=True)
        video = approved_video(row, roots)
        if video is None:
            row.update(extraction_status="video_unavailable",
                       extracted_cues="", next_action="review_media_path")
            summary["video_unavailable"] += 1
            print("EXTRACTION_DONE", num, "of", len(selected),
                  "result", "video_unavailable",
                  "elapsed_seconds", round(time.monotonic() - started, 1),
                  flush=True)
            continue
        try:
            # Extract from actual media only. Existing named SRTs are already
            # classified in the first audit and aren't in this second-pass pool.
            raw, count, origin = reader(
                video, {"embedded_en": row["actual_stream_index"]})
            if origin != "embedded_english_text":
                raise RuntimeError("extraction_source_not_embedded")
            if not intake.MIN_CUES <= count <= intake.MAX_CUES:
                raise RuntimeError("unusual_english_cue_count")
            if not isinstance(raw, bytes) or len(raw) > intake.MAX_BYTES:
                raise RuntimeError("extraction_outside_byte_limit")
            row.update(extraction_status="extracted_valid_srt",
                       extracted_cues=count, next_action="source_ready_review_timing")
            summary["extracted_valid_srt"] += 1
        except (OSError, RuntimeError, ValueError, TimeoutError, UnicodeError) as exc:
            # Never claim ready when the text decoder or cue parser failed.
            row.update(extraction_status=type(exc).__name__,
                       extracted_cues="", next_action="investigate_extraction_failure")
            summary["extraction_failed"] += 1
        print("EXTRACTION_DONE", num, "of", len(selected),
              "result", row.get("extraction_status"),
              "elapsed_seconds", round(time.monotonic() - started, 1),
              flush=True)
        if num % 10 == 0:
            print("EXTRACTION_SAMPLE_PROGRESS", num, len(selected), dict(summary),
                  flush=True)
    return dict(summary)


def summarize(rows):
    return {
        "rows": len(rows),
        "ffprobe_status": dict(sorted(Counter(row["ffprobe_status"]
                                            for row in rows).items())),
        "by_type": {kind: dict(sorted(Counter(
            row["ffprobe_status"] for row in rows if row["kind"] == kind).items()))
            for kind in ("Movie", "Episode")},
        "sample_extraction": dict(sorted(Counter(
            row.get("extraction_status", "")
            for row in rows if row.get("extraction_status")).items())),
        "verified_embedded": sum(row["ffprobe_status"] == "embedded_english_text_verified"
                                 for row in rows),
    }


def run(manifest, roots, sample_count, *, prober=probe_media,
        reader=intake.source):
    roots = intake.ensure_roots(roots)
    if not 0 <= sample_count <= MAX_EXTRACT:
        raise ValueError("sample_count must be 0..100")
    candidates = [dict(row) for row in manifest["items"]
                  if row.get("english_source") == "jellyfin_text_stream"]
    output = []
    for i, row in enumerate(candidates, 1):
        result = inspect(row, roots, prober=prober)
        row.update(result)
        row.setdefault("extracted_cues", "")
        row.setdefault("extraction_status", "")
        output.append(row)
        if i % 250 == 0 or i == len(candidates):
            print("FFPROBE_PROGRESS", i, len(candidates), flush=True)
    print("FFPROBE_PHASE_COMPLETE", len(candidates), "candidates",
          "moving_to_extraction_sample", sample_count, flush=True)
    sample = extract_sample(output, roots, sample_count, reader=reader)
    summary = summarize(output)
    summary["sample_total"] = sum(sample.values())
    return output, summary


def write_reports(folder, output, summary, originating):
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base = f"en-no-ja-verified-{stamp}"
    source = {"source_manifest": str(originating),
              "schema": "bruiser-verified-english-tracks-v1",
              "generated_utc": datetime.now(timezone.utc).isoformat(),
              "summary": summary,
              "notes": "FFprobe checks actual media streams; only a balanced sample was extracted; other tracks need text and timing validation before translation.",
              "items": output}
    files = [
        (folder / f"{base}.json", json.dumps(source, ensure_ascii=False, indent=2)),
        (folder / f"{base}.csv", None),
    ]
    for path, text in files:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY |
                     getattr(os, "O_NOFOLLOW", 0), 0o600)
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            if text is not None:
                handle.write(text + "\n")
            else:
                writer = csv.DictWriter(handle, fieldnames=FIELDS,
                                        extrasaction="ignore")
                writer.writeheader()
                writer.writerows(output)
            handle.flush()
            os.fsync(handle.fileno())
        print("PRIVATE_VERIFICATION_REPORT", path, flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--folder", type=Path, default=DEFAULT_REPORT_DIR)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--sample-extract", type=int, default=40)
    args = parser.parse_args()
    source = manifest_path(args.folder, args.input)
    manifest = load_manifest(source)
    output, summary = run(manifest, intake.service.SOURCE_ROOTS,
                          args.sample_extract)
    print("ENGLISH_MEDIA_STREAM_VERIFICATION",
          json.dumps(summary, ensure_ascii=False, sort_keys=True), flush=True)
    write_reports(args.folder, output, summary, source)
    print("READ ONLY for source media, subtitles, providers and AI.", flush=True)


if __name__ == "__main__":
    os.umask(0o077)
    main()
