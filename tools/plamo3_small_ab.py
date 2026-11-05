#!/usr/bin/env python3
"""Isolated PLaMo 3 Translate 0.8B vs 2B EN->JA experiment.

Uses llama.cpp's OpenAI-compatible *Completions* endpoint with PFN's exact
documented PFML3 translation prompt. Neither the existing SubHub workers nor
Jellyfin/media paths are modified. One process/model at a time, localhost only.
Standard Python library only. Output is private and create-only.
"""
from __future__ import annotations
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

MODEL_FILES = {
    "0.8b": "plamo-3-translate-0.8b-Q4_K_M.gguf",
    "2b": "plamo-3-translate-2b-Q4_K_M.gguf",
}
STOP = ["<|plamo:tag|>", "<|plamo:bos|>"]
# This *invented* demonstration script is intentionally not movie dialogue.
# It tests idioms, register, subtext, negation, and terse horror speech.
DEMO = [
    "I know what I saw.",
    "You don't know the half of it.",
    "Don't make a scene.",
    "He said he'd call. He never did.",
    "I'm not saying she's lying.",
    "I'm saying the timeline doesn't add up.",
    "You've got some nerve showing up here.",
    "Well, that's just great.",
    "We're not out of the woods yet.",
    "It wasn't supposed to end like this.",
    "There's something wrong with the basement.",
    "Keep your voice down. It can hear us.",
    "You've been drinking again, haven't you?",
    "That's not what I meant, and you know it.",
    "If this goes sideways, we walk.",
    "I wouldn't do that if I were you.",
]
TIME = re.compile(
    r"^(?P<s>\d\d:\d\d:\d\d,\d{3}) --> (?P<e>\d\d:\d\d:\d\d,\d{3})$")
JP = re.compile(r"[\u3040-\u30ff\u3400-\u9fff]")
BANNED_FILE = {"", ".", ".."}


def pfml3(source):
    if not isinstance(source, str) or not source.strip():
        raise ValueError("empty_english_source")
    return ("<|plamo:tag|>dataset<|plamo:msg|>translation"
            "<|plamo:tag|>input<|plamo:msg|>" + source +
            "<|plamo:tag|>output<|plamo:key|>lang<|plamo:val|>ja"
            "<|plamo:msg|>")


def timestamp(sec):
    sec = int(sec)
    return f"{sec//3600:02}:{sec//60%60:02}:{sec%60:02},000"


def samples():
    return [
        {"number": i + 1, "start": timestamp(i * 6),
         "end": timestamp(i * 6 + 5), "english": text}
        for i, text in enumerate(DEMO)
    ]


def parse_srt(text, limit=50):
    entries = []
    blocks = re.split(r"\n\s*\n", text.replace("\r\n", "\n").strip())
    for block in blocks:
        lines = [line.rstrip() for line in block.split("\n")]
        if len(lines) < 3 or not lines[0].strip().isdigit():
            raise ValueError("not_simple_srt_cues")
        times = TIME.fullmatch(lines[1].strip())
        if not times:
            raise ValueError("not_simple_srt_time")
        source = "\n".join(lines[2:]).strip()
        if not source:
            raise ValueError("empty_srt_cue")
        entries.append({"number": int(lines[0]), "start": times["s"],
                        "end": times["e"], "english": source})
        if len(entries) >= limit:
            break
    if not entries or any(b["number"] <= a["number"]
                          for a, b in zip(entries, entries[1:])):
        raise ValueError("invalid_srt_number_order")
    return entries


