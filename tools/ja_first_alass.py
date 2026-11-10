#!/usr/bin/env python3
"""Standalone alass v2.0.0: full per-cue/split/framerate JA alignment.

One optional, reusable engine for the EXISTING SubHub staged-JA publication
queue. Keep original bytes and dialogue. Use the previously owner-tested alass
binary and actual video/audio. Never run providers, AI, or overwrite media.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import statistics
import subprocess
import tempfile

import ja_first_publish_staged as gate
import ja_first_ffsubsync as ff
import ja_first_obvious_quality as quality

BINARY = Path.home() / "bruiser-pilot/sync-compare.WfaxCBpD/alass-linux64"
MAX_ABSOLUTE_SHIFT_S = 120
MAX_ALIGNED_SIZE = 2_000_000

def available():
    """Only use the binary already verified on this host, not PATH substitutes."""
    return (BINARY.is_file() and not BINARY.is_symlink()
            and os.access(BINARY, os.X_OK)
            and 2_000_000 < BINARY.stat().st_size < 6_000_000)

def _sha(data):
    return hashlib.sha256(data).hexdigest()

def assess(original, corrected, runtime):
    """Reject corruption/identity changes; DO NOT reject valid split/drift repairs."""
    before=ff.parse_cues(original)
    after=ff.parse_cues(corrected)
    if len(before)!=len(after) or len(before)<20:
        raise RuntimeError("alass_cue_count_changed")
    if [x["text"] for x in before]!=[x["text"] for x in after]:
        raise RuntimeError("alass_dialogue_changed")
    if any(x["start"]<0 or x["end"]<=x["start"] for x in after):
        raise RuntimeError("alass_invalid_interval")
    if any(x["start"]<after[i-1]["start"] for i,x in enumerate(after) if i):
        raise RuntimeError("alass_reordered_cues")
    if max(x["end"] for x in after)>runtime*1000+5000:
        raise RuntimeError("alass_out_of_video")
    shifts=[(b["start"]-a["start"])/1000 for a,b in zip(before,after)]
    if any(abs(n)>MAX_ABSOLUTE_SHIFT_S for n in shifts):
        raise RuntimeError("alass_extreme_shift_requires_review")
    def median(part):
        return round(statistics.median(part),3)
    n=len(shifts)
    metrics={
        "engine":"standalone_alass_v2",
        "mode":"original" if corrected==original else "aligned",
        "cues":n, "shift_min_s":round(min(shifts),3),
        "shift_max_s":round(max(shifts),3),
        "opening_median_s":median(shifts[:max(1,n//5)]),
        "middle_median_s":median(shifts[n//3:2*n//3]),
        "ending_median_s":median(shifts[-max(1,n//5):]),
        "nonuniform_correction":max(shifts)-min(shifts)>1.5,
        "source_sha256":_sha(original), "aligned_sha256":_sha(corrected)
    }
    return metrics

def prepare(jid,sid,*,aligner=None):
    """Existing source identity, no-overwrite, quality gates; alass only changes timing."""
    if not available():
        raise RuntimeError("existing_alass_binary_missing")
    row=gate.read_inventory(jid)
    gate.verify_search_identity(row,jid,sid)
    _,raw,record=gate.read_staging(jid,sid)
    video=gate.safe_media_path(str(row.get("host_path") or ""))
    streams,error=gate.ffprobe_streams(video)
    if error or not isinstance(streams,list):
        raise RuntimeError("cannot_verify_video_subtitle_streams")
    gate.check_no_existing_ja(video,streams)
    runtime=float(record.get("video_seconds") or 0)
    if not 600<=runtime<=4*3600 or abs(gate.subprocess_duration(video)-runtime)>0.5:
        raise RuntimeError("original_video_has_changed")
    src_metrics=gate.validate_srt(raw,runtime)
    if src_metrics["cues"]!=int(record.get("cues") or -1):
        raise RuntimeError("staging_cue_count_has_changed")
    quality.require_not_garbage(raw)
    if aligner is None:
        aligned,reference_type=align(video,raw)
    else:
        aligned=aligner(video,raw)
        reference_type="test_or_external"
    if not 0<len(aligned)<=MAX_ALIGNED_SIZE:
        raise RuntimeError("invalid_alass_output_size")
    # Existing QA confirms Japanese content/coverage did not disappear.
    if gate.validate_srt(aligned,runtime)!=src_metrics:
        raise RuntimeError("alass_subtitle_health_changed")
    metrics=assess(raw,aligned,runtime)
    metrics["alignment_reference"]=reference_type
    return {
        "jid":jid,"sid":sid,"row":row,"video":video,
        "target":gate.video_target(video), "original":raw,"chosen":aligned,
        "assessment":metrics
    }

def _embedded_english(video):
    """Reuse an English text track from the SAME media file, when available."""
    p=subprocess.run(["ffprobe","-v","error","-show_streams","-of","json",str(video)],
                     capture_output=True,timeout=45,check=False)
    if p.returncode:
        return None
    try:
        streams=json.loads(p.stdout)["streams"]
    except (ValueError,KeyError,TypeError):
        return None
    for stream in streams:
        if stream.get("codec_type")!="subtitle" or stream.get("codec_name") not in {
                "subrip","ass","ssa","mov_text","webvtt","text"}:
            continue
        tag=str((stream.get("tags") or {}).get("language") or "").lower()
        if tag not in {"en","eng","english"} or stream.get("disposition",{}).get("forced"):
            continue
        index=stream.get("index")
        if not isinstance(index,int):
            continue
        result=subprocess.run(
            ["ffmpeg","-nostdin","-hide_banner","-loglevel","error",
             "-i",str(video),"-map",f"0:{index}","-c:s","srt","-f","srt","pipe:1"],
            capture_output=True,timeout=120,check=False
        )
        if result.returncode or not 100<len(result.stdout)<=MAX_ALIGNED_SIZE:
            continue
        try:
            if len(ff.parse_cues(result.stdout))>=75:
                return result.stdout
        except (RuntimeError,UnicodeError):
            continue
    return None

def align(video,raw):
    """Full standalone alass: same-video embedded EN when present, else audio."""
    if not available():
        raise RuntimeError("standalone_alass_unavailable")
    if not gate.STAGED.is_dir() or gate.STAGED.is_symlink():
        raise RuntimeError("private_stage_missing")
    with tempfile.TemporaryDirectory(prefix=".alass-",dir=gate.STAGED) as folder:
        source=Path(folder)/"input.ja.srt"
        source.write_bytes(raw)
        choices=[]
        english=_embedded_english(video)
        if english is not None:
            ref=Path(folder)/"same-video.english.srt"
            ref.write_bytes(english)
            choices.append(("same_video_embedded_english",ref))
        choices.append(("video_audio",video))
        for label,reference in choices:
            dest=Path(folder)/(label+".ja.srt")
            try:
                p=subprocess.run([str(BINARY),str(reference),str(source),str(dest)],
                                 stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                                 timeout=600,check=False)
            except subprocess.TimeoutExpired:
                continue
            if p.returncode or not dest.is_file():
                continue
            if not 0<dest.stat().st_size<=MAX_ALIGNED_SIZE:
                continue
            return dest.read_bytes(),label
        raise RuntimeError("alass_failed_no_valid_output")


def artifact(jid,sid):
    if not gate.EXPECTED_ID_PATTERN.fullmatch(jid) or not str(sid).isdigit():
        raise RuntimeError("invalid_alass_provenance_identity")
    return gate.STAGED/"timing-adjusted"/(jid+".opensubtitles."+str(sid)+".ja.alass.srt")

def provenance_matches(jid,sid,source_hash,published_hash):
    """Authenticate a previously published alass output after library refresh."""
    filename=artifact(jid,sid)
    record=filename.with_name(filename.name+".json")
    if not filename.is_file() or not record.is_file():
        return False
    gate.private_file(filename,"alass_derived")
    gate.private_file(record,"alass_metadata")
    info=json.loads(record.read_text("utf-8"))
    if (info.get("schema")!="subhub-alass-v1"
        or info.get("jellyfin_id")!=jid or str(info.get("subtitle_id"))!=str(sid)
        or info.get("source_sha256")!=source_hash
        or info.get("aligned_sha256")!=published_hash
        or _sha(filename.read_bytes())!=published_hash):
        raise RuntimeError("alass_provenance_mismatch")
    return True

def preserve(item):
    """Preserve corrected bytes and original hash. Never replace past stage work."""
    if item["assessment"]["mode"]=="original":
        return
    path=artifact(item["jid"],item["sid"])
    folder=path.parent
    folder.mkdir(mode=0o700,exist_ok=True)
    if folder.is_symlink() or folder.stat().st_mode&0o077:
        raise RuntimeError("unsafe_alass_stage")
    metadata={
        "schema":"subhub-alass-v1",
        "jellyfin_id":item["jid"],"subtitle_id":item["sid"],
        "source_sha256":_sha(item["original"]),
        "aligned_sha256":_sha(item["chosen"]),
        "assessment":item["assessment"]
    }
    for dest,body in (
        (path,item["chosen"]),
        (path.with_name(path.name+".json"),
         (json.dumps(metadata,ensure_ascii=False,sort_keys=True,indent=2)+"\n").encode())
    ):
        if dest.is_symlink():
            raise RuntimeError("alass_stage_symlink")
        if dest.exists():
            if dest.read_bytes()!=body:
                raise RuntimeError("alass_stage_conflict")
            continue
        fd,tmp=tempfile.mkstemp(prefix=".pending-alass-",dir=folder)
        try:
            with os.fdopen(fd,"wb") as f:
                f.write(body);f.flush();os.fsync(f.fileno())
            os.chmod(tmp,0o600)
            os.link(tmp,dest)
        finally:
            Path(tmp).unlink(missing_ok=True)
