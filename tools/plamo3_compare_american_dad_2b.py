#!/usr/bin/env python3
"""One controlled REAL American Dad S19E13 2B vs accepted 8B comparison.

Take the exact 392 verified English cues + 392 Japanese 8B outputs from the
completed PRIVATE source-first episode. Run ONLY PLaMo 3 Translate 2B with the
creator's unchanged PFML3 grammar and previous-two-pair history. Checkpoint
each cue privately; create a separate optional .ja.PLaMo2B.srt and a private
392-cue three-column JSON for editorial comparison. Never edit the movie,
the 8B track, the 8B checkpoints, the source-first pipeline, or power caps.

2B is small enough to attempt full GPU offload (999 layers) within RTX 3050
6GB; use two CPU threads to avoid the previous hot CPU scenario. Neither
GPU temperature nor wall-clock speed is guaranteed by this setting.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import fcntl
import re
import sqlite3
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone

try:
    from . import plamo3_watch_american_dad as accepted
    from . import plamo3_real_film_ab as real
    from . import plamo3_8b_challenger as eight
except ImportError:
    import plamo3_watch_american_dad as accepted
    import plamo3_real_film_ab as real
    import plamo3_8b_challenger as eight

small = real.small
ROOT = real.ROOT
ACCEPTED = accepted.WORK
WORK = ROOT / "american-dad-s19e13-2b-compare"
MANIFEST = WORK / "manifest.json"
CHECKPOINT = WORK / "progress.sqlite3"
MODEL_FILENAME = "plamo-3-translate-2b-Q4_K_M.gguf"
MODEL_HASH = "2c288ecc7ebfe60c3561726580da3583767f3c41ca3ef5c6825bf6c4cc060787"
EXPECTED_EN = "8e6b84daa9a1b864e6113c239b83da4f07651ce8d0605970a6a0f24639532942"
EXPECTED_COUNT = 392
GPU_LAYERS = 999  # full offload rather than hot CPU/partial 8B 28-layer profile
CPU_THREADS = 2
TRACK = "PLaMo2B"
PORT = 18885


def private(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise RuntimeError("private_file_missing_or_symlink")
    st = path.stat()
    if st.st_uid != os.getuid() or st.st_mode & 0o077:
        raise RuntimeError("private_file_permissions")
    return path


def load_reference():
    """Two independent checks: original full source, and completed 8B SQLite."""
    eight.check_native_contract()
    state = json.loads(private(accepted.MANIFEST).read_text("utf-8"))
    if not (state.get("episode") == "S19E13"
            and state.get("version") == 2
            and state.get("source_first") is True
            and state.get("cue_count") == EXPECTED_COUNT
            and state.get("english_sha256") == EXPECTED_EN
            and state.get("model") == eight.MODEL
            and state.get("model_sha256") == accepted.MODEL_HASH):
        raise RuntimeError("accepted_8b_reference_manifest_not_proven")
    raw = private(accepted.SOURCE).read_bytes()
    if hashlib.sha256(raw).hexdigest() != EXPECTED_EN:
        raise RuntimeError("accepted_8b_english_source_hash_changed")
    rows = small.parse_srt(raw.decode("utf-8-sig"), limit=500)
    if len(rows) != EXPECTED_COUNT or (
            [r["number"] for r in rows] != list(range(1, EXPECTED_COUNT+1))
            or small.format_srt(rows,"english").encode("utf-8") != raw):
        raise RuntimeError("accepted_8b_english_source_not_identical_392")
    video = Path(state["video"])
    # Library media is only read; enforce existing source-first identity.
    if (not video.is_absolute() or video.is_symlink()
            or not video.is_file()
            or accepted.episode_id(video) != "S19E13"):
        raise RuntimeError("accepted_8b_video_not_same_episode")
    st = video.stat()
    if st.st_size != state["size"] or st.st_mtime_ns != state["mtime_ns"]:
        raise RuntimeError("accepted_8b_video_metadata_changed")
    read_uri = "file:" + str(private(accepted.CHECKPOINT).resolve()) + "?mode=ro"
    with sqlite3.connect(read_uri, uri=True, timeout=15) as db:
        db.execute("PRAGMA query_only=ON")
        translations = accepted.verify_checkpoints(db,rows)
    if len(translations) != EXPECTED_COUNT or any(
            r["status"] != accepted.SPOKEN for r in translations):
        raise RuntimeError("accepted_8b_translation_incomplete")
    text, count = accepted.jellyfin_srt(translations)
    if count != EXPECTED_COUNT:
        raise RuntimeError("accepted_8b_srt_count_mismatch")
    track = accepted.safe_dest(video)
    if not track.is_file() or track.is_symlink():
        raise RuntimeError("accepted_8b_jellyfin_track_missing")
    original_bytes = track.read_bytes()
    if original_bytes != text.encode("utf-8"):
        raise RuntimeError("accepted_8b_jellyfin_track_differs_from_checkpoint")
    return state, video, rows, translations, hashlib.sha256(original_bytes).hexdigest()


def manifest_for(state, video, cues, ref_hash):
    return {
        "version": 1, "purpose": "same_episode_2b_vs_8b_private_comparison",
        "episode": "S19E13", "original_video": str(video),
        "video_size": state["size"], "video_mtime_ns": state["mtime_ns"],
        "cue_count": EXPECTED_COUNT, "english_sha256": EXPECTED_EN,
        "accepted_8b_model_sha256": accepted.MODEL_HASH,
        "accepted_8b_subtitle_sha256": ref_hash,
        "selected_2b_model": MODEL_FILENAME,
        "model_sha256": MODEL_HASH,
        "gpu_layers": GPU_LAYERS, "cpu_threads": CPU_THREADS,
        "protocol": "PFN native PFML3 with 2 previous source-translation pairs",
        "history_pairs": real.HISTORY, "temperature": 0,
        "max_tokens": 512, "stop": real.STOP,
        "decoded_same_english_source": True,
    }


def prepare_private(existing):
    if WORK.is_symlink():
        raise RuntimeError("private_2b_work_symlink")
    WORK.mkdir(parents=True, exist_ok=True, mode=0o700)
    if WORK.stat().st_mode & 0o077:
        raise RuntimeError("private_2b_work_permissions")
    if MANIFEST.is_symlink():
        raise RuntimeError("private_manifest_symlink")
    if MANIFEST.exists():
        saved = json.loads(private(MANIFEST).read_text("utf-8"))
        if saved != existing:
            raise RuntimeError("2b_resume_manifest_differs_from_accepted_8b")
    else:
        small.atomic_json(MANIFEST, existing)


def db_open():
    if CHECKPOINT.is_symlink():
        raise RuntimeError("private_2b_checkpoint_symlink")
    db = sqlite3.connect(CHECKPOINT,timeout=15)
    db.execute("PRAGMA synchronous=FULL")
    db.execute("""CREATE TABLE IF NOT EXISTS translation (
        idx INTEGER PRIMARY KEY, id INTEGER NOT NULL,
        start TEXT NOT NULL, end TEXT NOT NULL, english TEXT NOT NULL,
        japanese TEXT NOT NULL, status TEXT NOT NULL, seconds REAL NOT NULL
    )""")
    db.commit()
    return db


def new_model_server(binary, model, logfile, port):
    """2B full GPU offload, two CPU threads; do not change thermal settings."""
    import urllib.error
    small.check_port(port)
    cmd = [str(binary),"-m",str(model),"-c","4096",
           "--host","127.0.0.1","--port",str(port),
           "-ngl",str(GPU_LAYERS),"-t",str(CPU_THREADS),
           "--alias","plamo-3-translate"]
    with logfile.open("xb") as output:
        proc = subprocess.Popen(
            cmd,stdin=subprocess.DEVNULL,stdout=output,
            stderr=subprocess.STDOUT,start_new_session=True)
    try:
        deadline=time.monotonic()+120
        while time.monotonic()<deadline:
            if proc.poll() is not None:
                raise RuntimeError("2b_server_exited_early_check_private_log")
            try:
                response=small.json_request(port,"/health",timeout=3)
                if isinstance(response,dict) and response.get("status")=="ok":
                    return proc
            except (urllib.error.URLError,TimeoutError,ValueError):
                pass
            time.sleep(1)
        raise RuntimeError("2b_server_health_timeout")
    except BaseException:
        small.stop_server(proc)
        raise


def checkpoint_translate(db,cues,port):
    prior = accepted.verify_checkpoints(db,cues)
    print(f"2B resume: {len(prior)}/{len(cues)} cues already saved",flush=True)
    for i in range(len(prior),len(cues)):
        source=cues[i]
        started=time.monotonic()
        if real.is_non_dialogue_caption(source["english"]):
            ja, status = source["english"],accepted.SOLO_SDH
        else:
            ja,_,status=real.request(
                port,source["english"],accepted.previous_pairs(prior))
            if status!=accepted.SPOKEN:
                raise RuntimeError(
                    "2b_cue_not_translated__held_at_"+str(source["number"]))
        seconds=round(time.monotonic()-started,3)
        db.execute("""INSERT INTO translation
                  (idx,id,start,end,english,japanese,status,seconds)
                  VALUES(?,?,?,?,?,?,?,?)""",
                  (i,source["number"],source["start"],source["end"],
                   source["english"],ja,status,seconds))
        db.commit()
        prior.append({**source,"japanese":ja,"status":status,"seconds":seconds})
        if i==0 or (i+1)%25==0 or i+1==len(cues):
            print(f"2B: {i+1}/{len(cues)} cues",flush=True)
    return prior


def create_new(path,content,mode=0o600):
    """Atomic create-only, with a fully written staging file."""
    path=Path(path)
    if path.exists() or path.is_symlink():
        if path.is_file() and not path.is_symlink() and path.read_bytes()==content:
            return
        raise RuntimeError("existing_output_conflicts__no_replace")
    tmp=None
    try:
        fd,tmp=tempfile.mkstemp(prefix=".plamo2b-",dir=str(path.parent))
        with os.fdopen(fd,"wb") as output:
            output.write(content)
            output.flush()
            os.fchmod(output.fileno(),mode)
            os.fsync(output.fileno())
        os.link(tmp,path)
    finally:
        if tmp is not None:
            Path(tmp).unlink(missing_ok=True)


def export_pair(cues, eight_rows, two_rows, reference_sha, wall):
    paired=[]
    for en,ja8,ja2 in zip(cues,eight_rows,two_rows):
        if any(en[key]!=v[key]
               for v in (ja8,ja2)
               for key in ("number","start","end","english")):
            raise RuntimeError("two_vs_eight_cue_alignment_failed")
        paired.append({
            **en,"plamo_8b":ja8["japanese"],"plamo_2b":ja2["japanese"],
            "8b_status":ja8["status"],"2b_status":ja2["status"],
            "2b_seconds":ja2["seconds"],
        })
    result={
        "schema":"plamo-3-2b-vs-8b-american-dad-s19e13",
        "episode":"S19E13",
        "cue_count":len(paired),
        "english_sha256":EXPECTED_EN,
        "model_2b_sha256":MODEL_HASH,
        "accepted_8b_subtitle_sha256":reference_sha,
        "gpu_layers":GPU_LAYERS,
        "cpu_threads":CPU_THREADS,
        "2b_wall_seconds_including_model_load":round(wall,3),
        "2b_sum_cue_seconds":round(sum(x["seconds"] for x in two_rows),3),
        "entries":paired,
        "private_only":True,
    }
    body=(json.dumps(result,ensure_ascii=False,indent=2)+"\n").encode("utf-8")
    dest=WORK/"s19e13-2b-vs-8b.private.json"
    if dest.exists():
        old=json.loads(private(dest).read_text("utf-8"))
        stable_keys=("schema","episode","cue_count","english_sha256",
                     "model_2b_sha256","accepted_8b_subtitle_sha256",
                     "gpu_layers","cpu_threads","entries","private_only")
        if any(old.get(k)!=result.get(k) for k in stable_keys):
            raise RuntimeError("previous_private_review_data_changed")
        return dest
    create_new(dest,body)
    return dest


def publish_alternative(video, manifest, accepted_sha, srt):
    """Only create second named alternate; never overwrite accepted 8B."""
    st=video.stat()
    if st.st_size!=manifest["video_size"] or st.st_mtime_ns!=manifest["video_mtime_ns"]:
        raise RuntimeError("episode_changed_during_comparison")
    accepted_track=accepted.safe_dest(video)
    if not accepted_track.is_file() or accepted_track.is_symlink() or (
        hashlib.sha256(accepted_track.read_bytes()).hexdigest()!=accepted_sha):
        raise RuntimeError("accepted_8b_track_changed")
    target=video.with_name(video.stem+".ja.PLaMo2B.srt")
    if target.is_symlink() or target.exists():
        if target.is_file() and target.read_bytes()==srt.encode("utf-8"):
            return target
        raise RuntimeError("existing_2b_alternative_conflicts_no_replace")
    create_new(target,srt.encode("utf-8"),mode=0o644)
    return target


def run(args):
    if args.port<1025 or args.port>65535:
        raise RuntimeError("invalid_server_port")
    state,video,cues,eight_rows,ref_sha=load_reference()
    # Model 2B was already used in the real-film benchmark. Exact weights,
    # not an alternate quant, from that verified 2B test.
    model=ROOT/"models"/MODEL_FILENAME
    if not model.is_file() or model.is_symlink():
        raise RuntimeError("prior_tested_2b_weight_missing")
    if not 1_000_000_000 <= model.stat().st_size <= 3_500_000_000:
        raise RuntimeError("2b_gguf_size_invalid")
    with model.open("rb") as f:
        if f.read(4)!=b"GGUF":
            raise RuntimeError("2b_gguf_header_invalid")
    if small.digest(model)!=MODEL_HASH:
        raise RuntimeError("2b_weight_not_exact_verified_reference")
    existing=manifest_for(state,video,cues,ref_sha)
    prepare_private(existing)
    lockfile=WORK/".lock"
    if lockfile.is_symlink():
        raise RuntimeError("2b_lock_symlink")
    with lockfile.open("a+b") as lock:
        try:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("2b_episode_comparison_already_running") from exc
        with db_open() as db:
            partial=accepted.verify_checkpoints(db,cues)
            started=time.monotonic()
            print("=== EXACT S19E13 392-CUE 2B vs APPROVED 8B ===",flush=True)
            print("Source:",len(cues),"English cues, SHA",EXPECTED_EN,flush=True)
            print("2B: full GPU offload, 2 CPU threads; GPU 32W cap untouched.",
                  flush=True)
            print("Accepted 8B track: READ-ONLY",accepted.safe_dest(video).name,
                  flush=True)
            if len(partial)<len(cues):
                binary=(ROOT/"runtime/llama-server").resolve(strict=True)
                logfile=WORK/("llama-2b-"+datetime.now(timezone.utc)
                              .strftime("%Y%m%dT%H%M%S")+".log")
                proc=new_model_server(binary,model,logfile,args.port)
                try:
                    two_rows=checkpoint_translate(db,cues,args.port)
                finally:
                    small.stop_server(proc)
            else:
                two_rows=partial
            wall=time.monotonic()-started
            if len(two_rows)!=len(cues):
                raise RuntimeError("2b_not_all_cues_complete")
            srt,count=accepted.jellyfin_srt(two_rows)
            private_srt=WORK/"S19E13.PLaMo2B.ja.srt"
            create_new(private_srt,srt.encode("utf-8"))
            artifact=export_pair(cues,eight_rows,two_rows,ref_sha,wall)
            print("=== ALL 392 CUES READY FOR QUALITY REVIEW ===",flush=True)
            print("Private comparison JSON:",artifact,flush=True)
            print("2B spoken subtitles:",count,flush=True)
            if args.install:
                published=publish_alternative(video,existing,ref_sha,srt)
                print("Jellyfin alternate:",published,flush=True)
                print("Select Japanese (PLaMo2B); the approved 8B track is unchanged.",
                      flush=True)
            else:
                print("No media-side 2B track installed (no --install).",flush=True)
            print("COPY private comparison JSON to Mac mini and upload in chat.",
                  flush=True)


def self_test():
    eight.check_native_contract()
    assert EXPECTED_COUNT==392
    assert len(EXPECTED_EN)==64 and len(MODEL_HASH)==64
    assert accepted.GPU_LAYERS==28
    assert GPU_LAYERS==999 and CPU_THREADS==2
    assert WORK!=ACCEPTED
    assert accepted.CHECKPOINT!=CHECKPOINT
    assert accepted.safe_dest(Path("/tv/American.Dad.S19E13.mkv")).name.endswith(".ja.PLaMo8B.srt")
    assert accepted.previous_pairs([
        {"english":"A","japanese":"あ","status":"translated"},
        {"english":"[SIGHS]","japanese":"[SIGHS]","status":"non_dialogue_passthrough"},
        {"english":"B","japanese":"び","status":"translated"}])==[("A","あ"),("B","び")]
    print("S19E13 2B/8B ISOLATED COMPARISON SELF-TEST PASSED",flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test",action="store_true")
    parser.add_argument("--install",action="store_true",
                        help="add create-only alternate PLaMo2B Jellyfin track")
    parser.add_argument("--port",type=int,default=PORT)
    args=parser.parse_args()
    if args.self_test:
        self_test()
    else:
        run(args)


if __name__=="__main__":
    main()