def format_srt(rows, field):
    return "\n\n".join(
        f"{r['number']}\n{r['start']} --> {r['end']}\n{r[field]}"
        for r in rows) + "\n"


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as inp:
        for block in iter(lambda: inp.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def json_request(port, path, body=None, timeout=15):
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=None if body is None else json.dumps(body, ensure_ascii=False).encode(),
        headers={"Content-Type": "application/json"},
        method="GET" if body is None else "POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as res:
        return json.load(res)


def check_port(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        if s.connect_ex(("127.0.0.1", port)) == 0:
            raise RuntimeError("benchmark_port_in_use_refusing_existing_service")


def start_server(binary, model, port, gpu_layers, logpath):
    check_port(port)
    cmd = [str(binary), "-m", str(model), "-c", "4096", "--host",
           "127.0.0.1", "--port", str(port), "-ngl",
           str(gpu_layers), "-t", "4", "--alias", "plamo-3-translate"]
    # No chat template needed: official PFML3 + raw Completions API.
    handle = logpath.open("xb")
    try:
        process = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=handle,
                                   stderr=subprocess.STDOUT, start_new_session=True)
    finally:
        handle.close()
    try:
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError("llama_server_exited_early_check_private_log")
            try:
                obj = json_request(port, "/health", timeout=3)
                if isinstance(obj, dict) and obj.get("status") == "ok":
                    return process
            except (urllib.error.URLError, TimeoutError, ValueError):
                pass
            time.sleep(1)
        raise RuntimeError("llama_server_health_timeout")
    except Exception:
        stop_server(process)
        raise


def stop_server(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)


def translate(port, english):
    body = {
        "model": "plamo-3-translate",
        "prompt": pfml3(english),
        "temperature": 0,
        "max_tokens": 256,
        "stop": STOP,
        "stream": False,
    }
    resp = json_request(port, "/v1/completions", body, timeout=180)
    choices = resp.get("choices") if isinstance(resp, dict) else None
    if not isinstance(choices, list) or not choices:
        raise ValueError("missing_completion")
    result = choices[0]
    if result.get("finish_reason") == "length":
        raise ValueError("translation_truncated_at_token_cap")
    ja = str(result.get("text") or "").strip()
    if not ja or "<|plamo:" in ja:
        raise ValueError("empty_or_unstripped_model_output")
    return ja, resp.get("usage") or {}


def atomic_json(path, value):
    temp = path.with_suffix(".tmp")
    with temp.open("x", encoding="utf-8") as out:
        json.dump(value, out, ensure_ascii=False, indent=2)
        out.write("\n")
        out.flush()
        os.fsync(out.fileno())
    temp.replace(path)


def gpu_preflight():
    # A GPU test should never implicitly kick Ollama, Wolf, or a game off VRAM.
    proc = subprocess.run(
        ["nvidia-smi", "--query-gpu=memory.free,utilization.gpu",
         "--format=csv,noheader,nounits"],
        capture_output=True, text=True, timeout=10, check=True)
    vals = [int(x.strip()) for x in proc.stdout.strip().splitlines()[0].split(",")[:2]]
    free_mib, util_pct = vals
    if free_mib < 3000 or util_pct > 20:
        raise RuntimeError(
            f"GPU_BUSY free_MiB={free_mib} util_pct={util_pct}; "
            "retry with --gpu-layers 0 for CPU or after gaming")
    return {"free_mib": free_mib, "util_pct": util_pct}


def read_dataset(args):
    if args.srt:
        path = Path(args.srt).expanduser().resolve(strict=True)
        if not path.is_file() or path.stat().st_size > 2_000_000:
            raise ValueError("source_srt_not_small_regular_file")
        return parse_srt(path.read_text(encoding="utf-8-sig"), args.limit), str(path)
    return samples()[:args.limit], "original_nonmovie_demonstration_dialogue"


def run(args):
    if args.self_test:
        self_test()
        return
    binary = Path(args.binary).expanduser().resolve(strict=True)
    if not binary.is_file() or not os.access(binary, os.X_OK):
        raise ValueError("llama_server_binary_missing")
    modeldir = Path(args.models).expanduser().resolve(strict=True)
    if modeldir.is_symlink():
        raise ValueError("symlink_model_dir")
    for path in (modeldir / fn for fn in MODEL_FILES.values()):
        if not path.is_file() or path.is_symlink() or path.stat().st_size < 100_000_000:
            raise ValueError("missing_or_partial_model_file: " + path.name)
    dataset, source = read_dataset(args)
    if not dataset:
        raise ValueError("no_english_cues")
    if args.gpu_layers > 0:
        gpu_preflight()
    outbase = Path(args.output_root).expanduser()
    outbase.mkdir(mode=0o700, parents=True, exist_ok=True)
    if outbase.is_symlink() or outbase.stat().st_mode & 0o077:
        raise ValueError("output_base_must_be_private")
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    outdir = outbase / ("plamo3-small-ab-" + stamp)
    outdir.mkdir(mode=0o700, exist_ok=False)
    (outdir / "SOURCE.en.srt").write_text(format_srt(dataset, "english"), encoding="utf-8")
    manifest = {
        "created_utc": stamp, "status": "running",
        "input": source, "cue_count": len(dataset),
        "source_sha256": hashlib.sha256(
            format_srt(dataset, "english").encode()).hexdigest(),
        "official_api": "PFML3 + llama.cpp /v1/completions",
        "temperature": 0, "max_tokens": 256, "stop": STOP,
        "gpu_layers": args.gpu_layers,
        "models": {},
    }
    atomic_json(outdir / "manifest.json", manifest)
    for key, filename in MODEL_FILES.items():
        model = modeldir / filename
        print(f"=== PLAMO {key} Q4_K_M | {len(dataset)} CUES ===", flush=True)
        record = {
            "file": filename, "model_sha256": digest(model),
            "entries": [], "errors": [], "generation_seconds": 0,
        }
        process = None
        try:
            if args.gpu_layers:
                gpu_preflight()
            process = start_server(binary, model, args.port, args.gpu_layers,
                                   outdir / (key + ".server.log"))
            for i, cue in enumerate(dataset, start=1):
                began = time.monotonic()
                try:
                    answer, usage = translate(args.port, cue["english"])
                except (urllib.error.URLError, TimeoutError, ValueError) as exc:
                    record["errors"].append({
                        "number": cue["number"], "error": type(exc).__name__ +
                        ": " + str(exc)[:100],
                    })
                    answer, usage = "", {}
                elapsed = time.monotonic() - began
                record["generation_seconds"] += elapsed
                record["entries"].append({
                    **cue, "japanese": answer,
                    "seconds": round(elapsed, 3), "usage": usage,
                    "has_japanese_script": bool(JP.search(answer))
                })
                print(f"[{i}/{len(dataset)}] {key} "
                      f"{elapsed:.2f}s | {'JA' if JP.search(answer) else 'HOLD'}",
                      flush=True)
            if len(record["entries"]) == len(dataset):
                # Keep every cue and timecode. A missing output is an empty
                # draft cue, not a fabricated or automatically published file.
                (outdir / (key + ".draft.ja.srt")).write_text(
                    format_srt(record["entries"], "japanese"), encoding="utf-8")
        except Exception as exc:
            record["errors"].append({"error": type(exc).__name__ + ": " + str(exc)[:180]})
            print("MODEL HELD:", type(exc).__name__, str(exc)[:100], flush=True)
        finally:
            if process is not None:
                stop_server(process)
            record["generation_seconds"] = round(record["generation_seconds"], 3)
            atomic_json(outdir / (key + ".json"), record)
            manifest["models"][key] = {
                "completed": len(record["entries"]), "errors": len(record["errors"]),
                "seconds": record["generation_seconds"],
                "sha256": record["model_sha256"]
            }
            atomic_json(outdir / "manifest.json", manifest)
    manifest["status"] = "finished"
    atomic_json(outdir / "manifest.json", manifest)
    print("\nPRIVATE PLaMo test outputs:", outdir, flush=True)
    print("SOURCE-ONLY SERVICE: UNCHANGED. NO JELLYFIN FILES MODIFIED.", flush=True)
    for key, data in manifest["models"].items():
        print(f"  {key} {data['completed']}/{len(dataset)} cues, "
              f"{data['errors']} errors, {data['seconds']}s inference", flush=True)


def self_test():
    s = samples()
    assert len(s) == len(DEMO) == 16
    assert s[0]["start"] == "00:00:00,000"
    assert parse_srt(format_srt(s, "english"), len(s)) == s
    assert "dataset<|plamo:msg|>translation" in pfml3("Hello")
    assert "lang<|plamo:val|>ja<|plamo:msg|>" in pfml3("Hello")
    assert STOP == ["<|plamo:tag|>", "<|plamo:bos|>"]
    assert format_srt([{**s[0], "japanese": "見ました。"}], "japanese").endswith("見ました。\n")
    try:
        parse_srt("bad")
        raise AssertionError("bad srt accepted")
    except ValueError:
        pass
    print("PLaMo SMALL A/B SELF-TEST PASSED: PFML3, source and SRT preservation")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--binary", default="~/bruiser-pilot/plamo3-ab/runtime/llama-server")
    p.add_argument("--models", default="~/bruiser-pilot/plamo3-ab/models")
    p.add_argument("--output-root", default="~/bruiser-pilot/plamo3-ab/results")
    p.add_argument("--srt", help="optional local ENGLISH SRT file; never modified")
    p.add_argument("--limit", type=int, default=16)
    p.add_argument("--gpu-layers", type=int, default=0, help="0=CPU-only; 99=GPU attempt")
    p.add_argument("--port", type=int, default=18878)
    p.add_argument("--self-test", action="store_true")
    args = p.parse_args(argv)
    if args.self_test:
        return self_test()
    if not 1 <= args.limit <= 100:
        p.error("--limit must be 1..100")
    if not 0 <= args.gpu_layers <= 99:
        p.error("--gpu-layers must be 0..99")
    if not 1025 <= args.port <= 65535:
        p.error("port must be unprivileged")
    run(args)


if __name__ == "__main__":
    main()
