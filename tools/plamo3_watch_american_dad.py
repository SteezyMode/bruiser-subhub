#!/usr/bin/env python3
"""One real American Dad episode: selected PLaMo 3 Translate 8B -> Jellyfin.

No A/B, no season batch, no provider search, no installed Gemma changes.
Find an actual English-source episode (prefer fresh S08, then S19/20, then
others; fall back to already-translated S19E07 as an alternate Japanese track).
Checkpoint EVERY source cue; on completion, install ONE named Japanese SRT
create-only beside the episode. Restart command resumes the SAME episode.

Model interface exactly matches selected PLaMo 8B test: 28 GPU layers,
official PFN PFML3, two prior successful pairs, temperature 0, max_tokens
512, official stopping tags. Does not modify source-only systemd schedule.
"""
from __future__ import annotations

import argparse
import contextlib
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
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
WORK = ROOT / "american-dad-one-episode"
CHECKPOINT = WORK / "progress.sqlite3"
SOURCE = WORK / "source.en.srt"
MANIFEST = WORK / "episode.json"
MODEL_HASH = "6b429549113ce0a61281ac72be195697241f89266f4247efec4893e4f580cf10"
GPU_LAYERS = 28
SHOW = re.compile(r"american[\s._!()-]*dad", re.I)
EPISODE = re.compile(r"(?<![a-z0-9])s(\d{1,2})[\s._-]*e(\d{1,3})(?!\d)", re.I)
ALT_EP = re.compile(r"(?<!\d)(\d{1,2})x(\d{1,3})(?!\d)", re.I)
SOLO_SDH = "non_dialogue_passthrough"
SPOKEN = "translated"


def episode_id(path):
    if not SHOW.search(str(path)):
        return None
    m = EPISODE.search(path.name) or ALT_EP.search(path.name)
    if not m:
        return None
    season, episode = map(int, m.groups())
    if not (1 <= season <= 40 and 1 <= episode <= 100):
        return None
    return f"S{season:02d}E{episode:02d}"


def episode_priority(tag, has_ja):
    """Preference order: fresh S08; fresh S19/20; other fresh; known S19E07 alt."""
    if not has_ja and tag.startswith("S08"):
        return (0, tag)
    if not has_ja and tag.startswith("S19"):
        return (1, tag)
    if not has_ja and tag.startswith("S20"):
        return (2, tag)
    if not has_ja:
        return (3, tag)
    if tag == "S19E07":
        return (4, tag)
    return (5, tag)


def safe_dest(video):
    return video.with_name(video.stem + ".ja.PLaMo8B.srt")


def find_episode(daily, wanted=None):
    roots = daily.ensure_roots(daily.service.SOURCE_ROOTS)
    choices = {}
    for video in daily.video_files(roots):
        tag = episode_id(video)
        if tag and (wanted is None or tag == wanted):
            choices.setdefault(tag, []).append(video)
    if wanted and wanted not in choices:
        raise RuntimeError("requested_real_episode_not_found_in_approved_library")
    ranked = []
    for tag, copies in choices.items():
        # Avoid racing alternative releases if one copy already contains JA;
        # still permit ONE explicit PLaMo8B alternative for comparison.
        for video in sorted(copies, key=str):
            if safe_dest(video).exists() or safe_dest(video).is_symlink():
                continue
            has_ja_sidecar = daily.already_ja(video)
            ranked.append((episode_priority(tag, has_ja_sidecar), video, tag))
    ranked.sort(key=lambda x: x[0])
    counts = {"no_english_source": 0, "unusable_source": 0,
              "already_japanese": 0}
    for _, video, tag in ranked:
        # Don't spend dozens of minutes scanning unneeded media.
        try:
            from ja_first_stage_timing_audit import safe_media_path
            video = safe_media_path(str(video))
            info = daily.probe(video)
            if not info["audio_en"]:
                counts["unusable_source"] += 1
                continue
            has_ja = daily.already_ja(video) or info["ja"]
            if has_ja and tag != "S19E07" and wanted is None:
                counts["already_japanese"] += 1
                continue
            if not daily.english_srt(video) and info["embedded_en"] is None:
                counts["no_english_source"] += 1
                continue
            raw, _, origin = daily.source(video, info)
            lines = small.parse_srt(raw.decode("utf-8-sig"), limit=12000)
            if not 150 <= len(lines) <= 1500:
                counts["unusable_source"] += 1
                continue
            if [x["number"] for x in lines] != list(range(1, len(lines) + 1)):
                counts["unusable_source"] += 1
                continue
            return video, tag, lines, origin, "alternate" if has_ja else "new", counts
        except (OSError, RuntimeError, ValueError, subprocess.SubprocessError,
                UnicodeError):
            counts["unusable_source"] += 1
    raise RuntimeError("no_verified_english_source_american_dad_episode: " +
                       json.dumps(counts, sort_keys=True))


