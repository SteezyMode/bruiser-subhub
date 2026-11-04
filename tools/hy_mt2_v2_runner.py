#!/usr/bin/env python3
"""SubHub v2: documented Hy-MT2 full-SRT runner, with singleton FORMAT recovery.

Translation uses ONE Ollama /api/chat call per consecutive 30-cue section, 
with source-anchored smaller groups only for structurally failing sections.
Exactly the model-card prompt and sampling parameters used in the successful
2026-11-03 30-cue test. NO system prompt, other models, or rewrite. Structural failures are retried in smaller groups.

Only mechanical file work: read English SRT, split, preserve raw replies,
verify numbering/timing, assemble separate draft. Never publishes to Jellyfin.
"""
import argparse
import fcntl
import hashlib
import json
import os
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


def translate(url, srt, full_gpu=False):
    # Explicit layer residency, independent of the documented translation knobs.
    options = dict(OPTIONS)
    if full_gpu:
        options.update({"num_gpu": 99, "num_ctx": 4096})
    req = urllib.request.Request(
        url + "/api/chat",
        data=json.dumps({
            "model": MODEL, "stream": False,
            "messages": [{"role": "user", "content": official_prompt(srt)}],
            "options": options,
        }).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=1800) as response:
        reply = json.load(response)
    return (reply.get("message") or {}).get("content", ""), reply.get("done_reason")


def normalize_timestamp_punctuation(source_cues, generated):
    """Remove ONLY a stray > following an EXACT source timestamp.

    This is mechanical SRT syntax repair; never inspect, rewrite or filter
    Japanese, and retain raw model responses in part-XXXX.raw.txt.
    Any other difference, missing cue, or malformed timestamp still fails.
    """
    original_timestamps = {timestamp for _, timestamp, _ in source_cues}
    corrected = []
    count = 0
    for line in generated.splitlines(keepends=True):
        value = line.rstrip("\r\n")
        ending = line[len(value):]
        if value.endswith(">") and value[:-1] in original_timestamps:
            value = value[:-1]
            count += 1
        corrected.append(value + ending)
    return "".join(corrected), count


def compare_structure(source_cues, generated):
    """Recover ONLY missing blank lines between complete, ordered SRT cues.

    Read exact original cue IDs/timestamps as boundaries rather than assuming
    the model remembered double newlines. Keep Japanese text verbatim.
    Missing/empty/out-of-order cues and timestamps always fail.
    """
    lines = generated.replace("\r\n", "\n").lstrip("\ufeff").split("\n")
    cursor = 0
    result = []
    for index, (number, timestamp, _) in enumerate(source_cues):
        while cursor < len(lines) and not lines[cursor].strip():
            cursor += 1
        if cursor >= len(lines) or lines[cursor].strip() != number:
            actual = lines[cursor][:90] if cursor < len(lines) else "<end of response>"
            raise ValueError(f"Cue {number}: expected original ID; found {actual!r}")
        cursor += 1
        if cursor >= len(lines) or lines[cursor].strip() not in (
            timestamp, timestamp + ">"
        ):
            actual = lines[cursor][:90] if cursor < len(lines) else "<end of response>"
            raise ValueError(
                f"Cue {number}: timestamp mismatch. Expected {timestamp!r}, got {actual!r}"
            )
        cursor += 1
        first = cursor
        if index + 1 < len(source_cues):
            next_number, next_timestamp, _ = source_cues[index + 1]
            while cursor < len(lines):
                if (
                    lines[cursor].strip() == next_number
                    and cursor + 1 < len(lines)
                    and lines[cursor + 1].strip() in (
                        next_timestamp, next_timestamp + ">"
                    )
                ):
                    break
                cursor += 1
        else:
            cursor = len(lines)
        dialogue_lines = lines[first:cursor]
        while dialogue_lines and not dialogue_lines[0].strip():
            dialogue_lines.pop(0)
        while dialogue_lines and not dialogue_lines[-1].strip():
            dialogue_lines.pop()
        if not dialogue_lines:
            raise ValueError(
                f"Cue {number}: no Japanese text; preserving raw output for review"
            )
        # Reject unexpected SRT-like headers in dialogue, instead of silently
        # merging missing or out-of-order subtitles into other cues.
        for a, b in zip(dialogue_lines, dialogue_lines[1:]):
            if a.strip().isdigit() and re.fullmatch(TIMESTAMP + r">?", b.strip()):
                raise ValueError(
                    f"Cue {number}: unexpected nested cue {a.strip()}; cannot safely align"
                )
        result.append((number, timestamp, "\n".join(dialogue_lines)))
    if any(line.strip() for line in lines[cursor:]):
        raise ValueError("Unexpected output after last original cue")
    return result


