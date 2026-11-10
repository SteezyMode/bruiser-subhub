#!/usr/bin/env python3
"""Read-only private EN/JA subtitle review packet for completed IASIP PLaMo8B.

Discovers ACTUAL published .ja.PLaMo8B.srt sidecars in the two existing series
roots. Prefers the exact model-pinned English input when available. Otherwise
extracts same-video embedded English *as a labeled comparison, not proof that
it matches the translator's source*. Emits full text/timing pairs to stdout;
redirect into a PRIVATE local file, NEVER public GitHub.
No service change, provider request, generation or media write.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOTS = (
    Path("/mnt/2TB/Plex Expansion/Television/Episodic/It's Always Sunny in Philadelphia"),
    Path("/mnt/BigDisk/Video/Television/Episodic/It's Always Sunny in Philadelphia"),
)
MANIFEST_ROOTS = (
    Path.home()/"bruiser-pilot/subhub-translation",
    Path.home()/"bruiser-pilot/plamo3-ab",
)
SUFFIX = ".ja.PLaMo8B.srt"
EXTENSIONS = {".mkv",".mp4",".avi",".m4v",".webm"}
TIMES = re.compile(
    r"(?P<sh>\d{1,3}):(?P<sm>\d\d):(?P<ss>\d\d)[,.](?P<sms>\d{3})"
    r"\s*-->\s*"
    r"(?P<eh>\d{1,3}):(?P<em>\d\d):(?P<es>\d\d)[,.](?P<ems>\d{3})"
)
EP = re.compile(r"(?i)(?<![A-Za-z0-9])S(\d{1,2})E(\d{1,3})(?!\d)")
JA = re.compile(r"[\u3040-\u30ff\u3400-\u9fff]")
LIMIT = 2_000_000


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def ms(h,m,s,sub):
    return ((int(h)*3600+int(m)*60+int(s))*1000+int(sub))


def cues(raw):
    if not raw or len(raw)>LIMIT:
        raise ValueError("invalid_srt_size")
    v=raw.decode("utf-8-sig").replace("\r\n","\n")
    out=[]
    for block in re.split(r"\n\s*\n",v.strip()):
        lines=block.strip().split("\n")
        row=1 if lines[0].strip().isdigit() else 0
        if row>=len(lines):raise ValueError("srt_block_empty")
        t=TIMES.search(lines[row])
        if not t or row+1>=len(lines):raise ValueError("bad_srt_timestamps")
        g=t.groupdict()
        begin=ms(g["sh"],g["sm"],g["ss"],g["sms"])
        end=ms(g["eh"],g["em"],g["es"],g["ems"])
        if end<=begin:raise ValueError("bad_srt_interval")
        out.append({"number":int(lines[0]) if row else len(out)+1,
                    "start_ms":begin,"end_ms":end,
                    "text":"\n".join(lines[row+1:]).strip()})
    return out


def discover():
    found=[]
    for root in ROOTS:
        if not root.is_dir():continue
        for sub in root.rglob("*.srt"):
            if sub.is_symlink() or not sub.is_file():
                continue
            if not sub.name.casefold().endswith(SUFFIX.casefold()):
                continue
            stem=sub.name[:-len(SUFFIX)]
            videos=[p for p in sub.parent.iterdir()
                    if p.is_file() and not p.is_symlink()
                    and p.suffix.casefold() in EXTENSIONS and p.stem==stem]
            if len(videos)==1:
                found.append((videos[0],sub))
    return sorted(found,key=lambda p: str(p[0]))


def pinned_source(video):
    for root in MANIFEST_ROOTS:
        if not root.is_dir():continue
        for manifest in root.rglob("manifest.json"):
            if not manifest.is_file() or manifest.is_symlink() or manifest.stat().st_size>256_000:
                continue
            try:
                m=json.loads(manifest.read_text("utf-8"))
                if m.get("video")!=str(video):
                    continue
                source=manifest.with_name("source.en.srt")
                if source.is_symlink() or not source.is_file() or source.stat().st_size>LIMIT:
                    continue
                data=source.read_bytes()
                expected=m.get("english_sha256")
                if expected and sha(data)!=expected:
                    continue
                if len(cues(data))<30:
                    continue
                return data,"pinned_PLaMo_source",str(manifest)
            except (ValueError,OSError,UnicodeError,TypeError):
                continue
    return None,None,None


def embedded_source(video):
    p=subprocess.run(["ffprobe","-v","error","-show_streams","-of","json",
                      str(video)],capture_output=True,timeout=40)
    if p.returncode:return None
    try:
        streams=json.loads(p.stdout)["streams"]
    except (ValueError,KeyError):
        return None
    indices=[]
    for stream in streams:
        if stream.get("codec_type")!="subtitle":
            continue
        if stream.get("codec_name") not in {"subrip","ass","ssa","mov_text","webvtt","text"}:
            continue
        lang=str(stream.get("tags",{}).get("language","")).lower()
        if lang in ("en","eng","english") and not stream.get("disposition",{}).get("forced"):
            indices.append(stream["index"])
    for idx in indices:
        p=subprocess.run(
            ["ffmpeg","-nostdin","-hide_banner","-loglevel","error",
             "-i",str(video),"-map",f"0:{idx}","-c:s","srt","-f","srt","pipe:1"],
            capture_output=True,timeout=90
        )
        if p.returncode==0 and 100<len(p.stdout)<LIMIT:
            try:
                if len(cues(p.stdout))>=30:
                    return p.stdout
            except (UnicodeError,ValueError):
                pass
    return None


def detail(video,sub):
    raw=sub.read_bytes()
    ja=cues(raw)
    en_raw,kind,manifest=pinned_source(video)
    if en_raw is None:
        en_raw=embedded_source(video)
        kind="embedded_same_video_comparison_not_confirmed_PLaMo_source" if en_raw else "english_not_found"
    en=cues(en_raw) if en_raw else []
    mapped={c["number"]:c for c in en}
    matched=sum(c["number"] in mapped and abs(c["start_ms"]-mapped[c["number"]]["start_ms"])<1000 for c in ja)
    tag=EP.search(video.name)
    return {
        "episode":f"S{int(tag.group(1)):02}E{int(tag.group(2)):02}" if tag else "unknown",
        "title":video.stem,"video":str(video),"japanese_sidecar":str(sub),
        "japanese_sha256":sha(raw),"english_source":kind,
        "english_manifest":manifest,
        "english_sha256":sha(en_raw) if en_raw else None,
        "japanese_cues":len(ja),"english_cues":len(en),
        "timing_pairs_within_1s":matched,
        "japanese_char_fraction":round(sum(bool(JA.search(c["text"])) for c in ja)/len(ja),3),
        "english":en,"japanese":ja
    }


def main():
    selected=discover()
    reports=[]
    for video,sub in selected:
        try:
            reports.append(detail(video,sub))
        except (OSError,ValueError,UnicodeError,subprocess.TimeoutExpired) as err:
            reports.append({"title":video.stem,"japanese_sidecar":str(sub),
                            "error":type(err).__name__})
    json.dump({
        "schema":"iasip_plamo_real_subtitle_review_v1",
        "read_only":True,"translation_jobs_started":0,
        "found_published_PLaMo_sidecars":len(selected),
        "episodes":reports
    },sys.stdout,ensure_ascii=False,indent=2)
    sys.stdout.write("\n")

if __name__=="__main__":
    main()
