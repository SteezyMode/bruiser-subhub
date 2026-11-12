#!/usr/bin/env python3
"""One-shot, read-only comparison of global and piecewise ffsubsync.

Runs on the owner OptiPlex, uses existing Sublarr Docker image's ffsubsync
against its read-only media bind and saved Japanese staging. The only files
written are temporary SRTs inside the container's /config, deleted immediately.
Never publishes, writes media, contacts subtitle providers or invokes AI.

Compare output only as diagnostics: source text must remain identical,
and audio VAD consistency ALONE never authorizes publication.
"""
from __future__ import annotations
import argparse
from difflib import SequenceMatcher
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import statistics
import subprocess
from urllib.parse import quote

try:
    from . import ja_first_srt_normalize as clean
except ImportError:
    import ja_first_srt_normalize as clean

ROOT=Path.home()/"bruiser-pilot/ja-first-inventory"
ALLOWED=(Path("/mnt/BigDisk/Video"),Path("/mnt/2TB/Plex Expansion"))
CONTAINER="sublarr-pilot"
JID=re.compile(r"[a-f0-9]{32}\Z")
STAMP=re.compile(r"\A((?:\d{1,3}:)?\d{2}:\d{2}[,.]\d{2,3})\s*-->\s*"
                 r"((?:\d{1,3}:)?\d{2}:\d{2}[,.]\d{2,3})\Z")
WORKER=r'''
import base64,json,subprocess,sys,tempfile
from pathlib import Path
video=Path(sys.argv[1])
penalty=sys.argv[2]
if not video.is_file() or penalty not in ("global","10"):
    raise SystemExit("invalid_trial_arguments")
raw=sys.stdin.buffer.read(2000001)
if not 0<len(raw)<=2000000:
    raise SystemExit("invalid_trial_subtitle_size")
with tempfile.TemporaryDirectory(prefix="subhub-piecewise-trial-",
                                 dir="/config") as tmp:
    src=Path(tmp)/"input.srt"
    out=Path(tmp)/"output.srt"
    src.write_bytes(raw)
    cmd=["ffsubsync",str(video),"-i",str(src),"-o",str(out)]
    if penalty!="global":
        cmd.extend(["--split-penalty",penalty,"--max-offset-seconds","90"])
    p=subprocess.run(cmd,capture_output=True,timeout=900)
    if p.returncode or not out.is_file() or not 0<out.stat().st_size<=2000000:
        print("TRIAL_RESULT_JSON:"+json.dumps(
            {"ok":False,"reason":"ffsubsync_failure","rc":p.returncode,
             "stderr":p.stderr.decode("utf8","replace")[-500:]}))
    else:
        print("TRIAL_RESULT_JSON:"+json.dumps(
            {"ok":True,"aligned_b64":base64.b64encode(out.read_bytes()).decode()}))
'''


def _index():
    p=sorted(ROOT.glob("ja-intake-*.json"))
    if not p or p[-1].is_symlink():
        raise RuntimeError("private_jellyfin_manifest_missing")
    d=json.loads(p[-1].read_text("utf8"))
    return {str(x.get("jellyfin_id")):x for x in d["items"]
            if isinstance(x,dict) and JID.fullmatch(
                str(x.get("jellyfin_id") or ""))}


def _stage(jid):
    db=ROOT/"japanese-stage.sqlite3"
    if not db.is_file() or db.is_symlink():
        raise RuntimeError("private_stage_database_missing")
    uri="file:"+quote(str(db.resolve()),safe="/")+"?mode=ro"
    with sqlite3.connect(uri,uri=True,timeout=10) as con:
        rows=con.execute(
            "SELECT subtitle_id,host_path,sha256,status,metrics_json "
            "FROM staged WHERE jellyfin_id=? AND status IN ('staged','held_duration_mismatch') "
            "ORDER BY staged_at DESC",(jid,)).fetchall()
    found=[]
    for sid,path,digest,status,metrics in rows:
        p=Path(path)
        if (p.is_symlink() or not p.is_file()
                or not p.resolve().is_relative_to((ROOT/"staged").resolve())
                or not 0<p.stat().st_size<=2_000_000):
            continue
        raw=p.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=digest:
            continue
        m=json.loads(metrics)
        normalized,report=clean.normalize(
            raw,expected_timestamps=m.get("cues"))
        found.append((sid,normalized,report))
    return found


