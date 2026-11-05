#!/usr/bin/env python3
"""Use selected PLaMo 3 Translate 8B for ONE complete film in Jellyfin.

This is not another A/B test. Translate every cue of the previously proven
Friday the 13th IV (1984) film, checkpoint each cue, create a usable JA SRT,
and install it next to the media as a named Japanese external subtitle track.
The ONE target is taken from the original immutable real-film benchmark.
No changes to the source-only service/timer or existing Japanese captions.

The provider-authored PFML3 input, two previous translated pairs, decoding,
GGUF and 28-GPU-layer runtime are IDENTICAL to the completed 8B evaluation.
No new style prompts, context hacks, rewriting or LLM quality raters.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time

try:
    from . import plamo3_real_film_ab as real
    from . import plamo3_8b_challenger as eight
except ImportError:
    import plamo3_real_film_ab as real
    import plamo3_8b_challenger as eight

small = real.small
ROOT = real.ROOT
SOURCE_RUN = ROOT / "real-results" / eight.ORIGINAL_08
LIVE_ROOT = ROOT / "actual-use"
OFFLOAD = 28  # verified by owner on 2026-11-05
EXPECTED_WEIGHT_SHA = "6b429549113ce0a61281ac72be195697241f89266f4247efec4893e4f580cf10"
STATUS_TRANSLATED = "translated"
STATUS_SOUND = "non_dialogue_passthrough"


def utc():
    return datetime.now(timezone.utc).isoformat()


def source_from_original_video():
    """Read the EXACT previously verified film and its labeled English track.

    Re-extract *all* existing text cues; verify that cues 153-252 equal the
    original 100 benchmark source words and timestamps byte-for-byte.
    """
    _, video, reference, _, _, _, _, sha = real.load_frozen_run(SOURCE_RUN)
    if sha != eight.EXPECTED_SOURCE_SHA256:
        raise RuntimeError("verified_100_cue_anchor_digest_changed")
    sys.path.insert(0, str(real.CONTROL))
    import daily_japanese as daily
    from ja_first_stage_timing_audit import safe_media_path
    video = safe_media_path(str(video))
    if daily.already_ja(video):
        raise RuntimeError("existing_japanese_sidecar_present__not_overwriting")
    info = daily.probe(video)
    if not info["audio_en"] or info["ja"] or info["embedded_en"] is None:
        raise RuntimeError("english_audio_or_embedded_source_no_longer_safe")
    proc = subprocess.run(
        ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
         "-i", str(video), "-map", f"0:{info['embedded_en']}",
         "-vn", "-an", "-c:s", "srt", "-f", "srt", "pipe:1"],
        capture_output=True, timeout=180, check=False,
    )
    if proc.returncode or not (2000 <= len(proc.stdout) <= 2_000_000):
        raise RuntimeError("original_embedded_english_extraction_failed")
    text = proc.stdout.decode("utf-8-sig")
    cues = small.parse_srt(text, limit=12000)
    if not (200 < len(cues) <= 12000):
        raise RuntimeError("unexpected_full_movie_cue_count")
    if [c["number"] for c in cues] != list(range(1, len(cues)+1)):
        raise RuntimeError("non_contiguous_original_movie_cue_ids")
    matched = cues[reference[0]["number"]-1:reference[-1]["number"]]
    if matched != reference:
        raise RuntimeError("full_movie_source_differs_from_locked_100_cues")
    return video, cues, daily, hashlib.sha256(
        small.format_srt(cues, "english").encode("utf-8")).hexdigest()


def preview_job(video, full_sha):
    if LIVE_ROOT.is_symlink():
        raise RuntimeError("private_work_root_symlink")
    LIVE_ROOT.mkdir(parents=True, mode=0o700, exist_ok=True)
    if LIVE_ROOT.stat().st_mode & 0o077:
        raise RuntimeError("private_work_root_permissions")
    key = hashlib.sha256((str(video.resolve()) + "\n" + full_sha).encode()).hexdigest()[:20]
    folder = LIVE_ROOT / ("film-" + key)
    if folder.is_symlink():
        raise RuntimeError("private_job_symlink")
    folder.mkdir(mode=0o700, exist_ok=True)
    if folder.stat().st_mode & 0o077:
        raise RuntimeError("private_job_permissions")
    return folder


def initialise_job(folder, video, cues, full_sha, weight_sha):
    manifest_path = folder / "manifest.json"
    record = {
        "version": 1, "film": "Friday the 13th: The Final Chapter (1984)",
        "movie_path": str(video), "movie_size": video.stat().st_size,
        "movie_mtime_ns": video.stat().st_mtime_ns,
        "english_sha256": full_sha, "cue_count": len(cues),
        "anchor_sha256": eight.EXPECTED_SOURCE_SHA256,
        "model": eight.MODEL, "model_sha256": weight_sha,
        "native_format": "PFN PFML3, English input / Japanese output, two prior pairs",
        "temperature": 0, "max_tokens": 512, "stop": real.STOP,
        "gpu_layers": OFFLOAD, "started_utc": utc(),
        "mode": "single_film_real_use", "source": "embedded English text",
        "final_sidecar": str(video.with_name(video.stem + ".ja.PLaMo8B.srt")),
    }
    if manifest_path.exists():
        old = json.loads(real._private_path(manifest_path).read_text("utf-8"))
        for key in ("version", "movie_path", "movie_size", "movie_mtime_ns",
                    "english_sha256", "cue_count", "anchor_sha256", "model",
                    "model_sha256", "native_format", "temperature", "max_tokens",
                    "stop", "gpu_layers", "mode", "source", "final_sidecar"):
            if record[key] != old.get(key):
                raise RuntimeError("checkpoint_source_or_model_changed__hold")
    else:
        small.atomic_json(manifest_path, record)
    original = folder / "full-source.en.srt"
    content = small.format_srt(cues, "english")
    if original.exists():
        if real._private_path(original).read_text("utf-8") != content:
            raise RuntimeError("previous_english_source_changed")
    else:
        with original.open("x", encoding="utf-8") as f:
            f.write(content)
    return record


def open_checkpoints(folder):
    db_path = folder / "translations.sqlite3"
    if db_path.is_symlink():
        raise RuntimeError("private_checkpoint_symlink")
    db = sqlite3.connect(db_path, timeout=12)
    db.execute("PRAGMA synchronous=FULL")
    db.execute("""CREATE TABLE IF NOT EXISTS cues (
        idx INTEGER PRIMARY KEY, cue_id INTEGER NOT NULL, start TEXT NOT NULL,
        end TEXT NOT NULL, english TEXT NOT NULL, japanese TEXT NOT NULL,
        status TEXT NOT NULL, elapsed REAL NOT NULL
    )""")
    db.commit()
    return db


def load_checkpoint(db, cues):
    rows = db.execute(
        "SELECT idx, cue_id, start, end, english, japanese, status, elapsed "
        "FROM cues ORDER BY idx").fetchall()
    if len(rows) > len(cues):
        raise RuntimeError("checkpoint_exceeds_source")
    output = []
    for expected_idx, line in enumerate(rows):
        idx, cue_id, start, end, en, ja, status, elapsed = line
        original = cues[expected_idx]
        if (idx != expected_idx or cue_id != original["number"]
                or start != original["start"] or end != original["end"]
                or en != original["english"]
                or status not in (STATUS_TRANSLATED, STATUS_SOUND)
                or (status == STATUS_TRANSLATED and
                    (not small.JP.search(ja) or "<|plamo:" in ja))
                or (status == STATUS_SOUND and ja != en)):
            raise RuntimeError("checkpoint_cue_mismatch_or_untranslated_line")
        output.append({**original, "japanese": ja, "status": status, "seconds": elapsed})
    return output


def previous_pairs(records):
    """Exactly two successful source/translation pairs; not SDH."""
    return [(r["english"], r["japanese"])
            for r in records if r["status"] == STATUS_TRANSLATED][-real.HISTORY:]


def clean_japanese(text):
    # Only SRT font/italics/bold/underline wrappers; no model retranslation.
    return real.INLINE_SRT_TAG.sub("", text).strip()


def render_jellyfin_srt(rows):
    """Keep original timing; omit nonspoken [SFX] from Japanese-viewing track."""
    result = []
    for line in rows:
        if line["status"] == STATUS_SOUND:
            continue
        ja = clean_japanese(line["japanese"])
        if not ja or not small.JP.search(ja) or "<|plamo:" in ja:
            raise RuntimeError("invalid_japanese_in_complete_movie")
        result.append({"number": len(result)+1,
                       "start": line["start"], "end": line["end"],
                       "japanese": ja})
    if len(result) < 100:
        raise RuntimeError("too_few_spoken_cues_to_publish")
    final_text = small.format_srt(result, "japanese")
    parsed = small.parse_srt(final_text, limit=12000)
    if len(parsed) != len(result):
        raise RuntimeError("final_jellyfin_srt_parse_failure")
    return final_text, len(result)


def verify_not_replaced(video, manifest, daily):
    if not video.is_file() or video.is_symlink():
        raise RuntimeError("original_video_missing_or_symlink")
    stat = video.stat()
    if (stat.st_size != manifest["movie_size"] or
            stat.st_mtime_ns != manifest["movie_mtime_ns"]):
        raise RuntimeError("media_changed_while_translating")
    if daily.already_ja(video):
        raise RuntimeError("another_japanese_subtitle_now_exists__not_overwriting")
    probe = daily.probe(video)
    if not probe["audio_en"] or probe["ja"] or probe["embedded_en"] is None:
        raise RuntimeError("japanese_stream_appeared_or_english_track_changed")


def install_jellyfin_sidecar(video, manifest, daily, content):
    """Write full verified subtitle atomically and CREATE ONLY.

    A temporary sibling is written on same media filesystem then os.link is
    create-only, atomic across a final race with other Japanese publishers.
    No deletion/replacement of existing tracks. Plain SRT identified by
    Jellyfin as a Japanese language track with PLaMo8B as visible name.
    """
    verify_not_replaced(video, manifest, daily)
    destination = Path(manifest["final_sidecar"])
    if destination.exists() or destination.is_symlink():
        raise RuntimeError("already_published__no_overwrite")
    temp = None
    try:
        fd, temp = tempfile.mkstemp(prefix=".subhub-plamo8b-", suffix=".tmp",
                                    dir=str(video.parent))
        with os.fdopen(fd, "wb") as f:
            f.write(content.encode("utf-8"))
            f.flush()
            os.fchmod(f.fileno(), 0o644)
            os.fsync(f.fileno())
        verify_not_replaced(video, manifest, daily)
        os.link(temp, destination)  # raises FileExistsError, never overwrite
        # Temp and final are the same inode; final appears complete instantly.
        with destination.open("rb") as f:
            if hashlib.sha256(f.read()).hexdigest() != hashlib.sha256(
                    content.encode("utf-8")).hexdigest():
                raise RuntimeError("published_sidecar_hash_incorrect")
        return destination
    finally:
        if temp is not None:
            try:
                Path(temp).unlink(missing_ok=True)
            except OSError:
                pass


def run(args):
    eight.check_native_contract()
    video, cues, daily, full_sha = source_from_original_video()
    folder = preview_job(video, full_sha)
    lockfile = folder / ".lock"
    if lockfile.is_symlink():
        raise RuntimeError("job_lock_symlink")
    with lockfile.open("a+b") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("this_film_is_already_translating") from exc
        weight = ROOT / "models" / eight.MODEL
        eight.validate_weight(weight)
        weight_sha = small.digest(weight)
        if weight_sha != EXPECTED_WEIGHT_SHA:
            raise RuntimeError("official_8b_gguf_weight_digest_changed")
        manifest = initialise_job(folder, video, cues, full_sha, weight_sha)
        db = open_checkpoints(folder)
        try:
            records = load_checkpoint(db, cues)
            print("=== ONE REAL FULL FILM: PLaMo 3 Translate 8B ===", flush=True)
            print("Film:", manifest["film"], flush=True)
            print("English source: same original film and verified 100-cue anchor", flush=True)
            print("Total cues:", len(cues), "| Saved/resumable:", len(records), flush=True)
            print("Chosen 8B weight SHA256:", weight_sha, flush=True)
            print("Jellyfin Japanese track on completion:",
                  Path(manifest["final_sidecar"]).name, flush=True)
            if not args.install:
                raise RuntimeError("actual_use_requires_explicit_--install")
            if len(records) < len(cues):
                binary = (ROOT / "runtime/llama-server").resolve(strict=True)
                if not binary.is_file() or not os.access(binary, os.X_OK):
                    raise RuntimeError("missing_pinned_llama_server")
                log = folder / ("llama-server-" + datetime.now(timezone.utc)
                                .strftime("%Y%m%dT%H%M%S") + ".log")
                print("Starting selected model, 28 GPU layers; no utilization gate.",
                      flush=True)
                proc = small.start_server(binary, weight, args.port, OFFLOAD, log)
                try:
                    for idx in range(len(records), len(cues)):
                        cue = cues[idx]
                        start = time.monotonic()
                        if real.is_non_dialogue_caption(cue["english"]):
                            ja, kind = cue["english"], STATUS_SOUND
                        else:
                            ja, usage, kind = real.request(
                                args.port, cue["english"], previous_pairs(records))
                            if kind != STATUS_TRANSLATED:
                                raise RuntimeError(
                                    "untranslated_spoken_cue_" + str(cue["number"])
                                    + "__checkpoint_held_not_published")
                        elapsed = round(time.monotonic()-start, 3)
                        db.execute(
                            "INSERT INTO cues (idx,cue_id,start,end,english,japanese,status,elapsed)"
                            " VALUES (?,?,?,?,?,?,?,?)",
                            (idx, cue["number"], cue["start"], cue["end"],
                             cue["english"], ja, kind, elapsed))
                        db.commit()
                        records.append({**cue, "japanese": ja, "status": kind,
                                        "seconds": elapsed})
                        if (idx+1) % 25 == 0 or idx == len(cues)-1:
                            print(f"{idx+1}/{len(cues)} cues | "
                                  f"spoken {sum(x['status']==STATUS_TRANSLATED for x in records)}"
                                  f" | sound cues {sum(x['status']==STATUS_SOUND for x in records)}",
                                  flush=True)
                finally:
                    small.stop_server(proc)
            verify_not_replaced(video, manifest, daily)
            subtitle, count = render_jellyfin_srt(records)
            draft = folder / "full-film.PLaMo8B.ja.srt"
            if draft.exists():
                if real._private_path(draft).read_text("utf-8") != subtitle:
                    raise RuntimeError("existing_complete_private_draft_changed")
            else:
                with draft.open("x", encoding="utf-8") as out:
                    out.write(subtitle)
            result = install_jellyfin_sidecar(video, manifest, daily, subtitle)
            print("=== INSTALLED — ACTUAL JELLYFIN JAPANESE SUBTITLE ===", flush=True)
            print("Movie:", video.name, flush=True)
            print("Japanese subtitle:", result, flush=True)
            print("Spoken subtitle cues:", count,
                  "| excluded nonspoken sound descriptions:", len(cues)-count,
                  flush=True)
            print("File size:", result.stat().st_size, "bytes", flush=True)
            print("In Jellyfin choose Japanese / PLaMo8B; refresh title if needed.",
                  flush=True)
            print("No source-only service/timer or old Japanese subtitles modified.",
                  flush=True)
        finally:
            db.close()


def self_test():
    rows = small.samples()[:3]
    records = [
        {**rows[0], "japanese": "日本語。", "status": STATUS_TRANSLATED},
        {**rows[1], "japanese": "[SIGHS]", "status": STATUS_SOUND},
        {**rows[2], "japanese": "大丈夫。", "status": STATUS_TRANSLATED}
    ]
    assert previous_pairs(records) == [
        (rows[0]["english"], "日本語。"),
        (rows[2]["english"], "大丈夫.") .replace(".", "。")
    ]
    assert clean_japanese('<font size="36">こんばんは。</font>') == "こんばんは。"
    assert real.is_non_dialogue_caption('<font size="36">[SIGHS]</font>')
    assert not real.is_non_dialogue_caption("<font>Watch out!</font>")
    eight.check_native_contract()
    print("PLaMo REAL MOVIE self-test passed: creator PFML3 + SDH + output cleanup")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install", action="store_true",
                        help="explicitly create a movie-side Jellyfin JA track on completion")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--port", type=int, default=18883)
    args = parser.parse_args()
    if args.self_test:
        self_test()
    else:
        if not 1025 <= args.port <= 65535:
            parser.error("port must be unprivileged")
        run(args)


if __name__ == "__main__":
    main()
