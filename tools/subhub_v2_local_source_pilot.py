#!/usr/bin/env python3
"""One-film local English-subtitle source selector and v2 draft-only translator.

This is a transition pilot, NOT a replacement for Sublarr provider acquisition.
Discover existing source tracks (explicit English, embedded English, or plain
release-matched .srt). Preserve source, media, and existing JA. No publishing.
"""
import argparse
import importlib.util
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOTS = (
    Path("/mnt/2TB/Plex Expansion/Movies/Horror"),
    Path("/mnt/BigDisk/Video/Movies/Horror"),
)
VIDEO_EXT = {".mkv", ".mp4", ".m4v"}
TEXT_CODECS = {"subrip", "mov_text", "ass", "ssa", "webvtt", "text"}
LANG_EN = {"en", "eng", "english", "en-us", "en-gb"}
LANG_JA = {"ja", "jp", "jpn", "japanese"}
MIN_CUES = 350
MAX_CUES = 1800


def lang(value):
    return str(value or "").casefold().replace("_", "-")


def check_english(cues):
    """Conservative language check, not a linguistic quality score."""
    dialogue = [
        text for _, _, text in cues
        if not re.fullmatch(r"\s*[\[({].*?[\])}]\s*", text, re.DOTALL)
    ]
    sample = dialogue[:100]
    if len(sample) < 50:
        return False
    good = sum(
        bool(re.search(r"[A-Za-z]{2,}", text))
        and not bool(re.search(r"[\u3040-\u30ff\u3400-\u9fff]", text))
        for text in sample
    )
    return good / len(sample) >= 0.80


def probe(path):
    try:
        proc = subprocess.run([
            "ffprobe", "-v", "error", "-show_entries",
            "stream=index,codec_name,codec_type:stream_tags=language,title:format=duration",
            "-of", "json", str(path)
        ], check=True, capture_output=True, text=True, timeout=30)
        return json.loads(proc.stdout)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, ValueError, OSError):
        return None


def has_japanese_stream(probe_data):
    if not probe_data:
        return False
    for s in probe_data.get("streams", []):
        if s.get("codec_type") != "subtitle":
            continue
        tags = {str(k).casefold(): str(v) for k, v in s.get("tags", {}).items()}
        if lang(tags.get("language")) in LANG_JA:
            return True
        if "japanese" in tags.get("title", "").casefold() or "日本語" in tags.get("title", ""):
            return True
    return False


def english_embedded_tracks(probe_data):
    if not probe_data:
        return []
    out = []
    for s in probe_data.get("streams", []):
        if s.get("codec_type") != "subtitle":
            continue
        if s.get("codec_name") not in TEXT_CODECS:
            continue
        tags = {str(k).casefold(): str(v) for k, v in s.get("tags", {}).items()}
        language = lang(tags.get("language"))
        title = tags.get("title", "").casefold()
        if language not in LANG_EN and "english" not in title:
            continue
        if "forced" in title:
            continue
        out.append((int(s["index"]), str(s["codec_name"])))
    return out


def matched_sidecars(video):
    # Do not treat unrelated files in the same folder as this video's source.
    for path in sorted(video.parent.iterdir()):
        if not path.is_file() or path.suffix.casefold() != ".srt":
            continue
        if path.name == video.stem + ".srt":
            yield path, "unmarked"
            continue
        if not path.name.startswith(video.stem + "."):
            continue
        suffix = path.name[len(video.stem) + 1:-4].lower()
        segments = set(re.split(r"[.\-_ ]+", suffix))
        if segments & LANG_JA or "japanese" in suffix:
            continue
        if segments & {"en", "eng", "english"}:
            yield path, "explicit-en"


def extract_embedded(video, index, output):
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=output.parent, prefix="extract-", suffix=".srt", delete=False
    ) as file:
        temp = Path(file.name)
    try:
        subprocess.run([
            "ffmpeg", "-nostdin", "-v", "error", "-y",
            "-i", str(video), "-map", f"0:{index}",
            "-f", "srt", str(temp),
        ], check=True, capture_output=True, timeout=180)
        return temp
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        temp.unlink(missing_ok=True)
        return None


