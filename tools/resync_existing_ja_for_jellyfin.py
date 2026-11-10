#!/usr/bin/env python3
"""Create selectable Japanese sync PREVIEWS for IASIP S01E04 in Jellyfin.

Uses EXISTING Sublarr container's ffsubsync: one video-embedded-English reference
and one independent audio-speech reference. No accounts, provider searches,
translation, installs, or video changes. Keeps original JA sidecar intact.
Only the --preview-in-jellyfin flag creates new (never overwriting) preview
sidecars in the EXISTING season directory. Outputs and provenance are otherwise
held privately in ~/bruiser-pilot/ja-timing-previews.
"""
from __future__ import annotations
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import statistics
import subprocess
import sys
import tempfile

SERIES_DIR=Path("/mnt/2TB/Plex Expansion/Television/Episodic/It's Always Sunny in Philadelphia/Season 01")
PRIVATE=Path.home()/"bruiser-pilot/ja-timing-previews/sunny-s01e04"
VIDEO_EXT={".mkv",".mp4",".avi",".m4v",".webm"}
TEXT_CODECS={"subrip","ass","ssa","mov_text","webvtt","text"}
CONTAINER="sublarr-pilot"
TIMESTAMP=re.compile(r"(\d{2}:\d{2}:\d{2}[,.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,.]\d{3})")
JP=re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uff66-\uff9f]")
MAX_SUBTITLE=2_000_000

WORKER=r'''
import base64,json,subprocess,sys,tempfile
from pathlib import Path
payload=json.load(sys.stdin)
video=Path(payload["video"])
if not video.is_file(): raise SystemExit("video_not_accessible")
source=base64.b64decode(payload["japanese"],validate=True)
english=base64.b64decode(payload["english"],validate=True)
if not 0<len(source)<2000001 or not 0<len(english)<2000001:
    raise SystemExit("invalid_subtitle_size")
result={}
with tempfile.TemporaryDirectory(prefix="bruiser-ja-repair-") as d:
    tmp=Path(d)
    inp=tmp/"ja.srt"
    ref=tmp/"english.srt"
    inp.write_bytes(source)
    ref.write_bytes(english)
    attempts=(
      ("reference",["ffsubsync",str(ref),"-i",str(inp),"-o",str(tmp/"reference.srt")]),
      ("audio",["ffsubsync",str(video),"-i",str(inp),"-o",str(tmp/"audio.srt"),"--vad","webrtc"])
    )
    for label,cmd in attempts:
        try:
            p=subprocess.run(cmd,capture_output=True,timeout=600,check=False)
            out=tmp/(label+".srt")
            if p.returncode or not out.is_file():
                result[label]={"status":"sync_failed","exit":p.returncode}
            elif not 0<out.stat().st_size<=2000000:
                result[label]={"status":"invalid_sync_output"}
            else:
                result[label]={"status":"ok","bytes":base64.b64encode(out.read_bytes()).decode("ascii")}
        except subprocess.TimeoutExpired:
            result[label]={"status":"sync_timeout"}
print(json.dumps(result))
'''

def abort(msg):
    raise SystemExit("REPAIR BLOCKED: "+msg)

def digest(raw):
    return hashlib.sha256(raw).hexdigest()

def run(command,**kwargs):
    return subprocess.run(command,check=True,**kwargs)

def parse_stamp(s):
    h,m,sec=s.replace(".",",").split(":")
    sc,ms=sec.split(",")
    return ((int(h)*3600+int(m)*60+int(sc))*1000+int(ms))

def parse_srt(raw):
    try: value=raw.decode("utf-8-sig").replace("\r\n","\n")
    except UnicodeError: abort("Subtitle is not UTF-8")
    cues=[]
    for block in re.split(r"\n\s*\n",value.strip()):
        lines=block.strip().split("\n")
        pos=1 if lines and lines[0].strip().isdigit() else 0
        if len(lines)<pos+2:abort("Invalid SRT cue block")
        time=TIMESTAMP.search(lines[pos])
        if not time:abort("Invalid SRT timing")
        start,end=map(parse_stamp,time.groups())
        if start<0 or end<=start:abort("Invalid subtitle times")
        text="\n".join(lines[pos+1:]).strip()
        if not text:abort("Empty subtitle cue")
        cues.append((start,end,text))
    if not cues:abort("No subtitle cues")
    return cues