def new_text(path, content):
    with path.open("x", encoding="utf-8") as f:
        f.write(content)


def save_verified_preview(workdir, completed):
    """Assemble only verified sections into a watchable partial SRT.

    Does not alter Japanese or overwrite any media/library files.
    """
    target = workdir / "verified-so-far.ja.srt"
    staging = workdir / "verified-so-far.ja.srt.tmp"
    staging.write_text(as_srt(completed), encoding="utf-8")
    os.replace(staging, target)


def wrap_plain_japanese_singleton(chunk, generated):
    """Restore only the SRT container for one model-produced Japanese utterance.

    Some single-cue calls ignore SRT framing and return just Japanese text.
    Preserve that output verbatim and reuse the exact source cue ID/timestamp.
    This is a format rescue, NOT translation repair or a quality judgment.
    Only clean, short Japanese text qualifies; any ambiguous reply is held.
    """
    if len(chunk) != 1:
        return None
    body = generated.strip()
    if not body or len(body) > 160 or len(body.splitlines()) > 2:
        return None
    if "\n\n" in body or "\r" in body or "```" in body or "-->" in body:
        return None
    if re.search(r"(?m)^\s*\d+\s*$", body):
        return None
    if re.search(r"[A-Za-z]{3,}", body):
        return None
    if not re.search(r"[\u3040-\u30ff\u3400-\u9fff]", body):
        return None
    number, timestamp, _ = chunk[0]
    return [(number, timestamp, body)]


