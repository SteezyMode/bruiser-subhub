#!/usr/bin/env python3
"""PLaMo 3 0.8B/2B REAL English-SRT comparison, with PFN-native PFML3 history.

This is *not* the SubHub worker: no provider requests, Jellyfin writes, 
media writes, model swaps, or AI sidecar publications. Source is an embedded
ENGLISH text track from a film in the current PRIVATE Jellyfin intake.
Outputs remain private in ~/bruiser-pilot/plamo3-ab/real-results/.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import time

try:
    from . import plamo3_small_ab as small
except ImportError:
    import plamo3_small_ab as small

ROOT = Path.home() / "bruiser-pilot/plamo3-ab"
CATALOG = Path.home() / "bruiser-pilot/ja-first-inventory"
CONTROL = Path.home() / "bruiser-pilot/subhub-control"
EXCLUDE = ("primate", "attachment", "the descent", "heretic", "hokum",
           "birth/rebirth", "yellowjackets", "american dad")
LIMIT = 100
HISTORY = 2
STOP = ["<|plamo:tag|>", "<|plamo:bos|>"]
PFN_URL = "https://huggingface.co/pfnet/plamo-3-translate-0.8b-GGUF"

# SRT/SDH is not uniformly spoken dialogue. PLaMo's job is to translate
# language, not to invent speech for a pure sound-effects caption. An
# untranslated isolated [SIGHS] or [MUSIC PLAYING] is a valid non-dialogue
# input. Keep it verbatim in these PRIVATE review tracks, label it explicitly,
# and never put it in translation history. Localizing SDH is future work.
INLINE_SRT_TAG = re.compile(r"</?(?:font|i|b|u)\b[^>]*>", re.I)
STANDALONE_SDH = re.compile(r"\[[A-Z][A-Z0-9 \t,'’!?.:/-]{0,100}\]")


def is_non_dialogue_caption(source):
    plain = INLINE_SRT_TAG.sub("", source).strip()
    return bool(STANDALONE_SDH.fullmatch(plain))


def load_frozen_run(folder):
    """Re-run the SAME immutable private 100 English cues from held 2026-11-05
    job. No catalog rescan, provider network, ffmpeg, or source rewrite.
    """
    original = Path(folder).expanduser()
    if original.is_symlink():
        raise RuntimeError("frozen_run_symlink")
    original = original.resolve(strict=True)
    approved_root = (ROOT / "real-results").resolve(strict=True)
    if original.parent != approved_root or not original.is_dir():
        raise RuntimeError("frozen_run_outside_private_results")
    if original.stat().st_uid != os.getuid() or original.stat().st_mode & 0o077:
        raise RuntimeError("frozen_run_not_private")
    manifest_file = _private_path(original / "manifest.json")
    english_file = _private_path(original / "source.en.srt")
    meta = json.loads(manifest_file.read_text(encoding="utf-8"))
    data = english_file.read_bytes()
    if hashlib.sha256(data).hexdigest() != meta.get("source_sha256"):
        raise RuntimeError("frozen_english_sha_mismatch")
    cues = small.parse_srt(data.decode("utf-8-sig"), limit=12000)
    if (len(cues) != LIMIT or meta.get("selected_cues") != LIMIT
            or cues[0]["number"] != meta.get("first_cue")
            or cues[-1]["number"] != meta.get("last_cue")
            or small.format_srt(cues, "english").encode("utf-8") != data):
        raise RuntimeError("frozen_english_cue_structure_mismatch")
    video = Path(str(meta.get("video_path") or ""))
    if not video.is_absolute() or video.is_symlink() or not video.is_file():
        raise RuntimeError("original_video_no_longer_available")
    stat = video.stat()
    if stat.st_size != meta.get("video_bytes") or stat.st_mtime_ns != meta.get("media_mtime_ns"):
        raise RuntimeError("original_video_metadata_changed")
    row = {"title": meta.get("title"), "year": meta.get("year"),
           "jellyfin_id": meta.get("jellyfin_id")}
    return (row, video, cues, meta["all_source_cues"],
            "frozen_embedded_english_text", meta.get("manifest"),
            original.name, meta["source_sha256"])



def verify_completed_reference(frozen_path, cues):
    """The previous 0.8B arm must be complete and mapped to the exact EN
    IDs/timestamps before running only 2B. No copying/editing original data.
    """
    path = _private_path(Path(frozen_path).resolve(strict=True) / "0.8b.json")
    data = path.read_bytes()
    record = json.loads(data)
    entries = record.get("entries")
    if record.get("status") != "complete" or not isinstance(entries, list):
        raise RuntimeError("reference_0_8b_not_complete")
    if len(entries) != len(cues) or len(cues) != LIMIT:
        raise RuntimeError("reference_0_8b_cue_count_mismatch")
    for en, translated in zip(cues, entries):
        if any(en[k] != translated.get(k)
               for k in ("number", "start", "end", "english")):
            raise RuntimeError("reference_0_8b_source_mismatch")
        if translated.get("status") not in (
                "translated", "non_dialogue_passthrough"):
            raise RuntimeError("reference_0_8b_contains_held_dialogue")
    return hashlib.sha256(data).hexdigest()


def native_prompt(source, history):
    """Verbatim PFN PFML3 element grammar: previous source/output pairs,
    then input/current, then empty output. NO made-up system prompt.
    Source and target attributes are explicitly documented language codes.
    """
    if not source or "<|plamo:" in source:
        raise ValueError("invalid_english_source")
    p = "<|plamo:tag|>dataset<|plamo:msg|>translation"
    for en, ja in history:
        if not en.strip() or not ja.strip() or "<|plamo:" in (en + ja):
            raise ValueError("invalid_translation_history")
        p += ("<|plamo:tag|>input<|plamo:key|>lang<|plamo:val|>en"
              "<|plamo:msg|>" + en)
        p += ("<|plamo:tag|>output<|plamo:key|>lang<|plamo:val|>ja"
              "<|plamo:msg|>" + ja)
    p += ("<|plamo:tag|>input<|plamo:key|>lang<|plamo:val|>en"
          "<|plamo:msg|>" + source)
    p += ("<|plamo:tag|>output<|plamo:key|>lang<|plamo:val|>ja"
          "<|plamo:msg|>")
    return p


def request(port, source, history):
    response = small.json_request(port, "/v1/completions", {
        "model": "plamo-3-translate",
        "prompt": native_prompt(source, history),
        "temperature": 0,
        "max_tokens": 512,  # PFN official example, NOT custom 256-cue cap
        "stop": STOP,
        "stream": False,
    }, timeout=180)
    choices = response.get("choices") or []
    if not choices:
        raise RuntimeError("missing_model_completion")
    first = choices[0]
    if first.get("finish_reason") == "length":
        raise RuntimeError("model_output_truncated")
    ja = str(first.get("text") or "").strip()
    if not ja or "<|plamo:" in ja:
        raise RuntimeError("empty_or_malformed_model_output")
    # A Latin-only response to *dialogue* is saved and explicitly marked as
    # held, rather than treated as Japanese or crashing the whole A/B.
    status = "translated" if small.JP.search(ja) else "held_non_japanese"
    return ja, response.get("usage") or {}, status


def _private_path(path):
    if not path.is_file() or path.is_symlink():
        raise RuntimeError("missing_or_symlinked_private_file")
    info = path.stat()
    if info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise RuntimeError("unsafe_private_file_permissions")
    return path


def search_misses():
    db = CATALOG / "japanese-search.sqlite3"
    if not db.is_file() or db.is_symlink():
        return set()
    with sqlite3.connect("file:" + str(db) + "?mode=ro", uri=True) as conn:
        return {str(x[0]) for x in conn.execute(
            "SELECT jellyfin_id FROM searches WHERE outcome='none'"
        )}


def choose_embedded_english():
    sys.path.insert(0, str(CONTROL))
    import daily_japanese as daily
    from ja_first_stage_timing_audit import safe_media_path

    files = sorted(CATALOG.glob("ja-intake-*.json"))
    if not files:
        raise RuntimeError("no_existing_private_jellyfin_intake")
    latest = _private_path(files[-1])
    if time.time() - latest.stat().st_mtime > 72 * 3600:
        raise RuntimeError("intake_too_old_refresh_separately_before_test")
    items = json.loads(latest.read_text("utf-8")).get("items", [])
    misses = search_misses()
    ranked = []
    for row in items:
        if not isinstance(row, dict) or row.get("kind") != "Movie":
            continue
        if row.get("status") != "ready_ja_search":
            continue
        if str(row.get("audio_language") or "") not in ("en", "eng"):
            continue
        title = str(row.get("title") or "").lower()
        if any(e in title for e in EXCLUDE):
            continue
        path = str(row.get("host_path") or "")
        if not path.startswith("/") or not row.get("imdb_id"):
            continue
        genres = {g.casefold() for g in row.get("genres", []) if isinstance(g, str)}
        genre_priority = 0 if "horror" in genres else (1 if "thriller" in genres else 2)
        # Previously searched titles with no JA match are best candidates for DIY,
        # without letting the source-only production job start AI translation.
        priority = (0 if str(row.get("jellyfin_id")) in misses else 1,
                    genre_priority, hashlib.sha256(path.encode()).hexdigest())
        ranked.append((priority, row))
    ranked.sort(key=lambda pair: pair[0])
    problems = {}
    for _, row in ranked[:200]:
        try:
            video = safe_media_path(str(row["host_path"]))
            if daily.already_ja(video):
                continue
            meta = daily.probe(video)
            # Embedded, explicitly tagged ENGLISH text track from this very
            # video, with confirmed default English audio. Do not rely on
            # filename guesses, remote services or external SRT timing.
            if not meta["audio_en"] or meta["ja"] or meta["embedded_en"] is None:
                continue
            proc = subprocess.run([
                "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
                "-i", str(video), "-map", "0:" + str(meta["embedded_en"]),
                "-vn", "-an", "-c:s", "srt", "-f", "srt", "pipe:1"
            ], capture_output=True, timeout=180, check=False)
            if proc.returncode or not 2000 < len(proc.stdout) <= 2_000_000:
                continue
            cues = small.parse_srt(proc.stdout.decode("utf-8-sig"), limit=12000)
            if len(cues) < LIMIT + 30:
                continue
            # Deterministic early/mid-film window, original IDs/timecodes.
            starts = [len(cues) // 5, len(cues) // 3, len(cues) // 2]
            for start in starts:
                subset = cues[start:start + LIMIT]
                if len(subset) != LIMIT:
                    continue
                useful = sum(bool(re.search(r"[A-Za-z]{3}", c["english"]))
                             for c in subset)
                if useful < 80:
                    continue
                if len({c["number"] for c in subset}) != LIMIT:
                    continue
                return row, video, subset, len(cues), "embedded_english_text", latest.name
        except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
            typ = type(exc).__name__
            problems[typ] = problems.get(typ, 0) + 1
            continue
    raise RuntimeError("no_safe_embedded_english_movie_found_among_first_200; "
                       "holds=" + repr(problems))


def benchmark(args):
    # Source and outputs are always located in a private non-media folder.
    if args.self_test:
        tests()
        return
    binary = (ROOT / "runtime/llama-server").resolve(strict=True)
    model_dir = ROOT / "models"
    if not binary.is_file() or not os.access(binary, os.X_OK):
        raise RuntimeError("missing_existing_pinned_llama_server")
    if not model_dir.is_dir() or model_dir.is_symlink():
        raise RuntimeError("missing_existing_pinned_model_directory")
    for filename in small.MODEL_FILES.values():
        model = model_dir / filename
        if not model.is_file() or model.is_symlink() or model.stat().st_size < 100_000_000:
            raise RuntimeError("missing_original_pinned_model_" + filename)
    frozen_name = None
    if args.frozen_run:
        (row, video, cues, total, origin, manifest_name,
         frozen_name, original_source_sha) = load_frozen_run(args.frozen_run)
    else:
        row, video, cues, total, origin, manifest_name = choose_embedded_english()
        original_source_sha = None
    if args.arm == "2b":
        if not args.frozen_run:
            raise RuntimeError("2b_only_requires_frozen_completed_0_8b_run")
        prior_0_8b_sha = verify_completed_reference(args.frozen_run, cues)
    else:
        prior_0_8b_sha = None
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    base = ROOT / "real-results"
    base.mkdir(parents=True, exist_ok=True, mode=0o700)
    if base.is_symlink() or base.stat().st_mode & 0o077:
        raise RuntimeError("unsafe_private_output_root")
    out = base / ("film-100-" + stamp)
    out.mkdir(mode=0o700)
    source_srt = small.format_srt(cues, "english")
    (out / "source.en.srt").write_text(source_srt, encoding="utf-8")
    details = {
        "status": "started", "title": row.get("title"), "year": row.get("year"),
        "video_path": str(video), "video_bytes": video.stat().st_size,
        "media_mtime_ns": video.stat().st_mtime_ns,
        "jellyfin_id": row["jellyfin_id"], "manifest": manifest_name,
        "subtitle_source": origin, "source_stream": "embedded_english_text",
        "all_source_cues": total, "selected_cues": LIMIT,
        "source_sha256": hashlib.sha256(source_srt.encode()).hexdigest(),
        "first_cue": cues[0]["number"], "last_cue": cues[-1]["number"],
        "runtime": "llama.cpp pinned b12119, NVIDIA CUDA",
        "model_native_protocol": "PFML3 (PFN official history grammar)",
        "source_lang": "en", "target_lang": "ja", "history_pairs": HISTORY,
        "temperature": 0, "max_tokens": 512, "stop": STOP,
        "published_to_jellyfin": False, "models": {},
        "frozen_prior_run": frozen_name,
        "requested_arm": args.arm,
        "reference_completed_0_8b_sha256": prior_0_8b_sha,
    }
    if original_source_sha and details["source_sha256"] != original_source_sha:
        raise RuntimeError("frozen_source_changed_during_snapshot")
    small.atomic_json(out / "manifest.json", details)
    print("=== FROZEN REAL ENGLISH SOURCE ===", flush=True)
    print(row["title"], "(", row.get("year"), ")",
          "| embedded English |", total, "total cues", flush=True)
    print("Frozen 100-cue sample:", cues[0]["number"], "to", cues[-1]["number"],
          "| SHA256:", details["source_sha256"], flush=True)
    print("No media or production service writes. PRIVATE output:", out, flush=True)

    for size, name in small.MODEL_FILES.items():
        if args.arm != "all" and size != args.arm:
            continue
        model = model_dir / name
        record = {"model": size, "model_filename": name,
                  "model_sha256": small.digest(model), "entries": [],
                  "status": "started"}
        proc = None
        started = time.monotonic()
        try:
            proc = small.start_server(binary, model, args.port, 99,
                                      out / (size + ".server.log"))
            previous = []
            for i, cue in enumerate(cues, 1):
                start = time.monotonic()
                if is_non_dialogue_caption(cue["english"]):
                    # SDH-only text such as <font>[SIGHS]</font> is NOT
                    # mistranslated dialogue. This was the entire cause of
                    # the original cue-159 validation false positive.
                    result, usage, cue_status = (
                        cue["english"], {}, "non_dialogue_passthrough")
                else:
                    result, usage, cue_status = request(
                        args.port, cue["english"], previous[-HISTORY:])
                    if cue_status == "translated":
                        previous.append((cue["english"], result))
                item = dict(cue, japanese=result, status=cue_status,
                            model_called=cue_status != "non_dialogue_passthrough",
                            seconds=round(time.monotonic()-start, 3), usage=usage)
                record["entries"].append(item)
                # Keep each A/B arm independent, preserve every output and
                # explicitly flag English-only dialogue instead of passing it.
                small.atomic_json(out / (size + ".json"), record)
                if i % 10 == 0 or i == 1 or cue_status != "translated":
                    print(f"{size}: {i}/{len(cues)} | {cue_status}", flush=True)
            if len(record["entries"]) == LIMIT:
                (out / (size + ".review.ja.srt")).write_text(
                    small.format_srt(record["entries"], "japanese"),
                    encoding="utf-8")
            record["translated_cues"] = sum(
                e["status"] == "translated" for e in record["entries"])
            record["non_dialogue_cues"] = sum(
                e["status"] == "non_dialogue_passthrough"
                for e in record["entries"])
            record["held_dialogue_cues"] = sum(
                e["status"] == "held_non_japanese" for e in record["entries"])
            record["status"] = ("complete_with_held_dialogue"
                if record["held_dialogue_cues"] else "complete")
        except Exception as exc:
            record["status"] = "HELD"
            record["hold_reason"] = type(exc).__name__ + ": " + str(exc)[:180]
            print(size, "HELD:", record["hold_reason"], flush=True)
        finally:
            if proc:
                small.stop_server(proc)
            record["wall_seconds_including_load"] = round(time.monotonic()-started, 3)
            record["sum_generation_seconds"] = round(
                sum(e["seconds"] for e in record["entries"]), 3)
            small.atomic_json(out / (size + ".json"), record)
            details["models"][size] = {
                "status": record["status"],
                "cues": len(record["entries"]),
                "translated_dialogue": record.get("translated_cues"),
                "non_dialogue_passthrough": record.get("non_dialogue_cues"),
                "held_untranslated_dialogue": record.get("held_dialogue_cues"),
                "wall_seconds_including_load": record["wall_seconds_including_load"],
                "sum_generation_seconds": record["sum_generation_seconds"],
                "model_sha256": record["model_sha256"],
            }
            small.atomic_json(out / "manifest.json", details)
            if record["status"] not in ("complete", "complete_with_held_dialogue"):
                details["status"] = "HELD"
                small.atomic_json(out / "manifest.json", details)
                raise RuntimeError(size + " model held; private partials preserved")
    details["status"] = ("complete_with_held_dialogue"
        if any(x["status"] == "complete_with_held_dialogue"
               for x in details["models"].values())
        else "complete_unreviewed")
    small.atomic_json(out / "manifest.json", details)
    print("=== REAL MODEL-NATIVE TEST COMPLETE ===", flush=True)
    print(json.dumps(details["models"], indent=2), flush=True)
    print("PRIVATE outputs:", out, flush=True)
    print("No media, Jellyfin, source-only jobs or timed subtitles changed.", flush=True)


def tests():
    src = "I won't leave."
    history = [("This isn't over.", "まだ終わってない。"),
               ("You're serious?", "本気なの？")]
    p = native_prompt(src, history)
    assert p.startswith("<|plamo:tag|>dataset<|plamo:msg|>translation")
    assert p.count("<|plamo:tag|>input") == 3
    assert p.count("<|plamo:tag|>output") == 3
    assert p.endswith("<|plamo:tag|>output<|plamo:key|>lang<|plamo:val|>ja<|plamo:msg|>")
    assert "This isn't over." in p and p.index("This isn't over.") < p.index("まだ終わってない。")
    assert "<|plamo:bos|>" not in p
    assert STOP == small.STOP
    assert "text" not in small.format_srt(small.samples(), "english")
    assert small.parse_srt(small.format_srt(small.samples(), "english")) == small.samples()
    try:
        native_prompt("", [])
        raise AssertionError("empty source not held")
    except ValueError:
        pass
    print("REAL FILM PLaMo PFML3 HISTORY SELF-TEST PASSED (no files/network/models)")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--self-test", action="store_true")
    p.add_argument("--arm", choices=("all", "0.8b", "2b"), default="all",
                   help="run both arms by default; use 2b to complement a completed frozen 0.8b result")
    p.add_argument("--frozen-run", type=Path,
                   help="reuse exact 100-cue source from earlier private held run")
    p.add_argument("--port", type=int, default=18879)
    args = p.parse_args()
    if args.self_test:
        tests()
        return
    if not 1025 <= args.port <= 65535:
        p.error("port must be unprivileged")
    benchmark(args)


if __name__ == "__main__":
    main()