def video_and_japanese():
    if not SERIES_DIR.is_dir():abort("Existing Sunny Season 01 directory not found")
    vids=[p for p in SERIES_DIR.iterdir() if p.is_file() and not p.is_symlink()
          and p.suffix.lower() in VIDEO_EXT and re.search(r"(?i)(?<![A-Za-z0-9])S01E04(?!\d)",p.name)]
    if len(vids)!=1:abort(f"Expected one S01E04 video; found {len(vids)} (no changes)")
    video=vids[0]
    preferred=video.with_name(video.stem+".ja.srt")
    if preferred.is_file() and not preferred.is_symlink():
        ja=preferred
    else:
        choices=[p for p in video.parent.iterdir() if p.is_file() and not p.is_symlink()
                 and p.name.startswith(video.stem+".") and p.suffix.lower()==".srt"
                 and re.search(r"(?i)\.(?:ja|jpn|japanese)(?:\.|$)",p.name)
                 and "BruiserSync" not in p.name]
        if len(choices)!=1:abort(f"Expected one Japanese SRT for S01E04; found {len(choices)}")
        ja=choices[0]
    if not 0<ja.stat().st_size<=MAX_SUBTITLE:abort("Japanese subtitle empty or oversized")
    return video,ja

def video_info(video):
    p=run(["ffprobe","-v","error","-show_format","-show_streams",
           "-of","json",str(video)],capture_output=True,text=True,timeout=45)
    d=json.loads(p.stdout)
    duration=float(d.get("format",{}).get("duration") or 0)
    if not 600<duration<4*3600:abort("Unexpected video duration")
    choices=[]
    for st in d.get("streams",[]):
        if st.get("codec_type")!="subtitle" or st.get("codec_name") not in TEXT_CODECS:
            continue
        lang=str(st.get("tags",{}).get("language","")).casefold()
        title=str(st.get("tags",{}).get("title","")).casefold()
        disp=st.get("disposition",{})
        if lang not in {"en","eng","english"} or disp.get("forced"):
            continue
        quality=(0 if disp.get("hearing_impaired") else 1)
        if any(v in title for v in ("signs","forced","songs","karaoke")):
            quality-=3
        choices.append((quality,int(st["index"])))
    choices.sort(reverse=True)
    for _,idx in choices:
        extract=subprocess.run(["ffmpeg","-nostdin","-hide_banner","-loglevel","error",
                                "-i",str(video),"-map",f"0:{idx}","-c:s","srt",
                                "-f","srt","pipe:1"],capture_output=True,timeout=100)
        if extract.returncode or not 100<len(extract.stdout)<=MAX_SUBTITLE:
            continue
        try:
            en=parse_srt(extract.stdout)
            if len(en)>=100:
                return duration,idx,extract.stdout
        except SystemExit:
            continue
    abort("No usable embedded English text reference (this script is specific to S01E04)")

def container_video(video):
    p=run(["docker","inspect","--format","{{json .Mounts}}",CONTAINER],
          capture_output=True,text=True,timeout=20)
    mounts=json.loads(p.stdout)
    matches=[]
    for m in mounts:
        if m.get("Type")!="bind":continue
        root=Path(m.get("Source","/"))
        dest=Path(m.get("Destination","/"))
        try:
            suffix=video.resolve(strict=True).relative_to(root.resolve(strict=True))
        except (OSError,ValueError):
            continue
        matches.append((len(root.parts),dest/suffix))
    if not matches:abort("Current video is not mounted read-only in Sublarr")
    matches.sort(key=lambda x:x[0],reverse=True)
    if len(matches)>1 and matches[0][0]==matches[1][0]:
        abort("Ambiguous Sublarr media mount")
    return str(matches[0][1])

def align(video,ja,en):
    mapped=container_video(video)
    payload=json.dumps({"video":mapped,
                        "japanese":base64.b64encode(ja).decode(),
                        "english":base64.b64encode(en).decode()}).encode()
    try:
        p=run(["docker","exec","-i",CONTAINER,"python3","-c",WORKER],
              input=payload,capture_output=True,timeout=1250)
        data=json.loads(p.stdout)
    except (subprocess.CalledProcessError,subprocess.TimeoutExpired,ValueError) as exc:
        abort("Existing Sublarr ffsubsync runner failed: "+type(exc).__name__)
    return data

