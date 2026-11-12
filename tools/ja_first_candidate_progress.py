"""Shared selection, failure receipts and next-action policy for Japanese sourcing.

This module does not call providers, synchronize subtitles, start models, or
write media. Only the applying publisher may persist a verified failed attempt.
Reattempt automatically when staged bytes, video/EN sidecars, or alignment
implementation changes. Pending source searches and incomplete provider results
are never treated as exhausted.
"""
from __future__ import annotations

from functools import lru_cache
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import time

ROOT=Path.home()/"bruiser-pilot/ja-first-inventory"
DB=ROOT/"japanese-candidate-failures.sqlite3"
SEARCH_DB=ROOT/"japanese-search.sqlite3"
MODULES={
    "alass":("ja_first_alass.py","ja_first_ffsubsync.py",
             "ja_first_publish_staged.py","ja_first_obvious_quality.py"),
    "ffsubsync":("ja_first_ffsubsync.py","ja_first_publish_staged.py",
                "ja_first_obvious_quality.py"),
    "final":("ja_first_publish_queue.py","ja_first_publish_shifted.py",
             "ja_first_publish_staged.py","ja_first_alass.py",
             "ja_first_ffsubsync.py","ja_first_obvious_quality.py"),
}

def tokens(text):
    text=re.sub(r"(?<=[a-z])['\u2019](?=[a-z])","",str(text or "").casefold())
    return set(re.findall(r"[a-z]+|[0-9]+(?:\.[0-9]+)?",text))

def release_match(row,candidate):
    """Ranking hint, NEVER proof of identity or permission to publish.

    Match the *video filename* (not genre directory) to provider filename and
    release-info. Prefer edition/source/resolution matches ahead of provider
    score; avoid inventing compatibility when metadata is missing.
    """
    video=Path(str(row.get("host_path") or "")).stem
    release=" ".join(str(candidate.get(k) or "")
                     for k in ("release_info","filename"))
    source=tokens(video)
    remote=tokens(release)
    if not source or not remote:
        return 0
    value=0
    editions=("uncut","extended","theatrical","unrated","remastered","remux")
    for word in editions:
        a=word in source
        b=word in remote
        if a and b:
            value+=8
        elif a!=b:
            value-=7
    for group in (("bluray","bdrip","brrip","bdr","bdremux"),
                  ("web","webdl","webrip","web-dl","web-rip"),
                  ("dvdrip","dvd"),("hdtv",)):
        a=bool(source.intersection(group))
        b=bool(remote.intersection(group))
        if a and b:
            value+=5
        elif a!=b:
            value-=3
    for resolution in ("2160p","1080p","720p","480p"):
        a=resolution in source
        b=resolution in remote
        if a and b:
            value+=3
        elif a and b is False and any(r in remote for r in ("2160p","1080p","720p","480p")):
            value-=4
    # Release group tags are weak evidence; use only when both names carry one.
    for word in source.intersection(remote):
        if (len(word)>=5 and word not in {"movie","japanese","subtitle",
                                           "bluray","webrip","dvdrip","remux",
                                           "1080p","2160p","720p"} and
                not word.isdigit()):
            value+=1
            if value>30:
                break
    return max(-30,min(30,value))

@lru_cache(maxsize=8)
def implementation_hash(engine):
    names=MODULES[engine]
    h=hashlib.sha256()
    folder=Path(__file__).resolve().parent
    for name in names:
        path=folder/name
        if not path.is_file() or path.is_symlink():
            raise RuntimeError("alignment_implementation_unavailable:"+name)
        h.update(name.encode())
        h.update(hashlib.sha256(path.read_bytes()).digest())
    return h.hexdigest()

def fingerprint(video_path,staged_sha,engine):
    """Stable only while the selected file/reference and algorithm are stable."""
    if engine not in MODULES or not re.fullmatch(r"[a-f0-9]{64}",str(staged_sha)):
        raise ValueError("invalid_candidate_receipt_key")
    video=Path(str(video_path))
    if not video.is_file() or video.is_symlink():
        raise RuntimeError("candidate_media_missing_or_symlink")
    st=video.stat()
    related=[]
    # When someone supplies an exact-stem English sidecar, invalidate the
    # previous failure receipt even though the movie itself is unchanged.
    prefix=(video.stem+".").casefold()
    for p in video.parent.iterdir():
        if (p.is_symlink() or not p.is_file() or
                p.suffix.casefold() not in {".srt",".ass",".vtt"} or
                not p.name.casefold().startswith(prefix)):
            continue
        suffix=p.name[len(video.stem)+1:].casefold()
        if not set(re.findall(r"[a-z]+",suffix)).intersection({"en","eng","english"}):
            continue
        meta=p.stat()
        related.append((p.name,meta.st_size,meta.st_mtime_ns))
    record=[str(video),st.st_size,st.st_mtime_ns,sorted(related),
            staged_sha,engine,implementation_hash(engine)]
    return hashlib.sha256(json.dumps(record,separators=(",",":")).encode()).hexdigest()

