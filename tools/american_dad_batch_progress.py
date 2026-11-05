#!/usr/bin/env python3
"""Read-only live progress bars for the American Dad existing-English 8B batch.

Displays a persistent overall episode denominator, actual SQLite cue counts
and last reported state. Does not scan media, run GPU inference, translate,
publish, request providers, or change any existing files.
"""
from __future__ import annotations
import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import time

ROOT = Path.home() / "bruiser-pilot/plamo3-ab"
STATE = ROOT / "american-dad-existing-english-batch"
PLAN = STATE / "queue.json"
STATUS = STATE / "run-status.jsonl"
PIDFILE = STATE / "batch.pid"
LOG = STATE / "batch.log"
PROCESS = "plamo8b_american_dad_existing_en_batch.py"
EPISODE_LINE = re.compile(r"=== EPISODE \d+/\d+: (S\d{2}E\d{2,3}) ===")


def private_read(path):
    if not path.is_file() or path.is_symlink():
        return None
    if path.stat().st_size > 1_000_000:
        return None
    return path.read_text("utf-8",errors="replace")


def load_plan():
    data=private_read(PLAN)
    if data is None:
        return None
    obj=json.loads(data)
    if obj.get("version")!=1 or not isinstance(obj.get("episodes"),list):
        raise RuntimeError("unexpected_queue_plan_structure")
    episodes=obj["episodes"]
    for r in episodes:
        if not isinstance(r,dict) or not re.fullmatch(
                r"S\d{2}E\d{2,3}",str(r.get("episode") or "")):
            raise RuntimeError("malformed_episode_in_queue")
        path=Path(str(r.get("video") or ""))
        if not path.is_absolute():
            raise RuntimeError("episode_media_path_not_absolute")
    if len({r["episode"] for r in episodes}) != len(episodes):
        raise RuntimeError("duplicate_episodes_in_queue")
    return obj


def live_pid():
    raw=private_read(PIDFILE)
    if raw is None or not raw.strip().isdigit():
        return None
    pid=int(raw.strip())
    if pid<2:
        return None
    try:
        args=Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\x00",b" ")
        if PROCESS.encode() not in args:
            return None
        os.kill(pid,0)
        return pid
    except (OSError,PermissionError):
        return None


def recent_log():
    if not LOG.is_file() or LOG.is_symlink():
        return []
    with LOG.open("rb") as file:
        length=file.seek(0,os.SEEK_END)
        file.seek(max(0,length-50000))
        data=file.read(50000)
    return data.decode("utf-8",errors="replace").splitlines()[-400:]


def last_results():
    text=private_read(STATUS)
    results={}
    if text is None:
        return results
    for line in text.splitlines():
        try:
            result=json.loads(line)
            tag=result.get("episode")
            if isinstance(tag,str):
                results[tag]=result
        except (ValueError,TypeError):
            pass
    return results


def episode_dir(row):
    video=Path(row["video"])
    digest=hashlib.sha256(str(video).encode()).hexdigest()[:16]
    return STATE / (row["episode"]+"-"+digest)


def cue_progress(row):
    folder=episode_dir(row)
    if folder.is_symlink():
        return (0,0)
    metadata=private_read(folder/"episode.json")
    if metadata is None:
        return (0,0)
    try:
        info=json.loads(metadata)
        if info.get("episode") != row["episode"] or info.get("video") != row["video"]:
            return (0,0)
        total=int(info.get("cue_count") or 0)
        if not (1 <= total <= 1500):
            return (0,0)
        dbfile=folder/"progress.sqlite3"
        if not dbfile.is_file() or dbfile.is_symlink():
            return (0,total)
        uri=dbfile.resolve().as_uri()+"?mode=ro"
        with sqlite3.connect(uri,uri=True,timeout=1) as db:
            n=db.execute("SELECT COUNT(*) FROM translation").fetchone()[0]
        return min(n,total),total
    except (ValueError,TypeError,sqlite3.Error,OSError):
        return (0,0)


def done_track(row):
    video=Path(row["video"])
    target=video.with_name(video.stem+".ja.PLaMo8B.srt")
    return target.is_file() and not target.is_symlink()


def bar(completed,total,length=28):
    if total<=0:
        return "["+"░"*length+"]"
    fraction=min(max(completed/total,0),1)
    done=round(fraction*length)
    return "["+"█"*done+"░"*(length-done)+"]"


