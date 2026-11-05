#!/usr/bin/env python3
"""American Dad: translate EVERY already-English-ready episode after Season 2.

This is a one-off, resumable household batch using the existing, working
S19E13 PLaMo 8B engine, not a new translation framework.

- Inspect embedded/local JA first; never overwrite an existing JA track.
- Translate embedded English text, otherwise local English SRT after ffsubsync.
- No subtitle-provider requests in this phase: missing-source seasons come next.
- Episodes in Season 20 then 21 then 19, then remaining after Season 2.
- Never touch the existing S19E13 8B / 2B tracks or completed checkpoints.
- Create private per-episode SQLite checkpoints and an atomic .ja.PLaMo8B.srt.
- CPU 2 threads, GPU 28 layers; owner-supplied 32 W GPU cap unchanged.
- Pause if CPU/GPU rises above configured thermal limits; don't run if
  temperatures cannot be observed.
- Correct Roger-as-「了解」 only for clear English name-address cues.
"""
from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import urllib.error
from datetime import datetime, timezone

try:
    from . import plamo3_watch_american_dad as engine
    from . import plamo3_source_first_american_dad as source
except ImportError:
    import plamo3_watch_american_dad as engine
    import plamo3_source_first_american_dad as source

real = engine.real
small = engine.small
ROOT = engine.ROOT
MEDIA = Path("/mnt/BigDisk/Video/Television/Episodic/American Dad! (2005)")
STATE = ROOT / "american-dad-existing-english-batch"
PORT = 18886
CPU_THREADS = 2
GPU_LAYERS = 28
CPU_PAUSE = 79.0
CPU_RESUME = 73.0
CPU_ABORT = 90.0
GPU_PAUSE = 73.0
GPU_RESUME = 67.0
GPU_ABORT = 83.0
COOL_TIMEOUT = 1200
MODEL_FILENAME = engine.eight.MODEL

def cpu_celsius():
    samples = []
    for hw in Path("/sys/class/hwmon").glob("hwmon*"):
        try:
            if (hw / "name").read_text().strip() != "coretemp":
                continue
            for temp in hw.glob("temp*_input"):
                value = float(temp.read_text().strip()) / 1000
                label = temp.with_name(temp.name.replace("_input", "_label"))
                tag = label.read_text().strip() if label.exists() else ""
                if 10 < value < 130:
                    samples.append((0 if "Package" in tag else 1, value))
        except (OSError, ValueError):
            pass
    if samples:
        level = min(x[0] for x in samples)
        return max(v for k, v in samples if k == level)
    for zone in Path("/sys/class/thermal").glob("thermal_zone*"):
        try:
            tag=(zone/"type").read_text().strip().lower()
            if tag not in ("x86_pkg_temp","cpu-thermal","cpu_thermal"):
                continue
            value=float((zone/"temp").read_text().strip())/1000
            if 10 < value < 130:
                return value
        except (OSError, ValueError):
            pass
    raise RuntimeError("CPU_THERMAL_SENSOR_MISSING__refusing_unmonitored_batch")

def gpu_state():
    proc=subprocess.run(
        ["nvidia-smi","--query-gpu=temperature.gpu,memory.free",
         "--format=csv,noheader,nounits"],
        capture_output=True,text=True,check=True,timeout=10)
    vals=proc.stdout.strip().splitlines()[0].split(",")
    gpu=float(vals[0].strip())
    free=int(vals[1].strip())
    if not (10 <= gpu <= 105 and 0 <= free <= 6400):
        raise RuntimeError("invalid_gpu_sensor_output")
    return gpu,free

def temperatures():
    cpu=cpu_celsius()
    gpu,_=gpu_state()
    return cpu,gpu

def thermal_gate():
    started=None
    while True:
        cpu,gpu=temperatures()
        if cpu >= CPU_ABORT or gpu >= GPU_ABORT:
            raise RuntimeError(
                f"THERMAL_ABORT cpu={cpu:.1f}C gpu={gpu:.1f}C; "
                "no more episodes, checkpoints preserved")
        if started is None and cpu < CPU_PAUSE and gpu < GPU_PAUSE:
            return
        if started is None:
            started=time.monotonic()
            print(f"THERMAL_PAUSE cpu={cpu:.1f}C gpu={gpu:.1f}C "
                  f"until <= {CPU_RESUME:.0f}C CPU and <= {GPU_RESUME:.0f}C GPU",
                  flush=True)
        if cpu <= CPU_RESUME and gpu <= GPU_RESUME:
            print(f"THERMAL_RESUME cpu={cpu:.1f}C gpu={gpu:.1f}C",flush=True)
            return
        if time.monotonic()-started > COOL_TIMEOUT:
            raise RuntimeError("THERMAL_COOLDOWN_TIMEOUT__resume_later")
        time.sleep(20)

