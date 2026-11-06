#!/usr/bin/env python3
"""Export sourced Japanese subtitle QA evidence into a PRIVATE tar.gz on stdout.

READ-ONLY. Uses systemd journal PUBLISHED events, not an expensive library scan.
Includes exact .ja.srt sidecars and any immediately adjacent matching English
text sidecars for editorial comparison. Does not read/copy video or audio.
Never commit the resulting archive to the public source repository.
"""
from __future__ import annotations

import argparse
import io
import json
from pathlib import Path
import re
import subprocess
import sys
import tarfile

PUBLISHED = re.compile(r"^PUBLISHED:\s+(/.+\.ja\.srt)\s*$")
ENGLISH = re.compile(r"(?:^|[._ -])(?:en|eng|english)(?:[._ -]|$)", re.I)
ROOTS = (Path("/mnt/BigDisk"), Path("/mnt/2TB"), Path("/mnt/1TBNVME"),
         Path("/home/optiplex"))


def publications(text):
    paths = []
    seen = set()
    for line in text.splitlines():
        match = PUBLISHED.search(line.strip())
        if match and match.group(1) not in seen:
            seen.add(match.group(1))
            paths.append(Path(match.group(1)))
    return paths


def english_for(japanese):
    """Require exact original video stem plus an English language tag."""
    base = japanese.name.removesuffix(".ja.srt")
    candidates = []
    for path in japanese.parent.iterdir():
        if (path.is_file() and not path.is_symlink()
                and path.suffix.casefold() in (".srt", ".ass", ".ssa", ".vtt")
                and path.name.casefold().startswith((base + ".").casefold())
                and ENGLISH.search(path.name[len(base) + 1:])):
            candidates.append(path)
    return sorted(candidates, key=lambda p: (p.suffix != ".srt", p.name))[:2]


def safe_read(path):
    if path.is_symlink() or not path.is_file():
        return None
    resolved = path.resolve()
    if not any(resolved.is_relative_to(root) for root in ROOTS):
        return None
    if path.stat().st_size > 2_000_000:
        return None
    return path.read_bytes()


def append_tar(tar, name, data):
    info = tarfile.TarInfo(name)
    info.size = len(data)
    info.mode = 0o600
    tar.addfile(info, io.BytesIO(data))


def pack(paths, output):
    entries = []
    payloads = []
    for path in paths:
        ja = safe_read(path)
        if ja is None:
            continue
        index = len(entries) + 1
        prefix = f"subtitles/{index:03}"
        payloads.append((f"{prefix}.ja.srt", ja))
        english = []
        for candidate in english_for(path):
            raw = safe_read(candidate)
            if raw is not None:
                target = f"{prefix}.en{candidate.suffix.lower()}"
                payloads.append((target, raw))
                english.append({"archive_file": target, "source_name": candidate.name})
        entries.append({"index": index, "source_name": path.name,
                        "source_path": str(path),
                        "japanese_file": f"{prefix}.ja.srt",
                        "english": english})
    if not entries:
        raise RuntimeError("No published Japanese SRT files found in journal window")
    manifest = {"kind": "sourced_japanese_quality_review", "count": len(entries),
                "paired_english_count": sum(bool(x["english"]) for x in entries),
                "entries": entries}
    with tarfile.open(fileobj=output, mode="w|gz") as tar:
        append_tar(tar, "manifest.json",
                   json.dumps(manifest, ensure_ascii=False, indent=2).encode())
        for name, raw in payloads:
            append_tar(tar, name, raw)
    print(f"QA_PACKAGE subtitles={len(entries)} paired_english="
          f"{manifest['paired_english_count']}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--since", default="2026-11-06 05:00:00")
    parser.add_argument("--until", default="2026-11-06 08:30:00")
    args = parser.parse_args()
    result = subprocess.run(
        ["journalctl", "--user", "-u", "bruiser-ja-source-autofill.service",
         "--since", args.since, "--until", args.until,
         "--no-pager", "-o", "cat"],
        capture_output=True, text=True, timeout=30, check=True)
    paths = publications(result.stdout)
    pack(paths, sys.stdout.buffer)


if __name__ == "__main__":
    main()