def snapshot():
    plan=load_plan()
    pid=live_pid()
    lines=recent_log()
    if plan is None:
        return {
            "running":bool(pid),
            "status":"NOT STARTED" if not pid else "STARTING",
            "total":0,"done":0,"held":0,"current":None,
            "log_tail":lines[-4:],
        }
    tasks=plan["episodes"]
    results=last_results()
    completed=[r for r in tasks if done_track(r)]
    complete={r["episode"] for r in completed}
    held=[
        r for r in tasks
        if r["episode"] not in complete and
        results.get(r["episode"],{}).get("status") in ("source_held","paused")
    ]
    current=None
    for line in reversed(lines):
        match=EPISODE_LINE.search(line)
        if match:
            current=match.group(1)
            break
    if current in complete:
        current=None
    if current is None:
        partially=[(r,cue_progress(r)) for r in tasks
                   if r["episode"] not in complete]
        partially=[(r,p) for r,p in partially if 0<p[0]<p[1]]
        if partially:
            current=partially[-1][0]["episode"]
        elif pid and len(completed)<len(tasks):
            remaining=[r for r in tasks if r["episode"] not in complete
                       and r not in held]
            if remaining:
                current=remaining[0]["episode"]
    current_row=next((r for r in tasks if r["episode"]==current),None)
    cues=cue_progress(current_row) if current_row else (0,0)
    has_finished=any("=== COMPLETE: published" in line for line in lines)
    thermal_pause=False
    for line in reversed(lines):
        if "THERMAL_RESUME" in line:
            break
        if "THERMAL_PAUSE" in line:
            thermal_pause=True
            break
    if pid:
        status="COOLING" if thermal_pause else "RUNNING"
    elif has_finished:
        status="FINISHED"
    else:
        status="STOPPED / PAUSED" if tasks else "NO EPISODES"
    return {
        "running": bool(pid),"status":status,
        "total":len(tasks),"done":len(completed),
        "held":len(held),"current":current,
        "cues_done":cues[0],"cues_total":cues[1],
        "last":next((line for line in reversed(lines)
                     if line.startswith(("BATCH_PAUSED","SOURCE_HELD",
                                         "EPISODE_HELD","THERMAL_PAUSE",
                                         "THERMAL_RESUME","=== COMPLETE"))),None),
        "log_tail":lines[-4:],
        "initial_ja":plan.get("initial_existing_ja",0),
        "initial_missing_en":plan.get("initial_missing_english",0),
    }


def display(s):
    print("American Dad — PLaMo 8B subtitle batch")
    print("Status:",s["status"])
    if not s["total"]:
        print("No saved batch queue or progress log was found.")
        print("Start with the existing-English batch launcher first.")
        return
    done,total=s["done"],s["total"]
    pct=done*100/total
    print("Episodes  ",bar(done,total),
          f"{done}/{total} ({pct:.1f}%)")
    print(f"Other: {s['held']} held/paused; "
          f"{s['initial_ja']} episodes already had Japanese; "
          f"{s['initial_missing_en']} lacked local English at startup")
    if s.get("current"):
        c,t=s["cues_done"],s["cues_total"]
        if t:
            print(f"Current {s['current']} ",bar(c,t),
                  f"{c}/{t} cues ({c*100/t:.1f}%)")
        else:
            print(f"Current {s['current']}: preparing English / starting model")
    elif done==total:
        print("All queued episodes have Japanese PLaMo8B subtitle files.")
    if s.get("last"):
        print("Last event:",s["last"][:180])
    if not s["running"] and done!=total:
        print("No active batch process detected. Restart the launcher to resume.")
    print("Data: real installed tracks and saved SQLite cue checkpoints.")


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--watch",action="store_true",help="refresh progress bars in place")
    ap.add_argument("--interval",type=int,default=4)
    args=ap.parse_args()
    if not 2<=args.interval<=60:
        ap.error("refresh interval must be 2–60 seconds")
    try:
        while True:
            state=snapshot()
            if args.watch:
                sys.stdout.write("\033[2J\033[H")
            display(state)
            sys.stdout.flush()
            if not args.watch:
                break
            print("\nRefreshes every",args.interval,
                  "seconds. Ctrl+C closes this view; batch keeps running.")
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nProgress view closed; background translation unaffected.")


if __name__=="__main__":
    main()