def safe_roger_name(english, japanese):
    """Correct name-address hallucinations, not legitimate acknowledgments.

    Only an English cue beginning 'Roger,' or 'Roger!' or 'Roger.'
    paired with a Japanese line beginning 「了解」 is rewritten.
    'Roger that' and a Japanese acknowledgment elsewhere remain unchanged.
    """
    def remove_tags(text):
        text=real.INLINE_SRT_TAG.sub("",text)
        return re.sub(r"^\s*\{\\an\d+\}", "", text).strip()
    en=remove_tags(english)
    if not re.match(r"(?i)^-?\s*Roger\s*[,!.?:]",en):
        return japanese
    # Preserve leading SRT positioning/italic tags and dialogue dash.
    match=re.match(r"^(\s*(?:\{\\an\d+\})?\s*(?:<i>)?\s*(?:-\s*)?)了解(?=[、。，.!?！？])",
                   japanese)
    if not match:
        return japanese
    return japanese[:match.end()-2] + "ロジャー" + japanese[match.end():]

def scan(daily, only=None):
    """One copy per episode; prefer same-file embedded English when available."""
    if not MEDIA.is_dir() or MEDIA.is_symlink():
        raise RuntimeError("expected_american_dad_library_directory_missing")
    by_episode={}
    for video in daily.video_files([MEDIA]):
        tag=engine.episode_id(video)
        if not tag or int(tag[1:3]) <= 2:
            continue
        if only is not None and tag not in only:
            continue
        by_episode.setdefault(tag,[]).append(video)
    work=[]; skipped_ja=[]; no_english=[]; failed=[]
    def episode_key(tag):
        season=int(tag[1:3])
        return (0 if season==20 else 1 if season==21 else
                2 if season==19 else 3,season,int(tag[4:]))
    for tag in sorted(by_episode,key=episode_key):
        candidates=[]
        ja=False
        for video in sorted(by_episode[tag]):
            try:
                info=daily.probe(video)
                if info["ja"] or daily.already_ja(video):
                    ja=True
                    continue
                if (info["embedded_en"] is None and
                        daily.english_srt(video) is None):
                    continue
                if not info["audio_en"]:
                    continue
                candidates.append((0 if info["embedded_en"] is not None else 1,
                                   str(video),video,info))
            except (OSError, ValueError, RuntimeError,
                    subprocess.SubprocessError):
                failed.append(tag)
        if ja:
            skipped_ja.append(tag)
        elif candidates:
            candidates.sort()
            _,_,video,info=candidates[0]
            work.append((tag,video,info))
        else:
            no_english.append(tag)
    return work,skipped_ja,no_english,failed

def scope_dir(video,tag):
    ident=hashlib.sha256(str(video).encode()).hexdigest()[:16]
    p=STATE / (tag+"-"+ident)
    if p.is_symlink():
        raise RuntimeError("private_episode_checkpoint_symlink")
    return p

@contextlib.contextmanager
def separate_episode(video,tag):
    original=(engine.WORK,engine.CHECKPOINT,engine.SOURCE,engine.MANIFEST)
    folder=scope_dir(video,tag)
    engine.WORK=folder
    engine.CHECKPOINT=folder/"progress.sqlite3"
    engine.SOURCE=folder/"source.en.srt"
    engine.MANIFEST=folder/"episode.json"
    try:
        yield folder
    finally:
        engine.WORK,engine.CHECKPOINT,engine.SOURCE,engine.MANIFEST=original

