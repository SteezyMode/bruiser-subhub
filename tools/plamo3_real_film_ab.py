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
    if not ja or "<|plamo:" in ja or not small.JP.search(ja):
        raise RuntimeError("missing_or_malformed_japanese")
    return ja, response.get("usage") or {}


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
    small.gpu_preflight()
    row, video, cues, total, origin, manifest_name = choose_embedded_english()
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
    }
    small.atomic_json(out / "manifest.json", details)
    print("=== FROZEN REAL ENGLISH SOURCE ===", flush=True)
    print(row["title"], "(", row.get("year"), ")",
          "| embedded English |", total, "total cues", flush=True)
    print("Frozen 100-cue sample:", cues[0]["number"], "to", cues[-1]["number"],
          "| SHA256:", details["source_sha256"], flush=True)
    print("No media or production service writes. PRIVATE output:", out, flush=True)

    for size, name in small.MODEL_FILES.items():
        small.gpu_preflight()
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
                result, usage = request(args.port, cue["english"], previous[-HISTORY:])
                item = dict(cue, japanese=result,
                            seconds=round(time.monotonic()-start, 3), usage=usage)
                record["entries"].append(item)
                previous.append((cue["english"], result))
                # On interruption preserve useful outputs, never reuse them as
                # unverified context for a fresh run.
                small.atomic_json(out / (size + ".json"), record)
                if i % 10 == 0 or i == 1:
                    print(f"{size}: {i}/{len(cues)} translated", flush=True)
            if len(record["entries"]) == LIMIT:
                (out / (size + ".review.ja.srt")).write_text(
                    small.format_srt(record["entries"], "japanese"),
                    encoding="utf-8")
            record["status"] = "complete"
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
                "wall_seconds_including_load": record["wall_seconds_including_load"],
                "sum_generation_seconds": record["sum_generation_seconds"],
                "model_sha256": record["model_sha256"],
            }
            small.atomic_json(out / "manifest.json", details)
            if record["status"] != "complete":
                details["status"] = "HELD"
                small.atomic_json(out / "manifest.json", details)
                raise RuntimeError(size + " model held; private partials preserved")
    details["status"] = "complete_unreviewed"
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
