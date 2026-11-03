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
    """Find an adjacent English SRT, including Jellyfin 'Undefined' sidecars.

    No changes to the translation model or its output. We only identify
    the existing English-language input. Refuse ambiguous sources.
    """
    dirs = [video.parent]
    dirs.extend(p for p in video.parent.iterdir()
                if p.is_dir() and p.name.lower() in ("subs", "subtitles"))
    paths = sorted(set(p for folder in dirs for p in folder.iterdir()
                       if p.is_file() and p.suffix.lower() == ".srt"))
    print("\nExternal SRT files visible in the movie folder:", flush=True)
    for p in paths:
        print(" ", p, flush=True)
    if not paths:
        print("  NONE VISIBLE in Sublarr's mounted media directory", flush=True)
        return None

    english_marker = re.compile(r"(?:^|[._ \-])(en|eng|english)(?:[._ \-]|$)", re.I)
    other_lang = re.compile(
        r"(?:^|[._ \-])(ja|jp|jpn|japanese|es|spa|spanish|fr|fre|french|"
        r"de|ger|german|pt|por|portuguese|ko|kor|korean|zh|chi|chinese|"
        r"ru|rus|russian|it|ita|italian)(?:[._ \-]|$)", re.I
    )

    eligible = []
    for p in paths:
        if other_lang.search(p.stem) and not english_marker.search(p.stem):
            continue
        # Examine only input-language plausibility; do NOT rewrite text.
        sample = p.read_text(encoding="utf-8-sig", errors="replace")[:12000]
        dialogue = "\n".join(
            line for line in sample.splitlines()
            if not line.strip().isdigit()
            and "-->" not in line
            and not line.strip().startswith(("NOTE ", "WEBVTT"))
        )
        tokens = re.findall(r"[A-Za-z]+(?:'[A-Za-z]+)?", dialogue)
        english_words = sum(
            word.lower() in {
                "the", "you", "your", "are", "is", "that", "what", "why",
                "have", "will", "with", "this", "they", "he", "she", "we",
                "and", "but", "don't", "not", "can", "did", "was", "it's",
                "for", "know", "just", "want", "how", "where", "there",
            }
            for word in tokens
        )
        plausible_english = len(tokens) >= 20 and english_words >= 5
        print(
            f"  Language check: {p.name}: {len(tokens)} Latin words, "
            f"{english_words} common English tokens; "
            f"{'English plausible' if plausible_english else 'not verified'}",
            flush=True
        )
        if plausible_english:
            eligible.append(p)
    if not eligible:
        raise RuntimeError("Found external SRT files but couldn't confirm English content.")

    # An 'Undefined' sidecar often simply has the video's exact filename
    # plus .srt, with no language suffix. Prefer that exact match.
    exact = [p for p in eligible if p.parent == video.parent
             and p.stem.casefold() == video.stem.casefold()]
    if len(exact) == 1:
        selected = exact[0]
    else:
        marked = [p for p in eligible if english_marker.search(p.stem)]
        if len(marked) == 1:
            selected = marked[0]
        elif len(eligible) == 1:
            selected = eligible[0]
        else:
            raise RuntimeError(
                "Multiple plausible English SRT files; refusing to choose "
                "an ambiguous source automatically: " +
                ", ".join(str(p) for p in eligible)
            )

    print("Selected English SRT:", selected, flush=True)
    print("Subtitle preview (source input, unchanged):", flush=True)
    print(selected.read_text(encoding="utf-8-sig", errors="replace")[:500], flush=True)
    return selected

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
        print("English source: external SRT:", sidecar, flush=True)
        return sidecar
    raise RuntimeError(
        "FILM FOUND but no English text SRT is accessible in Sublarr's video folder. "
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
