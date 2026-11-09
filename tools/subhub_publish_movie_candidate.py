#!/usr/bin/env python3
"""Host-side create-only publication of a validated, previously staged movie subtitle.

This bridges Sublarr's read-only library bind mount: no provider re-downloads,
no media edits, no remounting and no overwrite of existing Japanese subtitles.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

VIDEO_EXT={".mkv",".mp4",".avi",".m4v",".mov"}
MEDIA_ROOTS=(Path("/mnt/2TB"),Path("/mnt/BigDisk"),Path("/mnt/1TBNVME"))
STAGING="/config/bruiser-ja-screened"
REPORT=re.compile(r"/config/bruiser-ja-screened/([0-9a-f]{20})/report-([0-9a-f]{20})\.json\Z")
JP=re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uff66-\uff9f]")
TIMING=re.compile(r"(\d\d:\d\d:\d\d[,.]\d{3})\s*-->\s*(\d\d:\d\d:\d\d[,.]\d{3})")

def video_safety(video):
    if video.suffix.lower() not in VIDEO_EXT or video.is_symlink() or not video.is_file():
        raise RuntimeError("selected_movie_missing_or_unsafe")
    if not any(video.is_relative_to(root) for root in MEDIA_ROOTS):
        raise RuntimeError("movie_outside_existing_media_drives")
    if any(parent.is_symlink() for parent in video.parents):
        raise RuntimeError("symlink_in_video_path")
    return video

def docker_read(path,runner=subprocess.run):
    p=runner(["docker","exec","sublarr-pilot","cat",path],
             stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
             timeout=45,check=True)
    if not 0<len(p.stdout)<=3_000_000:
        raise RuntimeError("missing_or_oversized_staged_candidate")
    return p.stdout

def container_path(video,runner=subprocess.run):
    p=runner(["docker","inspect","-f","{{json .Mounts}}","sublarr-pilot"],
             capture_output=True,timeout=30,check=True)
    binds=json.loads(p.stdout)
    matches=[]
    for bind in binds:
        if bind.get("Type")!="bind":continue
        src=Path(str(bind.get("Source") or ""))
        dest=Path(str(bind.get("Destination") or ""))
        if src.is_absolute() and dest.is_absolute() and video.is_relative_to(src):
            matches.append((len(src.parts),str(dest/video.relative_to(src))))
    if not matches:
        raise RuntimeError("movie_not_in_sublarr_library_mount")
    return max(matches)[1]

def stamp_ms(value):
    h,m,rest=value.replace(".",",").split(":")
    sec,millis=rest.split(",")
    return ((int(h)*60+int(m))*60+int(sec))*1000+int(millis)

def cues(raw):
    try:txt=raw.decode("utf-8-sig")
    except UnicodeError as exc:raise RuntimeError("subtitle_not_utf8") from exc
    blocks=re.split(r"\r?\n\s*\r?\n",txt.strip())
    result=[]
    for block in blocks:
        lines=block.splitlines()
        if not lines:continue
        start=1 if lines[0].strip().isdigit() else 0
        if len(lines)<start+2:raise RuntimeError("malformed_subtitle")
        match=TIMING.fullmatch(lines[start].strip())
        if not match:raise RuntimeError("malformed_subtitle_timestamps")
        dialogue="\n".join(lines[start+1:]).strip()
        if not dialogue:raise RuntimeError("empty_subtitle_cue")
        a,b=stamp_ms(match[1]),stamp_ms(match[2])
        if b<=a:raise RuntimeError("invalid_cue_timing")
        result.append((a,b,dialogue))
    if not 100<=len(result)<=6000:raise RuntimeError("unexpected_subtitle_cue_count")
    if sum(bool(JP.search(x[2])) for x in result)/len(result)<.80:
        raise RuntimeError("candidate_not_predominantly_japanese")
    return result

def verify_candidate(source,aligned,runtime,report):
    if hashlib.sha256(source).hexdigest()!=report.get("sha256"):
        raise RuntimeError("source_checksum_mismatch")
    original,corrected=cues(source),cues(aligned)
    if len(original)!=len(corrected) or any(
        x[2]!=y[2] for x,y in zip(original,corrected)
    ):
        raise RuntimeError("alignment_changed_dialogue")
    shifts=[(y[0]-x[0])/1000 for x,y in zip(original,corrected)]
    if not shifts or max(abs(x) for x in shifts)>30 or max(shifts)-min(shifts)>8:
        raise RuntimeError("unexpected_timing_repair")
    first=min(x[0] for x in corrected)/1000
    last=max(x[1] for x in corrected)/1000
    if first>runtime*.25 or last<runtime*.76 or last>runtime+5:
        raise RuntimeError("subtitle_duration_inconsistent")
    ordered=sorted(corrected)
    if max((max(0,ordered[i+1][0]-ordered[i][1])
            for i in range(len(ordered)-1)),default=0)>900_000:
        raise RuntimeError("subtitle_large_gap")
    quality=report.get("quality_gate") or {}
    if quality.get("ok") is not True or (report.get("sync_preview") or {}).get("ok") is not True:
        raise RuntimeError("candidate_not_previously_approved")
    if abs(float(quality.get("video_seconds") or 0)-runtime)>2:
        raise RuntimeError("movie_changed_since_staging")
    return len(corrected)

def ffprobe(video,args,runner=subprocess.run):
    p=runner(["ffprobe","-v","error",*args,"-of","json",str(video)],
             capture_output=True,timeout=45,check=True)
    return json.loads(p.stdout)

def existing_ja(video):
    pattern=re.compile(r"\.(?:ja|jpn|japanese)(?:\.[a-z0-9]+)*\.(?:srt|ass|ssa|vtt)$",re.I)
    return any(p.name.startswith(video.stem+".") and pattern.search(p.name)
               for p in video.parent.iterdir())

def process(video,report_path,apply=False):
    video=video_safety(Path(video))
    match=REPORT.fullmatch(str(report_path))
    if not match:raise RuntimeError("invalid_staging_report_location")
    stage_id,candidate_id=match.groups()
    container_video=container_path(video)
    if hashlib.sha256(container_video.encode()).hexdigest()[:20]!=stage_id:
        raise RuntimeError("stage_is_for_different_movie_or_mount")
    report=json.loads(docker_read(str(report_path)))
    if report.get("video_file")!=video.name or report.get("source")!="opensubtitles":
        raise RuntimeError("stage_report_identity_mismatch")
    if report.get("source_format")!=".srt":raise RuntimeError("unsupported_subtitle_format")
    sha=report.get("sha256")
    if not isinstance(sha,str) or not re.fullmatch(r"[0-9a-f]{64}",sha) or not sha.startswith(candidate_id):
        raise RuntimeError("stage_checksum_identity_invalid")
    source=docker_read(f"{STAGING}/{stage_id}/source-{candidate_id}.srt")
    aligned=docker_read(f"{STAGING}/{stage_id}/aligned-{candidate_id}.srt")
    meta=ffprobe(video,["-show_entries","format=duration:stream=codec_type:stream_tags=language"])
    runtime=float(meta.get("format",{}).get("duration") or 0)
    if not 600<=runtime<=20000:raise RuntimeError("unreasonable_movie_runtime")
    cue_count=verify_candidate(source,aligned,runtime,report)
    if existing_ja(video) or any(
        s.get("codec_type")=="subtitle" and
        str((s.get("tags") or {}).get("language") or "").lower() in {"ja","jpn","japanese"}
        for s in meta.get("streams",[])
    ):
        raise RuntimeError("japanese_subtitle_already_present")
    target=video.with_name(video.stem+".ja.srt")
    if target.exists() or target.is_symlink():raise RuntimeError("target_already_exists")
    if not apply:
        return {"state":"ready","video":str(video),"target":str(target),"cues":cue_count}
    fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o644)
    try:
        with os.fdopen(fd,"wb") as stream:
            stream.write(aligned)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    return {"state":"published","video":str(video),"target":str(target),"cues":cue_count}

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video",required=True,type=Path)
    parser.add_argument("--report",required=True,type=Path)
    parser.add_argument("--apply",action="store_true")
    args=parser.parse_args(argv)
    print("MOVIE_JA_RESULT",json.dumps(process(args.video,args.report,args.apply),ensure_ascii=False))

if __name__=="__main__":
    try:main()
    except (ValueError,RuntimeError,OSError,subprocess.CalledProcessError,subprocess.TimeoutExpired) as exc:
        print("MOVIE_JA_HELD",str(exc)[:180],file=sys.stderr)
        raise SystemExit(1)
