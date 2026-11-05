#!/usr/bin/env python3
"""Reproduce ONLY the first invalid PLaMo real-film cue using PFN-native PFML3.

Source/result files from the original frozen private run are read-only.
Exact same model, context, temperature/stop/max tokens as original. Records
and prints the unfiltered /v1/completions result to PRIVATE diagnostics.
Nothing written to media, Jellyfin, SubHub producer, or original run.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys

try:
    from . import plamo3_real_film_ab as real
except ImportError:
    import plamo3_real_film_ab as real

small = real.small
MODEL_NAME = "plamo-3-translate"


def find_cue(folder, arm):
    folder = Path(folder).expanduser().resolve(strict=True)
    if not folder.is_dir() or folder.is_symlink() or folder.stat().st_mode & 0o077:
        raise RuntimeError("unsafe_private_run_directory")
    manifest = real._private_path(folder / "manifest.json")
    source = real._private_path(folder / "source.en.srt")
    record = real._private_path(folder / (arm + ".json"))
    meta = json.loads(manifest.read_text("utf-8"))
    en_bytes = source.read_bytes()
    if hashlib.sha256(en_bytes).hexdigest() != meta.get("source_sha256"):
        raise RuntimeError("original_frozen_english_sha256_mismatch")
    cues = small.parse_srt(en_bytes.decode("utf-8-sig"), limit=12000)
    entries = json.loads(record.read_text("utf-8")).get("entries", [])
    if len(entries) >= len(cues):
        raise RuntimeError("there_is_no_failed_next_cue")
    for a, b in zip(entries, cues):
        if (a.get("number"), a.get("english"), a.get("start"), a.get("end")) != (
            b["number"], b["english"], b["start"], b["end"]):
            raise RuntimeError("original_partial_results_do_not_match_source")
    history = [(a["english"], a["japanese"]) for a in entries[-real.HISTORY:]]
    if any(not ja.strip() for _, ja in history):
        raise RuntimeError("invalid_original_history")
    return folder, cues, entries, history, meta


def raw_completion(port, source, history):
    return small.json_request(port, "/v1/completions", {
        "model": MODEL_NAME,
        "prompt": real.native_prompt(source, history),
        "temperature": 0,
        "max_tokens": 512,
        "stop": real.STOP,
        "stream": False,
    }, timeout=180)


def summarize_result(obj):
    choice = (obj.get("choices") or [{}])[0] if isinstance(obj, dict) else {}
    raw = choice.get("text")
    if not isinstance(raw, str):
        raw = ""
    return {
        "raw_translation": raw,
        "finish_reason": choice.get("finish_reason"),
        "usage": obj.get("usage"),
        "character_length": len(raw),
        "japanese_script": bool(small.JP.search(raw)),
        "blank": not raw.strip(),
        "format_marker": "<|plamo:" in raw,
    }


def diagnose(folder, arm, port):
    original, cues, entries, history, meta = find_cue(folder, arm)
    failed = cues[len(entries)]
    print("=== FROZEN RUN / INVALID NEXT CUE ===", flush=True)
    print("Title:", meta.get("title"), "Source SHA256:", meta.get("source_sha256"), flush=True)
    print("Previously completed:", len(entries), flush=True)
    for offset in range(max(0, len(entries)-1), min(len(cues), len(entries)+2)):
        c = cues[offset]
        print("CUE", c["number"], "EN:", repr(c["english"]), flush=True)
    model_file = real.ROOT / "models" / small.MODEL_FILES[arm]
    runtime = (real.ROOT / "runtime/llama-server").resolve(strict=True)
    if not runtime.is_file() or not os.access(runtime, os.X_OK):
        raise RuntimeError("original_pinned_runtime_missing")
    if not model_file.is_file() or model_file.is_symlink():
        raise RuntimeError("original_model_missing")
    small.gpu_preflight()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    diag = original / ("diagnostic-" + arm + "-" + stamp + ".json")
    log = original / ("diagnostic-" + arm + "-" + stamp + ".server.log")
    proc = small.start_server(runtime, model_file, port, 99, log)
    try:
        obj = raw_completion(port, failed["english"], history)
    finally:
        small.stop_server(proc)
    view = summarize_result(obj)
    data = {
        "schema": 1, "mode": "one_raw_original_cue_reproduction",
        "original_source_sha256": meta["source_sha256"], "model": arm,
        "cue_id": failed["number"], "source_english": failed["english"],
        "history_pairs": history,
        "actual_model_response": obj, "summary": view,
    }
    small.atomic_json(diag, data)
    print("=== RAW MODEL RESPONSE (NO VALIDATION, NO RETRIES) ===", flush=True)
    print(json.dumps(view, ensure_ascii=False, indent=2), flush=True)
    print("PRIVATE diagnostic saved:", diag, flush=True)
    print("Source-only service, media and original results unchanged.", flush=True)


def tests():
    a = summarize_result({"choices": [{"text":"日本語", "finish_reason":"stop"}], "usage": {}})
    assert a["japanese_script"] and not a["blank"] and not a["format_marker"]
    a = summarize_result({"choices": [{"text":"Jason", "finish_reason":"stop"}]})
    assert not a["japanese_script"] and not a["blank"]
    assert not summarize_result({"choices":[{"text":"", "finish_reason":"stop"}]})["japanese_script"]
    hist = [("Say no.", "嫌だ。")]
    p = real.native_prompt("Go!", hist)
    assert p.count("<|plamo:tag|>input") == 2
    print("PLaMo one-cue failure diagnostic self-test passed.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path)
    parser.add_argument("--arm", choices=("0.8b", "2b"), default="0.8b")
    parser.add_argument("--port", type=int, default=18881)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return tests()
    if args.run is None:
        parser.error("--run private-run-directory required")
    if not 1025 <= args.port <= 65535:
        parser.error("invalid_port")
    diagnose(args.run, args.arm, args.port)


if __name__ == "__main__":
    main()
