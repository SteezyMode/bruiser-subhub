#!/usr/bin/env python3
"""One-off test of Tencent's documented Structured Data 1 template on real SRT.

NOT a subtitle pipeline. Calls the existing Ollama API directly, exactly once.
Prints raw output and checks whether subtitle numbers/timestamps survive.
Never publishes or changes media files.
"""
import json
import re
import subprocess
import urllib.request
from pathlib import Path

VIDEO = Path(
    "/media/bigdisk-video/Television/Serials/The Chair Company/"
    "The.Chair.Company.S01.1080p.AMZN.WEB-DL.H.264-EniaHD/"
    "The.Chair.Company.S01E04.1080p.AMZN.WEB-DL.H.264-EniaHD.mkv"
)
MODEL = "hf.co/tencent/Hy-MT2-7B-GGUF:Q4_K_M"
OUTPUT = Path("/tmp/hy-mt2-structured-srt-30.raw.txt")


def english_srt():
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "s", "-show_entries",
         "stream=index,codec_name:stream_tags=language,title", "-of", "json", str(VIDEO)],
        check=True, capture_output=True, text=True, timeout=45,
    )
    tracks = json.loads(probe.stdout).get("streams", [])
    choices = [
        t for t in tracks
        if t.get("codec_name") == "subrip"
        and t.get("tags", {}).get("language", "").lower() in ("en", "eng")
    ]
    if not choices:
        raise SystemExit("No English SRT track found")
    selected = next(
        (t for t in choices if "sdh" not in t.get("tags", {}).get("title", "").lower()),
        choices[0],
    )
    result = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-i", str(VIDEO),
         "-map", f"0:{selected['index']}", "-f", "srt", "-"],
        capture_output=True, check=True, timeout=180,
    )
    blocks = re.split(r"\n\s*\n", result.stdout.decode("utf-8-sig").replace("\r\n", "\n").strip())
    numbered = [b for b in blocks if re.match(r"^\d+\n\d\d:\d\d:\d\d,\d{3} --> ", b)]
    if len(numbered) < 30:
        raise SystemExit(f"Only {len(numbered)} SRT cues extracted")
    return "\n\n".join(numbered[:30]) + "\n"


def main():
    if OUTPUT.exists():
        raise SystemExit(f"Refusing to overwrite earlier test: {OUTPUT}")
    srt = english_srt()
    # Verbatim English 'Structured Data 1' prompt from Tencent's model card,
    # only substituting format_type=SRT, target_lang=Japanese, source_text=srt.
    prompt = (
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
    request = urllib.request.Request(
        "http://172.17.0.1:11434/api/chat",
        data=json.dumps({
            "model": MODEL, "stream": False,
            "messages": [{"role": "user", "content": prompt}],
            "options": {"temperature": 0.7, "top_p": 0.6,
                        "top_k": 20, "repeat_penalty": 1.05, "num_predict": 4096},
        }).encode(),
        headers={"Content-Type": "application/json"},
    )
    print("Testing Tencent's documented Structured Data 1 prompt with 30 real SRT cues", flush=True)
    with urllib.request.urlopen(request, timeout=1200) as response:
        result = json.load(response)
    answer = (result.get("message") or {}).get("content", "")
    if not answer:
        raise RuntimeError(f"Empty response: {result.get('done_reason')}")
    # Preserve exactly what the model said, even if the structure is wrong.
    with OUTPUT.open("x", encoding="utf-8") as f:
        f.write(answer)
    timestamp_re = r"(?m)^\d\d:\d\d:\d\d,\d{3} --> \d\d:\d\d:\d\d,\d{3}.*$"
    source_times = re.findall(timestamp_re, srt)
    result_times = re.findall(timestamp_re, answer)
    source_numbers = re.findall(r"(?m)^\d+$", srt)
    result_numbers = re.findall(r"(?m)^\d+$", answer)
    print("\n=== RAW MODEL OUTPUT ===\n")
    print(answer)
    print("\n=== STRUCTURE CHECK (NO REPAIR) ===")
    print("Timestamp lines:", len(result_times), "/", len(source_times),
          "| exactly preserved:", result_times == source_times)
    print("Cue numbers:", len(result_numbers), "/", len(source_numbers),
          "| exactly preserved:", result_numbers == source_numbers)
    print("Model finish reason:", result.get("done_reason"))
    print("Saved RAW output:", OUTPUT)
    print("No subtitles published, no service modified.")


if __name__ == "__main__":
    main()