def seed_verified_source(video, tag, cues, origin, source_sha, timing):
    """Only called AFTER source-first JA search and EN source verification.

    This immutable private input allows ffsubsync-adjusted EN timestamps to
    survive a restart; we do not secretly revert to an unsynced download.
    """
    if not episode_id(video) == tag:
        raise RuntimeError("wrong_episode_for_verified_english")
    if len(cues) < 150 or len(cues) > 1500:
        raise RuntimeError("episode_cue_count_outside_bounds")
    if [c["number"] for c in cues] != list(range(1, len(cues) + 1)):
        raise RuntimeError("episode_source_sparse_cue_ids")
    if not ROOT.is_dir() or ROOT.is_symlink():
        raise RuntimeError("plamo_private_root_missing")
    WORK.mkdir(parents=True, exist_ok=True, mode=0o700)
    if WORK.is_symlink() or WORK.stat().st_mode & 0o077:
        raise RuntimeError("plamo_episode_workdir_not_private")
    source_text = small.format_srt(cues, "english")
    sha = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
    st = video.stat()
    data = {
        "version": 2, "episode": tag, "video": str(video),
        "size": st.st_size, "mtime_ns": st.st_mtime_ns,
        "cue_count": len(cues), "english_sha256": sha,
        "original_english_sha256": source_sha,
        "origin": origin, "timing": timing, "source_first": True,
        "model": eight.MODEL, "model_sha256": MODEL_HASH,
        "gpu_layers": GPU_LAYERS, "temperature": 0,
        "max_tokens": 512, "history_pairs": 2, "stop": real.STOP,
        "track_mode": "new",
        "selected_utc": datetime.now(timezone.utc).isoformat(),
    }
    if MANIFEST.exists():
        previous = json.loads(real._private_path(MANIFEST).read_text("utf-8"))
        keys = ("version","episode","video","size","mtime_ns","cue_count",
                "english_sha256","original_english_sha256","origin",
                "timing","source_first","model","model_sha256",
                "gpu_layers","temperature","max_tokens","history_pairs",
                "stop","track_mode")
        if any(previous.get(k) != data[k] for k in keys):
            raise RuntimeError("different_existing_episode_checkpoint__do_not_mix")
        if real._private_path(SOURCE).read_text("utf-8") != source_text:
            raise RuntimeError("staged_source_changed")
    else:
        if SOURCE.exists() and (SOURCE.is_symlink()
                                or SOURCE.read_text("utf-8") != source_text):
            raise RuntimeError("staged_source_conflict")
        if not SOURCE.exists():
            with SOURCE.open("x", encoding="utf-8") as out:
                out.write(source_text)
        small.atomic_json(MANIFEST, data)
    return data


