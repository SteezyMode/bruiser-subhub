#!/usr/bin/env python3
"""Direct EN->JA SRT translation using the model author's subtitle prompt format.

No Sublarr translation logic, QA, rewriting, retries, or media-file modifications.
Run in the existing sublarr-pilot container, which has ffprobe/ffmpeg and Ollama access.
"""
import argparse
import json
import re
import subprocess
import urllib.request
from pathlib import Path

MODEL = "hf.co/17slever17/translate-gemma-4-sub-e4b-GGUF:Q4_K_XL"
SYSTEM = (
    "TASK: Translate English subtitles into Japanese.\n"
    "STYLE: neutral.\n"
    "Translate only CURRENT_SOURCE. PREVIOUS_SOURCE and PREVIOUS_TRANSLATION are context only. "
    "Preserve meaning, tone, slang, profanity, uncertainty, repetitions and incomplete speech. "
    "Return only the final translation without labels or commentary."
)


def read_srt(source):
    if source.suffix.lower() == ".srt":
        return source.read_text(encoding="utf-8-sig")
    if source.suffix.lower() not in (".mkv", ".mp4", ".m4v"):
        raise ValueError("Supply a .srt or a video with embedded English SRT subtitles")
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "s", "-show_entries",
         "stream=index,codec_name:stream_tags=language,title", "-of", "json", str(source)],
        capture_output=True, text=True, check=True, timeout=45,
    )
    tracks = json.loads(probe.stdout).get("streams", [])
    english = [t for t in tracks if t.get("codec_name") == "subrip" and
               t.get("tags", {}).get("language", "").lower() in ("en", "eng")]
    if not english:
        raise ValueError("No embedded English text SRT track in video")
    chosen = next((t for t in english if "sdh" not in
                   t.get("tags", {}).get("title", "").lower()), english[0])
    extracted = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-i", str(source), "-map",
         f"0:{chosen['index']}", "-f", "srt", "-"],
        capture_output=True, check=True, timeout=180,
    )
    return extracted.stdout.decode("utf-8-sig", errors="replace")


def split_srt(data):
    cues = []
    for block in re.split(r"\n\s*\n", data.replace("\r\n", "\n").strip()):
        lines = block.strip().splitlines()
        if lines and lines[0].strip().isdigit():
            lines.pop(0)
        if len(lines) >= 2 and re.match(r"^\d\d:\d\d:\d\d,\d{3} --> ", lines[0]):
            cues.append((lines[0], "\n".join(lines[1:]).strip()))
    if not cues:
        raise ValueError("No SRT cues found")
    return cues


def ask_ollama(url, model, source, previous_source, previous_translation):
    content = ""
    if previous_source:
        content += (f"[PREVIOUS_SOURCE]\n{previous_source}\n\n"
                    f"[PREVIOUS_TRANSLATION]\n{previous_translation}\n\n")
    content += f"[CURRENT_SOURCE]\n{source}"
    request = urllib.request.Request(
        url.rstrip("/") + "/api/chat",
        data=json.dumps({
            "model": model, "stream": False,
            "messages": [{"role": "system", "content": SYSTEM},
                         {"role": "user", "content": content}],
            "options": {"temperature": 0, "num_predict": 256, "num_ctx": 1344},
        }).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=240) as response:
        result = json.load(response)
    return (result.get("message") or {}).get("content", "").strip()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("source", type=Path, help="English .srt or video containing an English SRT track")
    p.add_argument("--output", type=Path, help="New Japanese .srt path (default: /tmp/<name>.ja.srt)")
    p.add_argument("--limit", type=int, help="Translate first N cues (quick quality sample)")
    p.add_argument("--ollama-url", help="Existing Ollama API URL; defaults to Sublarr connection")
    p.add_argument("--model", default=MODEL)
    a = p.parse_args()
    if not a.source.is_file():
        p.error("Source file not found")
    if a.limit is not None and a.limit < 1:
        p.error("--limit must be positive")
    output = a.output or (Path("/tmp") / (a.source.stem + ".ja.srt"))
    if output.exists():
        p.error(f"Refusing to replace existing file: {output}")
    # Sublarr keeps the active Ollama backend URL in its DB, which can differ
    # from the static OLLAMA_URL setting. Read the URL only, not its translation logic.
    from config import get_settings
    if a.ollama_url:
        url = a.ollama_url
    else:
        settings = get_settings()
        headers = {"X-Api-Key": settings.api_key} if settings.api_key else {}
        req = urllib.request.Request(
            "http://127.0.0.1:5765/api/v1/backends/ollama/config", headers=headers
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                backend_config = json.load(response)
        except Exception as exc:
            raise RuntimeError("Cannot read configured Ollama backend URL from Sublarr") from exc
        url = backend_config.get("url") or settings.ollama_url
    url = url.rstrip("/")
    print("Ollama endpoint:", url, flush=True)
    try:
        with urllib.request.urlopen(url + "/api/tags", timeout=10) as response:
            json.load(response)
    except Exception as exc:
        raise RuntimeError(f"Ollama is unreachable at {url}; translation not started") from exc
    cues = split_srt(read_srt(a.source))
    if a.limit:
        cues = cues[:a.limit]
    print(f"Source: {a.source}\nModel: {a.model}\nCues: {len(cues)}\nOutput: {output}", flush=True)
    translated = []
    prev_en = prev_ja = ""
    for n, (timing, english) in enumerate(cues, start=1):
        japanese = ask_ollama(url, a.model, english, prev_en, prev_ja)
        if not japanese:
            raise RuntimeError(f"Empty model output at cue {n}; no retry or replacement performed")
        translated.append(f"{n}\n{timing}\n{japanese}\n")
        print(f"{n}/{len(cues)} EN: {english.replace(chr(10), ' / ')}\n"
              f"      JA: {japanese.replace(chr(10), ' / ')}", flush=True)
        prev_en, prev_ja = english, japanese
    output.write_text("\n".join(translated) + "\n", encoding="utf-8")
    print(f"\nCreated {output} -- original media and subtitles untouched", flush=True)


if __name__ == "__main__":
    main()
