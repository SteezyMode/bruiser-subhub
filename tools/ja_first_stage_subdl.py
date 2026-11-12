#!/usr/bin/env python3
"""Stage real SubDL Japanese subtitles recovered by Sublarr title/S/E discovery.

Uses only the pinned dl.subdl.com ZIP URL for a saved candidate. Keeps media
untouched; the existing SubHub ALASS/ffsubsync publisher authenticates staged
provenance and makes the only create-only Japanese sidecar.
"""
from __future__ import annotations

import argparse
from io import BytesIO
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import zipfile

try:
    from . import ja_first_stage_saved_batch as stage
    from . import ja_first_stage_jellyfin as jelly
    from . import ja_first_publish_staged as publisher
    from . import subhub_download_ledger as ledger
except ImportError:
    import ja_first_stage_saved_batch as stage
    import ja_first_stage_jellyfin as jelly
    import ja_first_publish_staged as publisher
    import subhub_download_ledger as ledger

PROVIDER="subdl"
SCHEMA="sublarr-subdl-v1"
SUBDL_ID=re.compile(r"[a-zA-Z0-9_-]{3,120}\Z")
MAX_ARCHIVE=50_000_000
MAX_MEMBERS=100


def identity_ok(row,candidate):
    if (not isinstance(candidate,dict) or candidate.get("provider")!="subdl"
            or str(candidate.get("language") or "").casefold() not in ("ja","jpn")
            or candidate.get("forced") is True
            or not SUBDL_ID.fullmatch(str(candidate.get("subtitle_id") or ""))):
        return False
    if row.get("kind")!="Episode":
        return False
    expected={(row["season"],row["episode"])}
    tags=stage.named_episode(str(candidate.get("filename") or "")+" "+
                             str(candidate.get("release_info") or ""))
    if tags and tags!=expected:
        return False
    matches=set(candidate.get("matches") or [])
    # The source was discovered by a series-title and explicit S/E request.
    # Require episode evidence from result metadata or filename.
    return expected==tags or "episode" in matches and "season" in matches


def private_candidate(jid,row,subtitle_id=None):
    stage.private_file(stage.SEARCH_DB)
    with sqlite3.connect("file:"+str(stage.SEARCH_DB.resolve())+"?mode=ro",
                         uri=True,timeout=10) as db:
        found=db.execute("SELECT results_json FROM searches WHERE jellyfin_id=?",
                         (jid,)).fetchone()
    if not found:
        return []
    doc=json.loads(found[0])
    candidates=[c for c in doc.get("candidates",[])
                if identity_ok(row,c) and
                (subtitle_id is None or str(c.get("subtitle_id"))==subtitle_id)]
    candidates.sort(key=lambda c:-int(c.get("score") or 0))
    return candidates


def numeric_id(remote):
    digest=hashlib.sha256(("subdl:"+remote).encode("utf-8")).hexdigest()
    sid=str(jelly.MIN_ID+int(digest,16)%jelly.ID_RANGE)
    return sid,digest


def archive_srt(blob,row,candidate,runtime):
    if not zipfile.is_zipfile(BytesIO(blob)):
        raise RuntimeError("subdl_archive_not_zip")
    expected={(row["season"],row["episode"])}
    options=[]
    with zipfile.ZipFile(BytesIO(blob)) as arc:
        members=[m for m in arc.infolist()
                 if not m.is_dir() and m.filename.lower().endswith(".srt")]
        if len(arc.infolist())>MAX_MEMBERS:
            raise RuntimeError("subdl_archive_too_many_entries")
        for item in members:
            if not 0<item.file_size<=2_000_000:
                continue
            tags=stage.named_episode(Path(item.filename).stem)
            if tags and tags!=expected:
                continue
            # Never take an unnumbered entry out of a multi-episode archive.
            if not tags and len(members)!=1:
                continue
            priority=1 if tags==expected else 0
            options.append((priority,item))
        options.sort(key=lambda pair:-pair[0])
        for _,member in options:
            try:
                raw=arc.read(member)
                for encoding in ("utf-8-sig","utf-16","cp932","shift_jis"):
                    try:
                        content=raw.decode(encoding).encode("utf-8")
                        qa=publisher.validate_srt(content,runtime)
                        return content,qa,member.filename
                    except (UnicodeError,RuntimeError,ValueError):
                        continue
            except (RuntimeError,ValueError,zipfile.BadZipFile):
                continue
    raise RuntimeError("subdl_no_correct_episode_japanese_srt")


def download(candidate):
    sid=str(candidate["subtitle_id"])
    if not SUBDL_ID.fullmatch(sid):
        raise RuntimeError("unsafe_subdl_id")
    # A fixed provider host, never an arbitrary URL from an API result.
    url="https://dl.subdl.com/subtitle/"+sid+".zip"
    attempt=ledger.begin("subdl","sublarr_native_subdl")
    try:
        with urlopen(Request(url,headers={"User-Agent":"SubHub/1.0"}),timeout=70) as response:
            blob=response.read(MAX_ARCHIVE+1)
        ledger.finish(attempt,"downloaded",byte_count=len(blob))
    except Exception as exc:
        code=exc.code if isinstance(exc,HTTPError) else None
        ledger.finish(attempt,"quota_blocked" if code in (406,429) else "failed",
                      error_kind=("HTTP_"+str(code) if code else type(exc).__name__))
        raise
    if not 0<len(blob)<=MAX_ARCHIVE:
        raise RuntimeError("subdl_archive_empty_or_oversize")
    return blob