def _secure_readable(path):
    if not path.exists() and not path.is_symlink():
        return False
    if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o077:
        raise RuntimeError("unsafe_candidate_failure_db")
    return True

def known(jid,sid,engine,key,*,db_path=None):
    path=DB if db_path is None else Path(db_path)
    if not _secure_readable(path):
        return None
    with sqlite3.connect("file:"+str(path.resolve())+"?mode=ro",uri=True,timeout=10) as con:
        try:
            row=con.execute(
                "SELECT reason FROM failures WHERE jellyfin_id=? AND subtitle_id=? "
                "AND engine=? AND fingerprint=?",(jid,sid,engine,key)).fetchone()
        except sqlite3.OperationalError as exc:
            if "no such table" in str(exc):
                return None
            raise
    return row[0] if row else None

def stable_failure(exc):
    """Cache deterministic mismatches, never system failures or timeouts."""
    if not isinstance(exc,(RuntimeError,ValueError)):
        return False
    message=str(exc).split(":",1)[0]
    return message.startswith(("alass_reordered_cues","alass_out_of_video",
         "alass_extreme_shift_requires_review","alass_cue_count_changed",
         "alass_dialogue_changed","alass_invalid_interval",
         "alass_subtitle_health_changed","alass_no_validated_reference",
         "empty_or_malformed_srt_cue","japanese_text_density_insufficient",
         "subtitle_too_sparse_for_full_dialogue","sync_cue_count_changed",
         "sync_dialogue_changed","subtitle_health_hold",
         "ffsubsync_cue_count_changed","ffsubsync_changed_dialogue",
         "ffsubsync_shift_or_variation_excessive",
         "ffsubsync_invalid_video_coverage","obvious_source_quality_hold",
         "no_candidate_passed_trusted_sync_correction"))

def remember(jid,sid,engine,key,exc,*,db_path=None):
    if not stable_failure(exc):
        return False
    if not re.fullmatch(r"[a-f0-9]{32}",str(jid)):
        raise RuntimeError("invalid_failure_jellyfin_id")
    if not (str(sid)=="final" or re.fullmatch(r"[1-9][0-9]{3,13}",str(sid))):
        raise RuntimeError("invalid_failure_subtitle_id")
    if engine not in MODULES or not re.fullmatch(r"[a-f0-9]{64}",str(key)):
        raise RuntimeError("invalid_failure_engine_or_fingerprint")
    path=DB if db_path is None else Path(db_path)
    if path.parent.is_symlink() or not path.parent.is_dir() or path.parent.stat().st_mode & 0o077:
        raise RuntimeError("unsafe_candidate_failure_directory")
    _secure_readable(path)
    import os
    old_umask=os.umask(0o077)
    try:
        con=sqlite3.connect(path,timeout=12)
    finally:
        os.umask(old_umask)
    with con:
        con.execute("""CREATE TABLE IF NOT EXISTS failures(
          jellyfin_id TEXT NOT NULL, subtitle_id TEXT NOT NULL,
          engine TEXT NOT NULL, fingerprint TEXT NOT NULL,
          reason TEXT NOT NULL, recorded_at INTEGER NOT NULL,
          PRIMARY KEY(jellyfin_id,subtitle_id,engine,fingerprint))""")
        con.execute("INSERT OR REPLACE INTO failures VALUES (?,?,?,?,?,?)",
                    (jid,str(sid),engine,key,str(exc)[:240],int(time.time())))
        con.commit()
    path.chmod(0o600)
    return True

def next_action(jid,staged_ids,*,search_path=None,accept_candidate=None):
    """Describe the next safe step; never launch GPU or providers implicitly."""
    path=SEARCH_DB if search_path is None else Path(search_path)
    if not _secure_readable(path):
        return "search_japanese"
    with sqlite3.connect("file:"+str(path.resolve())+"?mode=ro",uri=True,timeout=10) as db:
        entry=db.execute("SELECT outcome,results_json FROM searches WHERE jellyfin_id=?",
                         (jid,)).fetchone()
    if not entry:
        return "search_japanese"
    outcome,raw=entry
    try:
        data=json.loads(raw)
    except (ValueError,TypeError):
        return "review_search_evidence"
    if not isinstance(data,dict):
        return "review_search_evidence"
    saved=set(map(str,staged_ids))
    for item in data.get("candidates") or []:
        if (isinstance(item,dict) and item.get("grade") in ("plausible","review")
                and str(item.get("subtitle_id") or "") not in saved
                and (accept_candidate is None or accept_candidate(item))):
            return "stage_alternate_saved_japanese"
    if (outcome in ("partial","deferred","error","in_progress") or
            data.get("incomplete_providers") or
            any(v!="ok" for v in (data.get("provider_gates") or {}).values())):
        return "retry_japanese_providers_after_reset"
    if outcome in ("none","plausible","review"):
        return "offer_owner_reviewed_plamo_after_english_validation"
    return "review_search_evidence"
