#!/usr/bin/env python3
"""Read-only ALASS recovery audit for already-held non-anime movie subtitles.

Run on the existing OptiPlex host. The audit reads the current private
Jellyfin inventory, the staged JA database, and real previous publisher hold
receipts from the source worker journal. It tests a bounded sample of those
same saved candidates through the INSTALLED ja_first_alass.prepare() code.

No provider searches, subtitle downloads, ffsubsync runs, publication, queue
updates, PLaMo work, or modifications to movie/subtitle files. ALASS uses
temporary scratch files which it deletes. This intentionally tests the normal
ALASS fallback path, NOT the earlier ineffective intensive ALASS sweep.
"""
from __future__ import annotations

import argparse
from collections import Counter, OrderedDict
import json
from pathlib import Path
import subprocess
import sys

HOST = Path.home() / "bruiser-pilot/subhub-control"
if str(HOST) not in sys.path:
    sys.path.insert(0,str(HOST))

import ja_first_alass as alass
import ja_first_movie_scope as movie_scope
import ja_first_publish_queue as queue
from benchmark_subtitle_search_paths import load_latest_manifest

SOURCE_UNIT = "bruiser-ja-source-autofill.service"
BUSY_UNITS = (
    SOURCE_UNIT, "bruiser-subhub-season-sources.service",
    "bruiser-subhub-batch.service", "bruiser-subhub-translation-batch.service",
    "bruiser-subhub-jellyfin-source.service", "bruiser-subhub-movie-ja.service",
    "bruiser-subhub-finish-scope.service",
)
TEXT_CODECS = {"subrip","srt","ass","ssa","mov_text","webvtt","text"}
EN_LANGS = {"en","eng","english"}


def require_idle(*,runner=subprocess.run):
    for unit in BUSY_UNITS:
        p=runner(["systemctl","--user","show","-p","ActiveState","--value",unit],
                 capture_output=True,text=True,check=False,timeout=8)
        if p.returncode or p.stdout.strip() not in ("inactive","failed"):
            raise RuntimeError("another_subhub_job_active_or_unverifiable:"+unit+
                               ":"+p.stdout.strip()[:40])


def held_ids(*,runner=subprocess.run):
    """Only genuine held receipts; never mistake untried staged rows for held."""
    p=runner(["journalctl","--user","-u",SOURCE_UNIT,"-o","cat",
              "--since","3 days ago","--no-pager"],
             capture_output=True,text=True,check=False,timeout=35)
    if p.returncode:
        raise RuntimeError("source_worker_journal_unavailable")
    ids=set()
    for line in p.stdout.splitlines():
        if not line.startswith("BRUISER_PUBLISH_ITEM:"):
            continue
        try:
            item=json.loads(line.partition(":")[2])
            jid=str(item.get("jellyfin_id") or "")
            if (item.get("result")=="held" and
                    queue.direct.EXPECTED_ID_PATTERN.fullmatch(jid)):
                ids.add(jid)
        except (ValueError,TypeError,AttributeError):
            continue
    return ids


def embedded_en(video,*,runner=subprocess.run):
    """Fast stream metadata only. ALASS itself extracts actual EN on trial."""
    try:
        p=runner(["ffprobe","-v","error","-show_streams","-of","json",str(video)],
                 capture_output=True,check=False,timeout=30)
        if p.returncode:
            return False
        streams=json.loads(p.stdout).get("streams") or []
        return any(
            isinstance(s,dict) and s.get("codec_type")=="subtitle" and
            s.get("codec_name") in TEXT_CODECS and
            str((s.get("tags") or {}).get("language") or "").lower() in EN_LANGS and
            not (s.get("disposition") or {}).get("forced")
            for s in streams
        )
    except (OSError,ValueError,TypeError,subprocess.TimeoutExpired):
        return False


def english_sidecar(video):
    """Read-only indication of an EN reference overlooked by NORMAL ALASS."""
    return alass._intensive_external_english(video) is not None