def frozen_english(video, info, daily, sync):
    if info["ja"] or daily.already_ja(video):
        raise RuntimeError("japanese_present__no_translation")
    if info["embedded_en"] is not None:
        raw=subprocess.run(
            ["ffmpeg","-nostdin","-hide_banner","-loglevel","error",
             "-i",str(video),"-map",f"0:{info['embedded_en']}",
             "-vn","-an","-c:s","srt","-f","srt","pipe:1"],
            capture_output=True,timeout=180,check=True).stdout
        kind="embedded"
        origin="batch_same_file_embedded_english"
    else:
        en=daily.english_srt(video)
        if en is None or en.is_symlink() or not en.is_file():
            raise RuntimeError("verified_local_english_disappeared")
        if en.stat().st_size > 2_000_000:
            raise RuntimeError("english_sidecar_too_large")
        raw=en.read_bytes()
        kind="external"
        origin="batch_ffsubsync_external_english"
    sha=hashlib.sha256(raw).hexdigest()
    if kind=="external":
        aligned,timing=source.validate_timing_source(video,raw,kind,sync)
    else:
        aligned,timing=raw,{"mode":"embedded_release_timing"}
    cues=small.parse_srt(aligned.decode("utf-8-sig"),limit=1501)
    if not 150 <= len(cues) <= 1500:
        raise RuntimeError("english_cue_count_outside_one_episode_bounds")
    if [r["number"] for r in cues]!=list(range(1,len(cues)+1)):
        raise RuntimeError("noncontiguous_english_cue_numbers")
    return cues,origin,sha,timing

def start_cool_server(binary,model,port,gpu_layers,logfile):
    if gpu_layers!=GPU_LAYERS:
        raise RuntimeError("gpu_layers_changed_from_proven_28")
    small.check_port(port)
    _,free=gpu_state()
    if free < 4600:
        raise RuntimeError(f"GPU_IN_USE__free_MiB={free}; no forced eviction")
    cmd=[str(binary),"-m",str(model),"-c","4096",
         "--host","127.0.0.1","--port",str(port),
         "-ngl",str(gpu_layers),"-t",str(CPU_THREADS),
         "--alias","plamo-3-translate"]
    with logfile.open("xb") as dest:
        proc=subprocess.Popen(cmd,stdin=subprocess.DEVNULL,
                              stdout=dest,stderr=subprocess.STDOUT,
                              start_new_session=True)
    try:
        deadline=time.monotonic()+120
        while time.monotonic()<deadline:
            if proc.poll() is not None:
                raise RuntimeError("batch_llama_server_exited__check_private_log")
            try:
                result=small.json_request(port,"/health",timeout=3)
                if isinstance(result,dict) and result.get("status")=="ok":
                    return proc
            except (urllib.error.URLError,TimeoutError,ValueError):
                pass
            time.sleep(1)
        raise RuntimeError("batch_llama_server_health_timeout")
    except BaseException:
        small.stop_server(proc)
        raise

def with_batch_inference(tag, video, source_rows, origin, raw_sha, timing):
    with separate_episode(video,tag) as folder:
        if engine.MANIFEST.exists():
            # For a resumable episode trust the immutable private source,
            # rather than re-synchronizing external English on every restart.
            print("RESUME checkpoint:",tag,flush=True)
        else:
            engine.seed_verified_source(video,tag,source_rows,origin,
                                        raw_sha,timing)
        original_start=small.start_server
        original_request=real.request
        request_count=0
        def guarded_request(port,english,history):
            nonlocal request_count
            if request_count%10==0:
                thermal_gate()
            request_count+=1
            ja,usage,status=original_request(port,english,history)
            if status==engine.SPOKEN:
                ja=safe_roger_name(english,ja)
            return ja,usage,status
        small.start_server=start_cool_server
        real.request=guarded_request
        try:
            print("TRANSLATING:",tag,video.name,flush=True)
            engine.run(argparse.Namespace(episode=tag,install=True,port=PORT))
        finally:
            real.request=original_request
            small.start_server=original_start

def append_result(outcome,tag,reason):
    path=STATE/"run-status.jsonl"
    with path.open("a",encoding="utf-8") as f:
        f.write(json.dumps({
            "time":datetime.now(timezone.utc).isoformat(),
            "episode":tag,"status":outcome,"reason":reason[:180]},
            ensure_ascii=False)+"\n")
        f.flush()
        os.fsync(f.fileno())

