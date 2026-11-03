#!/usr/bin/env python3
"""One clean, non-publishing comparison: Hy-MT2 7B and TranslateGemma 4B.

Both receive the same 30 consecutive English subtitle cues as one passage.
Each receives ONLY its own documented user prompt, not a homegrown prompt.
No SRT rewriting, line-count policing, retranslation, backtranslation or QA.
"""
import argparse
import datetime
import hashlib
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HY = "hf.co/tencent/Hy-MT2-7B-GGUF:Q4_K_M"
TG = "translategemma:4b"


def api(url, endpoint, payload=None, *, timeout=240):
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url + endpoint,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST" if payload is not None else "GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        message = error.read().decode("utf-8", errors="replace")[:1200]
        raise RuntimeError(f"{endpoint} returned HTTP {error.code}: {message}") from error


def current_ollama_url():
    # Use Sublarr only to read its existing Ollama URL, not to translate.
    from config import get_settings
    settings = get_settings()
    headers = {"X-Api-Key": settings.api_key} if settings.api_key else {}
    request = urllib.request.Request(
        "http://127.0.0.1:5765/api/v1/backends/ollama/config",
        headers=headers,
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        config = json.load(response)
    return (config.get("url") or settings.ollama_url).rstrip("/")


def load_source(path):
    if path.suffix.lower() == ".srt":
        return path.read_text(encoding="utf-8-sig")
    if path.suffix.lower() not in (".mkv", ".mp4", ".m4v"):
        raise ValueError("Input must be .srt, .mkv, .mp4, or .m4v")
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "s",
         "-show_entries", "stream=index,codec_name:stream_tags=language,title",
         "-of", "json", str(path)],
        check=True, capture_output=True, text=True, timeout=40,
    )
    streams = json.loads(probe.stdout).get("streams", [])
    choices = [
        stream for stream in streams
        if stream.get("codec_name") == "subrip"
        and stream.get("tags", {}).get("language", "").lower() in ("en", "eng")
    ]
    if not choices:
        raise ValueError("No embedded English SRT track found")
    track = next(
        (s for s in choices if "sdh" not in s.get("tags", {}).get("title", "").lower()),
        choices[0],
    )
    extracted = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-i", str(path),
         "-map", f"0:{track['index']}", "-f", "srt", "-"],
        check=True, capture_output=True, timeout=180,
    )
    return extracted.stdout.decode("utf-8-sig", errors="replace")


def get_cues(srt, limit):
    cues = []
    for block in re.split(r"\n\s*\n", srt.replace("\r\n", "\n").strip()):
        lines = block.strip().splitlines()
        if lines and lines[0].strip().isdigit():
            lines.pop(0)
        if len(lines) >= 2 and re.match(r"^\d\d:\d\d:\d\d,\d{3} --> ", lines[0]):
            cues.append("\n".join(lines[1:]))
        if len(cues) >= limit:
            break
    if len(cues) < limit:
        raise ValueError(f"Only {len(cues)} valid SRT cues found, need {limit}")
    # This test judges dialogue translation, NOT SRT formatting. Preserve
    # every original word but remove the timestamp metadata for both models.
    return "\n\n".join(cues)


def pull_if_missing(url, tag):
    names = {
        item.get("name") or item.get("model")
        for item in api(url, "/api/tags").get("models", [])
    }
    if tag in names:
        print("Installed model:", tag, flush=True)
        return
    print("Downloading official model:", tag, flush=True)
    request = urllib.request.Request(
        url + "/api/pull",
        data=json.dumps({"model": tag, "stream": True}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    last_percent = -10
    with urllib.request.urlopen(request, timeout=3600) as response:
        for line in response:
            update = json.loads(line)
            if "error" in update:
                raise RuntimeError(update["error"])
            total = update.get("total", 0)
            done = update.get("completed", 0)
            if total:
                percent = int(100 * done / total)
                if percent >= last_percent + 10:
                    print(f"  download {percent}%", flush=True)
                    last_percent = percent
            elif update.get("status") in ("success", "verifying sha256 digest"):
                print(" ", update["status"], flush=True)


def prompt_for(model, passage):
    if model == HY:
        # Exact 'Default Translation' English template on Tencent's model card.
        return (
            "Translate the following text into Japanese. Note that you should "
            "only output the translated result without any additional explanation:\n"
            + passage
        )
    # Exact Ollama TranslateGemma Prompt Guide template, EN -> JA.
    # Two blank lines after the last colon, as explicitly documented.
    return (
        "You are a professional English (en) to Japanese (ja) translator. "
        "Your goal is to accurately convey the meaning and nuances of the original "
        "English text while adhering to Japanese grammar, vocabulary, and cultural sensitivities.\n"
        "Produce only the Japanese translation, without any additional explanations or commentary. "
        "Please translate the following English text into Japanese:\n\n\n"
        + passage
    )


def run_one(url, model, passage):
    pull_if_missing(url, model)
    options = (
        {"temperature": 0.7, "top_p": 0.6, "top_k": 20,
         "repeat_penalty": 1.05, "num_predict": 4096}
        if model == HY else None
    )
    request = {
        "model": model,
        "stream": False,
        "messages": [{"role": "user", "content": prompt_for(model, passage)}],
        "keep_alive": 0,
    }
    if options is not None:
        request["options"] = options
    print(f"\n=== {model} ===", flush=True)
    start = time.monotonic()
    result = api(url, "/api/chat", request, timeout=1800)
    seconds = round(time.monotonic() - start, 1)
    answer = (result.get("message") or {}).get("content", "")
    if not answer:
        raise RuntimeError(f"{model} returned no translation: {result.get('error', 'empty')}")
    print(answer, flush=True)
    print(f"\nElapsed: {seconds}s; finish reason: {result.get('done_reason')}", flush=True)
    return {
        "model": model,
        "prompt": prompt_for(model, passage),
        "response": answer,
        "seconds": seconds,
        "finish_reason": result.get("done_reason"),
        "eval_count": result.get("eval_count"),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument("--model", choices=("hy", "tg", "both"), default="both")
    args = parser.parse_args()
    if args.limit < 1 or not args.source.is_file():
        parser.error("Source must exist and --limit must be positive")
    passage = get_cues(load_source(args.source), args.limit)
    url = current_ollama_url()
    api(url, "/api/tags", timeout=15)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = Path(f"/tmp/subhub-official-model-test-{stamp}.json")
    result = {
        "source": str(args.source),
        "cues": args.limit,
        "source_sha256": hashlib.sha256(passage.encode()).hexdigest(),
        "source_passage": passage,
        "models": [],
    }
    print(f"Same source for both models: {args.limit} consecutive cues", flush=True)
    print(f"Source SHA256: {result['source_sha256']}", flush=True)
    chosen = {"hy": [HY], "tg": [TG], "both": [HY, TG]}[args.model]
    try:
        for model in chosen:
            result["models"].append(run_one(url, model, passage))
    finally:
        out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
        print(f"\nSaved raw comparison: {out}", flush=True)


if __name__ == "__main__":
    main()
