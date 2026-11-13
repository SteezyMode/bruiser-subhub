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
    from . import ja_first_srt_normalize as structure
    from . import ja_first_candidate_progress as progress
except ImportError:
    import ja_first_stage_saved_batch as stage
    import ja_first_stage_jellyfin as jelly
    import ja_first_publish_staged as publisher
    import subhub_download_ledger as ledger
    import ja_first_srt_normalize as structure
    import ja_first_candidate_progress as progress

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
    if row.get("kind")=="Movie":
        # Share the conservative film identity predicate with OpenSubtitles.
        # Only the download/stage transport differs; publication still
        # requires exact-video synchronization and Japanese-content QA.
        return stage.movie_identity_ok(row,candidate)
    if row.get("kind")!="Episode":
        return False
    expected={(row["season"],row["episode"])}
    tags=stage.named_episode(str(candidate.get("filename") or "")+" "+
                             str(candidate.get("release_info") or ""))
    if tags and tags!=expected:
        return False
    matches=set(candidate.get("matches") or [])
    # The broad provider endpoint also returns other shows with the same
    # S/E numbers. Require actual series identity in the name OR verified
    # provider series match, not episode numbers alone.
    series=stage.tokens(row.get("series_title"))
    texts=(candidate.get("filename"),candidate.get("release_info"))
    named=any(stage.contiguous_words(stage.tokens(text),series)
              for text in texts) if series else False
    series_evidence=named or "series" in matches
    return series_evidence and (expected==tags or
                                {"episode","season"}.issubset(matches))


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


DETERMINISTIC_ZIP_HOLDS = frozenset({
    "subdl_archive_srt_rejected",
    "subdl_archive_no_matching_srt_member",
    "subdl_archive_only_forced_srt_members",
    "subdl_archive_no_srt_members",
})


def cached_zip_path(candidate):
    remote=str(candidate.get("subtitle_id") or "")
    if not SUBDL_ID.fullmatch(remote):
        raise RuntimeError("unsafe_subdl_id")
    _,digest=numeric_id(remote)
    return stage.STAGED/"subdl-source-zips"/(digest+".zip")


def known_rejected_cached(row,candidate):
    """One cached ZIP/validator version is tried at most once per movie.

    Any parser change or ZIP byte change invalidates the receipt. Never
    contact the provider just to establish a known rejection.
    """
    path=cached_zip_path(candidate)
    if path.is_symlink():
        raise RuntimeError("unsafe_private_subdl_archive_symlink")
    if not path.exists():
        return None
    if (not path.is_file() or path.stat().st_mode & 0o077
            or not 0<path.stat().st_size<=MAX_ARCHIVE):
        raise RuntimeError("unsafe_private_subdl_archive")
    sid,_=numeric_id(str(candidate["subtitle_id"]))
    digest=hashlib.sha256(path.read_bytes()).hexdigest()
    fingerprint=progress.fingerprint(row["host_path"],digest,"subdl-stage")
    return progress.known(str(row["jellyfin_id"]),sid,"subdl-stage",fingerprint)


def remember_cached_rejection(row,candidate,blob,error):
    reason=str(error).split(":",1)[0]
    if reason not in DETERMINISTIC_ZIP_HOLDS:
        return
    sid,_=numeric_id(str(candidate["subtitle_id"]))
    key=progress.fingerprint(
        row["host_path"],hashlib.sha256(blob).hexdigest(),"subdl-stage")
    progress.remember(str(row["jellyfin_id"]),sid,"subdl-stage",key,error)