def load_or_select(daily, wanted):
    if MANIFEST.exists() or MANIFEST.is_symlink():
        if MANIFEST.is_symlink():
            raise RuntimeError("existing_episode_selection_symlink")
        saved = json.loads(real._private_path(MANIFEST).read_text("utf-8"))
        if wanted and wanted != saved["episode"]:
            raise RuntimeError("another_episode_already_selected__do_not_mix_checkpoints")
        if saved.get("source_first"):
            from ja_first_stage_timing_audit import safe_media_path
            video = safe_media_path(saved["video"])
            stat = video.stat()
            if (stat.st_size != saved["size"]
                    or stat.st_mtime_ns != saved["mtime_ns"]):
                raise RuntimeError("source_first_episode_video_changed")
            info = daily.probe(video)
            if not info["audio_en"]:
                raise RuntimeError("english_audio_track_changed")
            if info["ja"] or daily.already_ja(video):
                raise RuntimeError("japanese_already_exists_no_new_translation")
            stored = real._private_path(SOURCE).read_text("utf-8")
            cues = small.parse_srt(stored, limit=1500)
            if (hashlib.sha256(stored.encode("utf-8")).hexdigest()
                    != saved["english_sha256"] or len(cues) != saved["cue_count"]):
                raise RuntimeError("source_first_checkpoint_english_changed")
            return video, cues, saved
        from ja_first_stage_timing_audit import safe_media_path
        video = safe_media_path(saved["video"])
        stat = video.stat()
        if stat.st_size != saved["size"] or stat.st_mtime_ns != saved["mtime_ns"]:
            raise RuntimeError("selected_episode_media_changed")
        info = daily.probe(video)
        if not info["audio_en"] or (not daily.english_srt(video)
                                      and info["embedded_en"] is None):
            raise RuntimeError("selected_episode_english_track_lost")
        raw, _, origin = daily.source(video, info)
        cues = small.parse_srt(raw.decode("utf-8-sig"), limit=12000)
        sha = hashlib.sha256(small.format_srt(cues, "english").encode()).hexdigest()
        if sha != saved["english_sha256"] or len(cues) != saved["cue_count"]:
            raise RuntimeError("selected_episode_source_changed")
        if origin != saved["origin"]:
            raise RuntimeError("english_source_provenance_changed")
        if real._private_path(SOURCE).read_text("utf-8") != small.format_srt(cues, "english"):
            raise RuntimeError("staged_english_source_changed")
        return video, cues, saved
    video, tag, cues, origin, track_mode, rejected = find_episode(daily, wanted)
    st = video.stat()
    source = small.format_srt(cues, "english")
    saved = {
        "version": 1, "episode": tag, "video": str(video),
        "size": st.st_size, "mtime_ns": st.st_mtime_ns,
        "cue_count": len(cues), "english_sha256": hashlib.sha256(
            source.encode("utf-8")).hexdigest(), "origin": origin,
        "model": eight.MODEL, "model_sha256": MODEL_HASH,
        "gpu_layers": GPU_LAYERS, "temperature": 0,
        "max_tokens": 512, "history_pairs": 2, "stop": real.STOP,
        "track_mode": track_mode, "selected_utc": datetime.now(timezone.utc).isoformat(),
    }
    # These are private, one-episode selection and cue source, never media writes.
    with SOURCE.open("x", encoding="utf-8") as writer:
        writer.write(source)
    small.atomic_json(MANIFEST, saved)
    print("SELECTED:", tag, "mode", track_mode,
          "| origin", origin, "|", len(cues), "English cues", flush=True)
    print("Rejected episode sources:", json.dumps(rejected), flush=True)
    return video, cues, saved


def checkpoints():
    path = CHECKPOINT
    if path.is_symlink():
        raise RuntimeError("checkpoint_symlink")
    db = sqlite3.connect(path, timeout=15)
    db.execute("PRAGMA synchronous=FULL")
    db.execute("""CREATE TABLE IF NOT EXISTS translation (
        idx INTEGER PRIMARY KEY, id INTEGER NOT NULL,
        start TEXT NOT NULL, end TEXT NOT NULL, english TEXT NOT NULL,
        japanese TEXT NOT NULL, status TEXT NOT NULL, seconds REAL NOT NULL)""")
    db.commit()
    return db


def verify_checkpoints(db, cues):
    rows = db.execute("""SELECT idx,id,start,end,english,japanese,status,seconds
                         FROM translation ORDER BY idx""").fetchall()
    if len(rows) > len(cues):
        raise RuntimeError("checkpoint_longer_than_source")
    output = []
    for position, (idx, number, begin, end, en, ja, status, seconds) in enumerate(rows):
        src = cues[position]
        if ((idx, number, begin, end, en) !=
            (position, src["number"], src["start"], src["end"], src["english"])):
            raise RuntimeError("checkpoint_source_mismatch")
        if status not in (SPOKEN, SOLO_SDH):
            raise RuntimeError("checkpoint_invalid_status")
        if status == SPOKEN and (not small.JP.search(ja) or "<|plamo:" in ja):
            raise RuntimeError("checkpoint_invalid_japanese")
        if status == SOLO_SDH and (ja != en or not real.is_non_dialogue_caption(en)):
            raise RuntimeError("checkpoint_invalid_SDH")
        output.append(dict(src, japanese=ja, status=status, seconds=seconds))
    return output


def previous_pairs(outputs):
    return [(o["english"], o["japanese"])
            for o in outputs if o["status"] == SPOKEN][-real.HISTORY:]


