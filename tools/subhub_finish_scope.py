#!/usr/bin/env python3
"""One owner-selected TV scope: source Japanese, then translate proven gaps.

This is one foreground systemd job, not a second provider engine. The existing
Jellyfin source batch owns provider quotas/ALASS/ffsubsync; the existing PLaMo
batch owns EN verification, translation checkpoints, QA and create-only writes.
A failed or quota-paused search is NOT proof Japanese subtitles do not exist.
Unverified duplicate versions are never sent to PLaMo automatically.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

try:
    from . import subhub_translation_batch as batch
except ImportError:
    import subhub_translation_batch as batch

SOURCE = Path.home() / "bruiser-pilot/subhub-control/subhub_jellyfin_batch.py"
TRANSLATOR = Path(__file__).with_name("subhub_translation_batch.py")
STATE = Path.home() / "bruiser-pilot/ja-first-inventory/finish-scope.json"
MAX_TRANSLATION_PICKS = 200
MAX_SEARCHES = 200


def scope_seasons(series, seasons=()):
    records = next((x for x in batch.catalog()
                    if x["series"] == series), None)
    if not records:
        raise ValueError("series_not_in_saved_jellyfin_queue")
    available = set(records["seasons"])
    requested = sorted(set(seasons)) if seasons else sorted(available)
    if not requested or not set(requested).issubset(available):
        raise ValueError("selected_season_not_in_jellyfin_queue")
    return requested


def plan(series, seasons=()):
    selected = scope_seasons(series, seasons)
    items = []
    for season in selected:
        report = batch.season_report(series, season)
        for row in report["items"]:
            items.append(dict(row, season=season))
    missing = [x for x in items if x["status"] != "covered"]
    # PLaMo only after a recorded Japanese miss or actual timing-QA failure.
    # A plausible candidate still awaiting repair is NOT exhausted.
    def may_translate(x):
        proof = x.get("search") or {}
        plausible = int(proof.get("plausible_candidates") or 0)
        return (bool(x.get("can_translate")) and
                (plausible == 0 or bool(x.get("failed_source_qa"))) and
                x.get("reason") != "duplicate_episode_versions")
    eligible = [x for x in missing if may_translate(x)]
    return {"series":series,"seasons":selected,"total":len(items),
            "covered":len(items)-len(missing),"missing":len(missing),
            "source_first":len(missing)-len(eligible),
            "plamo_ready":len(eligible),
            "duplicate_versions":sum(
                x.get("reason") == "duplicate_episode_versions" for x in missing),
            "picks":[{"season":x["season"],"episode":x["episode"]}
                     for x in eligible[:MAX_TRANSLATION_PICKS]]}


def write_state(payload):
    parent=STATE.parent
    if (not parent.is_dir() or parent.is_symlink() or
            parent.stat().st_mode & 0o077):
        raise RuntimeError("private_state_directory_unavailable")
    if STATE.is_symlink() or (STATE.exists() and
            (not STATE.is_file() or STATE.stat().st_mode & 0o077)):
        raise RuntimeError("unsafe_existing_finish_state")
    value=dict(payload,updated_utc=datetime.now(timezone.utc).isoformat())
    raw=json.dumps(value,ensure_ascii=False,sort_keys=True).encode("utf-8")
    if len(raw)>15_000:
        raise RuntimeError("finish_state_too_large")
    fd,temp=tempfile.mkstemp(prefix=".finish-",dir=parent)
    try:
        with os.fdopen(fd,"wb") as f:
            os.fchmod(f.fileno(),0o600)
            f.write(raw);f.flush();os.fsync(f.fileno())
        os.replace(temp,STATE)
    finally:
        Path(temp).unlink(missing_ok=True)


def command(args, label):
    if not args[0].is_file() or args[0].is_symlink():
        raise RuntimeError(label+"_worker_not_installed")
    print("FINISH_STEP",label,flush=True)
    with subprocess.Popen([sys.executable,"-B","-u",*map(str,args)],
            stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,text=True,bufsize=1) as p:
        assert p.stdout is not None
        for line in p.stdout:
            print(line,end="",flush=True)
        return p.wait()


def run(series, seasons=()):
    before=plan(series,seasons)
    receipt={"schema":"subhub-finish-scope-v1","series":series,
             "seasons":before["seasons"],"phase":"source",
             "state":"running","before":{k:v for k,v in before.items()
                                         if k!="picks"}}
    write_state(receipt)
    print("FINISH_BEGIN",json.dumps(receipt["before"],ensure_ascii=False),flush=True)
    if before["missing"] == 0:
        receipt.update(state="completed",phase="done",remaining=0)
        write_state(receipt)
        print("FINISH_COMPLETE all_selected_episodes_have_japanese",flush=True)
        return 0
    # One provider-bounded source pass. Its existing per-item/state locks,
    # Japanese identity checks, quota ceilings and publication QA remain intact.
    source=[SOURCE,"--series",series,"--max-searches",str(MAX_SEARCHES),"--run"]
    for sn in before["seasons"]:
        source.extend(("--season",str(sn)))
    rc=command(source,"source")
    if rc:
        receipt.update(state="held",phase="source_failed",source_rc=rc)
        write_state(receipt)
        print("FINISH_HELD source_worker_failed",flush=True)
        return 1
    after_source=plan(series,before["seasons"])
    receipt.update(phase="translation",after_source={
        k:v for k,v in after_source.items() if k!="picks"})
    write_state(receipt)
    picks=after_source["picks"]
    if picks:
        args=[TRANSLATOR,"--run","--series",series,"--season",
              str(picks[0]["season"])]
        for pick in picks:
            args.extend(("--pick",f'S{pick["season"]:02d}E{pick["episode"]:03d}'))
        rc=command(args,"plamo")
        if rc:
            print("FINISH_PLaMO_HELD work_checkpointed_review_needed",flush=True)
    # A partially searched scope cannot be described as finished.
    final=plan(series,before["seasons"])
    receipt.update(state="completed" if final["missing"]==0 else "partial",
                   phase="done",remaining=final["missing"],
                   after={k:v for k,v in final.items() if k!="picks"})
    write_state(receipt)
    print("FINISH_RESULT",json.dumps({"remaining":final["missing"],
        "covered":final["covered"],"total":final["total"],
        "state":receipt["state"]},ensure_ascii=False),flush=True)
    return 0 if final["missing"]==0 else 2


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--series",required=True)
    p.add_argument("--season",type=int,action="append",default=[])
    p.add_argument("--run",action="store_true")
    opts=p.parse_args(argv)
    if not opts.series or len(opts.series)>160 or any(
            ord(ch)<32 for ch in opts.series):
        p.error("invalid series")
    if len(opts.season)>60 or len(set(opts.season))!=len(opts.season) or any(
            not 1<=s<=60 for s in opts.season):
        p.error("invalid seasons")
    if opts.run:
        return run(opts.series,opts.season)
    print(json.dumps(plan(opts.series,opts.season),ensure_ascii=False))
    return 0


if __name__=="__main__":
    try:
        raise SystemExit(main())
    except (OSError,ValueError,RuntimeError) as e:
        print("FINISH_HELD",type(e).__name__,str(e)[:160],file=sys.stderr)
        raise SystemExit(1)
