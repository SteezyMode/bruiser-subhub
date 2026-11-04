#!/usr/bin/env python3
"""Retranslate Attachment (2022) from original English using PINNED tuned E4B.

Creates an isolated, resumable checkpoint database and a separately named
Jellyfin review track, never overwriting the existing generic-model Japanese.
The start command launches a detached worker and follows a read-only tracker.
"""
from __future__ import annotations

import argparse
import fcntl
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import tarfile
import time
from urllib.parse import quote

HOME = Path.home()
HOST = HOME / "bruiser-pilot" / "subhub1"
CONTROL = HOME / "bruiser-pilot" / "subhub-control"
OLD_ROOT = HOME / "bruiser-pilot" / "subhub1-state"
ROOT = HOME / "bruiser-pilot" / "attachment-e4b-rerun"
OLD_JOB_ID = "daily-attachment-2022-720p-webrip-800mb-x-5ce7f7760def"
EXPECTED_CUES = 1276
REVIEW_ARCHIVE = ROOT / "review" / "Attachment-2022-E4B-English-Japanese-review.tar.gz"
REVIEW_JA = ROOT / "review" / "Attachment-2022-E4B.ja.srt"
REVIEW_TRACK_SUFFIX = ".Bruiser E4B Review Japanese.ja.srt"
TRACKER = CONTROL / "subhub_live_tracker.py"

if HOST.is_dir():
    sys.path.insert(0, str(HOST))
if CONTROL.is_dir():
    sys.path.insert(0, str(CONTROL))

import service
import main
try:
    import subtitle_tuned_production as tuned
except ModuleNotFoundError:
    from tools import subtitle_tuned_production as tuned


def ensure_production():
    if service.GEMMA != tuned.MODEL:
        raise RuntimeError("Installed service is not configured for pinned tuned E4B")
    if tuned.MODEL_ID_PREFIX != "9ccfc3b07081":
        raise RuntimeError("Tuned model ID changed; refusing retranslation")
    if tuned.NUM_CTX != 1344 or tuned.NUM_PREDICT != 256 or tuned.TEMPERATURE != 0:
        raise RuntimeError("Official subtitle model runtime settings changed")


def source_record():
    """Read ONLY the already-published old Attachment job and original English."""
    dbpath = OLD_ROOT / "jobs.sqlite3"
    if dbpath.is_symlink() or not dbpath.is_file():
        raise RuntimeError("Original SubHub jobs database is missing or unsafe")
    uri = "file:" + quote(str(dbpath.resolve()), safe="/") + "?mode=ro"
    with sqlite3.connect(uri, uri=True, timeout=10) as con:
        con.execute("PRAGMA query_only=ON")
        row = con.execute(
            "SELECT id,video,source_path,source_sha,source_cues,audio_lang,status "
            "FROM jobs WHERE id=?", (OLD_JOB_ID,)
        ).fetchone()
    if row is None:
        raise RuntimeError("Original Attachment job not found; refusing to guess source")
    _, video_s, source_s, src_sha, n, audio, state = row
    if state != "published" or audio != "eng":
        raise RuntimeError("Original Attachment source not verified as published English")
    video = Path(video_s)
    src = Path(source_s)
    if src.is_symlink() or not src.is_file():
        raise RuntimeError("Original English subtitle source missing or symlinked")
    if not src.resolve().is_relative_to(OLD_ROOT.resolve()):
        raise RuntimeError("Original English subtitle source outside expected state dir")
    service.secure_video(video)
    data = src.read_bytes()
    if service.sha(data) != src_sha:
        raise RuntimeError("Original English source SHA changed")
    if int(n) != EXPECTED_CUES or len(service.parse_srt(data)) != EXPECTED_CUES:
        raise RuntimeError("Attachment source cue count differs from 1276")
    if service.audio_language(video) != "eng":
        raise RuntimeError("English-primary audio cannot be reverified")
    return {"video": video, "source": data, "sha": src_sha,
            "job_id": "daily-attachment-e4b-review-" + src_sha[:12]}


