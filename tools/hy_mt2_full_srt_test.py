#!/usr/bin/env python3
"""Direct, resumable full-SRT test using Tencent Hy-MT2's Structured Data 1 prompt.

Translation is ONE Ollama /api/chat call per consecutive 30-cue section.
Exactly the model-card prompt and sampling parameters used in the successful
2026-11-03 30-cue test. NO system prompt, other models, rewrite or retries.

Only mechanical file work: read English SRT, split, preserve raw replies,
verify numbering/timing, assemble separate draft. Never publishes to Jellyfin.
"""
import argparse
import fcntl
import hashlib
import json
import re
import subprocess
import time
import urllib.request
from pathlib import Path

MODEL = "hf.co/tencent/Hy-MT2-7B-GGUF:Q4_K_M"
OPTIONS = {
    "temperature": 0.7, "top_p": 0.6, "top_k": 20,
    "repeat_penalty": 1.05, "num_predict": 4096,
}
TIMESTAMP = r"\d\d:\d\d:\d\d,\d{3} --> \d\d:\d\d:\d\d,\d{3}(?:[ \t]+[^\n]+)?"
CUE = re.compile(rf"\A(\d+)\n({TIMESTAMP})\n(.+)\Z", re.DOTALL)


def parse_srt(data):
    blocks = re.split(r"\n[ \t]*\n", data.replace("\r\n", "\n").lstrip("\ufeff").strip())
    cues = []
    for index, block in enumerate(blocks, start=1):
        match = CUE.fullmatch(block.strip())
        if not match:
            raise ValueError(f"Malformed SRT structure at block {index}; no automatic repair")
        number, timestamp, dialogue = match.groups()
        if not dialogue.strip():
            raise ValueError(f"Empty subtitle text at block {index}")
        cues.append((number, timestamp, dialogue))
    if not cues:
        raise ValueError("No subtitle cues found")
    return cues


def as_srt(cues):
    return "\n\n".join(f"{number}\n{timestamp}\n{dialogue}" for number, timestamp, dialogue in cues) + "\n"


def source_srt(source):
    if source.suffix.lower() == ".srt":
        return source.read_text(encoding="utf-8-sig")
    if source.suffix.lower() not in (".mkv", ".mp4", ".m4v"):
        raise ValueError("Source must be an English .srt or video with an English embedded SRT")
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "s",
         "-show_entries", "stream=index,codec_name:stream_tags=language,title",
         "-of", "json", str(source)],
        check=True, capture_output=True, text=True, timeout=60,
    )
    streams = json.loads(probe.stdout).get("streams", [])
    matches = [
        s for s in streams
        if s.get("codec_name") == "subrip"
        and s.get("tags", {}).get("language", "").lower() in ("en", "eng")
    ]
    if not matches:
        raise ValueError("No English SRT subtitle stream found; no transcription or OCR attempted")
    track = next((s for s in matches if "sdh" not in
                  s.get("tags", {}).get("title", "").lower()), matches[0])
    print(f"English source: embedded subrip stream #{track['index']}", flush=True)
    extracted = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-i", str(source),
         "-map", f"0:{track['index']}", "-f", "srt", "-"],
        check=True, capture_output=True, timeout=180,
    )
    return extracted.stdout.decode("utf-8-sig", errors="replace")


def official_prompt(srt):
    # Tencent Hy-MT2-7B-GGUF README: "Structured Data 1", English template.
    # Only fill {format_type}=SRT, {target_lang}=Japanese, {source_text}=SRT.
    # Do not modify this template to optimize translation.
    return (
        "### Task\n"
        "Translate the user-facing text within the following SRT data into Japanese.\n"
        "### Strict Rules\n"
        "1. Structure Preservation: You MUST preserve the original SRT data structure, "
        "nesting, hierarchy, and indentation exactly as they are.\n"
        "2. Selective Translation: Translate ONLY the visible, user-facing text content/values.\n"
        "3. Strict Non-Translation: NEVER translate or alter code tags, keys, properties, "
        "object names, or variable placeholders. Leave them exactly in their original English/code form.\n"
        "### Source Data\n"
        + srt
    )


def configured_url():
    from config import get_settings
    config = get_settings()
    headers = {"X-Api-Key": config.api_key} if config.api_key else {}
    req = urllib.request.Request(
        "http://127.0.0.1:5765/api/v1/backends/ollama/config", headers=headers
    )
    with urllib.request.urlopen(req, timeout=15) as response:
        settings = json.load(response)
    return (settings.get("url") or config.ollama_url).rstrip("/")


def translate(url, srt):
    req = urllib.request.Request(
        url + "/api/chat",
        data=json.dumps({
            "model": MODEL, "stream": False,
            "messages": [{"role": "user", "content": official_prompt(srt)}],
            "options": OPTIONS,
        }).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=1800) as response:
        reply = json.load(response)
    return (reply.get("message") or {}).get("content", ""), reply.get("done_reason")


