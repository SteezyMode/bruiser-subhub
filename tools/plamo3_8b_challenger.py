#!/usr/bin/env python3
"""Isolated PLaMo 3 Translate 8B challenger on SAME frozen 100 EN film cues.

Does NOT edit source models, model prompts, Jellyfin, media, source-only timer,
or the two completed 0.8B/2B test results. The ONLY new inference arm is 8B.
Requires the previous tested llama.cpp server and official PFN Q4_K_M weights.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import time

try:
    from . import plamo3_real_film_ab as real
except ImportError:
    import plamo3_real_film_ab as real

small = real.small
ROOT = real.ROOT
MODEL = "plamo-3-translate-8b-Q4_K_M.gguf"
EXPECTED_SOURCE_SHA256 = "d4394793c9608ab8935cdba89a6bfb9be41d0e51e1274123966b78939fe1174a"
ORIGINAL_08 = "film-100-20261105T091004064058Z"
ORIGINAL_2B = "film-100-20261105T091839645501Z"
LAYER_TRIALS = (28, 20, 12, 0)  # Runtime placement only, no prompt/model changes.


def read_proven_reference(root: Path, folder: str, model: str, english):
    """Proof that each reference genuinely corresponds to identical EN/SRT."""
    if folder not in (ORIGINAL_08, ORIGINAL_2B):
        raise ValueError("unexpected_reference_folder")
    ref_dir = root / folder
    # Real-film loader checks private files, 100 cue IDs/timecodes, EN sha,
    # source media file identity and directory membership.
    _, _, rows, _, _, _, _, digest = real.load_frozen_run(ref_dir)
    if digest != EXPECTED_SOURCE_SHA256 or rows != english:
        raise RuntimeError("reference_source_not_identical")
    ref = real._private_path(ref_dir / (model + ".json"))
    payload = ref.read_bytes()
    state = json.loads(payload)
    if state.get("status") != "complete" or len(state.get("entries", [])) != 100:
        raise RuntimeError("reference_model_not_complete")
    for source, got in zip(english, state["entries"]):
        if any(source[key] != got.get(key)
               for key in ("number", "start", "end", "english")):
            raise RuntimeError("reference_model_alignment_mismatch")
        if got.get("status") not in ("translated", "non_dialogue_passthrough"):
            raise RuntimeError("reference_model_contains_unresolved_dialogue")
    return hashlib.sha256(payload).hexdigest()


def check_native_contract():
    """Do not silently substitute old Gemma prompt behavior or custom JSON."""
    out = real.native_prompt(
        "Go.", [("Wait.", "待て。"), ("No.", "いや。")])
    if not (out.startswith("<|plamo:tag|>dataset<|plamo:msg|>translation")
            and out.count("<|plamo:tag|>input") == 3
            and out.count("<|plamo:tag|>output") == 3
            and out.endswith(
                "<|plamo:tag|>output<|plamo:key|>lang<|plamo:val|>ja<|plamo:msg|>")
            and real.HISTORY == 2
            and real.STOP == ["<|plamo:tag|>", "<|plamo:bos|>"]):
        raise RuntimeError("native_PFN_PFML3_contract_changed")


def prepare():
    check_native_contract()
    base = ROOT / "real-results"
    _, video, cues, total, _, _, _, source_sha = real.load_frozen_run(
        base / ORIGINAL_08)
    if source_sha != EXPECTED_SOURCE_SHA256 or len(cues) != 100 or (
        cues[0]["number"], cues[-1]["number"]) != (153, 252):
        raise RuntimeError("frozen_100_cue_source_changed")
    refs = {
        "0.8b": read_proven_reference(base, ORIGINAL_08, "0.8b", cues),
        "2b": read_proven_reference(base, ORIGINAL_2B, "2b", cues),
    }
    return video, cues, total, refs


def validate_weight(path):
    if not path.is_file() or path.is_symlink() or path.stat().st_size < 4_500_000_000:
        raise RuntimeError("missing_or_incomplete_official_8b_GGUF")
    with path.open("rb") as inp:
        if inp.read(4) != b"GGUF":
            raise RuntimeError("invalid_GGUF_magic")


def start_offloaded_server(binary, model, out, port):
    """Only change layer placement to run on 6GB GPU. No VRAM busy gate.

    llama.cpp can exit at startup when too many layers fit neither VRAM nor
    CUDA workspace. Try bounded settings: 28,20,12,0 layers. Changes in
    layer placement do NOT modify model weights or decoding method.
    """
    errors = []
    for ngl in LAYER_TRIALS:
        log = out / ("8b.ngl-" + str(ngl) + ".server.log")
        print(f"8B server load: GPU layers={ngl}", flush=True)
        try:
            return small.start_server(binary, model, port, ngl, log), ngl
        except (OSError, RuntimeError) as exc:
            reason = type(exc).__name__ + ": " + str(exc)[:180]
            errors.append({"gpu_layers": ngl, "reason": reason})
            print(f"8B load failed at {ngl} layers: {reason}", flush=True)
            # start_server handles teardown of any process it created.
    raise RuntimeError("all_8B_offload_attempts_failed: " + json.dumps(errors))


def evaluate(port, cues, record, out):
    previous = []
    for i, cue in enumerate(cues, 1):
        started = time.monotonic()
        if real.is_non_dialogue_caption(cue["english"]):
            jp, usage, kind = cue["english"], {}, "non_dialogue_passthrough"
        else:
            # EXACT same model creator PFML3 prompt, previous-two-pairs,
            # temperature=0, max_tokens=512, stop tags, native API route.
            jp, usage, kind = real.request(
                port, cue["english"], previous[-real.HISTORY:])
            if kind == "translated":
                previous.append((cue["english"], jp))
        result = {
            **cue, "japanese": jp, "status": kind,
            "model_called": kind != "non_dialogue_passthrough",
            "seconds": round(time.monotonic() - started, 3),
            "usage": usage,
        }
        record["entries"].append(result)
        small.atomic_json(out / "8b.json", record)
        if i == 1 or i % 10 == 0 or kind != "translated":
            print(f"8B: {i}/100 | {kind}", flush=True)
    record["translated_cues"] = sum(x["status"] == "translated"
                                    for x in record["entries"])
    record["non_dialogue_cues"] = sum(x["status"] == "non_dialogue_passthrough"
                                      for x in record["entries"])
    record["held_dialogue_cues"] = sum(x["status"] == "held_non_japanese"
                                       for x in record["entries"])
    record["status"] = ("complete_with_held_dialogue"
                        if record["held_dialogue_cues"] else "complete")
    # DRAFT only, for private review. No Jellyfin/library-adjacent files.
    (out / "8b.review.ja.srt").write_text(
        small.format_srt(record["entries"], "japanese"), encoding="utf-8")


def run(args):
    video, cues, total, refs = prepare()
    binary = (ROOT / "runtime/llama-server").resolve(strict=True)
    if not binary.is_file() or not os.access(binary, os.X_OK):
        raise RuntimeError("original_llama_server_missing")
    model = ROOT / "models" / MODEL
    validate_weight(model)
    base = ROOT / "real-results"
    if base.is_symlink() or base.stat().st_mode & 0o077:
        raise RuntimeError("private_results_directory_permissions")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    out = base / ("film-100-8b-" + stamp)
    out.mkdir(mode=0o700)
    source = small.format_srt(cues, "english")
    # Private independent copy; original stays immutable.
    (out / "source.en.srt").write_text(source, encoding="utf-8")
    manifest = {
        "status": "started", "model": "8b", "model_filename": MODEL,
        "model_sha256": small.digest(model),
        "film": "Friday the 13th: The Final Chapter (1984)",
        "original_cue_first": 153, "original_cue_last": 252,
        "frozen_english_sha256": EXPECTED_SOURCE_SHA256,
        "frozen_source_path": ORIGINAL_08,
        "references_sha256": refs,
        "video_path": str(video), "all_source_cues": total,
        "temperature": 0, "history_pairs": 2, "max_tokens": 512,
        "stop": real.STOP, "source_lang": "en", "target_lang": "ja",
        "protocol": "PLaMo 3 PFN-native PFML3 direct llama.cpp /v1/completions",
        "runtime": "existing pinned llama.cpp b12119 CUDA",
        "candidate_gpu_layers": list(LAYER_TRIALS),
        "published": False,
    }
    small.atomic_json(out / "manifest.json", manifest)
    record = {
        "model": "8b", "model_filename": MODEL,
        "model_sha256": manifest["model_sha256"], "entries": [],
        "status": "started",
    }
    process = None
    since = time.monotonic()
    try:
        process, ngl = start_offloaded_server(binary, model, out, args.port)
        record["gpu_layers"] = ngl
        manifest["gpu_layers"] = ngl
        small.atomic_json(out / "manifest.json", manifest)
        evaluate(args.port, cues, record, out)
    except Exception as exc:
        record["status"] = "HELD"
        record["hold_reason"] = type(exc).__name__ + ": " + str(exc)[:220]
        print("8B HELD:", record["hold_reason"], flush=True)
    finally:
        if process is not None:
            small.stop_server(process)
        record["wall_seconds_including_load"] = round(time.monotonic()-since, 3)
        record["sum_generation_seconds"] = round(
            sum(x["seconds"] for x in record["entries"]), 3)
        small.atomic_json(out / "8b.json", record)
        manifest["status"] = record["status"]
        manifest["completed_cues"] = len(record["entries"])
        manifest["translated_dialogue"] = record.get("translated_cues")
        manifest["non_dialogue_passthrough"] = record.get("non_dialogue_cues")
        manifest["held_untranslated_dialogue"] = record.get("held_dialogue_cues")
        manifest["wall_seconds_including_load"] = record["wall_seconds_including_load"]
        small.atomic_json(out / "manifest.json", manifest)
    print("=== PLaMo 8B CHALLENGER ===", flush=True)
    print(json.dumps({
        "status": record["status"],
        "cues": len(record["entries"]),
        "translated_dialogue": record.get("translated_cues"),
        "sdh_passthrough": record.get("non_dialogue_cues"),
        "held_dialogue": record.get("held_dialogue_cues"),
        "wall_seconds": record["wall_seconds_including_load"],
        "gpu_layers": record.get("gpu_layers"),
        "private_result": str(out / "8b.json"),
    }, indent=2), flush=True)
    print("Jellyfin and existing 0.8B/2B outputs unchanged.", flush=True)
    if record["status"] not in ("complete", "complete_with_held_dialogue"):
        raise RuntimeError("8b_challenger_held_check_private_8b_json")


def self_test():
    check_native_contract()
    assert LAYER_TRIALS == (28, 20, 12, 0)
    assert MODEL == "plamo-3-translate-8b-Q4_K_M.gguf"
    assert len(EXPECTED_SOURCE_SHA256) == 64
    assert real.is_non_dialogue_caption('<font size="36">[SIGHS]</font>')
    assert not real.is_non_dialogue_caption('Hey, come back!')
    print("8B CHALLENGER SELF-TEST PASSED: original PFML3 and fixed source")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--port", type=int, default=18882)
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if not 1025 <= args.port <= 65535:
        parser.error("port must be unprivileged")
    run(args)


if __name__ == "__main__":
    main()