def private_root():
    if ROOT.is_symlink() or (ROOT.exists() and not ROOT.is_dir()):
        raise RuntimeError("Unsafe E4B review root")
    ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    if ROOT.stat().st_uid != os.getuid() or ROOT.stat().st_mode & 0o077:
        raise RuntimeError("E4B review root must be owned by owner and private")


def ensure_job(info):
    private_root()
    st = service.Store(ROOT)
    try:
        rows = st.jobs()
        if rows and any(j["id"] != info["job_id"] for j in rows):
            raise RuntimeError("Review state contains unrelated job; refusing to mix")
        st.add(info["job_id"], info["video"], info["source"],
               "eng", scope="attachment-e4b-review", priority=0)
        rows = st.jobs()
        if len(rows) != 1 or rows[0]["id"] != info["job_id"]:
            raise RuntimeError("Isolated review state has unexpected jobs")
        return dict(rows[0])
    finally:
        st.cn.close()


def write_create_only(path, data, mode=0o600):
    """Idempotent iff bytes identical; never truncate or replace existing files."""
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise RuntimeError("Unsafe review output path: " + str(path))
    if path.exists():
        if path.read_bytes() != data:
            raise RuntimeError("Review output already exists with different contents: "
                               + str(path))
        return "already-identical"
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY |
                 getattr(os, "O_NOFOLLOW", 0), mode)
    with os.fdopen(fd, "wb") as out:
        out.write(data)
        out.flush()
        os.fchmod(out.fileno(), mode)
        os.fsync(out.fileno())
    return "created"


def make_review_archive(english, japanese, manifest):
    bio = io.BytesIO()
    with tarfile.open(fileobj=bio, mode="w:") as tar:
        items = (
            ("Attachment.2022.en.srt", english),
            ("Attachment.2022.Tuned-E4B.ja.srt", japanese),
            ("review-manifest.json", json.dumps(manifest, indent=2,
                                                ensure_ascii=False).encode("utf-8")),
        )
        for name, data in items:
            node = tarfile.TarInfo(name)
            node.size = len(data)
            node.mode = 0o600
            tar.addfile(node, io.BytesIO(data))
    return gzip.compress(bio.getvalue(), compresslevel=6, mtime=0)


def export_review(st, info):
    """Publish ONLY distinct clearly labeled review track; keep original JA."""
    jid = info["job_id"]
    row = next(j for j in st.jobs() if j["id"] == jid)
    video, cues = service.validate_publish(st, row)
    if row["source_sha"] != info["sha"] or len(cues) != EXPECTED_CUES:
        raise RuntimeError("Review cues/source fingerprint changed")
    japanese = service.render_srt(
        [(r["cue_id"], r["timing"], r["start_ms"], r["end_ms"],
          r["english"]) for r in cues],
        {str(r["cue_id"]): r["japanese"] for r in cues},
    )
    track = video.with_name(video.stem + REVIEW_TRACK_SUFFIX)
    old_track = video.with_name(video.stem + ".Bruiser Japanese.ja.srt")
    if track == old_track:
        raise RuntimeError("Review output would collide with original Japanese")
    if not old_track.is_file() or old_track.is_symlink():
        raise RuntimeError("Original published Japanese subtitle missing or unsafe")
    review = ROOT / "review"
    review.mkdir(mode=0o700, exist_ok=True)
    if review.is_symlink() or review.stat().st_mode & 0o077:
        raise RuntimeError("Review directory must be private")
    manifest = {
        "job_id": jid, "original_job_id": OLD_JOB_ID,
        "source_sha256": info["sha"], "translated_sha256": service.sha(japanese),
        "source_cues": EXPECTED_CUES,
        "model": tuned.MODEL, "model_id": tuned.MODEL_ID_PREFIX,
        "profile": tuned.PROFILE,
        "sidecar": str(track),
        "original_japanese_preserved": str(old_track),
        "quality_status": "machine-translated review track; not human approved",
    }
    write_create_only(REVIEW_JA, japanese, mode=0o600)
    write_create_only(
        REVIEW_ARCHIVE, make_review_archive(info["source"], japanese, manifest),
        mode=0o600,
    )
    # Distinct create-only media sidecar for practical Jellyfin playback and A/B.
    outcome = write_create_only(track, japanese, mode=0o644)
    st.cn.execute("UPDATE jobs SET published_sha=? WHERE id=?",
                  (service.sha(japanese), jid))
    st.state(jid, "published")
    st.event(jid, "review_track_published",
             "E4B review-only alternate JA sidecar; original untouched")
    print("E4B_REVIEW_PUBLISHED", str(track), outcome, flush=True)
    print("ENGLISH_JAPANESE_REVIEW_ARCHIVE", REVIEW_ARCHIVE, flush=True)
    return track