def jellyfin_srt(outputs):
    # Clean known formatting wrappers, remove English-only sound descriptions.
    translations = []
    for row in outputs:
        if row["status"] == SOLO_SDH:
            continue
        japanese = real.INLINE_SRT_TAG.sub("", row["japanese"]).strip()
        if not japanese or not small.JP.search(japanese) or "<|plamo:" in japanese:
            raise RuntimeError("invalid_japanese_for_jellyfin")
        translations.append(dict(number=len(translations)+1,
                                 start=row["start"], end=row["end"],
                                 japanese=japanese))
    result = small.format_srt(translations, "japanese")
    if len(small.parse_srt(result, limit=12000)) != len(translations):
        raise RuntimeError("assembled_jellyfin_srt_invalid")
    return result, len(translations)


def write_new_sidecar(video, saved, daily, srt):
    # Create only, atomically; do NOT overwrite even if another Japanese track
    # exists. This is a new named alternative for manual selection in Jellyfin.
    target = safe_dest(video)
    if target.exists() or target.is_symlink():
        raise RuntimeError("plamo8b_sidecar_already_exists__no_replace")
    st = video.stat()
    if st.st_size != saved["size"] or st.st_mtime_ns != saved["mtime_ns"]:
        raise RuntimeError("movie_modified_during_translation")
    now = daily.probe(video)
    if saved.get("source_first"):
        if daily.already_ja(video) or now["ja"]:
            raise RuntimeError("japanese_track_appeared_no_machine_overwrite")
        if not now["audio_en"]:
            raise RuntimeError("english_audio_track_disappeared")
    elif not now["audio_en"] or (not daily.english_srt(video)
                                  and now["embedded_en"] is None):
        raise RuntimeError("english_source_track_disappeared")
    tmp = None
    try:
        fd, tmp = tempfile.mkstemp(prefix=".subhub-plamo8b-",
                                   suffix=".tmp", dir=str(video.parent))
        with os.fdopen(fd, "wb") as out:
            out.write(srt.encode("utf-8"))
            out.flush()
            os.fchmod(out.fileno(), 0o644)
            os.fsync(out.fileno())
        os.link(tmp, target)  # atomic CREATE only
        return target
    finally:
        if tmp:
            with contextlib.suppress(OSError):
                Path(tmp).unlink(missing_ok=True)