def candidates(rows,stage_rows,held):
    by_id={str(row.get("jellyfin_id") or ""):row for row in rows
           if isinstance(row,dict)}
    picked=OrderedDict()
    for jid,sid,_ in stage_rows:
        jid=str(jid)
        if jid not in held or jid in picked:
            continue
        row=by_id.get(jid)
        if (row is None or row.get("status")!="ready_ja_search" or
                not movie_scope.matches(row,movie_scope.MOVIES_NO_ANIME)):
            continue
        picked[jid]=(str(sid),row)
    return picked


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--english-limit",type=int,default=4)
    parser.add_argument("--audio-limit",type=int,default=2)
    args=parser.parse_args(argv)
    if not 0<=args.english_limit<=8 or not 0<=args.audio_limit<=8 or not (
        args.english_limit or args.audio_limit):
        parser.error("Need 1..8 English and/or 1..8 audio trials")
    require_idle()
    if not alass.available():
        raise RuntimeError("installed_alass_unavailable")
    rows=load_latest_manifest()
    stages=queue.stages()
    holds=held_ids()
    options=candidates(rows,stages,holds)
    print("AUDIT: prior held movie titles:",len(options),
          "| held receipts (all media):",len(holds),flush=True)
    if not options:
        print("NO ELIGIBLE HELD MOVIES: no provider or media changes made",flush=True)
        return

    embedded=[]
    audio=[]
    with_sidecar=0
    for jid,(sid,row) in options.items():
        video=Path(str(row.get("host_path") or ""))
        if video.is_symlink() or not video.is_file():
            continue
        has_embedded=embedded_en(video)
        # Only scan for external sidecars when no embedded reference exists.
        has_sidecar=not has_embedded and english_sidecar(video)
        with_sidecar+=int(has_sidecar)
        record=(jid,sid,row,has_embedded,has_sidecar)
        (embedded if has_embedded else audio).append(record)
    print("REFERENCE INVENTORY: embedded EN:",len(embedded),
          "| no embedded EN:",len(audio),
          "| no embedded EN but local EN sidecar:",with_sidecar,flush=True)
    selected=embedded[:args.english_limit]+audio[:args.audio_limit]
    print("TEST PLAN: English-reference trials:",min(len(embedded),args.english_limit),
          "| audio-only trials:",min(len(audio),args.audio_limit),flush=True)
    if not selected:
        print("NO TRIALS: selected reference groups are empty",flush=True)
        return

    verdicts=Counter()
    for idx,(jid,sid,row,has_embedded,has_sidecar) in enumerate(selected,1):
        # Recheck work state before each potentially costly audio alignment.
        require_idle()
        label=str(row.get("title") or "Unnamed movie")
        print("\nTRIAL",idx,"/",len(selected),json.dumps({
            "movie":label,"year":row.get("year"),"jellyfin_id":jid,
            "subtitle_id":sid,"embedded_english":has_embedded,
            "english_sidecar":has_sidecar},ensure_ascii=False),flush=True)
        try:
            ready=alass.prepare(jid,sid)
            details=ready["assessment"]
            ref=details.get("alignment_reference","unknown")
            verdicts["ready"]+=1
            if has_embedded and ref=="video_audio":
                verdicts["english_to_audio_fallback_ready"]+=1
            print("TRIAL_RESULT",json.dumps({
                "status":"ready_dry_run","movie":label,"reference":ref,
                "shift_min_s":details.get("shift_min_s"),
                "shift_max_s":details.get("shift_max_s"),
                "nonuniform_correction":details.get("nonuniform_correction"),
                "published":False},ensure_ascii=False),flush=True)
        except (RuntimeError,ValueError,OSError,KeyError,subprocess.TimeoutExpired,
                subprocess.CalledProcessError) as exc:
            verdicts["held"]+=1
            msg=(str(exc) or type(exc).__name__)[:250]
            category=msg.partition(":")[0]
            verdicts["reason:"+category]+=1
            print("TRIAL_RESULT",json.dumps({
                "status":"held","movie":label,
                "reason":msg,"published":False},ensure_ascii=False),flush=True)
    print("\nAUDIT_SUMMARY:",json.dumps(dict(verdicts),sort_keys=True),flush=True)
    print("READ ONLY: no provider, ffsubsync, AI, subtitle publication or queue writes.",
          flush=True)


if __name__=="__main__":
    try:
        main()
    except (RuntimeError,OSError,ValueError,subprocess.TimeoutExpired) as exc:
        print("AUDIT_HELD:",type(exc).__name__,str(exc)[:200],file=sys.stderr)
        raise SystemExit(1) from None
