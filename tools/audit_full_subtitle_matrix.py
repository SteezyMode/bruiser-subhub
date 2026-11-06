#!/usr/bin/env python3
"""Bruiser whole-library EN/JA subtitle presence matrix (READ ONLY).

Unlike the narrower EN-without-JA census, this records BOTH languages for EVERY
Jellyfin movie and episode. It does not parse/extract subtitle dialogue,
contact subtitle providers, run models, or change any media or services.

Stores private reports with one row per playable file, with separate category
views: both languages, EN only, JA only, neither, and unknown.
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
import sys

try:
    import daily_japanese as intake
    import jellyfin_english_sources as jellyfin
    import library_english_sources as library
    from audit_english_without_japanese import streams as jellyfin_streams, lang
except ModuleNotFoundError:
    from tools import daily_japanese as intake
    from tools import jellyfin_english_sources as jellyfin
    from tools import library_english_sources as library
    from tools.audit_english_without_japanese import streams as jellyfin_streams, lang

DEFAULT_FOLDER = Path.home() / "bruiser-pilot" / "coverage-audits"
EN = {"en", "eng", "english"}
JA = {"ja", "jp", "jpn", "japanese"}
SUB_EXT = {".srt", ".ass", ".ssa", ".vtt", ".sup", ".sub", ".idx"}
TEXT_EXT = {".srt", ".ass", ".ssa", ".vtt"}
TEXT_CODECS = {"srt", "subrip", "ass", "ssa", "webvtt", "mov_text", "text"}
TOKEN_SPLIT = re.compile(r"[.\s_\[\]()-]+")
CATEGORIES = ("both", "english_only", "japanese_only", "neither", "unknown")
FIELDS = (
    "category", "kind", "series", "season", "episode", "title", "year",
    "video_path", "jellyfin_id", "audio_language",
    "english_subtitles", "japanese_subtitles",
    "english_text", "japanese_text", "english_bitmap", "japanese_bitmap",
    "english_sources", "japanese_sources", "unlabeled_sidecars",
    "english_verification", "metadata_status",
)


def sidecar_cache(video, cache):
    directory = video.parent
    if directory not in cache:
        if len(cache) > 20000:
            cache.clear()  # keep memory bounded for unusually fragmented libraries
        try:
            cache[directory] = [
                path for path in directory.iterdir()
                if path.suffix.casefold() in SUB_EXT and not path.is_symlink()
                   and path.is_file()
            ]
        except OSError:
            cache[directory] = None
    if cache[directory] is None:
        return None
    prefix = video.stem.casefold() + "."
    return [path for path in cache[directory]
            if path.name.casefold().startswith(prefix)]


def scan_one(video, item, cache, verified=None):
    """Recognize explicit EN and JA, including titles where both exist."""
    english, japanese, unlabeled = [], [], []
    en_text = ja_text = en_bitmap = ja_bitmap = False
    sidecars = sidecar_cache(video, cache)
    if sidecars is None:
        return {"category": "unknown", "metadata_status": "sidecar_listing_failed",
                "english_subtitles": "", "japanese_subtitles": "",
                "english_sources": "", "japanese_sources": "",
                "english_text": "", "japanese_text": "",
                "english_bitmap": "", "japanese_bitmap": "",
                "unlabeled_sidecars": "", "english_verification": ""}

    for path in sidecars:
        ext = path.suffix.casefold()
        suffix = path.name[len(video.stem)+1:-len(ext)]
        tags = set(x for x in TOKEN_SPLIT.split(suffix.casefold()) if x)
        if "forced" in tags or "signs" in tags:
            continue  # forced/signs-only subtitles are not full dialogue
        en = bool(tags & EN)
        ja = bool(tags & JA) or "editorial" in tags
        if en and not ja:
            english.append("file:" + path.name)
            en_text |= ext in TEXT_EXT
            en_bitmap |= ext not in TEXT_EXT
        elif ja and not en:
            japanese.append("file:" + path.name)
            ja_text |= ext in TEXT_EXT
            ja_bitmap |= ext not in TEXT_EXT
        elif not en and not ja:
            unlabeled.append(path.name)

    streams = jellyfin_streams(item)
    metadata = "jellyfin_streams" if streams is not None else "streams_missing"
    default_audio = ""
    if streams is not None:
        audios = [s for s in streams if isinstance(s, dict)
                  and s.get("Type") == "Audio"]
        audio = next((s for s in audios if s.get("IsDefault") is True),
                     audios[0] if audios else {})
        default_audio = lang(audio.get("Language"))
        for sub in streams:
            if (not isinstance(sub, dict) or sub.get("Type") != "Subtitle"
                    or sub.get("IsForced") is True):
                continue
            language = lang(sub.get("Language"))
            if language not in EN | JA:
                continue
            codec = str(sub.get("Codec") or "unknown").casefold()
            external = "external" if sub.get("IsExternal") else "embedded"
            index = sub.get("Index", "")
            where = f"jellyfin:{external}:{codec}:{index}"
            if language in EN:
                english.append(where)
                en_text |= codec in TEXT_CODECS
                en_bitmap |= codec not in TEXT_CODECS
            else:
                japanese.append(where)
                ja_text |= codec in TEXT_CODECS
                ja_bitmap |= codec not in TEXT_CODECS

    has_en, has_ja = bool(english), bool(japanese)
    if has_en and has_ja:
        category = "both"
    elif has_en:
        category = "english_only"
    elif has_ja:
        category = "japanese_only"
    elif streams is not None:
        category = "neither"
    else:
        category = "unknown"

    # If Jellyfin omitted stream metadata, a sidecar cannot prove that the
    # opposite language is absent inside the video.
    if streams is None and category in ("english_only", "japanese_only"):
        category = "unknown"
    # An unlabeled same-stem subtitle could contain either language. The
    # single-language and neither labels require unambiguous evidence.
    if unlabeled and category in ("english_only", "japanese_only", "neither"):
        category = "unknown"

    verification = (verified or {}).get("ffprobe_status", "not_checked")
    if verification == "jellyfin_track_not_in_video":
        verification = "prior_mismatch_video_lacked_reported_english"
    elif verification == "embedded_english_text_verified":
        verification = "actual_embedded_english_confirmed"
    elif verification == "jellyfin_external_text_unresolved":
        verification = "external_english_unresolved"

    # A previous real ffprobe checked this exact video and found no embedded
    # English. Don't count the stale Jellyfin-only claim as a confirmed source.
    if verification in ("prior_mismatch_video_lacked_reported_english",
                        "external_english_unresolved"):
        if not any(source.startswith("file:") for source in english):
            has_en = False
            en_text = False
            en_bitmap = False
            category = "unknown" if not has_ja else "japanese_only"

    return {
        "category": category, "audio_language": default_audio,
        "english_subtitles": has_en, "japanese_subtitles": has_ja,
        "english_text": en_text, "japanese_text": ja_text,
        "english_bitmap": en_bitmap, "japanese_bitmap": ja_bitmap,
        "english_sources": " | ".join(sorted(set(english))),
        "japanese_sources": " | ".join(sorted(set(japanese))),
        "unlabeled_sidecars": " | ".join(sorted(set(unlabeled))),
        "english_verification": verification,
        "metadata_status": metadata,
    }


def earlier_verification(folder):
    """Reuse private previous ffprobe results; never redo slow full-media scans."""
    reports = sorted(folder.glob("en-no-ja-verified-20*.json"))
    for path in reversed(reports):
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 60_000_000:
            continue
        if path.stat().st_mode & 0o077:
            continue
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if doc.get("schema") == "bruiser-verified-english-tracks-v1":
            return {str(x["video_path"]): x for x in doc.get("items", [])
                    if isinstance(x, dict) and x.get("video_path")}
    return {}


def collect(client, roots, verified=None):
    roots = intake.ensure_roots(roots)
    catalog = library.catalog(client)
    seen, cache, records = set(), {}, []
    skipped = Counter()
    for item in catalog.values():
        video = library.get_video(item, roots)
        if video is None:
            skipped["missing_or_out_of_scope"] += 1
            continue
        canonical = str(video.resolve())
        if canonical in seen:
            skipped["duplicate_path"] += 1
            continue
        seen.add(canonical)
        try:
            observed = scan_one(video, item, cache, (verified or {}).get(canonical))
        except (OSError, ValueError, RuntimeError, PermissionError) as exc:
            skipped["inspection_failure"] += 1
            observed = {"category": "unknown", "metadata_status": type(exc).__name__,
                        "english_subtitles": "", "japanese_subtitles": "",
                        "english_text": "", "japanese_text": "", "english_bitmap": "",
                        "japanese_bitmap": "", "english_sources": "", "japanese_sources": "",
                        "unlabeled_sidecars": "", "english_verification": ""}
        r = {
            "kind": item.get("Type") or "", "series": item.get("SeriesName") or "",
            "season": item.get("ParentIndexNumber") if type(item.get("ParentIndexNumber")) is int else "",
            "episode": item.get("IndexNumber") if type(item.get("IndexNumber")) is int else "",
            "title": str(item.get("Name") or video.stem),
            "year": item.get("ProductionYear") if type(item.get("ProductionYear")) is int else "",
            "video_path": canonical, "jellyfin_id": str(item.get("Id") or ""),
            "audio_language": "",
        }
        r.update(observed)
        records.append(r)
        if len(records) % 2000 == 0:
            print("MATRIX_PROGRESS", len(records), "of", len(catalog), flush=True)
    records.sort(key=lambda r: (r["kind"] != "Movie",
                  str(r["series"]).casefold(), str(r["title"]).casefold(),
                  r["season"] or 0, r["episode"] or 0, r["video_path"]))
    counts = Counter(r["category"] for r in records)
    summary = {
        "jellyfin_catalog": len(catalog), "files_inspected": len(records),
        "categories": {k: counts[k] for k in CATEGORIES},
        "english_detected": sum(bool(r["english_subtitles"]) for r in records),
        "japanese_detected": sum(bool(r["japanese_subtitles"]) for r in records),
        "english_text_indicated": sum(bool(r["english_text"]) for r in records),
        "japanese_text_indicated": sum(bool(r["japanese_text"]) for r in records),
        "unlabeled_subtitle_files": sum(bool(r["unlabeled_sidecars"]) for r in records),
        "japanese_audio": sum(lang(r["audio_language"]) in JA for r in records),
        "previous_english_video_mismatches": sum(
            r["english_verification"] == "prior_mismatch_video_lacked_reported_english"
            for r in records),
        "previous_english_video_confirmed": sum(
            r["english_verification"] == "actual_embedded_english_confirmed"
            for r in records),
        "errors": dict(skipped),
        "interpretation": "Track/file presence, not a guarantee of subtitle completeness, timing, or language accuracy. Previously verified English mismatches are flagged.",
    }
    return records, summary


def write_private(folder, rows, summary):
    folder = Path(folder)
    if folder.is_symlink():
        raise RuntimeError("Unsafe report directory")
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    if folder.stat().st_mode & 0o077:
        raise RuntimeError("Report directory is not private (must be 0700)")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base = "subtitle-matrix-" + stamp
    bundle = {"schema": "bruiser-full-subtitle-matrix-v1",
              "generated_utc": datetime.now(timezone.utc).isoformat(),
              "summary": summary, "items": rows}
    targets = [(base + ".json", bundle)]
    for category in ("all", *CATEGORIES):
        targets.append((base + "." + category + ".csv",
                        rows if category == "all" else
                        [r for r in rows if r["category"] == category]))
    for name, data in targets:
        dest = folder / name
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(dest, flags, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as out:
            if name.endswith(".json"):
                json.dump(data, out, ensure_ascii=False, indent=2)
                out.write("\n")
            else:
                writer = csv.DictWriter(out, fieldnames=FIELDS, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(data)
            out.flush()
            os.fsync(out.fileno())
        print("PRIVATE_MATRIX", dest, flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--folder", type=Path, default=DEFAULT_FOLDER)
    args = parser.parse_args()
    client = jellyfin.Jellyfin()
    print("JELLYFIN_AUTH", jellyfin.authenticate(client), flush=True)
    verified = earlier_verification(args.folder) if args.folder.is_dir() else {}
    print("PRIOR_ENGLISH_VERIFICATION", len(verified), flush=True)
    rows, summary = collect(client, intake.service.SOURCE_ROOTS, verified)
    print("SUBTITLE_MATRIX_SUMMARY",
          json.dumps(summary, ensure_ascii=False, sort_keys=True), flush=True)
    write_private(args.folder, rows, summary)
    print("DONE: no subtitle-provider calls, AI jobs, subtitle extraction, "
          "video modifications or service changes.", flush=True)


if __name__ == "__main__":
    os.umask(0o077)
    main()
