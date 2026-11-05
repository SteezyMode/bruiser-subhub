#!/usr/bin/env python3
"""Spoiler-free one-film Japanese-source rescue, using Sublarr 1.18.0 itself.

Run inside the EXISTING sublarr-pilot container with PYTHONPATH=/app:
  python3 - --title 'You Were Never Really Here' --apply

Uses one existing OpenSubtitles account, searches by verified film filename,
downloads at most 3 provider results into /config scratch, and screens language,
coverage and playback timing before proposing/creating a JA sidecar.

--apply creates a SINGLE .ja.srt/.ja.ass sidecar only if all conservative gates
pass and no Japanese sidecar already exists. O_EXCL, no overwrite. No AI,
no other videos touched, no plot details or dialogue printed. Existing sidecars
are never deleted, replaced or silently 'upgraded'. Detection of bad semantic
MT is inherently imperfect: a screened source is not guaranteed human-quality.
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
import tempfile
from urllib.parse import quote
import sqlite3

TARGET_TITLE = "You Were Never Really Here"
MEDIA_ROOTS = (
    Path("/media/bigdisk-video/Movies"),
    Path("/media/expansion-video/Movies"),
)
JA_CHARS = re.compile(r"[\u3040-\u30ff\u3400-\u9fff]")
VID_EXT = {".mkv",".mp4",".m4v",".avi",".mov"}
SUB_EXT = {".srt",".ass",".ssa"}
OUT_ROOT = Path("/config/bruiser-ja-screened")
SKIP_FORCED = ("forced","signs")


def token(s):
    return re.sub(r"[^a-z0-9]+","",str(s).casefold())


def find_video(title, roots=MEDIA_ROOTS):
    key=token(title)
    if len(key)<12:
        raise RuntimeError("movie title not specific enough")
    hits=[]
    for root in roots:
        if not root.is_dir():
            continue
        for directory,dirs,files in os.walk(root, followlinks=False):
            dirs[:]=[d for d in dirs if not Path(directory,d).is_symlink()]
            for file in files:
                p=Path(directory,file)
                if p.suffix.lower() not in VID_EXT or p.is_symlink():
                    continue
                if key in token(file+" "+Path(directory).name) and p.is_file():
                    hits.append(p)
    return hits


def existing_ja_sidecars(video):
    return [p for p in video.parent.iterdir() if p.is_file() and
            p.name.casefold().startswith(video.stem.casefold()+".") and
            re.search(r"\.(?:ja|jpn|japanese)(?:\.[a-z]+)?\.(?:srt|ass|ssa|vtt)$",
                      p.name.casefold())]


def has_embedded_japanese(video):
    cmd=["ffprobe","-v","error","-select_streams","s",
         "-show_entries","stream_tags=language",
         "-of","json",str(video)]
    p=subprocess.run(cmd,capture_output=True,text=True,timeout=45,check=True)
    data=json.loads(p.stdout)
    return any(str((stream.get("tags") or {}).get("language","")).lower() in
               ("jpn","ja") for stream in data.get("streams",[]))


def duration(video):
    p=subprocess.run(["ffprobe","-v","error","-show_entries","format=duration",
        "-of","default=noprint_wrappers=1:nokey=1",str(video)],
        capture_output=True,text=True,timeout=45,check=True)
    return float(p.stdout.strip())


def credentials(settings):
    """Read UI provider settings from DB instead of fresh-process defaults.

    This mirrors Sublarr 1.18's boot/UI config split, including encrypted
    values. DB and encryption-key are read only. Never print secrets.
    """
    names=("opensubtitles_api_key","opensubtitles_username","opensubtitles_password")
    values={k:str(getattr(settings,k,"") or "") for k in names}
    db_url=settings.get_database_url()
    if not db_url.startswith("sqlite:///"):
        raise RuntimeError("Non-SQLite Sublarr config: no safe credential extraction")
    db_path=Path(db_url[len("sqlite:///"):])
    if not db_path.is_file():
        raise RuntimeError("Existing Sublarr database unavailable")
    uri="file:"+quote(str(db_path.resolve()),safe="/")+"?mode=ro"
    with sqlite3.connect(uri,uri=True,timeout=15) as db:
        db.execute("PRAGMA query_only=ON")
        stored=dict(db.execute("SELECT key,value FROM config_entries "
            "WHERE key IN ('opensubtitles_api_key','opensubtitles_username',"
            "'opensubtitles_password')").fetchall())
    sensitive=[v for v in stored.values() if isinstance(v,str) and v.startswith("enc:v1:")]
    cipher=None
    if sensitive:
        from cryptography.fernet import Fernet,InvalidToken
        key=Path(settings.config_dir)/".encryption_key"
        if not key.is_file():
            raise RuntimeError("Existing config decryption key missing")
        cipher=Fernet(key.read_bytes().strip())
    for k in names:
        val=stored.get(k)
        if not isinstance(val,str): continue
        if val.startswith("enc:v1:"):
            try: val=cipher.decrypt(val[7:].encode()).decode("utf-8")
            except Exception:
                raise RuntimeError("Stored OpenSubtitles settings unreadable") from None
        values[k]=val.strip()
    if not values["opensubtitles_api_key"] or values["opensubtitles_api_key"].startswith("***"):
        raise RuntimeError("OpenSubtitles key not available to isolated process")
    return {k.removeprefix("opensubtitles_"):v for k,v in values.items()}


def select_candidates(results, title):
    found=[]
    title_key=token(title)
    for r in results:
        if r.language not in ("ja","jpn") or r.forced:
            continue
        if not r.subtitle_id:
            continue
        release=token((r.release_info or "")+" "+(r.filename or ""))
        matches=set(r.matches or [])
        # A filename/release title match or genuine OpenSubtitles video hash is
        # required. Same title can have 2017/2018 release metadata.
        identity=("hash" in matches or "title" in matches or title_key in release)
        if not identity:
            continue
        trust=1000 if "hash" in matches else 200 if "title" in matches else 80
        year=30 if "year" in matches else 0
        exact=40 if title_key in release else 0
        matchscore=trust+year+exact+int(getattr(r,"uploader_trust",0) or 0)
        found.append((matchscore,r))
    found.sort(key=lambda item:item[0],reverse=True)
    return found


def subtitle_format(blob, provider_hint=""):
    head=blob[:5000].lstrip(b"\xef\xbb\xbf\r\n\t ")
    if head.startswith(b"[Script Info]"):return ".ass"
    if b"-->" in head and re.search(rb"\d\d:\d\d:\d\d[,.]\d{3}\s*-->",head):
        return ".srt"
    return ""


def health(cues, runtime, allow_offset_sec=0):
    if not cues:
        return {"ok":False,"reason":"empty"}
    dialogue=[c for c in cues if str(c.get("text") or "").strip()]
    japanese=sum(bool(JA_CHARS.search(str(c.get("text") or ""))) for c in dialogue)
    ratio=japanese/max(1,len(dialogue))
    last=max(int(c.get("end") or 0) for c in cues)
    first=min(int(c.get("start") or 0) for c in cues)
    invalid=sum(int(c.get("end") or 0)<=int(c.get("start") or 0) for c in cues)
    over=sum(int(c.get("end") or 0)>runtime*1000+5000+allow_offset_sec*1000 for c in cues)
    ordered=sorted(cues,key=lambda c:(c["start"],c["end"]))
    overlaps=sum(ordered[i+1]["start"]+300<ordered[i]["end"]
                 for i in range(len(ordered)-1))
    dense=sum(len(str(c.get("text") or ""))/max((c["end"]-c["start"])/1000,0.1)>27
              for c in dialogue)
    dup=sum(str(dialogue[i].get("text","")).strip()==str(dialogue[i-1].get("text","")).strip()
            for i in range(1,len(dialogue))) if len(dialogue)>1 else 0
    # Don't punish harmless conversational paraphrase. This catches malformed
    # tracks, forced-only and extreme density; NOT semantic accuracy.
    reason=[]
    if len(cues)<max(80,int(runtime/35)):reason.append("too_few_cues")
    if ratio<0.85:reason.append("not_predominantly_japanese")
    if first>runtime*1000*.25:reason.append("begins_too_late")
    if last<runtime*1000*.76:reason.append("ends_too_early")
    if invalid or over>0:reason.append("invalid_timing")
    if overlaps>len(cues)*.035:reason.append("excessive_overlap")
    if dense>len(dialogue)*.10:reason.append("excessive_reading_speed")
    if dup>len(dialogue)*.07:reason.append("excessive_identical_repetition")
    non_ja=[c for c in dialogue if not JA_CHARS.search(str(c.get("text") or ""))]
    latin=[c for c in non_ja if re.search(r"[A-Za-z]{3,}",str(c.get("text") or ""))]
    non_latin=[c for c in non_ja if c not in latin]
    # Publish only aggregated spoiler-free content diagnostics, no quotes or cues.
    latin_quartiles=[0,0,0,0]
    for item in latin:
        bucket=min(3,max(0,int(int(item["start"])/(runtime*1000)*4)))
        latin_quartiles[bucket]+=1
    return {
        "ok":not reason,"holds":reason,"cue_count":len(cues),
        "japanese_fraction":round(ratio,3),
        "non_japanese_cues":len(non_ja),
        "non_japanese_latin_word_cues":len(latin),
        "non_japanese_non_latin_cues":len(non_latin),
        "latin_word_cues_by_film_quarter":latin_quartiles,
        "first_seconds":round(first/1000,2),
        "last_seconds":round(last/1000,2),
        "overlap_events":overlaps,"dense_events":dense,
        "video_seconds":round(runtime,2)
    }



def search_movie_sources(provider, video, title, query_type=None):
    """Search both exact file-hash and title/year; bad hash match must not end discovery.

    Upstream 1.18 provider queries by moviehash *instead of* title when a file
    path is present and only falls back to title on empty results. A poor hash
    hit is not proof that no alternate human-quality Japanese subtitle exists.
    """
    if query_type is None:
        from providers.base import VideoQuery
        query_type=VideoQuery
    exact = provider.search(query_type(
        title=title, year=2017, languages=["ja"], file_path=str(video)
    ))
    general = provider.search(query_type(
        title=title, year=2017, languages=["ja"]
    ))
    seen=set()
    merged=[]
    for item in list(exact or [])+list(general or []):
        key=(str(item.provider_name),str(item.subtitle_id))
        if key not in seen:
            merged.append(item)
            seen.add(key)
    return merged


def stage_private_candidate(video, result, content, fmt, assessment, sync=None,
                            aligned=None):
    """Persist downloaded source and its spoiler-free assessment; no media writes.

    Avoids losing quota-counted files on a quality hold, creates only private
    /config records, and refuses to overwrite a different archived candidate.
    """
    if fmt not in SUB_EXT:
        raise RuntimeError("Unsafe subtitle staging format")
    root = OUT_ROOT / hashlib.sha256(str(video).encode()).hexdigest()[:20]
    if root.is_symlink():
        raise RuntimeError("Unsafe private staging path")
    root.mkdir(parents=True,exist_ok=True,mode=0o700)
    if not root.is_dir():
        raise RuntimeError("Unable to create private staging folder")
    digest=hashlib.sha256(content).hexdigest()
    name=digest[:20]
    source=root/("source-"+name+fmt)
    data=root/("report-"+name+".json")
    def create_once(file,body):
        if file.exists():
            if file.read_bytes()!=body:
                raise RuntimeError("Conflicting private staged candidate")
            return
        fd=os.open(file,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        try:
            with os.fdopen(fd,"wb") as f:
                f.write(body)
        except BaseException:
            file.unlink(missing_ok=True)
            raise
    create_once(source,content)
    if aligned is not None and Path(aligned).is_file():
        translated_path=root/("aligned-"+name+fmt)
        # Preserve the first independently measured correction; a retry must
        # never replace a previous scratch file on the same digest.
        if not translated_path.exists():
            create_once(translated_path,Path(aligned).read_bytes())
    metadata={
        "video_file":video.name,
        "source":"opensubtitles",
        "subtitle_id":str(getattr(result,"subtitle_id","")),
        "uploader":str(getattr(result,"uploader_name","")),
        "sha256":digest,
        "original_filename":str(getattr(result,"filename","")),
        "source_format":fmt,
        "language_flag":"Japanese",
        "human_translation_verified":False,
        "quality_gate":assessment,
        "sync_preview":sync,
        "notes":"Source stored privately; never published automatically when held.",
    }
    if not data.exists():
        create_once(data,(json.dumps(metadata,ensure_ascii=False,indent=2)+"\n").encode("utf-8"))
    return source, data

def sync_candidate(video, input_path, output_path):
    from services.sync_engines.ffsubsync_output import parse_ffsubsync_shift
    args=["ffsubsync",str(video),"-i",str(input_path),"-o",str(output_path)]
    try:
        p=subprocess.run(args,capture_output=True,text=True,timeout=600)
    except subprocess.TimeoutExpired:
        return {"ok":False,"hold":"ffsubsync_timeout"}
    if p.returncode!=0:
        return {"ok":False,"hold":"ffsubsync_error"}
    delta=parse_ffsubsync_shift(p.stdout+"\n"+p.stderr)
    if delta is None or abs(delta)>30_000:
        return {"ok":False,"hold":"no_or_excessive_shift","shift_ms":delta}
    return {"ok":True,"shift_ms":delta}


def publish_create_only(video,source,extension):
    # Never overwrite existing Japanese sidecars; O_EXCL provides atomic guard
    # against concurrent Sublarr/owner save while processing.
    if existing_ja_sidecars(video):
        raise RuntimeError("Japanese sidecar already exists; no overwrite")
    if extension not in SUB_EXT:
        raise RuntimeError("Unsupported output format")
    target=video.with_name(video.stem+".ja"+extension)
    flags=os.O_WRONLY|os.O_CREAT|os.O_EXCL
    fd=os.open(target,flags,0o644)
    try:
        with os.fdopen(fd,"wb") as f:
            with open(source,"rb") as src:
                while chunk:=src.read(65536):f.write(chunk)
            f.flush()
            os.fsync(f.fileno())
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    return target



def publish_synced_alternative(video,source,extension):
    """Create an independently named corrected JA sidecar, never edit source."""
    if extension not in SUB_EXT:
        raise RuntimeError("Existing sidecar format not supported")
    target=video.with_name(video.stem+".BruiserSynced.ja"+extension)
    fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o644)
    try:
        with os.fdopen(fd,"wb") as out, open(source,"rb") as inp:
            while chunk:=inp.read(65536):out.write(chunk)
            out.flush()
            os.fsync(out.fileno())
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    return target


def repair_local_japanese(video,runtime):
    """Fix a saved JP track's constant offset if and only if independently safe.

    Unconditionally keep the original unchanged and create a separate new
    .BruiserSynced.ja.srt/ass if a meaningful correction is measured.
    Never print subtitle dialogue. If several sources exist, hold rather than
    guessing which to trust.
    """
    existing=existing_ja_sidecars(video)
    if not existing:
        return False
    print("EXISTING_JAPANESE_SIDECARS",len(existing),flush=True)
    if len(existing)!=1:
        print("HELD_EXISTING_MULTIPLE: no subtitles overwritten or guessed",flush=True)
        return True
    original=existing[0]
    if "BruiserSynced" in original.name:
        print("ALREADY_HAS_BRUISER_SYNCED_JAPANESE",flush=True)
        return True
    extension=original.suffix.lower()
    if extension not in SUB_EXT:
        print("HELD_EXISTING_UNSUPPORTED_FORMAT",extension,flush=True)
        return True
    from services.sync_preview import load_cues
    original_cues=load_cues(str(original))
    screen=health(original_cues,runtime,allow_offset_sec=30)
    if not screen["ok"]:
        print("HELD_EXISTING_CONTENT",json.dumps(screen),flush=True)
        return True
    OUT_ROOT.mkdir(mode=0o700,parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="bruiser-repair-",dir=str(OUT_ROOT)) as temp:
        aligned=Path(temp)/("aligned"+extension)
        result=sync_candidate(video,original,aligned)
        if not result["ok"]:
            print("HELD_EXISTING_SYNC",result,flush=True)
            return True
        if abs(result["shift_ms"])<400:
            print("EXISTING_TRACK_ALREADY_CLOSE",result["shift_ms"],"ms",flush=True)
            return True
        corrected_cues=load_cues(str(aligned))
        after=health(corrected_cues,runtime)
        if not after["ok"] or len(corrected_cues)!=len(original_cues):
            print("HELD_EXISTING_SYNC_QUALITY",json.dumps(after),flush=True)
            return True
        new_path=publish_synced_alternative(video,aligned,extension)
        print("SPOILER_FREE_RESULT: CORRECTED_COPY_CREATED",new_path.name,
              "offset_ms",result["shift_ms"],"cues",len(corrected_cues),
              "original_preserved",True,flush=True)
        return True


def run(title=TARGET_TITLE,apply=False,max_downloads=3):
    from config import get_settings
    settings=get_settings()
    if token(title)!=token(TARGET_TITLE):
        raise RuntimeError("Safety: this initial rescue is pinned to the requested film")
    vids=find_video(title)
    if len(vids)!=1:
        print("FILM_MATCH_COUNT",len(vids),flush=True)
        raise RuntimeError("Expected one exact video filename; no changes")
    video=vids[0]
    if video.is_symlink():
        raise RuntimeError("Refusing symlink movie path")
    length=duration(video)
    if length<1800 or length>20000:raise RuntimeError("Video duration unexpected")
    print("FILM_VIDEO_MATCHED",video.name,"duration_sec",round(length,1),flush=True)
    if not apply:
        print("READY_FOR_SPOILER_FREE_AUTOMATIC_SOURCE_SYNC: --apply required")
        return
    if repair_local_japanese(video,length):
        return
    if has_embedded_japanese(video):
        print("ALREADY_HAS_EMBEDDED_JAPANESE",video.name,flush=True)
        return
    from providers.opensubtitles import OpenSubtitlesProvider
    from services.sync_preview import load_cues
    kwargs=credentials(settings)
    client=OpenSubtitlesProvider(**kwargs)
    try:
        client.initialize()
        if not getattr(client,"session",None):
            raise RuntimeError("Provider could not initialize")
        results=search_movie_sources(client,video,title)
        candidates=select_candidates(results,title)[:max_downloads]
        print("SOURCE_SEARCH_STRATEGY hash_plus_title_and_year",flush=True)
        print("JAPANESE_CANDIDATES",len(candidates),flush=True)
        if not candidates:
            print("SOURCE_MISS: no safely identified Japanese source; NO TRANSLATION run")
            return
        OUT_ROOT.mkdir(mode=0o700,parents=True,exist_ok=True)
        for ix,(identity_score,result) in enumerate(candidates,1):
            print("SCREENING",ix,"identity",identity_score,"source","opensubtitles",
                  "machine_origin_unverified",flush=True)
            raw=client.download(result)
            if not isinstance(raw,bytes) or not 32<len(raw)<3_000_000:
                print("HELD: empty or oversized download",flush=True)
                continue
            fmt=subtitle_format(raw)
            if not fmt:
                print("HELD: invalid actual subtitle format",flush=True)
                continue
            with tempfile.TemporaryDirectory(prefix="bruiser-film-",dir=str(OUT_ROOT)) as t:
                source=Path(t)/("source"+fmt)
                source.write_bytes(raw)
                cues=load_cues(str(source))
                before=health(cues,length,allow_offset_sec=30)
                # A language hold must not prevent a non-destructive timing
                # inspection: separately diagnose alignment and translation.
                corrected=Path(t)/("aligned"+fmt)
                syn=sync_candidate(video,source,corrected)
                after=(health(load_cues(str(corrected)),length)
                       if syn["ok"] and corrected.is_file() else None)
                staged_source,staged_report=stage_private_candidate(
                    video,result,raw,fmt,before,syn,
                    corrected if corrected.is_file() else None)
                print("CANDIDATE_STAGED_PRIVATELY",ix,
                      "source_file",str(staged_source),
                      "report_file",str(staged_report),
                      "original_preserved",True,flush=True)
                if not before["ok"]:
                    print("HELD_CONTENT",json.dumps(before,ensure_ascii=False),flush=True)
                    print("SYNC_DIAGNOSTIC_ONLY",syn,flush=True)
                    continue
                if not syn["ok"]:
                    print("HELD_TIMING",syn,flush=True)
                    continue
                if not after or not after["ok"] or after["cue_count"]!=before["cue_count"]:
                    print("HELD_ALIGNED_CONTENT",json.dumps(after,ensure_ascii=False),flush=True)
                    continue
                target=publish_create_only(video,corrected,fmt)
                info={
                    "title":title,"video_file":video.name,"source":"opensubtitles",
                    "subtitle_id":result.subtitle_id,
                    "content_sha256":hashlib.sha256(raw).hexdigest(),
                    "source_uploader":getattr(result,"uploader_name",""),
                    "source_identity_score":identity_score,
                    "format":fmt,
                    "health":after,
                    "sync":syn,
                    "provenance":"provider-original-candidate-origin-not-verified",
                    "translation_quality":"NOT independently verified; natural paraphrase is allowed",
                    "published_video_sidecar":target.name,
                }
                audit=OUT_ROOT/(hashlib.sha256(str(video).encode()).hexdigest()[:20]+".json")
                audit.write_text(json.dumps(info,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
                os.chmod(audit,0o600)
                print("SPOILER_FREE_RESULT: PUBLISHED",target.name,
                      "Japanese cues",after["cue_count"],
                      "offset_ms",syn["shift_ms"],
                      "provider_origin_unverified",flush=True)
                return
        print("NO_APPROVED_CANDIDATE: no media changed; retain as source-missing/review")
    finally:
        client.terminate()


if __name__=="__main__":
    a=argparse.ArgumentParser()
    a.add_argument("--title",default=TARGET_TITLE)
    a.add_argument("--apply",action="store_true")
    a.add_argument("--max-downloads",type=int,default=3,choices=(1,2,3))
    args=a.parse_args()
    try:run(args.title,args.apply,args.max_downloads)
    except Exception as exc:
        # No dialogue or spoilers in error reports.
        print("SOURCE_RESCUE_HELD",type(exc).__name__,str(exc)[:180],file=sys.stderr)
        sys.exit(1)