def cached_archive(candidate):
    """Reuse saved provider ZIP bytes after one GET, including QA-rejected ZIPs.

    A failed extraction must not burn tomorrow's quota just to see the same
    release. Cache is private and bounded; never contains credentials or
    untrusted paths from the provider. Media/staging DB remain untouched.
    """
    remote=str(candidate["subtitle_id"])
    _,digest=numeric_id(remote)
    stage.STAGED.mkdir(mode=0o700,exist_ok=True)
    if (stage.STAGED.is_symlink() or not stage.STAGED.is_dir() or
            stage.STAGED.stat().st_mode & 0o077):
        raise RuntimeError("unsafe_private_staging_folder")
    folder=stage.STAGED/"subdl-source-zips"
    folder.mkdir(mode=0o700,exist_ok=True)
    if (folder.is_symlink() or not folder.is_dir() or
            folder.stat().st_mode & 0o077):
        raise RuntimeError("unsafe_private_subdl_cache")
    dest=folder/(digest+".zip")
    if dest.is_symlink():
        raise RuntimeError("unsafe_private_subdl_archive_symlink")
    if dest.exists():
        if (not dest.is_file() or dest.stat().st_mode & 0o077 or
                not 0<dest.stat().st_size<=MAX_ARCHIVE):
            raise RuntimeError("unsafe_private_subdl_archive")
        raw=dest.read_bytes()
        if not zipfile.is_zipfile(BytesIO(raw)):
            raise RuntimeError("cached_subdl_archive_not_zip")
        print("SUBDL_ARCHIVE_CACHE: hit (provider GET skipped)",flush=True)
        return raw
    blob=download(candidate)
    # Only valid ZIP containers are cached. Invalid/no-byte provider replies
    # must not poison the release's deterministic private cache entry.
    if zipfile.is_zipfile(BytesIO(blob)):
        try:
            fd=os.open(str(dest),os.O_WRONLY|os.O_CREAT|os.O_EXCL|
                       getattr(os,"O_NOFOLLOW",0),0o600)
        except FileExistsError:
            if (dest.is_symlink() or not dest.is_file()
                    or dest.read_bytes()!=blob):
                raise RuntimeError("conflicting_cached_subdl_archive")
        else:
            try:
                with os.fdopen(fd,"wb") as out:
                    out.write(blob)
                    out.flush()
                    os.fsync(out.fileno())
            except BaseException:
                dest.unlink(missing_ok=True)
                raise
        print("SUBDL_ARCHIVE_CACHE: saved for future validation",flush=True)
    return blob


