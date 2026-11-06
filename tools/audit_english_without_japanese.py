#!/usr/bin/env python3
"""Complete, read-only Jellyfin catalog of English-text / no-Japanese media.

Writes *private* CSV and JSON reports for Bruiser's future translation queue.
The report is NOT a translation command; it contacts NO subtitle providers and
does not create or replace any subtitle beside media.

Classification is conservative: an English SRT with parsed cues is ready as
a text source; an embedded text track is a CANDIDATE pending extraction/timing
verification at translation preflight. Bitmap subs are NOT English text.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sqlite3
import sys

try:
    import daily_japanese as intake
    import jellyfin_english_sources as jellyfin
    import library_english_sources as library
except ModuleNotFoundError:
    from tools import daily_japanese as intake
    from tools import jellyfin_english_sources as jellyfin
    from tools import library_english_sources as library

REPORT_DIR = Path.home() / "bruiser-pilot" / "coverage-audits"
EN = {"en", "eng", "english"}
JA = {"ja", "jp", "jpn", "japanese"}
TEXT_CODECS = {"subrip", "srt", "ass", "ssa", "webvtt", "mov_text", "text"}
TEXT_FILES = {".srt", ".ass", ".ssa", ".vtt"}
ALL_SUB_FILES = TEXT_FILES | {".sup", ".sub"}
FIELDS = (
    "kind", "series", "season", "episode", "title", "year", "video_path",
    "jellyfin_id", "english_source", "english_source_file",
    "english_stream_codec", "english_stream_index", "english_cues",
    "english_stream_is_external", "english_stream_path", "audio_language",
    "english_status", "japanese_status", "jellyfin_only_prior",
    "queue_readiness",
)


def lang(value):
    return str(value or "").strip().casefold().split("-", 1)[0].split("_", 1)[0]


def streams(item):
    top = item.get("MediaStreams")
    if isinstance(top, list):
        return top
    for source in item.get("MediaSources") or []:
        if isinstance(source, dict) and isinstance(source.get("MediaStreams"), list):
            return source["MediaStreams"]
    return None


def stream_info(item):
    subs = streams(item)
    if subs is None:
        return None
    ja = []
    en = []
    for stream in subs:
        if not isinstance(stream, dict) or stream.get("Type") != "Subtitle":
            continue
        if stream.get("IsForced") is True:
            continue
        l = lang(stream.get("Language"))
        if l in JA:
            ja.append(stream)
        if l in EN and str(stream.get("Codec") or "").casefold() in TEXT_CODECS:
            en.append(stream)
    en.sort(key=lambda x: (
        x.get("IsExternal") is not True,
        str(x.get("Codec") or "").casefold() != "subrip",
        x.get("Index") if type(x.get("Index")) is int else 9999))
    return {"japanese": ja, "english_text": en}


def all_sidecars(video):
    # A cache belongs to the current audit only; no guessing based on
    # substring matches (e.g. "Movie 2" versus "Movie").
    return [p for p in intake.sidecars(video)
            if p.suffix.casefold() in ALL_SUB_FILES and
            p.is_file() and not p.is_symlink()]


def classify(video, item, *, source_reader=intake.source,
             probe=intake.probe):
    candidates = all_sidecars(video)
    english = []
    japanese = []
    for p in candidates:
        tags = intake.tags(p, video)
        if tags & JA or "editorial" in tags:
            japanese.append(p)
        if (tags & EN and not tags & JA
                and "forced" not in tags and "signs" not in tags):
            english.append(p)
    info = stream_info(item)
    if info is None:
        # Read only media header when Jellyfin is missing stream metadata.
        try:
            p = probe(video)
        except (OSError, RuntimeError, ValueError):
            return {"category": "unknown_stream_metadata",
                    "english_status": "unknown", "japanese_status": "unknown"}
        info = {"japanese": [{"Codec": "unknown"}] if p.get("ja") else [],
                "english_text": ([{"Codec": "unknown", "Index": p["embedded_en"]}]
                                 if p.get("embedded_en") is not None else [])}
    if japanese:
        return {"category": "has_japanese", "english_status": "not_needed",
                "japanese_status": "japanese_sidecar"}
    if info["japanese"]:
        return {"category": "has_japanese", "english_status": "not_needed",
                "japanese_status": "japanese_media_stream"}

    base = {"japanese_status": "none_detected"}
    # An existing SRT is independently validated; metadata alone is not enough.
    srts = sorted((p for p in english if p.suffix.casefold() == ".srt"),
                  key=lambda p: ("sdh" in intake.tags(p, video), p.name))
    for p in srts:
        try:
            # source() applies actual parser / contiguous cue-id / size gates.
            raw, count, origin = source_reader(video, {"embedded_en": None},
                                               runner=None)
            if count >= intake.MIN_CUES:
                return dict(base, category="candidate",
                    english_status="parsed_external_srt",
                    english_source="external_srt", english_source_file=str(p),
                    english_stream_codec="srt", english_stream_index="",
                    english_stream_is_external=True, english_stream_path="",
                    english_cues=count, queue_readiness="source_text_ready")
        except (OSError, RuntimeError, ValueError, UnicodeError):
            # Other valid sources should not be hidden by a corrupt .en.srt.
            break

    other_text = sorted((p for p in english if p.suffix.casefold() in TEXT_FILES
                         and p.suffix.casefold() != ".srt"), key=str)
    if other_text:
        p = other_text[0]
        return dict(base, category="candidate",
            english_status="text_sidecar_needs_conversion",
            english_source="external_text", english_source_file=str(p),
            english_stream_codec=p.suffix.lstrip("."), english_stream_index="",
            english_stream_is_external=True, english_stream_path="",
            english_cues="", queue_readiness="validate_and_convert")
    if info["english_text"]:
        x = info["english_text"][0]
        return dict(base, category="candidate",
            english_status="jellyfin_text_track_unverified",
            english_source="jellyfin_text_stream", english_source_file="",
            english_stream_codec=x.get("Codec") or "unknown",
            english_stream_index=(x.get("Index") if type(x.get("Index")) is int else ""),
            english_stream_is_external=x.get("IsExternal") is True,
            english_stream_path=str(x.get("Path") or ""),
            english_cues="", queue_readiness="verify_extract_before_translate")
    if srts:
        return dict(base, category="invalid_english_srt",
            english_status="invalid_english_srt",
            english_source="external_srt", english_source_file=str(srts[0]),
            english_stream_codec="srt", english_stream_index="",
            english_cues="", queue_readiness="needs_source_repair")
    # Keep an unlabeled same-stem SRT visible for separate language review.
    # It may be English but is NOT safe to claim as English automatically.
    unlabeled = [p for p in candidates
                 if p.suffix.casefold() == ".srt"
                 and not intake.tags(p,video) & (EN | JA)
                 and p not in english and p not in japanese]
    if unlabeled:
        return dict(base, category="unlabeled_srt_needs_language_review",
            english_status="unlabeled_srt", english_source="unlabeled_srt",
            english_source_file=str(unlabeled[0]),
            english_cues="", queue_readiness="identify_language_and_validate")
    if any(p.suffix.casefold() not in TEXT_FILES for p in english):
        return dict(base, category="english_bitmap_only",
            english_status="bitmap_not_text", queue_readiness="needs_ocr_or_english")
    return dict(base, category="missing_english_text",
                english_status="none_detected", queue_readiness="needs_english_source")


def prior_jellyfin_only(state):
    db = Path(state) / "catalog.sqlite3"
    if not db.is_file() or db.is_symlink():
        return set()
    with sqlite3.connect("file:" + str(db) + "?mode=ro",
                         uri=True, timeout=15) as conn:
        return {str(x[0]) for x in conn.execute(
            "SELECT path FROM media WHERE state='jellyfin_only'")}


def collect(*, client, roots, probe=intake.probe, source_reader=intake.source):
    roots = intake.ensure_roots(roots)
    items = library.catalog(client)
    old_jellyfin_only = prior_jellyfin_only(library.STATE)
    counts = Counter()
    rows = []
    unresolved = []
    seen = set()
    for item in items.values():
        video = library.get_video(item, roots)
        if video is None:
            counts["out_of_scope_or_missing"] += 1
            continue
        path = str(video.resolve())
        if path in seen:
            counts["duplicate_path"] += 1
            continue
        seen.add(path)
        try:
            result = classify(video, item, probe=probe,
                              source_reader=source_reader)
        except (OSError, RuntimeError, ValueError, PermissionError) as exc:
            result = {"category": "inspection_error",
                      "english_status": type(exc).__name__,
                      "japanese_status": "unknown",
                      "queue_readiness": "manual_review"}
        counts[result["category"]] += 1
        media_streams = streams(item) or []
        audio = [x for x in media_streams
                 if isinstance(x, dict) and x.get("Type") == "Audio"]
        default_audio = next((x for x in audio if x.get("IsDefault") is True),
                             audio[0] if audio else {})
        item_row = {
            "kind": item.get("Type", ""), "series": item.get("SeriesName") or "",
            "season": item.get("ParentIndexNumber") if type(item.get("ParentIndexNumber")) is int else "",
            "episode": item.get("IndexNumber") if type(item.get("IndexNumber")) is int else "",
            "title": str(item.get("Name") or video.stem),
            "year": item.get("ProductionYear") if type(item.get("ProductionYear")) is int else "",
            "video_path": path, "jellyfin_id": str(item.get("Id") or ""),
            "english_source": "", "english_source_file": "",
            "english_stream_codec": "", "english_stream_index": "",
            "english_cues": "", "english_status": "",
            "english_stream_is_external": "", "english_stream_path": "",
            "audio_language": lang(default_audio.get("Language")),
            "japanese_status": "", "jellyfin_only_prior":
                path in old_jellyfin_only, "queue_readiness": "",
        }
        item_row.update({k: v for k, v in result.items() if k in FIELDS})
        if result["category"] == "candidate":
            rows.append(item_row)
            counts["jellyfin_only_candidates"] += bool(item_row["jellyfin_only_prior"])
            counts["japanese_audio_in_candidates"] += item_row["audio_language"] in JA
        if result["category"] in (
                "unknown_stream_metadata", "inspection_error",
                "invalid_english_srt",
                "unlabeled_srt_needs_language_review") or (
                    item_row["jellyfin_only_prior"] and
                    result["category"] != "candidate"):
            unresolved.append(item_row)
            if item_row["jellyfin_only_prior"]:
                counts["prior_jellyfin_only_unresolved"] += 1
    rows.sort(key=lambda r: (
        r["kind"] != "Movie", r["series"].casefold(), r["season"] or 0,
        r["episode"] or 0, r["title"].casefold(), r["video_path"]))
    counts["catalog_items"] = len(items)
    counts["media_inspected"] = len(seen)
    counts["english_no_japanese_candidates"] = len(rows)
    counts["unresolved"] = len(unresolved)
    counts["prior_jellyfin_only_inventory"] = len(old_jellyfin_only)
    summary = dict(counts)
    summary["by_english_source"] = dict(sorted(Counter(
        r["english_source"] for r in rows).items()))
    summary["by_queue_readiness"] = dict(sorted(Counter(
        r["queue_readiness"] for r in rows).items()))
    summary["episodes_by_series"] = dict(sorted(Counter(
        (r["series"] or "unknown series") for r in rows
        if r["kind"] == "Episode").items(), key=lambda x: (-x[1], x[0])))
    return summary, rows, unresolved


def save_private(folder, base, summary, rows, unresolved):
    folder = Path(folder)
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    if folder.is_symlink() or (folder.stat().st_mode & 0o077):
        raise RuntimeError("Private report directory must be 0700 and not a symlink")
    artifacts = (
        (base + ".json", json.dumps({
            "schema": "bruiser-english-without-japanese-v1",
            "generated_utc": datetime.now(timezone.utc).isoformat(),
            "caveat": "Embedded English must be extracted and timed before translation; metadata is not semantic QA.",
            "summary": summary, "items": rows, "unresolved": unresolved,
        }, ensure_ascii=False, indent=2) + "\n"),
        (base + ".csv", None),
        (base + ".unresolved.csv", None),
    )
    for filename, body in artifacts:
        path = folder / filename
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                     getattr(os, "O_NOFOLLOW", 0), 0o600)
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            if body is not None:
                f.write(body)
            else:
                writer = csv.DictWriter(f, fieldnames=FIELDS)
                writer.writeheader()
                writer.writerows(unresolved if filename.endswith(".unresolved.csv")
                                 else rows)
            f.flush()
            os.fsync(f.fileno())
        print("PRIVATE_REPORT", path, flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--save", action="store_true",
                        help="write a private JSON + candidate and unresolved CSV")
    parser.add_argument("--folder", type=Path, default=REPORT_DIR)
    args = parser.parse_args()
    client = jellyfin.Jellyfin()
    print("JELLYFIN_AUTH", jellyfin.authenticate(client), flush=True)
    totals, rows, unresolved = collect(client=client,
                                       roots=intake.service.SOURCE_ROOTS)
    print("COVERAGE_AUDIT_SUMMARY", json.dumps(totals, sort_keys=True), flush=True)
    print("FIRST_CANDIDATES")
    for r in rows[:12]:
        print(json.dumps({
            "kind": r["kind"], "series": r["series"], "title": r["title"],
            "season": r["season"], "episode": r["episode"],
            "english_status": r["english_status"],
            "queue_readiness": r["queue_readiness"],
        }, ensure_ascii=False, sort_keys=True))
    if args.save:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        save_private(args.folder, "en-no-ja-" + stamp, totals, rows, unresolved)
    print("READ ONLY for media, subtitles, providers and translation.", flush=True)


if __name__ == "__main__":
    os.umask(0o077)
    main()