def _map_video(video):
    path=Path(video)
    if (not path.is_absolute() or not path.is_file()
            or path.is_symlink() or not any(
                path.resolve().is_relative_to(root.resolve()) for root in ALLOWED)):
        raise RuntimeError("media_file_not_safe_or_available")
    p=subprocess.run(["docker","inspect","--format","{{json .Mounts}}",CONTAINER],
                     capture_output=True,text=True,check=True,timeout=30)
    mounts=json.loads(p.stdout)
    options=[]
    for m in mounts:
        if m.get("Type")!="bind":
            continue
        root=Path(m["Source"])
        try:
            relative=path.relative_to(root)
        except ValueError:
            continue
        options.append((len(root.parts),str(Path(m["Destination"])/relative)))
    if not options:
        raise RuntimeError("video_not_visible_in_sublarr")
    return max(options)[1]


def _parse(raw):
    text=raw.decode("utf-8-sig")
    items=[]
    for block in re.split(r"\r?\n[ \t]*\r?\n",text.strip()):
        lines=block.strip().splitlines()
        ix=int(bool(lines and lines[0].strip().isdigit()))
        if len(lines)<ix+2:
            raise RuntimeError("trial_output_bad_cue")
        match=STAMP.fullmatch(lines[ix].strip())
        if not match:
            raise RuntimeError("trial_output_bad_stamp")
        a,b=map(clean._milliseconds,match.groups())
        if b<=a:
            raise RuntimeError("trial_output_invalid_interval")
        items.append((a,b,"\n".join(lines[ix+1:]).strip()))
    return items