def run(args):
    eight.check_native_contract()
    sys.path.insert(0, str(real.CONTROL))
    import daily_japanese as daily
    from ja_first_stage_timing_audit import safe_media_path

    WORK.mkdir(parents=True, exist_ok=True, mode=0o700)
    if WORK.is_symlink() or WORK.stat().st_mode & 0o077:
        raise RuntimeError("private_one_episode_workdir_unsafe")
    lockfile = WORK / ".lock"
    if lockfile.is_symlink():
        raise RuntimeError("episode_lock_symlink")
    with lockfile.open("a+b") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("episode_translation_already_running") from exc
        video, cues, saved = load_or_select(daily, args.episode)
        video = safe_media_path(str(video))
        destination = safe_dest(video)
        if destination.exists() or destination.is_symlink():
            raise RuntimeError("target_track_already_exists__no_overwrite")
        if saved["model_sha256"] != MODEL_HASH or saved["gpu_layers"] != GPU_LAYERS:
            raise RuntimeError("checkpoint_model_settings_changed")
        model = ROOT / "models" / eight.MODEL
        eight.validate_weight(model)
        if small.digest(model) != MODEL_HASH:
            raise RuntimeError("official_8B_weight_hash_changed")
        db = checkpoints()
        try:
            output = verify_checkpoints(db, cues)
            print("=== PLaMo8B -> ONE ACTUAL AMERICAN DAD EPISODE ===", flush=True)
            print("Episode:", saved["episode"], "| English cues:", len(cues),
                  "| already translated:", len(output), flush=True)
            print("Version:", saved["track_mode"], "| source:", saved["origin"],
                  "| source SHA256:", saved["english_sha256"], flush=True)
            print("Jellyfin track will be:", destination.name, flush=True)
            if len(output) < len(cues):
                binary = (ROOT / "runtime/llama-server").resolve(strict=True)
                if not binary.is_file() or not os.access(binary, os.X_OK):
                    raise RuntimeError("llama_runtime_missing")
                logfile = WORK / ("llama-" + datetime.now(timezone.utc)
                                   .strftime("%Y%m%dT%H%M%S") + ".log")
                print("MODEL: PLaMo 8B Q4, 28 GPU layers, official PFML3.", flush=True)
                proc = small.start_server(binary, model, args.port,
                                          GPU_LAYERS, logfile)
                try:
                    for i in range(len(output), len(cues)):
                        row = cues[i]
                        started = time.monotonic()
                        if real.is_non_dialogue_caption(row["english"]):
                            ja, kind = row["english"], SOLO_SDH
                        else:
                            ja, _, kind = real.request(
                                args.port, row["english"], previous_pairs(output))
                            if kind != SPOKEN:
                                raise RuntimeError(
                                    "model_did_not_translate_spoken_cue_" +
                                    str(row["number"]))
                        elapsed = round(time.monotonic() - started, 3)
                        db.execute(
                            "INSERT INTO translation "
                            "(idx,id,start,end,english,japanese,status,seconds)"
                            " VALUES (?,?,?,?,?,?,?,?)",
                            (i, row["number"], row["start"], row["end"],
                             row["english"], ja, kind, elapsed))
                        db.commit()
                        output.append(dict(row, japanese=ja,
                                           status=kind, seconds=elapsed))
                        if i == 0 or (i+1) % 25 == 0 or i+1 == len(cues):
                            print(f"{i+1}/{len(cues)} cues, "
                                  f"Japanese dialogue {sum(x['status']==SPOKEN for x in output)}",
                                  flush=True)
                finally:
                    small.stop_server(proc)
            if len(output) != len(cues):
                raise RuntimeError("not_all_episode_cues_processed")
            content, count = jellyfin_srt(output)
            draft = WORK / "AmericanDad.PLaMo8B.ja.srt"
            if draft.exists() or draft.is_symlink():
                if draft.is_symlink() or draft.read_text(encoding="utf-8") != content:
                    raise RuntimeError("existing_private_draft_different")
            else:
                with draft.open("x", encoding="utf-8") as writer:
                    writer.write(content)
            if not args.install:
                print("DRAFT COMPLETE, not installed because --install not provided.",
                      flush=True)
                print("Saved private draft:", draft, flush=True)
                return
            installed = write_new_sidecar(video, saved, daily, content)
            print("=== READY TO WATCH IN JELLYFIN ===", flush=True)
            print("Episode:", saved["episode"], flush=True)
            print("Japanese track:", installed, flush=True)
            print("Translated spoken cues:", count,
                  "| English-only sound captions omitted:", len(cues)-count,
                  flush=True)
            print("Jellyfin: play this episode; select Japanese (PLaMo8B).", flush=True)
            print("Original episode/earlier subtitles and source-only timer unchanged.",
                  flush=True)
        finally:
            db.close()


def self_test():
    a = Path("/shows/American.Dad.S19E07.mkv")
    assert episode_id(a) == "S19E07"
    assert episode_id(Path("/films/Friday.the.13th.S19E07.mkv")) is None
    assert episode_priority("S08E10", False) < episode_priority("S19E01", False)
    assert episode_priority("S19E10", False) < episode_priority("S19E07", True)
    assert safe_dest(a).name == "American.Dad.S19E07.ja.PLaMo8B.srt"
    rows = small.samples()[:3]
    output = [dict(rows[0], japanese="こんにちは", status=SPOKEN),
              dict(rows[1], japanese="[SIGHS]", status=SOLO_SDH),
              dict(rows[2], japanese="大丈夫", status=SPOKEN)]
    assert previous_pairs(output) == [
        (rows[0]["english"], "こんにちは"),
        (rows[2]["english"], "大丈夫"),
    ]
    assert len(small.parse_srt(jellyfin_srt(output)[0])) == 2
    eight.check_native_contract()
    print("AMERICAN DAD ONE-EPISODE PLaMo8B SELF-TEST PASSED")


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--install", action="store_true",
                     help="create new named JA subtitle alongside episode, no overwrite")
    cli.add_argument("--self-test", action="store_true")
    cli.add_argument("--episode", help="optional real existing S08E01 style ID")
    cli.add_argument("--port", type=int, default=18884)
    args = cli.parse_args()
    if args.self_test:
        return self_test()
    if args.episode and not re.fullmatch("S\d{2}E\d{2,3}", args.episode):
        cli.error("--episode must be S19E07 etc")
    if not 1025 <= args.port <= 65535:
        cli.error("port must be unprivileged")
    run(args)


if __name__ == "__main__":
    main()
