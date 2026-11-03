#!/usr/bin/env python3
"""Find The Descent: Part 2 (2009) in existing Sublarr mounts and translate it.

Only source discovery and a call to the existing, documented Hy-MT2 SRT runner.
Never changes model, prompt, generation options, Japanese, Jellyfin or video.
If English text subtitles are absent, prints available tracks and exits clearly.
"""
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOTS = (Path("/media/bigdisk-video"), Path("/media/expansion-video"))
VIDEO_EXTENSIONS = {".mkv", ".mp4", ".m4v"}
WORKDIR = Path("/tmp/subhub-hy7-descent-part2")
TRANSLATOR = Path("/tmp/subhub_hy_mt2_descent_runner.py")


def is_descent_part2(path):
    # Restrict detection to filename and immediate containing folder.
    title = " ".join((path.name, path.parent.name))
    norm = re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()
    if "descent" not in norm or "2005" in norm:
        return False
    return (
        bool(re.search(r"\bdescent\s+(?:part\s+)?2\b", norm))
        or bool(re.search(r"\bdescent\b.*\b2009\b", norm))
    )


def find_movie():
    found = []
    for root in ROOTS:
        if not root.is_dir():
            print("Mount not present:", root, flush=True)
            continue
        print("Scanning filenames under:", root, flush=True)
        for base, _, filenames in os.walk(root):
            for name in filenames:
                path = Path(base) / name
                if path.suffix.lower() in VIDEO_EXTENSIONS and is_descent_part2(path):
                    found.append(path)
    # Avoid duplicate mount points and duplicated matches from paths.
    movies = sorted({str(p.resolve()): p for p in found}.values())
    if not movies:
        raise RuntimeError(
            "The Descent Part 2 (2009) wasn't found by filename/folder under the "
            "two known media mounts. No source changed."
        )
    print("\nFilm candidates:", flush=True)
    for p in movies:
        print(" ", p, flush=True)
    # Multiple editions of the SAME title: prefer larger main video,
    # and show the actual selection. No media is overwritten or published.
    choice = max(movies, key=lambda p: p.stat().st_size)
    print("Selected largest candidate:", choice, flush=True)
    return choice


def find_english_sidecar(video):
    paths = list(video.parent.glob("*.srt"))
    for sub in ("Subs", "subs", "Subtitles", "subtitles"):
        if (video.parent / sub).is_dir():
            paths.extend((video.parent / sub).glob("*.srt"))
    english_marker = re.compile(r"(?:^|[._ \-])(en|eng|english)(?:[._ \-]|$)", re.I)
    candidates = [p for p in paths if english_marker.search(p.stem)]
    # Do not guess that an unmarked .srt is English.
    if not candidates:
        return None
    # Prefer title-matched sidecars over unrelated files.
    def score(p):
        is_exact = p.stem.lower().startswith(video.stem.lower() + ".")
        is_named = bool(re.search(r"(?:^|[._ \-])english(?:[._ \-]|$)", p.stem, re.I))
        is_sdh = "sdh" in p.stem.lower() or "hi" in p.stem.lower().split(".")
        return (is_exact, is_named, not is_sdh)
    matches = sorted(candidates, key=score, reverse=True)
    print("English-named sidecars:", *map(str, matches), sep="\n  ", flush=True)
    return matches[0]


def inspect_streams(video):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "s",
         "-show_entries", "stream=index,codec_name:stream_tags=language,title",
         "-of", "json", str(video)],
        check=True, capture_output=True, text=True, timeout=120
    )
    streams = json.loads(out.stdout).get("streams", [])
    print("\nEmbedded subtitle streams:", flush=True)
    if not streams:
        print("  none", flush=True)
    for s in streams:
        print(
            f"  #{s.get('index')} {s.get('codec_name')} "
            f"language={s.get('tags', {}).get('language', '?')} "
            f"title={s.get('tags', {}).get('title', '?')}", flush=True
        )
    return streams


def source_for(video):
    streams = inspect_streams(video)
    en = [
        s for s in streams if s.get("codec_name") == "subrip"
        and s.get("tags", {}).get("language", "").lower() in ("en", "eng")
    ]
    if en:
        print("English source: embedded SubRip track.", flush=True)
        return video
    sidecar = find_english_sidecar(video)
    if sidecar:
        print("English source: named external SRT:", sidecar, flush=True)
        return sidecar
    raise RuntimeError(
        "FILM FOUND but no identified English TEXT SRT track or sidecar. "
        "If an English PGS subtitle is listed, it needs OCR first; "
        "do not feed picture subtitles to a text model. "
        "No translation was started or existing media changed."
    )


def main():
    if not TRANSLATOR.is_file():
        raise RuntimeError(f"Translation runner missing: {TRANSLATOR}")
    movie = find_movie()
    source = source_for(movie)
    spec = importlib.util.spec_from_file_location("hy7_descent_runner", TRANSLATOR)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    print("\n=== BEGIN Hy-MT2 7B (same model, same official prompt/settings) ===", flush=True)
    print("Target:", movie, flush=True)
    print("Source:", source, flush=True)
    print("Draft only: ", WORKDIR / "full-episode.draft.ja.srt", flush=True)
    print("Raw model outputs remain separate from mechanically validated SRTs.", flush=True)
    sys.argv = [
        str(TRANSLATOR), str(source), "--workdir", str(WORKDIR),
        "--batch-size", "30"
    ]
    module.main()


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"\nSTOPPED: {error}", file=sys.stderr, flush=True)
        sys.exit(1)
