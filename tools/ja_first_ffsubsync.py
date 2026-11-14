#!/usr/bin/env python3
"""ffsubsync verification for SubHub's existing host-staged JA-first queue.

Uses read-only video bind inside Sublarr, private temporary subtitle files,
then the existing host create-only publication gate. No provider calls, model,
media remount, or changes to existing subtitles. This is a conservative pilot,
not an editorial Japanese-quality guarantee.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

import ja_first_publish_staged as gate
import ja_first_obvious_quality as source_quality
import ja_first_srt_normalize as structure
from bruiser_ja_movie_rescue import health

CONTAINER = "sublarr-pilot"
MAX_SHIFT_SECONDS = 30.0
MAX_SHIFT_SPREAD_SECONDS = 5.0  # Allow modest release/frame-rate drift; extreme (12s+) held; alass preferred.
NO_CHANGE_THRESHOLD_SECONDS = 0.4
# Conservative local repair of short overlapping Japanese subtitle cues.
# No subtitle text or cue START timestamps are ever altered by this pass.
MAX_OVERLAP_REPAIR_FRACTION = 0.16
MAX_SINGLE_TRIM_MS = 1500
MAX_TRIM_DURATION_FRACTION = 0.55
MAX_TOTAL_TRIM_FRACTION = 0.09
MIN_REPAIRED_CUE_MS = 800
CLIP_GAP_MS = 50

WORKER = r'''
import base64, json, subprocess, sys, tempfile
from pathlib import Path
video=Path(sys.argv[1])
raw=sys.stdin.buffer.read(2000001)
if not video.is_file() or not 0<len(raw)<=2000000:
    raise SystemExit("invalid_video_or_subtitle")
with tempfile.TemporaryDirectory(prefix="bruiser-ja-sync-",dir="/config") as directory:
    source=Path(directory)/"source.srt"
    aligned=Path(directory)/"aligned.srt"
    source.write_bytes(raw)
    try:
        result=subprocess.run(["ffsubsync",str(video),"-i",str(source),"-o",str(aligned)],
                              capture_output=True,timeout=600,check=False)
    except subprocess.TimeoutExpired:
        raise SystemExit("ffsubsync_timeout")
    if result.returncode or not aligned.is_file() or not 0<aligned.stat().st_size<=2000000:
        raise SystemExit("ffsubsync_failed")
    print(json.dumps({"aligned_b64":base64.b64encode(aligned.read_bytes()).decode("ascii")}))
'''

CLOCK = re.compile(r"\A(?:(\d{1,3}):)?(\d{2}):(\d{2})[,.](\d{2,3})\Z")
ARROW = re.compile(r"\A(\S+)\s*-->\s*(\S+)(?:\s+.*)?\Z")


def parse_ms(stamp):
    m = CLOCK.fullmatch(stamp.strip())
    if not m:
        raise RuntimeError("bad_srt_timestamp")
    h, minute, second, fraction = m.groups()
    return (int(h or 0)*3600 + int(minute)*60 + int(second))*1000 + int(fraction.ljust(3,"0"))


def parse_cues(raw):
    try:
        text=raw.decode("utf-8-sig")
    except UnicodeError:
        raise RuntimeError("non_utf8_srt") from None
    cues=[]
    for block in re.split(r"\r?\n[ \t]*\r?\n",text.strip()):
        lines=block.splitlines()
        ix=int(bool(lines and lines[0].strip().isdigit()))
        if len(lines)<ix+2:
            raise RuntimeError("malformed_srt_cue")
        match=ARROW.fullmatch(lines[ix].strip())
        if not match:
            raise RuntimeError("malformed_srt_arrow")
        start,end=map(parse_ms,match.groups())
        if end<=start:
            raise RuntimeError("invalid_srt_interval")
        cues.append({"start":start,"end":end,"text":"\n".join(lines[ix+1:]).strip()})
    return cues


def keep_source_dialogue(source, aligned):
    """Use sync output ONLY for timestamps; always keep the source dialogue.

    Some alignment engines reflow subtitle lines or normalize whitespace.
    Accept that formatting difference only when every cue has exactly the
    original non-whitespace characters in the same order. Never approve
    dropped, added, or reordered words; never modify the source stage.
    """
    old=parse_cues(source)
    new=parse_cues(aligned)
    if len(old)!=len(new):
        raise RuntimeError("sync_cue_count_changed")
    if any("".join(a["text"].split()) != "".join(b["text"].split())
           for a,b in zip(old,new)):
        raise RuntimeError("sync_dialogue_changed")
    if all(a["text"]==b["text"] for a,b in zip(old,new)):
        return aligned
    lines=[]
    for i,(original,corrected) in enumerate(zip(old,new),1):
        if corrected["start"]<0 or corrected["end"]<=corrected["start"]:
            raise RuntimeError("sync_invalid_interval")
        lines.append(f'{i}\n{format_ms(corrected["start"])} --> '
                     f'{format_ms(corrected["end"])}\n{original["text"]}')
    return ("\n\n".join(lines)+"\n").encode("utf-8")


def path_in_container(host_path,mounts):
    """Only existing Docker bind-mount mappings; reject ambiguous mappings."""
    host=Path(host_path)
    if not host.is_absolute() or host.is_symlink() or not host.is_file():
        raise RuntimeError("host_video_missing_or_symlinked")
    possibilities=[]
    for mount in mounts:
        if mount.get("Type")!="bind":
            continue
        src=Path(mount.get("Source") or "")
        dest=Path(mount.get("Destination") or "")
        if not src.is_absolute() or not dest.is_absolute():
            continue
        try:
            suffix=host.relative_to(src)
        except ValueError:
            continue
        if not host.resolve(strict=True).is_relative_to(src.resolve(strict=True)):
            continue
        possibilities.append((len(src.parts),dest/suffix))
    possibilities.sort(key=lambda item:item[0],reverse=True)
    if not possibilities or (len(possibilities)>1 and possibilities[0][0]==possibilities[1][0]):
        raise RuntimeError("container_mount_unavailable_or_ambiguous")
    return str(possibilities[0][1])


def format_ms(milliseconds):
    milliseconds = int(milliseconds)
    if milliseconds < 0:
        raise RuntimeError("overlap_repair_negative_timestamp")
    hours, milliseconds = divmod(milliseconds, 3600000)
    minutes, milliseconds = divmod(milliseconds, 60000)
    seconds, milliseconds = divmod(milliseconds, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"


def repair_minor_overlaps(aligned, runtime):
    """Fix conservatively bounded END-only collisions on a derived candidate.

    Source downloads remain untouched. Never shift starts or edit dialogue.
    Reject severe simultaneous/stacked subtitles, large trims and any new
    readability or coverage failure; the caller then HOLDS publication.
    """
    cues = parse_cues(aligned)
    before = health(cues, runtime)
    details = {"overlap_repaired_cues": 0, "overlap_trimmed_ms": 0}
    if "excessive_overlap" not in before.get("holds", []):
        return aligned, details
    if set(before["holds"]) != {"excessive_overlap"}:
        raise RuntimeError("overlap_repair_other_quality_holds")
    if any(cues[i+1]["start"] < cues[i]["start"] for i in range(len(cues)-1)):
        raise RuntimeError("overlap_repair_out_of_order_source")

    repaired = [dict(cue) for cue in cues]
    trimmed = 0
    count = 0
    original_duration = sum(cue["end"]-cue["start"] for cue in cues)
    for i in range(len(repaired)-1):
        current, following = repaired[i], repaired[i+1]
        if current["end"] <= following["start"] + 300:
            continue
        end = following["start"] - CLIP_GAP_MS
        duration = current["end"] - current["start"]
        removed = current["end"] - end
        if (end-current["start"] < MIN_REPAIRED_CUE_MS
                or removed > MAX_SINGLE_TRIM_MS
                or removed > duration*MAX_TRIM_DURATION_FRACTION):
            raise RuntimeError("overlap_repair_requires_unsafe_trim")
        current["end"] = end
        count += 1
        trimmed += removed
    if (not count or count/len(cues) > MAX_OVERLAP_REPAIR_FRACTION
            or trimmed > original_duration*MAX_TOTAL_TRIM_FRACTION):
        raise RuntimeError("overlap_repair_exceeds_safety_budget")
    # Rebuild only the private ffsubsync candidate, not the downloaded file.
    rendered = "\n\n".join(
        f'{i+1}\n{format_ms(cue["start"])} --> '
        f'{format_ms(cue["end"])}\n{cue["text"]}'
        for i, cue in enumerate(repaired)
    ) + "\n"
    body = rendered.encode("utf-8")
    again = parse_cues(body)
    if (len(again) != len(cues)
            or [x["text"] for x in again] != [x["text"] for x in cues]
            or [x["start"] for x in again] != [x["start"] for x in cues]):
        raise RuntimeError("overlap_repair_modified_dialogue_or_start")
    verified = health(again, runtime)
    if not verified["ok"]:
        raise RuntimeError("overlap_repair_did_not_pass_validation:"+
                           ",".join(verified["holds"]))
    details.update(overlap_repaired_cues=count, overlap_trimmed_ms=trimmed)
    return body, details


def check_alignment(original,aligned,runtime):
    before=parse_cues(original)
    after=parse_cues(aligned)
    if len(before)!=len(after) or not before:
        raise RuntimeError("ffsubsync_cue_count_changed")
    if [cue["text"] for cue in before] != [cue["text"] for cue in after]:
        raise RuntimeError("ffsubsync_changed_dialogue")
    shifts=[(b["start"]-a["start"])/1000 for a,b in zip(before,after)]
    # An audio matcher can return a different offset for the cold open than
    # the remainder of an episode. A plausible runtime is not proof of sync:
    # reject substantial variable shifts instead of publishing visible drift.
    if max(abs(value) for value in shifts)>MAX_SHIFT_SECONDS or max(shifts)-min(shifts)>MAX_SHIFT_SPREAD_SECONDS:
        raise RuntimeError("ffsubsync_shift_or_variation_excessive")
    if (min(c["start"] for c in after)<0
            or max(c["end"] for c in after)>runtime*1000+5000
            or min(c["start"] for c in after)>runtime*1000*0.25
            or max(c["end"] for c in after)<runtime*1000*0.76):
        raise RuntimeError("ffsubsync_invalid_video_coverage")
    old=health(before,runtime,allow_offset_sec=30)
    new=health(after,runtime)
    # The original may have a repairable overlap. Publication is gated on
    # the final candidate passing the FULL quality check; we never pass an
    # uncorrected original with this defect through as "unchanged".
    old_other=set(old.get("holds",[]))-{"excessive_overlap"}
    if old_other or not new["ok"]:
        raise RuntimeError("subtitle_health_hold:"+",".join(
            sorted(old_other.union(new.get("holds",[])))))
    unchanged=(old["ok"] and max(abs(value) for value in shifts)
               < NO_CHANGE_THRESHOLD_SECONDS)
    return {"mode":"original" if unchanged else "corrected",
            "shift_range_seconds":[round(min(shifts),3),round(max(shifts),3)],
            "cues":len(after),"japanese_fraction":new["japanese_fraction"]}


def align_in_container(video,raw,*,runner=subprocess.run):
    mounts=runner(["docker","inspect","--format","{{json .Mounts}}",CONTAINER],
                  capture_output=True,check=True,timeout=25)
    mapped=path_in_container(video,json.loads(mounts.stdout))
    result=runner(["docker","exec","-i",CONTAINER,"python3","-c",WORKER,mapped],
                  input=raw,capture_output=True,check=True,timeout=650)
    synced=base64.b64decode(json.loads(result.stdout)["aligned_b64"],validate=True)
    if not 0<len(synced)<=2_000_000:
        raise RuntimeError("aligned_srt_invalid_size")
    return synced


def prepare(jid,sid,*,aligner=align_in_container):
    row=gate.read_inventory(jid)
    gate.verify_search_identity(row,jid,sid)
    _,raw,metrics=gate.read_staging(jid,sid)
    video=gate.safe_media_path(str(row.get("host_path") or ""))
    streams,error=gate.ffprobe_streams(video)
    if error or not isinstance(streams,list):
        raise RuntimeError("ffprobe_missing_or_failed")
    gate.check_no_existing_ja(video,streams)
    runtime=float(metrics.get("video_seconds") or 0)
    if not 600<=runtime<=4*3600 or abs(gate.subprocess_duration(video)-runtime)>0.5:
        raise RuntimeError("video_changed_since_staging")
    # Normalize only unambiguous technical defects in a private working copy.
    # No relaxation of cue/text identity, health, or audio-timing acceptance.
    source,repair=structure.normalize(
        raw,expected_timestamps=int(metrics.get("cues") or -1),
        trial_release_note=True,trial_local_swap=True,
        trial_chronological_reorder=True)
    qa=gate.validate_srt(source,runtime)
    # Cheap, high-recall corruption screen before the expensive audio sync.
    # It does not grade idiom choice, fluent machine translation, or meaning.
    quality=source_quality.require_not_garbage(source)
    synced=aligner(video,source)
    # Sync tools may reflow text. Keep the original JA dialogue byte-for-byte
    # per cue; their output is only authority for candidate timestamps.
    synced=keep_source_dialogue(source,synced)
    # Preserve source bytes; only touch the private aligned candidate.
    synced,overlap_report=repair_minor_overlaps(synced,runtime)
    if gate.validate_srt(synced,runtime)!=qa:
        raise RuntimeError("synced_srt_cue_or_language_changed")
    decision=check_alignment(source,synced,runtime)
    decision.update(overlap_report)
    chosen=source if decision["mode"]=="original" else synced
    if source!=raw:
        decision["mode"]="corrected"
        decision["structural_repair"]=repair
    return {"jid":jid,"sid":sid,"row":row,"video":video,
            "target":gate.video_target(video),"original":raw,"chosen":chosen,
            "assessment":decision,"source_quality":quality}


def record_path(jid,sid):
    if not gate.EXPECTED_ID_PATTERN.fullmatch(jid) or not sid.isdigit():
        raise RuntimeError("invalid_record_identity")
    return gate.STAGED/"timing-adjusted"/(jid+"."+gate.source_label(jid,sid)+"."+sid+".ja.ffsubsync.srt")


def provenance_matches(jid,sid,original_hash,published_hash):
    path=record_path(jid,sid)
    info=path.with_name(path.name+".json")
    if not path.is_file() or not info.is_file():
        return False
    gate.private_file(path,"ffsubsync_derived")
    gate.private_file(info,"ffsubsync_record")
    detail=json.loads(info.read_text("utf-8"))
    if (detail.get("schema")!="subhub-ffsubsync-v1"
            or detail.get("jellyfin_id")!=jid
            or str(detail.get("subtitle_id"))!=sid
            or detail.get("original_sha256")!=original_hash
            or detail.get("synced_sha256")!=published_hash):
        raise RuntimeError("ffsubsync_provenance_mismatch")
    if hashlib.sha256(path.read_bytes()).hexdigest()!=published_hash:
        raise RuntimeError("ffsubsync_provenance_file_changed")
    return True


def preserve(prepared):
    if prepared["assessment"]["mode"]=="original":
        return
    path=record_path(prepared["jid"],prepared["sid"])
    folder=path.parent
    folder.mkdir(mode=0o700,exist_ok=True)
    if folder.is_symlink() or folder.stat().st_mode&0o077:
        raise RuntimeError("private_derived_folder_unsafe")
    body=prepared["chosen"]
    record={"schema":"subhub-ffsubsync-v1",
            "jellyfin_id":prepared["jid"],"subtitle_id":prepared["sid"],
            "original_sha256":hashlib.sha256(prepared["original"]).hexdigest(),
            "synced_sha256":hashlib.sha256(body).hexdigest(),
            "assessment":prepared["assessment"]}
    info=path.with_name(path.name+".json")
    metadata=(json.dumps(record,sort_keys=True,indent=2)+"\n").encode("utf-8")
    for dest,data in ((path,body),(info,metadata)):
        if dest.is_symlink():
            raise RuntimeError("derived_file_symlink")
        if dest.exists():
            if dest.read_bytes()!=data:
                raise RuntimeError("derived_file_conflict")
            continue
        fd,temp=tempfile.mkstemp(prefix=".pending-",dir=folder)
        try:
            with os.fdopen(fd,"wb") as output:
                output.write(data)
                output.flush()
                os.fsync(output.fileno())
            os.chmod(temp,0o600)
            os.link(temp,dest)
        finally:
            Path(temp).unlink(missing_ok=True)