def compare_structure(source_cues, generated):
    translated = parse_srt(generated)
    original_structure = [(n, t) for n, t, _ in source_cues]
    translated_structure = [(n, t) for n, t, _ in translated]
    if translated_structure != original_structure:
        raise ValueError(
            f"Structure mismatch: expected {len(original_structure)} cues "
            f"with identical indices/timestamps, got {len(translated_structure)}"
        )
    return translated


def new_text(path, content):
    with path.open("x", encoding="utf-8") as f:
        f.write(content)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--batch-size", type=int, default=30)
    parser.add_argument("--workdir", type=Path, default=Path("/tmp/subhub-hy-mt2-full-chair-test"))
    args = parser.parse_args()
    if not args.source.is_file() or args.batch_size < 1:
        parser.error("Source must exist and batch size must be positive")
    source_cues = parse_srt(source_srt(args.source))
    source_text = as_srt(source_cues)
    digest = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
    manifest = {
        "source": str(args.source), "sha256": digest,
        "cues": len(source_cues), "batch_size": args.batch_size,
        "model": MODEL, "options": OPTIONS,
        "prompt_template_sha256": hashlib.sha256(official_prompt("").encode()).hexdigest(),
    }
    workdir = args.workdir
    workdir.mkdir(parents=True, exist_ok=True)
    # Only one translation process can write to this test directory at a time.
    lock_fd = (workdir / ".run.lock").open("a")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit(f"Full-episode test already running in {workdir}")
    manifest_path = workdir / "manifest.json"
    if manifest_path.exists():
        if json.loads(manifest_path.read_text(encoding="utf-8")) != manifest:
            raise SystemExit(f"Workdir contains a different test. Refusing to mix results: {workdir}")
    else:
        new_text(manifest_path, json.dumps(manifest, indent=2) + "\n")
    english_copy = workdir / "original.en.srt"
    if not english_copy.exists():
        new_text(english_copy, source_text)
    elif english_copy.read_text(encoding="utf-8") != source_text:
        raise SystemExit("Existing English source differs: refusing to continue")
    existing_draft = workdir / "full-episode.draft.ja.srt"
    if existing_draft.exists():
        compare_structure(source_cues, existing_draft.read_text(encoding="utf-8"))
        print(f"Already complete: {len(source_cues)} cues in {existing_draft}", flush=True)
        return
    url = configured_url()
    print(f"Model: {MODEL}\nOllama: {url}\nSource cues: {len(source_cues)}",
          f"\nBatch size: {args.batch_size}\nWorkdir: {workdir}", flush=True)
    chunks = [
        source_cues[offset:offset + args.batch_size]
        for offset in range(0, len(source_cues), args.batch_size)
    ]
    completed = []
    for index, chunk in enumerate(chunks, start=1):
        chunk_name = f"part-{index:04d}"
        raw_file = workdir / f"{chunk_name}.raw.txt"
        verified_file = workdir / f"{chunk_name}.ja.srt"
        if verified_file.exists():
            parsed = compare_structure(chunk, verified_file.read_text(encoding="utf-8"))
            completed.extend(parsed)
            print(f"[{index}/{len(chunks)}] Reusing verified segment ({len(chunk)} cues)", flush=True)
            continue
        if raw_file.exists():
            raise SystemExit(
                f"Previous unverified response at {raw_file}; stopping, NOT re-running "
                "or silently rewriting it. Share that file to investigate."
            )
        text = as_srt(chunk)
        print(f"[{index}/{len(chunks)}] Translating cues {chunk[0][0]}–{chunk[-1][0]}", flush=True)
        started = time.monotonic()
        translated_raw, finish_reason = translate(url, text)
        elapsed = round(time.monotonic() - started, 1)
        new_text(raw_file, translated_raw)
        if finish_reason != "stop":
            raise SystemExit(
                f"Model stopped with reason {finish_reason!r} after {elapsed}s. "
                f"Raw response saved at {raw_file}; no silent retry."
            )
        try:
            parsed = compare_structure(chunk, translated_raw)
        except ValueError as e:
            raise SystemExit(
                f"Part {index} has incorrect SRT structure: {e}\n"
                f"Raw response saved at {raw_file}; no translation was changed."
            ) from e
        new_text(verified_file, as_srt(parsed))
        completed.extend(parsed)
        print(f"  {len(chunk)}/{len(chunk)} timestamps and IDs preserved; {elapsed}s", flush=True)
    if len(completed) != len(source_cues):
        raise SystemExit(f"Internal cue count mismatch: {len(completed)} != {len(source_cues)}")
    final_file = workdir / "full-episode.draft.ja.srt"
    if final_file.exists():
        raise SystemExit(f"Draft already exists: {final_file} (not overwritten)")
    new_text(final_file, as_srt(completed))
    print(f"\nCOMPLETE: {len(completed)} original cues, same indexes/timestamps.", flush=True)
    print(f"Japanese draft: {final_file}", flush=True)
    print(f"English source: {english_copy}", flush=True)
    print("Draft only. Not published; Japanese quality and readability need viewing review.", flush=True)


if __name__ == "__main__":
    main()