def archive_srt(blob,row,candidate,runtime):
    if not zipfile.is_zipfile(BytesIO(blob)):
        raise RuntimeError("subdl_archive_not_zip")
    movie=row.get("kind")=="Movie"
    expected={(row["season"],row["episode"])} if not movie else set()
    options=[]
    with zipfile.ZipFile(BytesIO(blob)) as arc:
        members=[m for m in arc.infolist()
                 if not m.is_dir() and m.filename.lower().endswith(".srt")]
        if len(arc.infolist())>MAX_MEMBERS:
            raise RuntimeError("subdl_archive_too_many_entries")
        if not members:
            raise RuntimeError("subdl_archive_no_srt_members")
        # A full Japanese track packaged alongside a separately labelled
        # forced/signs track is NOT an ambiguous choice between releases.
        # Forced-only tracks must never be accepted as full dialogue.
        def is_forced(item):
            words=set(stage.tokens(Path(item.filename).stem))
            return bool(words & {"forced", "signs", "signsonly"})
        normal_members=[m for m in members if not is_forced(m)]
        if not normal_members:
            raise RuntimeError("subdl_archive_only_forced_srt_members")
        for item in normal_members:
            if not 0<item.file_size<=2_000_000:
                continue
            if movie:
                words=stage.tokens(Path(item.filename).stem)
                title=stage.tokens(row.get("title"))
                year=str(row.get("year") or "")
                match=any(words[i:i+len(title)]==title
                          for i in range(len(words)-len(title)+1)) if title else False
                # An explicit different release year is authoritative even
                # when the provider's higher-level candidate name matched.
                member_years={word for word in words
                              if re.fullmatch(r"(?:19|20)\d{2}",word)}
                # Match the established film identity rule: festival and
                # theatrical release years may differ by ONE, not fifteen.
                if member_years and any(abs(int(w)-int(year))>1
                                        for w in member_years):
                    continue
                # For multiple distinct non-forced files, retain the strict
                # original title AND year requirement. With exactly one full
                # SRT, the other ZIP member(s) were forced/sign-only and
                # cannot make the choice ambiguous; still demand a matching
                # movie title when the ZIP contains multiple SRTs.
                if len(members)>1 and not match:
                    continue
                if len(normal_members)>1 and year not in words:
                    continue
                priority=2 if match and year in words else 1 if len(normal_members)==1 else 0
            else:
                tags=stage.named_episode(Path(item.filename).stem)
                if tags and tags!=expected:
                    continue
                if not tags and len(normal_members)!=1:
                    continue
                priority=1 if tags==expected else 0
            options.append((priority,item))
        if not options:
            raise RuntimeError("subdl_archive_no_matching_srt_member")
        options.sort(key=lambda pair:-pair[0])
        rejected=[]
        # Preserve the first plausibly decoded format failure instead of
        # reporting only noisy failures from subsequent fallback encodings.
        first_decoding_failure=None
        for _,member in options:
            try:
                raw=arc.read(member)
            except (RuntimeError,ValueError,zipfile.BadZipFile):
                rejected.append("member_unreadable")
                continue
            decoded=False
            for encoding in ("utf-8-sig","utf-16","cp932","shift_jis"):
                try:
                    content=raw.decode(encoding).encode("utf-8")
                except UnicodeError:
                    continue
                decoded=True
                try:
                    # SubDL archives may contain the same mechanical SRT
                    # defects as saved OpenSubtitles stages. Normalize only
                    # lossless, strictly validated defects; the original
                    # bytes remain in the private ZIP cache as provenance.
                    working,repair=structure.normalize(
                        content,trial_release_note=True,trial_local_swap=True)
                    qa=publisher.validate_srt(working,runtime)
                    qa["original_zip_member_sha256"]=hashlib.sha256(raw).hexdigest()
                    qa["structural_repair"]=repair
                    return working,qa,member.filename
                except (RuntimeError,ValueError) as exc:
                    # Stable error category only. Filename, raw provider bytes,
                    # private paths and arbitrary exception strings stay out
                    # of the shared progress and dashboard logs.
                    code=str(exc).split(":",1)[0]
                    if not re.fullmatch(r"[A-Za-z0-9_]{1,85}",code):
                        code="content_validation_error"
                    if first_decoding_failure is None:
                        first_decoding_failure=code
                    rejected.append(code)
            if not decoded:
                rejected.append("member_undecodable")
    # Distinguish no matching ZIP member from an identity-matching SRT that
    # fails Japanese content, duration or structural validation. This matters
    # when quota is exhausted: an error should not imply no provider result.
    reason=first_decoding_failure or (",".join(sorted(set(rejected))[:3]) or "unknown")
    raise RuntimeError("subdl_archive_srt_rejected:"+reason)


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
    blob=cached_archive(candidate)
    try:
        raw,qa,member=archive_srt(blob,row,candidate,runtime)
    except RuntimeError as exc:
        # A structurally invalid saved ZIP must not be counted as new work on
        # every daily scan. Cache only stable, byte-backed validation failures.
        remember_cached_rejection(row,candidate,blob,exc)
        raise
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
        "original_zip_member_sha256":qa.get("original_zip_member_sha256"),
        "structural_repair":qa.get("structural_repair"),
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
            reason=str(exc).split(":",1)[0]
            if isinstance(exc, RuntimeError) and (
                    reason.startswith("subdl_archive_") or
                    reason=="subdl_no_correct_episode_japanese_srt"):
                print("SUBDL_REJECTED:",str(exc)[:150],flush=True)
            else:
                # Only expose a safe fixed-code error token, never a URL,
                # provider credential, media path or arbitrary exception text.
                code=str(exc).split(":",1)[0]
                if not re.fullmatch(r"[A-Za-z0-9_]{1,90}",code):
                    code="unclassified"
                errors.append(type(exc).__name__+":"+code)
    if errors:
        print("SUBDL_HELD:",",".join(errors[:3]),flush=True)


if __name__=="__main__":
    try:main()
    except (OSError,RuntimeError,ValueError,sqlite3.Error) as exc:
        print("SUBDL_STAGE_HELD:",type(exc).__name__,str(exc)[:110],flush=True)
        raise SystemExit(1)
