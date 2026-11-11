#!/usr/bin/env python3
"""Source-first, queue-owned PLaMo8B handoff for one verified-English media item.

This is a bounded, opt-in bridge to the existing proven PLaMo 8B GGUF runtime,
not a second subtitle provider or a replacement for the active source worker.

Default: read-only queue plan. Explicit owner movie pilot accepts new Jellyfin\nitems before matrix refresh, without creating automatic provider or AI work.\n--prepare: write verified English checkpoint
without GPU use.  --apply: after source-only batch is idle, resume cue translation
and create ONE Japanese sidecar; never overwrite.  The planned unattended
dispatcher can use the same one-item API after reboot-safe controller exists.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import tempfile
import time

HOME = Path.home()
QUEUE = HOME / "bruiser-pilot/coverage-queue/coverage.sqlite3"
ROOT = HOME / "bruiser-pilot/plamo3-ab"
WORK = HOME / "bruiser-pilot/subhub-translation"
BATCH_STATE = ROOT / "american-dad-existing-english-batch/batch.pid"
ALLOWED_ACTIONS = {"validate_english_for_ja_fallback",
                   "recover_english_for_ja_fallback"}
OWNER_REVIEW_ACTIONS = {"review_saved_ja", "download_saved_ja",
                        "align_existing_staged_ja", "search_ja"}
SEARCH_DB = HOME / "bruiser-pilot/ja-first-inventory/japanese-search.sqlite3"
PLANNABLE_ACTIONS = {
    "validate_english_for_ja_fallback",
    "recover_english_for_ja_fallback",
    "search_en",
}
MODEL_NAME = "plamo-3-translate-8b-Q4_K_M.gguf"
JELLYFIN_ID = re.compile(r"[a-f0-9]{32}\Z")


def utc():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def safe_db(path):
    path = Path(path)
    if (not path.is_file() or path.is_symlink() or
            path.stat().st_mode & 0o077 or
            path.stat().st_uid != os.getuid()):
        raise RuntimeError("private_coverage_queue_unavailable")
    return sqlite3.connect("file:" + str(path.resolve()) + "?mode=ro",
                           uri=True, timeout=10)


def eligible(db, jid=None, limit=15, owner_review=False):
    """Exact ID lookup; owner-review requests cannot reach unrelated episodes."""
    cond = " AND m.jellyfin_id=?" if jid else ""
    params = [jid] if jid else []
    params.append(limit)
    if owner_review:
        target_sql="t.target IN ('ja','review') "
        action = """AND m.kind='Episode' AND (
                    (t.target='ja' AND t.state IN ('pending','held')
                     AND t.action IN ('review_saved_ja','download_saved_ja',
                         'align_existing_staged_ja','search_ja')
                     AND (t.state='held' OR t.action='review_saved_ja'))
                    OR (t.target='review' AND t.state='pending'
                        AND t.action='review_uncertain'))"""
    else:
        target_sql="t.target='ja' "
        action = """AND t.state='pending'
                    AND t.action IN ('validate_english_for_ja_fallback',
                                     'recover_english_for_ja_fallback')"""
    return [dict(zip(("jellyfin_id","path","kind","title","series","action",
                      "state","target","english_text"), r))
            for r in db.execute("""
                SELECT m.jellyfin_id,m.path,m.kind,m.title,m.series,t.action,t.state,
                       t.target,m.en_text
                  FROM tasks AS t JOIN media AS m ON m.path=t.path
                 WHERE t.active=1 AND """ + target_sql + action + cond +
                 " ORDER BY t.priority,m.title LIMIT ?", params)]


def review_has_source_evidence(jid):
    """An owner may choose AI after an actual saved source search, not an API error."""
    if not JELLYFIN_ID.fullmatch(str(jid or "")):
        return False
    with safe_db(SEARCH_DB) as db:
        row = db.execute(
            "SELECT outcome,searched_at FROM searches WHERE jellyfin_id=?", (jid,)
        ).fetchone()
    if not row:
        return False
    outcome, searched_at = row
    return (outcome in ("none", "review", "plausible")
            and isinstance(searched_at, int)
            and 0 <= time.time() - searched_at <= 31 * 86400)


def validate_row(row, owner_review=False):
    if owner_review:
        if not JELLYFIN_ID.fullmatch(str(row.get("jellyfin_id") or "")):
            raise RuntimeError("owner_review_requires_exact_jellyfin_identity")
        if row["action"]=="review_uncertain":
            if (row["target"]!="review" or row["kind"]!="Episode"
                    or row["state"]!="pending"):
                raise RuntimeError("unlabeled_audio_review_not_eligible")
        elif (row["target"]!="ja" or row["kind"]!="Episode" or
                row["action"] not in OWNER_REVIEW_ACTIONS or
                row["state"] not in ("pending","held") or
                (row["state"] != "held" and row["action"] != "review_saved_ja") or
                not review_has_source_evidence(row["jellyfin_id"])):
            raise RuntimeError("review_source_evidence_missing_or_not_eligible")
    elif row["action"] not in ALLOWED_ACTIONS:
        raise RuntimeError("japanese_sourcing_not_exhausted_or_english_not_available")
    elif row["state"] != "pending":
        raise RuntimeError("not_a_pending_japanese_fallback_task")
    if row["target"]!="ja" and not (
            owner_review and row["target"]=="review"
            and row["action"]=="review_uncertain"):
        raise RuntimeError("not_a_japanese_fallback_task")
    if not row["jellyfin_id"] or not row["path"].startswith("/"):
        raise RuntimeError("invalid_coverage_queue_identity")
    if row["kind"] not in ("Movie","Episode"):
        raise RuntimeError("invalid_media_kind")
    if not row["english_text"] and row["action"]!="recover_english_for_ja_fallback" and not (
            owner_review and
            ((row["action"]=="review_uncertain"
              and row["target"]=="review") or
             (row["target"]=="ja" and row["state"]=="held"
              and row["action"] in OWNER_REVIEW_ACTIONS))):
        raise RuntimeError("english_text_not_indicated")


def explicit_movie_pilot(jid, movie_path, source, safe_media_path):
    """ONE owner-selected new Jellyfin movie, not an unattended queue override.

    A new item may appear in Jellyfin before the global 13k-item coverage
    snapshot. Verify exact Jellyfin ID, movie type and literal local path
    before using the same verified-English and create-only translation gates.
    Do NOT create a queue task, consume a provider quota, or claim Japanese
    sourcing is exhausted. This bypass is deliberately opt-in for a pilot.
    """
    if not JELLYFIN_ID.fullmatch(str(jid or "")):
        raise RuntimeError("invalid_explicit_jellyfin_id")
    if not isinstance(movie_path, str) or not movie_path.startswith("/"):
        raise RuntimeError("absolute_explicit_movie_path_required")
    video = safe_media_path(movie_path)
    if video.is_symlink() or not video.is_file():
        raise RuntimeError("explicit_movie_file_missing_or_symlink")
    client = source.NativeJellyfin()
    item = client.get("/Items/" + jid)
    if (not isinstance(item, dict) or item.get("Id") != jid
            or item.get("Type") != "Movie"
            or item.get("Path") != str(video)):
        raise RuntimeError("jellyfin_movie_identity_or_path_does_not_match")
    return {
        "jellyfin_id": jid, "path": str(video), "kind": "Movie",
        "title": str(item.get("Name") or ""), "series": "",
        "target": "ja", "action": "explicit_owner_movie_pilot",
        "state": "pending", "english_text": 1,
    }


def recent_running_source():
    """Do not start model inference while either source worker is active."""
    try:
        for unit in ("bruiser-subhub-batch.service",
                     "bruiser-ja-source-autofill.service",
                     "bruiser-subhub-season-sources.service"):
            check = subprocess.run(
                ["systemctl","--user","is-active","--quiet",unit],
                check=False, timeout=8, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL)
            if check.returncode == 0:
                return True
            if check.returncode not in (3,4):
                raise RuntimeError("source_service_state_unverifiable")
        return False
    except (OSError, subprocess.TimeoutExpired):
        raise RuntimeError("cannot_verify_source_batch_inactive")


def other_translation_running(pid_file=BATCH_STATE):
    """Avoid racing the older American Dad PLaMo batch after host reconnect."""
    path = Path(pid_file)
    if not path.exists():
        return False
    if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o077:
        raise RuntimeError("unsafe_previous_translation_pid_file")
    try:
        pid = int(path.read_text().strip())
    except ValueError:
        raise RuntimeError("invalid_previous_translation_pid_file")
    if pid < 2:
        raise RuntimeError("invalid_previous_translation_pid")
    try:
        os.kill(pid,0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        raise RuntimeError("previous_translation_pid_unverifiable")


def private_folder(jid, path, root=WORK):
    digest = hashlib.sha256((str(jid)+"\0"+str(path)).encode("utf-8")).hexdigest()[:24]
    root = Path(root)
    return root / ("ja-" + digest)


def atomic_json(path, data):
    if path.is_symlink():
        raise RuntimeError("unsafe_state_symlink")
    fd, temporary = tempfile.mkstemp(prefix=".state-", dir=str(path.parent))
    try:
        with os.fdopen(fd,"w",encoding="utf-8") as out:
            json.dump(data,out,ensure_ascii=False,sort_keys=True)
            out.write("\n")
            out.flush()
            os.fchmod(out.fileno(),0o600)
            os.fsync(out.fileno())
        os.replace(temporary,path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def modules():
    """Use the installed and previously tested PLaMo engine; never download it."""
    if not ROOT.is_dir() or ROOT.is_symlink():
        raise RuntimeError("proven_plamo_install_missing")
    sys.path.insert(0,str(ROOT))
    sys.path.insert(0,str(ROOT/"source-first-code"))
    from importlib import import_module
    batch=import_module("plamo8b_american_dad_existing_en_batch")
    engine=import_module("plamo3_watch_american_dad")
    source=import_module("plamo3_source_first_american_dad")
    sys.path.insert(0,str(engine.real.CONTROL))
    sys.path.insert(0,str(source.CONTROL))
    small=engine.small
    daily=import_module("daily_japanese")
    sync=import_module("ja_first_ffsubsync")
    from ja_first_stage_timing_audit import safe_media_path
    return batch,engine,source,small,daily,sync,safe_media_path


def normalize_external_english(raw, sync):
    """Normalize separators and quarantine one provably bogus final rewind.

    Downloaded SRTs can contain excess blank separators or a malformed trailer
    pointing to time zero after the movie's last legitimate cue. Only one
    strictly qualified trailer is excluded; all other corrupt cues hold.
    Work exclusively on a private in-memory copy; preserve the source SRT.
    """
    if not raw or len(raw) > 2_000_000:
        raise RuntimeError("english_srt_size_invalid")
    try:
        text=raw.decode("utf-8-sig")
    except UnicodeError:
        raise RuntimeError("english_srt_non_utf8") from None
    if "\x00" in text:
        raise RuntimeError("english_srt_contains_nul")
    line_text=text.replace("\r\n","\n").replace("\r","\n")
    clean=re.sub(r"\n[ \t]*\n(?:[ \t]*\n)+", "\n\n", line_text)
    clean=clean.strip("\n")+"\n"
    # Verbatim nonblank lines must survive in the same order. No subtitle
    # dialogue, number, time or textual annotation may be edited or discarded.
    if ([v for v in line_text.splitlines() if v.strip()] !=
            [v for v in clean.splitlines() if v.strip()]):
        raise RuntimeError("unsafe_english_normalization_modified_content")
    encoded=clean.encode("utf-8")
    trailer_quarantined=False
    before_count=len(re.findall(
        r"(?m)^[ \t]*\d{1,3}:\d{2}:\d{2}[,.]\d{3}[ \t]*-->",
        line_text))
    try:
        after=sync.parse_cues(encoded)
    except RuntimeError as exc:
        if str(exc)!="bad_srt_timestamp":
            raise
        # Quarantine one malformed cue pointing to ~0 seconds AFTER the
        # movie's actual final credits, never rewrite its timestamps.
        # Previous valid cues must include at least 45 minutes of video.
        blocks=re.split(r"\n[ \t]*\n",clean.strip("\n"))
        if len(blocks)<151:
            raise
        tail=blocks[-1].splitlines()
        offset=int(bool(tail and tail[0].strip().isdigit()))
        if len(tail)<offset+1:
            raise
        timing=tail[offset].strip()
        clock=r"\d{1,3}:\d{2}:\d{1,2}[,.]\d{1,3}"
        match=re.fullmatch(
            rf"({clock})\s*-->\s*({clock})(?:\s+.*)?",timing)
        if not match:
            raise
        def seconds(value):
            h,m,sec=value.replace(",",".").split(":")
            return int(h)*3600+int(m)*60+float(sec)
        start,end=map(seconds,match.groups())
        if not (0<=start<5 and start<end<=5):
            raise
        shortened="\n\n".join(blocks[:-1]).strip("\n")+"\n"
        preceding=sync.parse_cues(shortened.encode("utf-8"))
        if (len(preceding)<150 or len(preceding)!=before_count
                or preceding[-1]["end"]<45*60*1000):
            raise
        # The downloaded .en.srt remains untouched; record evidence in log.
        print("SUBHUB_AI_EN_TRAILING_CUE_QUARANTINED"
              " reason=malformed_near_zero_timestamp_at_end"
              " original_block_sha256="+
              hashlib.sha256(blocks[-1].encode()).hexdigest()[:16],
              " prior_valid_cues="+str(len(preceding)),
              " original_file_unchanged",flush=True)
        trailer_quarantined=True
        clean=shortened
        encoded=clean.encode("utf-8")
        after=preceding
    if len(after)!=before_count:
        raise RuntimeError("english_normalization_cue_count_changed")
    if encoded!=raw:
        print("SUBHUB_AI_EN_SOURCE_NORMALIZED"
              " mode="+("separators_and_quarantined_trailer"
                         if trailer_quarantined else "separators_or_line_endings")
              +" original_file_unchanged",
              flush=True)
    return encoded


def verify_owner_unlabeled_audio(video):
    """Owner confirmation is permitted only for EN/untagged audio, never known JA/foreign."""
    run=subprocess.run(
        ["ffprobe","-v","error","-select_streams","a",
         "-show_entries","stream_tags=language","-of","json",str(video)],
        capture_output=True,text=True,check=False,timeout=40)
    if run.returncode:
        raise RuntimeError("owner_review_audio_probe_failed")
    data=json.loads(run.stdout)
    streams=data.get("streams") or []
    if not isinstance(streams,list) or not streams:
        raise RuntimeError("owner_review_audio_track_missing")
    langs=[str((stream.get("tags") or {}).get("language") or "")
           .lower().split("-")[0] for stream in streams]
    if any(lang not in ("","und","unknown","mul","zxx",
                        "en","eng","english") for lang in langs):
        raise RuntimeError("known_non_english_audio_cannot_be_overridden")
    print("SUBHUB_AI_OWNER_AUDIO_UNTAGGED_ENGLISH_SUBTITLE_REQUIRED",
          flush=True)


def acquire_exact_english(video, jid, kind, source):
    """Find English only for the SAME Jellyfin video, never by fuzzy title.

    Uses the existing Jellyfin provider credentials. A video-hash match is
    necessary for unattended download; it is NOT timing approval. The caller
    must subsequently run exact-video ffsubsync and refuse unsafe alignment.
    """
    from urllib.parse import quote
    if not JELLYFIN_ID.fullmatch(str(jid or "")) or kind not in ("Episode","Movie"):
        raise RuntimeError("english_search_requires_exact_jellyfin_identity")
    client=source.NativeJellyfin()
    item=client.get("/Items/"+jid)
    if (not isinstance(item,dict) or item.get("Id")!=jid
            or item.get("Type")!=kind or item.get("Path")!=str(video)):
        raise RuntimeError("english_search_jellyfin_video_identity_mismatch")
    season=item.get("ParentIndexNumber") if kind=="Episode" else None
    episode=item.get("IndexNumber") if kind=="Episode" else None
    if kind=="Episode" and (
            type(season) is not int or type(episode) is not int
            or season<1 or episode<1):
        raise RuntimeError("english_search_episode_identity_missing")
    results=client.get("/Items/"+jid+"/RemoteSearch/Subtitles/eng")
    if not isinstance(results,list):
        raise RuntimeError("english_provider_search_not_list")
    accepted=[]
    for result in results:
        if not isinstance(result,dict) or result.get("IsHashMatch") is not True:
            continue
        if (not result.get("Id") or not result.get("ProviderName")
                or result.get("IsForced") is True):
            continue
        if str(result.get("Format") or "").casefold() not in ("srt","subrip"):
            continue
        if str(result.get("ThreeLetterISOLanguageName") or "").casefold() not in ("en","eng"):
            continue
        if kind=="Episode":
            tags=re.findall(r"(?i)s(\\d{1,2})[\\s._-]*e(\\d{1,3})",
                            str(result.get("Name") or ""))
            if tags and any((int(ss),int(ee))!=(season,episode)
                            for ss,ee in tags):
                continue
        accepted.append(result)
    if not accepted:
        raise RuntimeError("no_exact_video_hash_english_srt_found")
    accepted.sort(key=lambda x:(-int(x.get("DownloadCount") or 0),
                                str(x.get("ProviderName") or "")))
    chosen=accepted[0]
    client.post("/Items/"+jid+"/RemoteSearch/Subtitles/"+
                quote(str(chosen["Id"]),safe=""))
    print("SUBHUB_AI_ENGLISH_DOWNLOADED video_hash_verified"
          " provider="+str(chosen["ProviderName"])[:45]+
          " timing=unverified_pending_ffsubsync",flush=True)


def saved_media(video, jid, info, daily, source, small, sync, safe_media_path,
                *, kind="Episode", allow_unlabeled_audio=False):
    """Exact-file EN only; hold bad external sync, missing EN, unexpected audio."""
    video = safe_media_path(str(video))
    if video.is_symlink() or not video.is_file():
        raise RuntimeError("missing_or_symlinked_video")
    if daily.already_ja(video) or info["ja"]:
        raise RuntimeError("japanese_already_present_skip")
    if not info["audio_en"]:
        if not allow_unlabeled_audio:
            raise RuntimeError("english_audio_not_verified")
        verify_owner_unlabeled_audio(video)
    if info["embedded_en"] is None and daily.english_srt(video) is None:
        print("SUBHUB_AI_ENGLISH_MISSING source_search_for_exact_video",flush=True)
        acquire_exact_english(video,jid,kind,source)
        if daily.english_srt(video) is None:
            raise RuntimeError("english_download_not_available_as_sidecar")
    if info["embedded_en"] is not None:
        result = subprocess.run(
            ["ffmpeg","-nostdin","-hide_banner","-loglevel","error",
             "-i",str(video),"-map",f"0:{info['embedded_en']}",
             "-vn","-an","-c:s","srt","-f","srt","pipe:1"],
            capture_output=True,check=False,timeout=180)
        if result.returncode:
            raise RuntimeError("embedded_english_extraction_failed")
        raw = result.stdout
        provenance = "embedded_same_media"
        aligned = raw
        timing = {"mode":"same_file_embedded"}
    else:
        candidate = daily.english_srt(video)
        if (candidate is None or candidate.is_symlink() or
                not candidate.is_file() or candidate.stat().st_size > 2_000_000):
            raise RuntimeError("external_english_source_unsafe")
        raw = candidate.read_bytes()
        provenance = "external_audio_synced"
        normalized = normalize_external_english(raw, sync)
        aligned,timing=source.validate_timing_source(
            video,normalized,"external",sync)
    cues = small.parse_srt(aligned.decode("utf-8-sig"),limit=1501)
    if not 150 <= len(cues) <= 1500:
        raise RuntimeError("source_cue_count_outside_safe_initial_pilot_bounds")
    if [c["number"] for c in cues] != list(range(1,len(cues)+1)):
        raise RuntimeError("noncontiguous_english_cue_numbers")
    return video,cues,hashlib.sha256(raw).hexdigest(),provenance,timing


def prepared_source(row, folder, mod):
    """Immutable source for restart. A changing video or cue digest blocks reuse."""
    batch,engine,source,small,daily,sync,safe_media_path=mod
    video=safe_media_path(row["path"])
    st=video.stat()
    manifest=folder/"manifest.json"
    srt=folder/"source.en.srt"
    if manifest.exists() or srt.exists() or manifest.is_symlink() or srt.is_symlink():
        if any(x.is_symlink() for x in (manifest,srt)):
            raise RuntimeError("unsafe_pinned_source_symlink")
        # A crash between writing EN source and committing its immutable
        # manifest leaves an orphan. Safe recovery is allowed ONLY when no
        # model checkpoint exists, so no translated cues could depend on it.
        if srt.is_file() and not manifest.exists():
            checkpoint = folder/"progress.sqlite3"
            if checkpoint.exists() or checkpoint.is_symlink():
                raise RuntimeError("orphan_source_with_checkpoints_hold")
            if srt.stat().st_size>2_000_000 or srt.stat().st_mode & 0o077:
                raise RuntimeError("unsafe_orphan_source_hold")
            srt.unlink()
        elif not (manifest.is_file() and srt.is_file()):
            raise RuntimeError("incomplete_pinned_source_hold")
        else:
            m=json.loads(manifest.read_text("utf-8"))
            if (m.get("jellyfin_id")!=row["jellyfin_id"] or
                    m.get("video")!=str(video) or m.get("size")!=st.st_size or
                    m.get("mtime_ns")!=st.st_mtime_ns or
                    m.get("model_sha256")!=engine.MODEL_HASH):
                raise RuntimeError("pinned_source_or_model_identity_changed")
            src=srt.read_text("utf-8")
            if hashlib.sha256(src.encode()).hexdigest()!=m.get("english_sha256"):
                raise RuntimeError("pinned_english_source_hash_changed")
            cues=small.parse_srt(src,limit=1501)
            if len(cues)!=m["cue_count"] or len(cues)>1500:
                raise RuntimeError("pinned_english_cue_count_changed")
            return video,cues,m
    info=daily.probe(video)
    video,cues,sha,origin,timing=saved_media(
        video,row["jellyfin_id"],info,daily,source,small,sync,safe_media_path,
        kind=row["kind"], allow_unlabeled_audio=(
            (row.get("action")=="review_uncertain"
             and row.get("target")=="review") or
            (row.get("target")=="ja" and row.get("state")=="held"
             and row.get("action") in OWNER_REVIEW_ACTIONS)))
    now=video.stat()
    if (now.st_size!=st.st_size or now.st_mtime_ns!=st.st_mtime_ns):
        raise RuntimeError("media_changed_during_english_preparation")
    canonical=small.format_srt(cues,"english")
    m={
        "schema":1,"jellyfin_id":row["jellyfin_id"],"video":str(video),
        "kind":row["kind"],"size":st.st_size,"mtime_ns":st.st_mtime_ns,
        "cue_count":len(cues),"english_sha256":hashlib.sha256(
            canonical.encode("utf-8")).hexdigest(),
        "original_sha256":sha,"origin":origin,"timing":timing,
        "model_sha256":engine.MODEL_HASH,"model":MODEL_NAME,
        "created_utc":utc(),
    }
    with srt.open("x",encoding="utf-8") as out:
        out.write(canonical)
        out.flush()
        os.fsync(out.fileno())
    atomic_json(manifest,m)
    return video,cues,m


@contextmanager
def scoped_engine(engine, folder):
    old=(engine.WORK,engine.CHECKPOINT,engine.SOURCE,engine.MANIFEST)
    engine.WORK=folder
    engine.CHECKPOINT=folder/"progress.sqlite3"
    engine.SOURCE=folder/"source.en.srt"
    engine.MANIFEST=folder/"manifest.json"
    try:
        yield
    finally:
        engine.WORK,engine.CHECKPOINT,engine.SOURCE,engine.MANIFEST=old


MOVIE_GPU_PAUSE = 78.0
MOVIE_GPU_RESUME = 72.0
MOVIE_GPU_ABORT = 83.0


def movie_thermal_limits(batch):
    """Movie-only in-process override; do not patch the American Dad runtime."""
    if not 0 < MOVIE_GPU_RESUME < MOVIE_GPU_PAUSE < MOVIE_GPU_ABORT:
        raise RuntimeError("unsafe_movie_thermal_thresholds")
    if batch.GPU_ABORT != MOVIE_GPU_ABORT:
        raise RuntimeError("unexpected_proven_runtime_gpu_abort_limit")
    batch.GPU_PAUSE = MOVIE_GPU_PAUSE
    batch.GPU_RESUME = MOVIE_GPU_RESUME
    print("SUBHUB_AI_GPU_THERMALS"
          f" pause={MOVIE_GPU_PAUSE:g}C resume={MOVIE_GPU_RESUME:g}C"
          f" abort={MOVIE_GPU_ABORT:g}C", flush=True)


def recover_held_cue(request, retry, port, english, history, spoken):
    """Preserve checkpoints; retry a Latin-only answer without preceding cues.

    The proven two-attempt model call runs first. Only a non-Japanese response
    triggers one context-free two-attempt retry. Never store Latin-only dialogue.
    """
    def attempt(context):
        try:
            return retry(request, port, english, context)
        except RuntimeError as exc:
            # Only exact known *response-format* failures are local to a cue.
            # GPU, thermal, network, disk and model-server failures must
            # propagate rather than being disguised as subtitle omissions.
            if not re.fullmatch(
                r"cue_model_error_after_retry:"
                r"(?:missing_model_completion|model_output_truncated|"
                r"empty_or_malformed_model_output)",str(exc)):
                raise
            print("SUBHUB_AI_CUE_RECOVERY"
                  " malformed_completion_after_internal_retry",flush=True)
            return "", {}, "held_non_japanese"
    japanese, usage, status = attempt(history)
    if status != spoken and history:
        print("SUBHUB_AI_CUE_RECOVERY retry_without_history", flush=True)
        japanese, usage, status = attempt([])
    return japanese, usage, status



# A failed isolated dialogue cue must not abort a feature-length subtitle.
# This is explicitly a small, auditable omission budget, never a fake translation.
HELD_STATUS = "held_translation"
MAX_HELD_CUES = 10
MAX_CONSECUTIVE_HELD = 2


def verify_movie_checkpoints(engine, db, cues):
    """Validate every saved cue, including explicitly recorded held dialogue.

    Identical invariants to the proven engine's verifier, with one additional
    movie-only status: held, with an EMPTY Japanese field. This cannot be
    mistaken for translated or non-dialogue text, and survives restart.
    """
    rows=db.execute(
        "SELECT idx,id,start,end,english,japanese,status,seconds "
        "FROM translation ORDER BY idx").fetchall()
    if len(rows)>len(cues):
        raise RuntimeError("checkpoint_longer_than_source")
    if not any(r[6]==HELD_STATUS for r in rows):
        return engine.verify_checkpoints(db,cues)
    output=[]
    for position,(idx,number,begin,end,en,ja,status,seconds) in enumerate(rows):
        cue=cues[position]
        if ((idx,number,begin,end,en)!=(position,cue["number"],
                cue["start"],cue["end"],cue["english"])):
            raise RuntimeError("checkpoint_source_mismatch")
        if status==HELD_STATUS:
            if ja not in ("",None):
                raise RuntimeError("held_cue_must_not_contain_fake_translation")
        elif status==engine.SPOKEN:
            if not engine.small.JP.search(ja or "") or "<|plamo:" in ja:
                raise RuntimeError("checkpoint_invalid_japanese")
        elif status==engine.SOLO_SDH:
            if ja!=en or not engine.real.is_non_dialogue_caption(en):
                raise RuntimeError("checkpoint_invalid_SDH")
        else:
            raise RuntimeError("checkpoint_invalid_status")
        output.append(dict(cue,japanese=ja or "",status=status,seconds=seconds))
    return output


def held_summary(output):
    """Bound omissions while keeping the original complete EN source frozen."""
    held=[row for row in output if row["status"]==HELD_STATUS]
    streak=0
    for row in output:
        streak=streak+1 if row["status"]==HELD_STATUS else 0
        if streak>MAX_CONSECUTIVE_HELD:
            raise RuntimeError("too_many_consecutive_held_cues_manual_review")
    if len(held)>MAX_HELD_CUES:
        raise RuntimeError("too_many_held_cues_manual_review")
    return held


def translate(row, folder, mod, port=18888):
    batch,engine,source,small,daily,sync,safe_media_path=mod
    if recent_running_source():
        raise RuntimeError("source_batch_still_running_retry_after_it_finishes")
    if other_translation_running():
        raise RuntimeError("existing_american_dad_translator_active")
    # Movie-only thermal profile: no changes to legacy American Dad scripts.
    movie_thermal_limits(batch)
    # Independent gate: other PLaMo or Wolf sessions must release GPU RAM.
    batch.thermal_gate()
    video,cues,m=prepared_source(row,folder,mod)
    if daily.already_ja(video) or daily.probe(video)["ja"]:
        raise RuntimeError("japanese_source_arrived_while_queued_no_translation")
    weight=ROOT/"models"/MODEL_NAME
    engine.eight.validate_weight(weight)
    if small.digest(weight)!=engine.MODEL_HASH:
        raise RuntimeError("official_plamo_weight_hash_mismatch")
    destination=engine.safe_dest(video)
    if destination.exists() or destination.is_symlink():
        raise RuntimeError("named_ja_track_exists_no_overwrite")
    with scoped_engine(engine,folder):
        db=engine.checkpoints()
        try:
            output=verify_movie_checkpoints(engine,db,cues)
            held_summary(output)
            print(f"SUBHUB_AI_START media={row['jellyfin_id']} "
                  f"cues={len(cues)} resumed={len(output)}",flush=True)
            if len(output)<len(cues):
                binary=ROOT/"runtime/llama-server"
                logfile=folder/("llama-"+datetime.now(timezone.utc).strftime(
                    "%Y%m%dT%H%M%SZ")+".log")
                # Do not import American Dad movie scanning: only reuse thermal
                # monitoring and the verified 8B CUDA server setup.
                proc=batch.start_cool_server(binary,weight,port,28,logfile)
                try:
                    for idx in range(len(output),len(cues)):
                        cue=cues[idx]
                        started=time.monotonic()
                        if engine.real.is_non_dialogue_caption(cue["english"]):
                            ja,status=cue["english"],engine.SOLO_SDH
                        else:
                            # Same gate as the episode worker, before each
                            # actual model cue, not every tenth saved row.
                            batch.thermal_gate()
                            ja,_,status=recover_held_cue(
                                engine.real.request,batch.translate_with_one_retry,
                                port,cue["english"],engine.previous_pairs(output),
                                engine.SPOKEN)
                            if status!=engine.SPOKEN:
                                # Never count Latin-only model output as Japanese.
                                # Commit a held marker so the next cue can run
                                # and so restarts never retry the same bad cue.
                                ja,status="",HELD_STATUS
                                print("SUBHUB_AI_CUE_HELD number="+str(cue["number"])
                                      +" reason=non_japanese_after_retries",
                                      flush=True)
                            # Name-specific repair applies only to that series.
                            if (status==engine.SPOKEN and
                                    row.get("series","").casefold().startswith("american dad")):
                                ja=batch.safe_roger_name(cue["english"],ja)
                        seconds=round(time.monotonic()-started,3)
                        db.execute(
                            "INSERT INTO translation(idx,id,start,end,english,"
                            "japanese,status,seconds) VALUES(?,?,?,?,?,?,?,?)",
                            (idx,cue["number"],cue["start"],cue["end"],
                             cue["english"],ja,status,seconds))
                        db.commit()
                        output.append(dict(cue,japanese=ja,status=status,
                                           seconds=seconds))
                        held_summary(output)
                        if idx==0 or (idx+1)%25==0 or idx+1==len(cues):
                            print("SUBHUB_AI_PROGRESS",
                                  str(idx+1)+"/"+str(len(cues)),flush=True)
                finally:
                    small.stop_server(proc)
            if len(output)!=len(cues):
                raise RuntimeError("incomplete_cue_translation_no_publication")
            held=held_summary(output)
            if held:
                print("SUBHUB_AI_REVIEW_NEEDED held_cues="+str(len(held))
                      +" cue_numbers="+",".join(str(c["number"]) for c in held),
                      flush=True)
            # Omit only explicitly held dialogue, not fake a Japanese line.
            # Original EN is retained for targeted future correction.
            content,spoken=engine.jellyfin_srt(
                [c for c in output if c["status"]!=HELD_STATUS])
            if not content.strip() or spoken<50:
                raise RuntimeError("insufficient_translated_dialogue")
            # engine.write_new_sidecar is create-only, validates source video,
            # and refuses if another Japanese track arrived.
            published=engine.write_new_sidecar(
                video,{"size":m["size"],"mtime_ns":m["mtime_ns"],
                       "source_first":True},daily,content)
            atomic_json(folder/"result.json",{
                "state":"published","jellyfin_id":row["jellyfin_id"],
                "cue_count":len(cues),"dialogue_count":spoken,
                "held_cue_numbers":[c["number"] for c in held],
                "held_count":len(held),
                "published_utc":utc(),"subtitle_name":published.name})
            print(("SUBHUB_AI_PUBLISHED_WITH_HELD_CUES" if held
                   else "SUBHUB_AI_PUBLISHED")+" media="+row["jellyfin_id"]+
                  " spoken="+str(spoken)+" held="+str(len(held)),flush=True)
        finally:
            db.close()


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    group=parser.add_mutually_exclusive_group()
    group.add_argument("--prepare",action="store_true",
                       help="verify one title's English and checkpoint source, no GPU")
    group.add_argument("--apply",action="store_true",
                       help="translate exactly one eligible title with proven GPU engine")
    parser.add_argument("--jellyfin-id",help="exact Jellyfin item ID; mandatory for writes")
    parser.add_argument("--owner-reviewed-source",action="store_true",
                        help="Explicit owner AI fallback for one reviewed/held searched episode")
    parser.add_argument("--limit",type=int,default=15)
    parser.add_argument("--explicit-movie-pilot",action="store_true",
                        help="owner-opt-in newly added movie before queue refresh; no JA provider attempts")
    parser.add_argument("--movie-path",help="exact host path for the explicit Jellyfin movie pilot")
    args=parser.parse_args(argv)
    if not 1<=args.limit<=50:
        parser.error("--limit must be 1..50")
    if (args.prepare or args.apply) and not args.jellyfin_id:
        parser.error("--prepare/--apply requires --jellyfin-id")
    if args.owner_reviewed_source and (args.explicit_movie_pilot or
                                      not args.jellyfin_id or
                                      not (args.prepare or args.apply)):
        parser.error("--owner-reviewed-source requires an exact queued episode")
    if args.explicit_movie_pilot:
        if not (args.prepare or args.apply) or not args.movie_path:
            parser.error("--explicit-movie-pilot requires --prepare or --apply and --movie-path")
    elif args.movie_path:
        parser.error("--movie-path is only valid with --explicit-movie-pilot")
    rows = []
    if not args.explicit_movie_pilot:
        with safe_db(QUEUE) as db:
            rows=eligible(db,args.jellyfin_id,args.limit,
                          owner_review=args.owner_reviewed_source)
        if not (args.prepare or args.apply):
            from collections import Counter
            print("SUBHUB_AI_HANDOFF_READ_ONLY")
            print("Pending source-exhausted JA:",len(rows),
                  "(bounded view, not total backlog)")
            print("Routes:",json.dumps(dict(Counter(r["action"] for r in rows))))
            for r in rows:
                print(r["jellyfin_id"],r["kind"],r["title"],
                      r["action"],"EN indicated" if r["english_text"] else "EN missing")
            print("No GPU, Jellyfin, media, queue or provider changes")
            return
        if len(rows)!=1:
            raise RuntimeError("requested_exact_pending_fallback_task_not_found")
        row=rows[0]
        validate_row(row,owner_review=args.owner_reviewed_source)
        if args.owner_reviewed_source:
            print("SUBHUB_AI_OWNER_REVIEW_FALLBACK media="+row["jellyfin_id"]+
                  " action="+row["action"]+" state="+row["state"],flush=True)
    if args.explicit_movie_pilot:
        if recent_running_source():
            raise RuntimeError("source_batch_still_running_retry_after_it_finishes")
        mod=modules()
        row=explicit_movie_pilot(args.jellyfin_id,args.movie_path,
                                 mod[2],mod[6])
    if WORK.is_symlink():
        raise RuntimeError("unsafe_translation_work_root")
    WORK.mkdir(parents=True,exist_ok=True,mode=0o700)
    if WORK.stat().st_mode & 0o077:
        raise RuntimeError("translation_work_root_not_private")
    folder=private_folder(row["jellyfin_id"],row["path"])
    if folder.is_symlink():
        raise RuntimeError("unsafe_translation_work_item")
    folder.mkdir(mode=0o700,exist_ok=True)
    if folder.stat().st_mode & 0o077:
        raise RuntimeError("translation_work_item_not_private")
    lock_path=WORK/".translation.lock"
    if lock_path.is_symlink():
        raise RuntimeError("unsafe_translation_lock")
    with lock_path.open("a+b") as lock:
        fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        if recent_running_source():
            raise RuntimeError("source_batch_still_running_retry_after_it_finishes")
        if not args.explicit_movie_pilot:
            if args.owner_reviewed_source:
                # Recheck the queue and source proof immediately before GPU use.
                with safe_db(QUEUE) as db:
                    fresh=eligible(db,row["jellyfin_id"],1,owner_review=True)
                if (len(fresh)!=1 or fresh[0]["path"]!=row["path"]):
                    raise RuntimeError("review_queue_changed_repreview_required")
                validate_row(fresh[0],owner_review=True)
            mod=modules()
        else:
            # Recheck current Jellyfin identity immediately before first write;
            # no past queue snapshot can authorize an unrelated file.
            row=explicit_movie_pilot(args.jellyfin_id,args.movie_path,
                                     mod[2],mod[6])
            print("SUBHUB_AI_EXPLICIT_MOVIE_PILOT media="+row["jellyfin_id"]+
                  " title="+row["title"],flush=True)
        if args.prepare:
            video,cues,m=prepared_source(row,folder,mod)
            print("SUBHUB_AI_ENGLISH_PREPARED media="+row["jellyfin_id"]+
                  " cues="+str(len(cues))+" origin="+m["origin"])
            print("No GPU work or subtitle publication performed")
        else:
            translate(row,folder,mod)


if __name__=="__main__":
    try:
        main()
    except (OSError,ValueError,RuntimeError,sqlite3.Error,
            subprocess.TimeoutExpired) as exc:
        print("SUBHUB_AI_HELD",type(exc).__name__,str(exc)[:220],
              file=sys.stderr)
        raise SystemExit(1) from None