def run(args):
    sys.path.insert(0,str(real.CONTROL))
    import daily_japanese as daily
    sys.path.insert(0,str(source.CONTROL))
    import ja_first_ffsubsync as sync
    if STATE.is_symlink():
        raise RuntimeError("private_batch_state_symlink")
    STATE.mkdir(parents=True,exist_ok=True,mode=0o700)
    if STATE.stat().st_mode & 0o077:
        raise RuntimeError("private_batch_state_permissions")
    lockpath=STATE/".lock"
    if lockpath.is_symlink():
        raise RuntimeError("batch_lock_symlink")
    with lockpath.open("a+b") as lock:
        try:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("another_american_dad_batch_running")
        work,ja,missing,errors=scan(daily,
           only=set(args.episode) if args.episode else None)
        print("=== AMERICAN DAD EXISTING ENGLISH -> JAPANESE (PLaMo 8B) ===",
              flush=True)
        print("After Season 2; order S20, S21, S19, others.",flush=True)
        print("Existing JA episodes skipped:",len(ja),
              "| missing local English:",len(missing),
              "| source probe errors:",len(errors),flush=True)
        print("English-ready and JA-missing episodes:",len(work),flush=True)
        print("CPU threads:",CPU_THREADS,"GPU layers:",GPU_LAYERS,
              "| GPU power cap unchanged.",flush=True)
        if not args.apply:
            for tag,video,info in work:
                print(tag,"embedded_EN" if info["embedded_en"] is not None
                      else "local_EN",flush=True)
            print("PREVIEW ONLY: add --apply to run full resumable batch.",
                  flush=True)
            return
        if not work:
            print("No English-ready episodes need new Japanese tracks.",flush=True)
            return
        # Do not begin a lengthy batch without both temperature sensors.
        cpu,gpu=temperatures()
        print(f"THERMALS AT START: CPU {cpu:.1f}C / GPU {gpu:.1f}C",
              flush=True)
        thermal_gate()
        selected=work if args.limit==0 else work[:args.limit]
        total=len(selected)
        good=0;held=0
        for index,(tag,video,info) in enumerate(selected,1):
            print(f"=== EPISODE {index}/{total}: {tag} ===",flush=True)
            if daily.already_ja(video) or daily.probe(video)["ja"]:
                print("SKIP: Japanese appeared; no overwrite.",flush=True)
                append_result("already_japanese",tag,"existing_local_or_embedded_ja")
                continue
            try:
                with separate_episode(video,tag):
                    if engine.MANIFEST.exists():
                        old=json.loads(real._private_path(engine.MANIFEST).read_text("utf-8"))
                        if (old.get("video") != str(video)
                            or old.get("episode") != tag
                            or not old.get("source_first")):
                            raise RuntimeError("episode_checkpoint_identity_mismatch")
                        # engine.run() will load the exact saved English source.
                        cues=[];origin="";raw_sha="";timing={}
                    else:
                        cues,origin,raw_sha,timing=frozen_english(
                            video,info,daily,sync)
                thermal_gate()
                with_batch_inference(tag,video,cues,origin,raw_sha,timing)
                good+=1
                append_result("published",tag,"new_named_8b_ja_sidecar")
            except (OSError,ValueError,UnicodeError,
                    subprocess.SubprocessError) as exc:
                held+=1
                print("EPISODE_HELD",tag,type(exc).__name__,
                      str(exc)[:150],flush=True)
                append_result("source_held",tag,str(exc))
                continue
            except RuntimeError as exc:
                # Thermal, GPU/engine, output and checkpoint errors stop the
                # batch immediately so nothing is silently skipped.
                print("BATCH_PAUSED",tag,str(exc)[:180],flush=True)
                append_result("paused",tag,str(exc))
                raise
        print("=== COMPLETE: published",good,"of",total,
              "| held",held,"| existing Japanese untouched ===",flush=True)
        print("Status file:",STATE/"run-status.jsonl",flush=True)

def self_test():
    engine.eight.check_native_contract()
    assert engine.GPU_LAYERS==GPU_LAYERS==28
    assert CPU_THREADS==2
    assert safe_roger_name("Roger, you know","了解、わかる")=="ロジャー、わかる"
    assert safe_roger_name("Roger that.","了解。")=="了解。"
    assert safe_roger_name("Noted, Roger","了解。")=="了解。"
    assert safe_roger_name("Roger, you know","ロジャー、わかる")=="ロジャー、わかる"
    assert safe_roger_name(r"{\an8}Roger.","{\an8}了解。")==r"{\an8}ロジャー。"
    print("PLaMo8B BATCH SELF-TEST PASSED (Roger + native protocol)")

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply",action="store_true")
    parser.add_argument("--self-test",action="store_true")
    parser.add_argument("--episode",action="append",
                        help="optional S20E01 style episode filter; repeatable")
    parser.add_argument("--limit",type=int,default=0,
                        help="optional max new episodes; 0 means no limit")
    args=parser.parse_args()
    if args.self_test:
        return self_test()
    if args.limit<0 or args.limit>1000:
        parser.error("--limit must be between 0 and 1000")
    if args.episode and any(not re.fullmatch(r"S\d{2}E\d{2,3}",x) for x in args.episode):
        parser.error("--episode must be S20E01 format")
    run(args)

if __name__=="__main__":
    main()