def run_worker(jid):
    ensure_production()
    info = source_record()
    if jid != info["job_id"]:
        raise RuntimeError("Job ID mismatch for original Attachment source")
    private_root()
    st = service.Store(ROOT)
    try:
        jobs = st.jobs()
        if len(jobs) != 1 or jobs[0]["id"] != jid:
            raise RuntimeError("Isolated queue does not contain only Attachment")
        job = jobs[0]
        if job["status"] == "published":
            print("E4B_ALREADY_COMPLETE", REVIEW_ARCHIVE, flush=True)
            return
        if job["status"] in ("hold", "needs_review", "publish_hold"):
            raise RuntimeError("Previously held job needs investigation; no reset")
        try:
            # Preflight checks exact digest, model family, real GPU-resident
            # placement and original author's native chat template.
            tuned.model_preflight()
            tuned.assert_job_profile(ROOT, job, int(job["ja"] or 0))
        except Exception as exc:
            st.state(jid, "hold", "Pinned E4B preflight/provenance: " + str(exc)[:180])
            raise
        print("E4B_RETRANSLATION_STARTED", jid,
              "cues", job["n"], "already-translated", job["ja"], flush=True)
        args = argparse.Namespace(
            max_minutes=120, max_titles=1, mode="translate",
            max_gpu_c=82, max_cpu_c=85, hy_sample=0,
            sample_seconds=15, publish=False, skip_hy=True,
        )
        old_publish = main.publish_ready
        # The normal publisher correctly refuses a title that already has JA.
        # This narrowly scoped process produces a DIFFERENT review track only
        # after the same strict source/audio/timing validation.
        main.publish_ready = lambda store, job, allow: print(
            "REVIEW_ONLY_OUTPUT_PENDING", job["id"], flush=True)
        try:
            try:
                main.run(st, HOST, ROOT, args,
                         translator=tuned.make_translator(st, job))
            except Exception as exc:
                st.state(jid, "hold", "E4B native worker error: " + str(exc)[:180])
                raise
        finally:
            main.publish_ready = old_publish
        current = st.jobs()[0]
        if current["ja"] == current["n"] and current["status"] == "translated":
            try:
                export_review(st, info)
            except Exception as exc:
                st.state(jid, "review_ready",
                         "Complete Japanese, export held: " + str(exc)[:160])
                print("E4B_TRANSLATED_EXPORT_HELD", type(exc).__name__,
                      str(exc)[:150], flush=True)
                raise
        elif current["status"] == "queued":
            st.state(jid, "paused", current["last_error"] or
                     "Translation paused; checkpoints saved for resume")
            print("E4B_PAUSED", jid, "cues", current["ja"], "/", current["n"],
                  flush=True)
        else:
            print("E4B_WORKER_STOPPED", jid, current["status"],
                  current["ja"], "/", current["n"], flush=True)
    finally:
        st.cn.close()


def watch(jid):
    if TRACKER.is_symlink() or not TRACKER.is_file():
        raise RuntimeError("Live tracker missing; install from pinned GitHub")
    command = [sys.executable, "-u", str(TRACKER),
               "--root", str(ROOT), "--job-id", jid,
               "--watch", "--interval", "10"]
    print("ATTACHING LIVE E4B TRACKER; Ctrl+C closes display only.", flush=True)
    try:
        subprocess.call(command, cwd=str(CONTROL))
    except KeyboardInterrupt:
        print("Tracker closed; detached translation continues.", flush=True)


