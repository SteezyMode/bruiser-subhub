#!/usr/bin/env python3
"""Stage a pinned, previously verified Japanese S01E01 subtitle into /tmp only.

This intentionally avoids a fresh provider search, because the search endpoint
can intermittently omit a candidate that was validated in a previous response.

The OpenSubtitles API key is supplied via SUBHUB_OS_API_KEY in the executing
container, never committed. One download may consume one account allowance.

No changes to Jellyfin, Sublarr configuration, media-library files, database,
scan schedules, auto-publishing, or translation jobs.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from providers.base import SubtitleFormat, SubtitleResult
from providers.opensubtitles import OpenSubtitlesProvider

SUBTITLE_ID = "8498498"
NAME = "Its.Always.Sunny.in.Philadelphia.S01E01.WEB-DL.DSNP.ja"
SCRATCH = Path("/tmp/bruiser-subhub-v2-ja-first")


def inspect_content(content: bytes) -> tuple[str, str]:
    if not content or len(content) > 2_000_000:
        raise RuntimeError("Subtitle is empty or exceeds the 2 MB pilot limit")

    for encoding in ("utf-8-sig", "utf-16", "cp932", "shift_jis"):
        try:
            text = content.decode(encoding)
        except UnicodeError:
            continue
        srt_cues = len(
            re.findall(r"\d{2}:\d{2}:\d{2}[,.]\d{3}\s*-->", text)
        )
        ass_cues = len(re.findall(r"(?m)^Dialogue:\s*", text))
        if max(srt_cues, ass_cues) < 20:
            continue
        ja = len(re.findall(r"[\u3040-\u30ff\u3400-\u9fff]", text))
        if ja < 50:
            raise RuntimeError("Too few Japanese characters in the subtitle")
        fmt = "srt" if srt_cues else "ass"
        print(
            "Content: %d bytes | encoding: %s | %s cues: %d | JA chars: %d"
            % (len(content), encoding, fmt.upper(), max(srt_cues, ass_cues), ja),
            flush=True,
        )
        # Small, informative preview without copying whole subtitle.
        preview = []
        for line in text.splitlines():
            if re.search(r"[\u3040-\u30ff\u3400-\u9fff]", line):
                preview.append(line.strip()[:180])
                if len(preview) == 3:
                    break
        print("First Japanese text lines:", flush=True)
        for line in preview:
            print("  " + line, flush=True)
        return text, fmt
    raise RuntimeError("No recognizable full-episode SRT/ASS timing cues")


def main():
    print("=== PINNED OPENSUBTITLES JA PILOT ===", flush=True)
    print("Known candidate:", NAME, "| id:", SUBTITLE_ID, flush=True)

    # Find existing valid staging file before spending another allowance.
    if SCRATCH.is_dir():
        for extension in ("srt", "ass"):
            existing = SCRATCH / f"sunny-s01e01.opensubtitles.{SUBTITLE_ID}.ja.{extension}"
            if existing.is_file():
                inspect_content(existing.read_bytes())
                print("ALREADY STAGED:", existing, flush=True)
                print("No additional download.", flush=True)
                return

    api_key = os.environ.get("SUBHUB_OS_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("SUBHUB_OS_API_KEY not provided")

    provider = OpenSubtitlesProvider(api_key=api_key)
    provider.initialize()
    try:
        if not provider.session:
            raise RuntimeError("OpenSubtitles provider could not initialize")

        result = SubtitleResult(
            provider_name="opensubtitles",
            subtitle_id=SUBTITLE_ID,
            language="ja",
            format=SubtitleFormat.UNKNOWN,
            filename=NAME,
            release_info="Its.Always.Sunny.in.Philadelphia.S01E01.WEB-DL.DSNP",
            score=240,
            matches={"series", "season", "episode"},
            provider_data={"file_id": int(SUBTITLE_ID)},
        )
        print("Downloading exactly one known candidate...", flush=True)
        content = provider.download(result)
        if not isinstance(content, bytes):
            raise RuntimeError("Native provider returned no subtitle bytes")
        _, validated_ext = inspect_content(content)
        if result.format.value in ("srt", "ass", "ssa") and (
            "srt" if result.format.value == "srt" else "ass"
        ) != validated_ext:
            raise RuntimeError("Subtitle format disagrees with timing structure")
        SCRATCH.mkdir(parents=True, exist_ok=True, mode=0o700)
        out = SCRATCH / (
            f"sunny-s01e01.opensubtitles.{SUBTITLE_ID}.ja.{validated_ext}"
        )
        fd = os.open(str(out), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
        print("STAGED:", out, flush=True)
        print("NOT PUBLISHED: still needs text and release timing review.", flush=True)
    finally:
        provider.terminate()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("PILOT STOPPED:", type(exc).__name__, str(exc)[:250], flush=True)
        raise SystemExit(1) from None