def validate(original,raw,duration):
    candidate=parse_srt(raw)
    if len(original)!=len(candidate):abort("Sync changed cue count")
    if [x[2] for x in original]!=[x[2] for x in candidate]:
        abort("Sync altered Japanese dialogue; refusing preview")
    if candidate[0][0]<0 or max(x[1] for x in candidate)>duration*1000+7000:
        abort("Sync moves cues outside video")
    if any(candidate[i+1][0]<candidate[i][0] for i in range(len(candidate)-1)):
        abort("Sync reorders cues")
    shifts=[(b[0]-a[0])/1000 for a,b in zip(original,candidate)]
    if max(abs(n) for n in shifts)>120:abort("Sync shifted over 120 seconds")
    summary={}
    for name,subset in (("opening",shifts[:max(1,len(shifts)//5)]),
                        ("middle",shifts[len(shifts)//3:2*len(shifts)//3]),
                        ("ending",shifts[-max(1,len(shifts)//5):])):
        summary[name+"_median_s"]=round(statistics.median(subset),3)
    summary.update(cues=len(candidate),shift_min_s=round(min(shifts),3),
                   shift_max_s=round(max(shifts),3),
                   original_sha256=None,
                   candidate_sha256=digest(raw))
    return summary

def write_create_only(path,data):
    if path.is_symlink():abort("Symlink at output path")
    if path.exists():
        if not path.is_file() or path.read_bytes()!=data:
            abort("Existing output differs: "+str(path))
        return False
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o644)
    with os.fdopen(fd,"wb") as f:
        f.write(data);f.flush();os.fsync(f.fileno())
    return True

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--preview-in-jellyfin",action="store_true",
                    help="Create separately selectable preview sidecars; never replace original JA")
    args=ap.parse_args()
    video,ja=video_and_japanese()
    original_bytes=ja.read_bytes()
    original=parse_srt(original_bytes)
    if len(original)<150 or sum(bool(JP.search(c[2])) for c in original)<len(original)*.35:
        abort("Existing JA subtitle is not a substantial Japanese dialogue track")
    duration,idx,en=video_info(video)
    print(f"VIDEO: {video.name} ({duration:.1f}s)")
    print(f"ORIGINAL JAPANESE: {ja.name}, {len(original)} cues, hash={digest(original_bytes)[:16]}")
    print(f"REFERENCE: existing embedded English stream #{idx}; no downloads")
    results=align(video,original_bytes,en)
    outputs=[]
    names={"reference":"BruiserSyncReference","audio":"BruiserSyncAudio"}
    for mode in ("reference","audio"):
        record=results.get(mode,{})
        if record.get("status")!="ok":
            print(f"ENGINE {mode}: {record.get('status','missing')}")
            continue
        raw=base64.b64decode(record["bytes"],validate=True)
        try:
            report=validate(original,raw,duration)
        except SystemExit as e:
            print(f"ENGINE {mode}: held ({str(e)[:130]})")
            continue
        report["original_sha256"]=digest(original_bytes)
        if raw==original_bytes:
            print(f"ENGINE {mode}: exact original output; not a correction")
            continue
        # Jellyfin supports title tokens in exact video-stem subtitle filenames.
        target=video.with_name(video.stem+"."+names[mode]+".ja.srt")
        outputs.append((mode,raw,report,target))
        print("ENGINE",mode,json.dumps(report,ensure_ascii=False))
    if not outputs:
        abort("Neither ffsubsync mode produced a safe changed-JA preview; original untouched")
    PRIVATE.mkdir(parents=True,exist_ok=True,mode=0o700)
    if PRIVATE.is_symlink() or PRIVATE.stat().st_mode & 0o077:
        abort("Private preview staging directory insecure")
    summary={"source_video":str(video),"source_ja":str(ja),
             "original_sha256":digest(original_bytes),"video_seconds":duration,
             "english_stream_index":idx,
             "status":"PREVIEW_ONLY_NOT_VERIFIED_BY_PLAYBACK",
             "variants":{}}
    for mode,raw,report,target in outputs:
        staging=PRIVATE/(mode+".ja.srt")
        write_create_only(staging,raw)
        summary["variants"][mode]={"private":str(staging),"jellyfin":str(target),
                                    "report":report}
    manifest=(json.dumps(summary,ensure_ascii=False,indent=2)+"\n").encode("utf-8")
    write_create_only(PRIVATE/"manifest.json",manifest)
    if args.preview_in_jellyfin:
        for mode,raw,report,target in outputs:
            write_create_only(target,raw)
            print(f"JELLYFIN PREVIEW ADDED [{mode}]: {target.name}")
        print("ACTION: refresh S01E04 metadata in Jellyfin if tracks do not appear;")
        print("compare BruiserSyncReference/BruiserSyncAudio in opening, middle, ending.")
        print("ORIGINAL remains intact and selectable. No preview marked default.")
    else:
        print("PRIVATE PREVIEWS READY (no media-side changes):",PRIVATE)
        print("Re-run --preview-in-jellyfin to expose new tracks for playback.")
    print("NOT CERTIFIED: actual spoken-dialogue playback still must choose the correct track")

if __name__=="__main__":
    try:main()
    except (OSError,ValueError,subprocess.SubprocessError) as exc:
        print("REPAIR BLOCKED:",type(exc).__name__,str(exc)[:160],file=sys.stderr)
        raise SystemExit(1) from None
