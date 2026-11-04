#!/usr/bin/env python3
"""One-title SubHub v2 handoff. Uses installed Sublarr + unchanged Hy-MT2 runner.

No new DB, service, prompt, review model, or publishing by default.
Durable checkpoints are inside Sublarr's existing /config Docker volume.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

CONTAINER = "sublarr-pilot"
PINNED_RUNNER = (
    "https://raw.githubusercontent.com/SteezyMode/bruiser-subhub/"
    "096d2caf5c180188e04c141db859e59b89748e10/"
    "tools/hy_mt2_full_srt_test.py"
)
HEADER = re.compile(
    r"(\d+)\n"
    r"(\d{2}:\d{2}:\d{2},\d{3} --> \d{2}:\d{2}:\d{2},\d{3}(?:[ \t]+[^\n]+)?)"
    r"\n(.+)",
    re.DOTALL,
)
JA_TOKEN = re.compile(r"(?i)(?:^|[._ -])(?:ja|jp|jpn|japanese)(?:[._ -]|$)")


def cmd(*args, capture=False):
    # Always execute. Previous conditional expression bypassed subprocess.run
    # entirely when capture=False (including Docker cp/exec/translation).
    result = subprocess.run(
        list(map(str, args)), check=True,
        text=True, stdout=subprocess.PIPE if capture else None,
    )
    return result.stdout if capture else None


def read_srt(file):
    text = file.read_text(encoding="utf-8-sig").replace("\r\n", "\n").replace("\r", "\n").strip()
    found = []
    for i, block in enumerate(re.split(r"\n[ \t]*\n", text), 1):
        hit = HEADER.fullmatch(block.strip())
        if not hit or not hit[3].strip():
            raise ValueError(f"Malformed/empty subtitle cue {i} in {file}")
        found.append((int(hit[1]), hit[2], hit[3]))
    if not found or len({n for n, _, _ in found}) != len(found):
        raise ValueError(f"No cues or repeated cue number in {file}")
    return found


def validate(source, candidate):
    expected = read_srt(source)
    actual = read_srt(candidate)
    if len(expected) != len(actual):
        raise ValueError(f"Cue-count mismatch: EN={len(expected)} JA={len(actual)}")
    for (en_n, en_time, _), (ja_n, ja_time, ja_text) in zip(expected, actual):
        if (en_n, en_time) != (ja_n, ja_time):
            raise ValueError(f"Different ID/timestamp at English cue {en_n}")
        if not re.search(r"[\u3040-\u30ff\u3400-\u9fff]", ja_text):
            # Some sound effects are intentionally English (e.g. music cues).
            # Do not falsely declare quality; warn without rejecting whole film.
            print(f"WARNING: cue {en_n} contains no detectable Japanese", flush=True)
    return len(expected)


def docker_inspect():
    data = json.loads(cmd("docker", "inspect", CONTAINER, capture=True))[0]
    volume = next((m for m in data["Mounts"] if m["Destination"] == "/config"), None)
    if not volume or not volume["RW"]:
        raise RuntimeError("Sublarr /config must be a writable persistent mount")
    return data


def start_sublarr():
    data = docker_inspect()
    if not data["State"]["Running"]:
        print("Starting existing Sublarr container...", flush=True)
        cmd("docker", "start", CONTAINER)
    for attempt in range(30):
        ok = subprocess.run(
            ["docker", "exec", CONTAINER, "python3", "-c",
             "import urllib.request; "
             "urllib.request.urlopen('http://127.0.0.1:5765/api/v1/health',timeout=2)"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        ).returncode == 0
        if ok:
            return
        time.sleep(2)
    raise RuntimeError("Sublarr did not become healthy after restart")


def start_ollama_if_needed():
    try:
        urllib.request.urlopen("http://127.0.0.1:11434/api/version", timeout=3).close()
        return
    except Exception:
        print("Starting installed Ollama service...", flush=True)
    subprocess.run(["sudo", "-n", "systemctl", "start", "ollama"], check=True)
    urllib.request.urlopen("http://127.0.0.1:11434/api/version", timeout=15).close()


def embedded_japanese(video):
    run = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "s",
         "-show_entries", "stream=index:stream_tags=language,title",
         "-of", "json", str(video)],
        capture_output=True, text=True, check=True,
    )
    for stream in json.loads(run.stdout).get("streams", []):
        tags = {k.lower(): str(v) for k, v in stream.get("tags", {}).items()}
        language = tags.get("language", "").lower()
        title = tags.get("title", "").lower()
        if language in {"ja", "jp", "jpn", "japanese"} or "japanese" in title or "日本語" in title:
            return True
    return False


def japanese_sidecars(video):
    extensions = {".srt", ".ass", ".ssa", ".vtt", ".sub"}
    found = []
    for path in video.parent.iterdir():
        if not path.is_file() or path.suffix.lower() not in extensions:
            continue
        if not path.name.startswith(video.stem):
            continue
        remainder = path.name[len(video.stem):]
        if JA_TOKEN.search(remainder):
            found.append(path)
    return found


def create_only_copy(source, dest):
    """Crash-safe create-only file even when state and media are different drives."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        raise FileExistsError(f"Existing file protected: {dest}")
    fd, temp_name = tempfile.mkstemp(prefix=dest.name + ".tmp-", dir=dest.parent)
    try:
        with os.fdopen(fd, "wb") as out, source.open("rb") as inp:
            shutil.copyfileobj(inp, out)
            out.flush()
            os.fsync(out.fileno())
        try:
            os.link(temp_name, dest)
        except FileExistsError:
            raise FileExistsError(f"Someone created output while staging: {dest}")
        dir_fd = os.open(dest.parent, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    finally:
        Path(temp_name).unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--english", type=Path, required=True)
    parser.add_argument("--existing-ja", type=Path, help="Review/export a completed JA draft without inference")
    parser.add_argument("--publish", action="store_true", help="Create new JA sidecar only after all safety checks")
    parser.add_argument("--state", type=Path, default=Path.home() / "bruiser-pilot/subhub-v2")
    args = parser.parse_args()
    video = args.video.expanduser().resolve(strict=True)
    english = args.english.expanduser().resolve(strict=True)
    if not video.is_file() or video.suffix.lower() not in {".mkv", ".mp4", ".m4v"}:
        parser.error("--video must be an existing video")
    source_cues = read_srt(english)
    ja_files = japanese_sidecars(video)
    embedded = embedded_japanese(video)
    print(f"Video: {video}", flush=True)
    print(f"English: {len(source_cues)} cues", flush=True)
    print(f"Already-present Japanese sidecars: {len(ja_files)}; embedded Japanese: {embedded}", flush=True)
    if args.publish and (ja_files or embedded):
        raise SystemExit("REFUSED: Video already contains Japanese. Existing human/editorial work is protected.")

    job_hash = hashlib.sha256(
        (str(video) + "\n").encode() + hashlib.sha256(english.read_bytes()).digest()
    ).hexdigest()[:16]
    state = args.state.expanduser() / "jobs" / job_hash
    state.mkdir(parents=True, exist_ok=True)
    draft = state / "draft.ja.srt"

    if args.existing_ja:
        external = args.existing_ja.expanduser().resolve(strict=True)
        count = validate(english, external)
        if not draft.exists():
            create_only_copy(external, draft)
        elif draft.read_bytes() != external.read_bytes():
            raise SystemExit(f"REFUSED: Existing saved draft differs: {draft}")
        print(f"Reused completed draft; {count} cues validated", flush=True)
    else:
        start_sublarr()
        start_ollama_if_needed()
        job = "/config/subhub-v2/jobs/" + job_hash
        cmd("docker", "exec", CONTAINER, "mkdir", "-p", job)
        cmd("docker", "cp", english, f"{CONTAINER}:{job}/source.en.srt")
        runner = args.state.expanduser() / "hy_mt2_verified_runner.py"
        if not runner.is_file():
            print("Installing pinned, already-proven Hy-MT2 runner...", flush=True)
            with urllib.request.urlopen(PINNED_RUNNER, timeout=30) as response:
                source_code = response.read()
            runner.parent.mkdir(parents=True, exist_ok=True)
            runner.write_bytes(source_code)
        cmd("docker", "cp", runner, f"{CONTAINER}:/config/subhub-v2/runner.py")
        cmd("docker", "exec", CONTAINER, "python3", "-m", "py_compile",
            "/config/subhub-v2/runner.py")
        print(f"Resuming persistent translation job {job_hash}", flush=True)
        cmd("docker", "exec", "-e", "PYTHONPATH=/app", CONTAINER,
            "python3", "-u", "/config/subhub-v2/runner.py",
            job + "/source.en.srt", "--workdir", job, "--full-gpu")
        final = f"{CONTAINER}:{job}/full-episode.draft.ja.srt"
        fetched = state / "fresh-draft.ja.srt"
        cmd("docker", "cp", final, fetched)
        validate(english, fetched)
        if draft.exists():
            if draft.read_bytes() != fetched.read_bytes():
                raise SystemExit("REFUSED: A different completed draft already exists in this job")
        else:
            create_only_copy(fetched, draft)

    count = validate(english, draft)
    print(f"VALIDATED JAPANESE DRAFT: {draft} ({count} matching cues)", flush=True)
    if args.publish:
        dest = video.with_suffix(".ja.srt")
        if japanese_sidecars(video) or embedded_japanese(video):
            raise SystemExit("REFUSED: Japanese track appeared during processing")
        create_only_copy(draft, dest)
        print(f"CREATED JAPANESE SIDECAR: {dest}", flush=True)
    else:
        print("DRAFT ONLY. No media directory or subtitle track modified.", flush=True)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, subprocess.CalledProcessError, RuntimeError) as exc:
        raise SystemExit(f"SubHub v2 pilot failed safely: {exc}") from exc