def find_movies(roots):
    seen = set()
    for root in roots:
        if not root.is_dir():
            print(f"SKIP: root unavailable: {root}", flush=True)
            continue
        for video in sorted(
            (v for v in root.rglob("*") if v.is_file() and v.suffix.lower() in VIDEO_EXT),
            key=lambda p: str(p).casefold(),
        ):
            if video in seen:
                continue
            seen.add(video)
            if "the descent part 2" in video.name.casefold():
                continue
            yield video


def select(bridge, roots, state, scan_limit=500):
    import hashlib
    inspected = 0
    for video in find_movies(roots):
        if inspected >= scan_limit:
            print(f"Reached {scan_limit} video probes.", flush=True)
            break
        if bridge.japanese_sidecars(video):
            continue
        inspected += 1
        data = probe(video)
        if not data or has_japanese_stream(data):
            continue
        streams = data.get("streams", [])
        audio = [
            lang(s.get("tags", {}).get("language", ""))
            for s in streams if s.get("codec_type") == "audio"
        ]
        if audio and all(l and l not in LANG_EN and l != "und" for l in audio):
            continue

        suggestions = list(matched_sidecars(video))
        suggestions.sort(key=lambda s: (s[1] != "explicit-en", str(s[0])))
        for path, flavor in suggestions:
            try:
                cues = bridge.read_srt(path)
                if not MIN_CUES <= len(cues) <= MAX_CUES or not check_english(cues):
                    continue
            except (OSError, UnicodeError, ValueError):
                continue
            print(f"SELECTED existing {flavor} SRT: {len(cues)} cues", flush=True)
            return video, path

        for index, codec in english_embedded_tracks(data):
            identity = hashlib.sha256(
                (str(video) + str(index) + str(video.stat().st_mtime_ns)).encode()
            ).hexdigest()[:18]
            output = state / "sources" / (identity + ".en.srt")
            if output.exists():
                try:
                    cues = bridge.read_srt(output)
                    if MIN_CUES <= len(cues) <= MAX_CUES and check_english(cues):
                        print(f"SELECTED saved embedded English source: {len(cues)} cues", flush=True)
                        return video, output
                except (OSError, UnicodeError, ValueError):
                    pass
            extracted = extract_embedded(video, index, output)
            if not extracted:
                continue
            try:
                cues = bridge.read_srt(extracted)
                if not MIN_CUES <= len(cues) <= MAX_CUES or not check_english(cues):
                    continue
                output.parent.mkdir(parents=True, exist_ok=True)
                if not output.exists():
                    # Source is generated outside the media folder; never overwrite.
                    try:
                        extracted.rename(output)
                    except FileExistsError:
                        pass
                print(f"SELECTED embedded English ({codec}): {len(cues)} cues", flush=True)
                return video, output
            except (OSError, UnicodeError, ValueError):
                continue
            finally:
                extracted.unlink(missing_ok=True)
    print(f"No eligible local source among {inspected} inspected videos.", flush=True)
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bridge", type=Path, required=True)
    parser.add_argument("--state", type=Path, default=Path.home() / "bruiser-pilot/subhub-v2")
    parser.add_argument("--scan-limit", type=int, default=500)
    parser.add_argument("--select-only", action="store_true")
    args = parser.parse_args()
    if args.scan_limit < 1:
        parser.error("scan-limit must be positive")
    module = importlib.util.spec_from_file_location("subhub_bridge", args.bridge)
    bridge = importlib.util.module_from_spec(module)
    module.loader.exec_module(bridge)
    picked = select(bridge, ROOTS, args.state, args.scan_limit)
    if picked is None:
        print("No video or subtitle was modified. Provider acquisition remains the next fallback.", flush=True)
        return 2
    video, english = picked
    print("MOVIE:", video, flush=True)
    print("ENGLISH:", english, flush=True)
    if args.select_only:
        print("Selection only; no translation or publishing.", flush=True)
        return 0
    print("Starting the existing SubHub v2 Hy-MT2 translator; DRAFT ONLY.", flush=True)
    subprocess.run([
        sys.executable, "-u", str(args.bridge),
        "--video", str(video), "--english", str(english),
        "--state", str(args.state),
    ], check=True)
    print("COMPLETE: Japanese draft ready. Nothing published.", flush=True)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, subprocess.CalledProcessError) as e:
        raise SystemExit(f"Source selection/translation failed safely: {e}") from e