def stage_one(row,candidate,runtime):
    jid=row["jellyfin_id"]
    remote=str(candidate["subtitle_id"])
    sid,digest=numeric_id(remote)
    # Never consume a second download allowance for an already staged file.
    if (jid,sid) in stage.read_staged():
        print("STAGED_SUBDL:",jid,"source_id:",sid,"cached",flush=True)
        return
    blob=download(candidate)
    raw,qa,member=archive_srt(blob,row,candidate,runtime)
    stage.STAGED.mkdir(mode=0o700,exist_ok=True)
    if stage.STAGED.is_symlink() or stage.STAGED.stat().st_mode & 0o077:
        raise RuntimeError("unsafe_private_staging_folder")
    target=stage.STAGED/f"{jid}.subdl.{sid}.ja.srt"
    if target.is_symlink():
        raise RuntimeError("stage_file_symlink")
    checksum=hashlib.sha256(raw).hexdigest()
    new=False
    if target.exists():
        if not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest()!=checksum:
            raise RuntimeError("conflicting_existing_subdl_stage")
    else:
        fd=os.open(str(target),os.O_WRONLY|os.O_CREAT|os.O_EXCL|
                   getattr(os,"O_NOFOLLOW",0),0o600)
        with os.fdopen(fd,"wb") as dest:
            dest.write(raw)
        new=True
    meta={
        "provider":PROVIDER,"source_schema":SCHEMA,
        "source_jellyfin_id":jid,"source_remote_id_sha256":digest,
        "source_filename":str(candidate.get("filename") or "")[:240],
        "source_release":str(candidate.get("release_info") or "")[:240],
        "source_series_title":str(row.get("series_title") or "")[:160],
        "source_season":row.get("season"),"source_episode":row.get("episode"),
        "source_archive_member":str(member)[:240],
        "format":"srt","bytes":len(raw),"sha256":checksum,
        "video_seconds":round(runtime,3),
        "cues":qa["cues"],
        "japanese_characters":qa["japanese_characters"],
        "japanese_cue_fraction":qa["japanese_cue_fraction"]
    }
    try:
        with stage.stage_db() as db:
            existing=db.execute(
                "SELECT sha256,host_path FROM staged WHERE jellyfin_id=? AND subtitle_id=?",
                (jid,sid)).fetchone()
            if existing and existing!=(checksum,str(target)):
                raise RuntimeError("subdl_stage_id_collision")
            db.execute("""INSERT INTO staged
                (jellyfin_id,subtitle_id,host_path,sha256,staged_at,status,metrics_json)
                VALUES(?,?,?,?,strftime('%s','now'),'staged',?)
                ON CONFLICT(jellyfin_id,subtitle_id) DO NOTHING""",
                (jid,sid,str(target),checksum,json.dumps(meta,sort_keys=True)))
            db.commit()
    except BaseException:
        if new:
            target.unlink(missing_ok=True)
        raise
    print("STAGED_SUBDL:",jid,"source_id:",sid,flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jellyfin-id",required=True)
    parser.add_argument("--subtitle-id",default="",
                        help="exact saved SubDL release to attempt within deep source recovery")
    parser.add_argument("--apply",action="store_true")
    args=parser.parse_args()
    if not re.fullmatch(r"[a-f0-9]{32}",args.jellyfin_id):
        parser.error("Invalid Jellyfin media ID")
    inventory=stage.read_inventory()
    row=inventory.get(args.jellyfin_id)
    if not row or row.get("status")!="ready_ja_search":
        raise RuntimeError("media_not_eligible")
    if args.subtitle_id and not SUBDL_ID.fullmatch(args.subtitle_id):
        parser.error("Invalid SubDL saved candidate ID")
    candidates=private_candidate(args.jellyfin_id,row,args.subtitle_id or None)
    print("SUBDL_SAVED_CANDIDATES:",len(candidates),flush=True)
    if not candidates or not args.apply:
        return
    runtime=stage.duration_if_safe(row)
    errors=[]
    for candidate in candidates:
        try:
            stage_one(row,candidate,runtime)
            return
        except HTTPError as exc:
            if exc.code in (406,429):
                print("PROVIDER_LIMIT_REACHED: SubDL",flush=True)
                return
            errors.append("HTTP_"+str(exc.code))
        except (RuntimeError,OSError,ValueError,zipfile.BadZipFile) as exc:
            errors.append(type(exc).__name__)
    print("SUBDL_HELD:",",".join(errors[:3]),flush=True)


if __name__=="__main__":
    try:main()
    except (OSError,RuntimeError,ValueError,sqlite3.Error) as exc:
        print("SUBDL_STAGE_HELD:",type(exc).__name__,str(exc)[:110],flush=True)
        raise SystemExit(1)