def _diagnose_cue_changes(before,after):
    """Explain missing/altered cue identities WITHOUT declaring sync safe.

    A subtitle tool can drop one subtitle (often release metadata), but we
    must identify that text before deciding whether to retry differently.
    Never use matched-only timing data as approval to publish.
    """
    a=["".join(c[2].split()) for c in before]
    b=["".join(c[2].split()) for c in after]
    matcher=SequenceMatcher(None,a,b,autojunk=False)
    changes=[]
    matched=[]
    for tag,lo,hi,l2,h2 in matcher.get_opcodes():
        if tag=="equal":
            matched.extend((i,l2+i-lo) for i in range(lo,hi))
            continue
        if len(changes)>=8:
            continue
        changes.append({
            "edit":tag,
            "source_cues":[{"number":i+1,
                             "at_seconds":round(before[i][0]/1000,3),
                             "text":before[i][2][:150]}
                            for i in range(lo,min(hi,lo+3))],
            "output_cues":[{"number":i+1,
                             "at_seconds":round(after[i][0]/1000,3),
                             "text":after[i][2][:150]}
                            for i in range(l2,min(h2,l2+3))],
            "source_span":hi-lo,"output_span":h2-l2
        })
    result={"matching_dialogue_cues":len(matched),"cue_edits":changes,
            "diagnostic_only":True}
    if len(matched)>=9:
        thirds=[]
        for lo,hi in ((0,len(before)//3),
                      (len(before)//3,2*len(before)//3),
                      (2*len(before)//3,len(before))):
            values=[(after[j][0]-before[i][0])/1000 for i,j in matched
                    if lo<=i<hi]
            thirds.append(round(statistics.median(values),3) if values else None)
        result["matched_only_shift_median_by_third_seconds"]=thirds
    return result


def _evaluate(original,output,runtime):
    before=_parse(original)
    after=_parse(output)
    if len(before)!=len(after):
        return {"safe_dialogue":False,"failure":"cue_count_changed",
                "before":len(before),"after":len(after),
                **_diagnose_cue_changes(before,after)}
    if any("".join(a[2].split())!="".join(b[2].split())
           for a,b in zip(before,after)):
        return {"safe_dialogue":False,"failure":"dialogue_text_changed",
                **_diagnose_cue_changes(before,after)}
    offsets=[(b[0]-a[0])/1000 for a,b in zip(before,after)]
    thirds=[offsets[:len(offsets)//3],
            offsets[len(offsets)//3:2*len(offsets)//3],
            offsets[2*len(offsets)//3:]]
    return {"safe_dialogue":True,"cues":len(before),
            "shift_min_seconds":round(min(offsets),2),
            "shift_max_seconds":round(max(offsets),2),
            "shift_median_by_third":[round(statistics.median(x),2) for x in thirds],
            "reordered":any(after[i][0]<after[i-1][0]
                            for i in range(1,len(after))),
            "final_end_after_seconds":round(max(x[1] for x in after)/1000,2),
            "video_seconds":round(runtime,2),
            "outside_video_count":sum(x[1]>runtime*1000+5000 for x in after),
            "validated_independently":False}


def _run(video,original,mode,runtime):
    result=subprocess.run(
        ["docker","exec","-i",CONTAINER,"python3","-c",WORKER,
         video,"global" if mode=="global" else "10"],
        input=original,capture_output=True,timeout=990,check=False)
    body=result.stdout.decode("utf-8","replace").splitlines()
    matches=[x.partition("TRIAL_RESULT_JSON:")[2] for x in body
             if x.startswith("TRIAL_RESULT_JSON:")]
    if result.returncode or len(matches)!=1:
        return {"error":"container_or_trial_failed",
                "rc":result.returncode,"stderr":result.stderr.decode(
                    "utf8","replace")[-260:]}
    record=json.loads(matches[0])
    if not record["ok"]:
        return {"error":record.get("reason"),"rc":record.get("rc"),
                "stderr":record.get("stderr")}
    output=base64.b64decode(record["aligned_b64"],validate=True)
    return _evaluate(original,output,runtime)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--id",action="append",required=True,
                        help="exact Jellyfin movie ID; may repeat")
    parser.add_argument("--all-staged",action="store_true",
                        help="compare each saved release, not just latest")
    args=parser.parse_args(argv)
    if len(args.id)>6 or any(not JID.fullmatch(jid) for jid in args.id):
        parser.error("1..6 exact Jellyfin IDs required")
    rows=_index()
    print("=== GLOBAL VS PIECEWISE FFSUBSYNC — DRY RUN ===",flush=True)
    for jid in args.id:
        row=rows.get(jid)
        if not row:
            print("NOT IN CURRENT INVENTORY:",jid[:8],flush=True)
            continue
        print("\nMOVIE:",row.get("title"),row.get("year"),
              "ID:",jid[:8],flush=True)
        try:
            mapped=_map_video(row.get("host_path"))
            runtime=float((row.get("run_time_ticks") or 0)/10_000_000)
            if runtime<=0:
                # Use stage runtime, not an inferred cut length.
                db=ROOT/"japanese-stage.sqlite3"
                with sqlite3.connect("file:"+quote(str(db.resolve()),safe="/")+
                                     "?mode=ro",uri=True,timeout=8) as conn:
                    item=conn.execute(
                        "SELECT metrics_json FROM staged WHERE jellyfin_id=? "
                        "ORDER BY staged_at DESC LIMIT 1",(jid,)).fetchone()
                runtime=float(json.loads(item[0]).get("video_seconds") or 0)
            if runtime<600:
                raise RuntimeError("video_duration_unavailable")
            try:
                records=_stage(jid)
            except RuntimeError as exc:
                print("  STRUCTURE HOLD:",str(exc),flush=True)
                if str(exc)=="staged_srt_cue_order_invalid":
                    print("  A source timestamp reversal must be investigated "
                          "before running audio sync; cue text is untouched.",
                          flush=True)
                continue
            if not records:
                print("  No safely staged Japanese SRT",flush=True)
            for sid,source,repair in records if args.all_staged else records[:1]:
                print("  STAGE:",sid,"repaired:",
                      repair["structural_repair"],"cues:",
                      repair["retained_dialogue_cues"],flush=True)
                for mode in ("global","piecewise_10"):
                    print("  TESTING:",mode,flush=True)
                    try:
                        report=_run(mapped,source,mode,runtime)
                    except (OSError,ValueError,RuntimeError,
                            subprocess.TimeoutExpired) as exc:
                        report={"error":type(exc).__name__+":"+str(exc)[:110]}
                    print("  RESULT",mode,json.dumps(
                        report,ensure_ascii=False),flush=True)
        except (OSError,ValueError,RuntimeError,
                subprocess.CalledProcessError) as exc:
            print("  HOLD:",type(exc).__name__,str(exc)[:220],flush=True)
    print("\nNO PUBLICATION. No saved Japanese subtitles, videos, or "
          "provider histories changed.",flush=True)


if __name__=="__main__":
    main()