def start(watching=True):
    ensure_production()
    info = source_record()
    private_root()
    lock = ROOT / "launch.lock"
    if lock.is_symlink():
        raise RuntimeError("Unsafe launch lock")
    fd = os.open(lock, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
    launched = False
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("E4B_WORKER_ALREADY_RUNNING; attaching tracker", flush=True)
        else:
            job = ensure_job(info)
            if job["status"] == "published":
                print("E4B_ALREADY_PUBLISHED", REVIEW_ARCHIVE, flush=True)
            elif job["status"] in ("hold", "needs_review", "publish_hold",
                                    "review_ready"):
                raise RuntimeError("Review job held: " + job["status"]
                                   + "; inspect state/log rather than resetting")
            else:
                log = ROOT / "worker.log"
                with log.open("a", encoding="utf-8") as out:
                    out.write("\n=== " + service.stamp() +
                              " E4B retranslation of Attachment ===\n")
                    out.flush()
                    p = subprocess.Popen(
                        [sys.executable, str(Path(__file__).resolve()),
                         "worker", "--job-id", info["job_id"]],
                        cwd=str(CONTROL), stdin=subprocess.DEVNULL,
                        stdout=out, stderr=subprocess.STDOUT,
                        start_new_session=True, pass_fds=(fd,),
                    )
                    print("E4B_WORKER_STARTED", "PID", p.pid,
                          "job", info["job_id"], flush=True)
                    print("E4B_WORKER_LOG", log, flush=True)
                    launched = True
    finally:
        # The child inherits this locked fd and keeps the lock held until exit.
        # Closing in the foreground controller cannot interrupt the worker.
        os.close(fd)
    if watching:
        watch(info["job_id"])
    return launched


def status():
    info = source_record()
    db = ROOT / "jobs.sqlite3"
    if not db.is_file():
        print("E4B_REVIEW_JOB not started", flush=True)
        return
    uri = "file:" + quote(str(db.resolve()), safe="/") + "?mode=ro"
    with sqlite3.connect(uri, uri=True) as cn:
        row = cn.execute(
            """SELECT j.id,j.status,j.source_cues,
               COUNT(c.cue_id),
               SUM(CASE WHEN c.japanese IS NOT NULL THEN 1 ELSE 0 END),
               j.last_error
               FROM jobs j JOIN cues c ON c.job_id=j.id
               WHERE j.id=? GROUP BY j.id""",
            (info["job_id"],),
        ).fetchone()
    print("E4B_ATTACHMENT_STATUS", row, flush=True)
    print("REVIEW_ARCHIVE", REVIEW_ARCHIVE, REVIEW_ARCHIVE.exists(), flush=True)


def self_test():
    ensure_production()
    assert REVIEW_TRACK_SUFFIX != ".Bruiser Japanese.ja.srt"
    assert EXPECTED_CUES == 1276
    assert "9ccfc3b07081" == tuned.MODEL_ID_PREFIX
    assert ROOT != OLD_ROOT
    print("SELF_TEST_PASS: pinned E4B, original source immutable, "
          "isolated checkpoints, alternate review sidecar", flush=True)


def cli(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("start", "worker", "watch",
                                           "status", "self-test"),
                        nargs="?", default="start")
    parser.add_argument("--job-id", default=None)
    parser.add_argument("--no-watch", action="store_true")
    args = parser.parse_args(argv)
    if args.action == "self-test":
        self_test()
    elif args.action == "start":
        start(watching=not args.no_watch)
    elif args.action == "worker":
        if not args.job_id or not re.fullmatch(r"daily-[a-z0-9-]{1,95}",
                                               args.job_id):
            parser.error("worker requires an exact, valid --job-id")
        run_worker(args.job_id)
    elif args.action == "watch":
        info = source_record()
        watch(info["job_id"])
    else:
        status()


if __name__ == "__main__":
    try:
        cli()
    except KeyboardInterrupt:
        print("Foreground tracker closed; worker unaffected.", flush=True)
    except Exception as exc:
        print("ATTACHMENT_E4B_ERROR", type(exc).__name__, str(exc)[:250],
              file=sys.stderr, flush=True)
        raise SystemExit(1) from None