def run_verified_segment(chunk, url, workdir, name, full_gpu):
    """Reuse, translate, or safely subdivide a structurally broken segment.

    Every output cue is checked against original English IDs/timestamps. Never
    infer missing Japanese, rewrite dialogue, overwrite existing raw responses,
    or repeat completed segments. Fallback changes ONLY the number of cues per
    request, not the translation prompt, model, or sampling settings.
    """
    raw_file = workdir / f"{name}.raw.txt"
    verified_file = workdir / f"{name}.ja.srt"

    if verified_file.exists():
        parsed = compare_structure(chunk, verified_file.read_text(encoding="utf-8"))
        print(f"  Reusing {name}: {len(parsed)} verified cues", flush=True)
        return parsed

    reason = None
    elapsed = None
    if raw_file.exists():
        generated = raw_file.read_text(encoding="utf-8")
        finish_reason = "stop"  # Existing raw responses were saved before validation.
        print(f"  Inspecting saved {name} response", flush=True)
    else:
        print(f"  Translating {name} (cues {chunk[0][0]}–{chunk[-1][0]})", flush=True)
        started = time.monotonic()
        generated, finish_reason = translate(url, as_srt(chunk), full_gpu=full_gpu)
        elapsed = round(time.monotonic() - started, 1)
        new_text(raw_file, generated)

    if finish_reason == "stop":
        try:
            parsed = compare_structure(chunk, generated)
        except ValueError as exc:
            reason = str(exc)
        else:
            new_text(verified_file, as_srt(parsed))
            suffix = f"; {elapsed}s" if elapsed is not None else " (saved response)"
            print(f"  Verified {name}: {len(parsed)}/{len(chunk)} cues{suffix}", flush=True)
            return parsed
    else:
        reason = f"model finish reason {finish_reason!r}"

    # A 30-cue model reply can omit or merge an SRT header. Re-translate only
    # that section in smaller groups, keeping the original failed raw file.
    if len(chunk) == 1:
        # The original prompt/model/options are unchanged. If a single-cue
        # request returned ONLY a clean Japanese utterance, restore its exact
        # source SRT ID/time without changing Japanese text or calling a model.
        wrapped = wrap_plain_japanese_singleton(chunk, generated) if finish_reason == "stop" else None
        if wrapped:
            new_text(verified_file, as_srt(wrapped))
            print(f"  FORMAT-ONLY rescue {name}: wrapped plain Japanese; semantic quality unverified", flush=True)
            return wrapped
        # A single punctuation/formatting slip must not kill a long film run.
        # Retain every raw reply and allow at most three fresh attempts.
        for attempt in range(1, 4):
            retry_file = workdir / f"{name}.retry-{attempt:02}.raw.txt"
            if retry_file.exists():
                retry_response = retry_file.read_text(encoding="utf-8")
                retry_finish = "stop"
            else:
                print(
                    f"  Retry cue {chunk[0][0]} ({attempt}/3), same prompt/model/options",
                    flush=True,
                )
                retry_response, retry_finish = translate(
                    url, as_srt(chunk), full_gpu=full_gpu
                )
                new_text(retry_file, retry_response)
            if retry_finish != "stop":
                continue
            try:
                parsed = compare_structure(chunk, retry_response)
            except ValueError as exc:
                reason = str(exc)
                wrapped = wrap_plain_japanese_singleton(chunk, retry_response)
                if wrapped:
                    new_text(verified_file, as_srt(wrapped))
                    print(f"  FORMAT-ONLY rescue {name} from {retry_file.name}: semantic quality unverified", flush=True)
                    return wrapped
            else:
                new_text(verified_file, as_srt(parsed))
                print(f"  Verified singleton cue {chunk[0][0]}", flush=True)
                return parsed
        raise SystemExit(
            f"Unable to verify single cue {chunk[0][0]} in {name}: {reason}. "
            f"All raw replies preserved; last attempt {retry_file}."
        )

    subsize = 10 if len(chunk) > 10 else (5 if len(chunk) > 5 else
              (2 if len(chunk) > 2 else 1))
    print(
        f"  {name}: structural mismatch ({reason}); "
        f"retrying this segment as {subsize}-cue groups",
        flush=True,
    )
    repaired = []
    for offset in range(0, len(chunk), subsize):
        subchunk = chunk[offset:offset + subsize]
        subname = f"{name}.c{subchunk[0][0]}-{subchunk[-1][0]}"
        repaired.extend(run_verified_segment(
            subchunk, url, workdir, subname, full_gpu
        ))
    if len(repaired) != len(chunk):
        raise SystemExit(f"Internal repair cue-count mismatch in {name}")
    # One final strict check across the repaired combined segment.
    parsed = compare_structure(chunk, as_srt(repaired))
    new_text(verified_file, as_srt(parsed))
    print(f"  Repaired and verified {name}: {len(parsed)} cues", flush=True)
    return parsed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--batch-size", type=int, default=30)
    parser.add_argument("--full-gpu", action="store_true", help="Force 99 GPU layers at the existing 4096-token context; does not change translation sampling")
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
    if args.full_gpu:
        print("GPU placement: requesting all layers (num_gpu=99, num_ctx=4096); translation settings unchanged", flush=True)
    print(f"Model: {MODEL}\nOllama: {url}\nSource cues: {len(source_cues)}",
          f"\nBatch size: {args.batch_size}\nWorkdir: {workdir}", flush=True)
    chunks = [
        source_cues[offset:offset + args.batch_size]
        for offset in range(0, len(source_cues), args.batch_size)
    ]
    completed = []
    for index, chunk in enumerate(chunks, start=1):
        chunk_name = f"part-{index:04d}"
        verified_file = workdir / f"{chunk_name}.ja.srt"
        if verified_file.exists():
            parsed = compare_structure(
                chunk, verified_file.read_text(encoding="utf-8")
            )
            print(
                f"[{index}/{len(chunks)}] Reusing verified segment "
                f"({len(parsed)} cues)", flush=True
            )
        else:
            print(
                f"[{index}/{len(chunks)}] Processing cues "
                f"{chunk[0][0]}–{chunk[-1][0]}", flush=True
            )
            parsed = run_verified_segment(
                chunk, url, workdir, chunk_name, args.full_gpu
            )
        completed.extend(parsed)
        save_verified_preview(workdir, completed)
        print(
            f"  Progress: {len(completed)}/{len(source_cues)} verified; "
            f"saved {workdir / 'verified-so-far.ja.srt'}", flush=True
        )
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
