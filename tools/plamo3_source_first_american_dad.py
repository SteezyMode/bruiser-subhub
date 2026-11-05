#!/usr/bin/env python3
"""ONE American Dad episode: Japanese-first source acquisition -> PLaMo 8B.

Execution order (no skipping a local Japanese source):
1. Inspect actual episode for local/embedded Japanese (done, no AI).
2. Search for a verified Japanese release via existing Sublarr provider;
   stage privately, audio sync, publish create-only only if existing QA fits.
3. If no usable Japanese release: use same-file embedded English, otherwise
   existing named English SRT, otherwise try exact-video-hash Jellyfin EN SRT.
4. Audio-sync external English using existing ffsubsync; if unsupported hold.
5. Translate selected episode by PLaMo 8B via the unchanged verified PFML3
   model engine. No EN source -> hold for future audio transcription.

Never change live timers, existing publisher settings, original subtitles,
Gemma runtime, PLaMo model prompts, video, or other episodes. Provider errors
and unverified candidates are explicitly reported, never called successes.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import time
from urllib.parse import quote

try:
    from . import plamo3_watch_american_dad as episode
    from . import plamo3_real_film_ab as real
except ImportError:
    import plamo3_watch_american_dad as episode
    import plamo3_real_film_ab as real

small = real.small
ROOT = real.ROOT
CONTROL = ROOT / "source-first-code"
JA_ROOT = Path.home() / "bruiser-pilot/ja-first-inventory"
MAX_CANDIDATES = 6


def helpers():
    if not CONTROL.is_dir() or CONTROL.is_symlink():
        raise RuntimeError("source_first_helpers_not_staged")
    sys.path.insert(0, str(CONTROL))
    sys.path.insert(0, str(real.CONTROL))
    import daily_japanese as daily
    import ja_first_search_pilot as ja_search
    import ja_first_stage_saved_batch as ja_stage
    import ja_first_publish_queue as ja_publish
    import ja_first_ffsubsync as ff_sync
    return daily, ja_search, ja_stage, ja_publish, ff_sync, None


def candidate_order(daily, wanted=None):
    """All candidates checked for local JA before any searches/translations.

    For one evening's actual viewing, prefer an episode with already-local
    English, respecting S08/S19/S20 priority. No AI for episodes with JA.
    """
    roots = daily.ensure_roots(daily.service.SOURCE_ROOTS)
    found = {}
    for video in daily.video_files(roots):
        tag = episode.episode_id(video)
        if tag and (wanted is None or tag == wanted):
            found.setdefault(tag, []).append(video)
    if wanted and wanted not in found:
        raise RuntimeError("requested_episode_not_in_actual_media_library")
    candidates = []
    present = []
    for tag, copies in found.items():
        if any(daily.already_ja(v) for v in copies):
            present.append(tag)
            continue
        for video in copies:
            if episode.safe_dest(video).exists() or episode.safe_dest(video).is_symlink():
                present.append(tag)
                continue
            try:
                info = daily.probe(video)
                if info["ja"]:
                    present.append(tag)
                    continue
                if not info["audio_en"]:
                    continue
                en_ready = bool(info["embedded_en"] is not None or daily.english_srt(video))
                season = int(tag[1:3])
                preferred = 0 if season == 8 else 1 if season == 19 else 2 if season == 20 else 3
                rank = (0 if en_ready else 1, preferred, tag, str(video))
                candidates.append((rank, tag, video, en_ready))
            except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
                continue
    candidates.sort(key=lambda row: row[0])
    return candidates, sorted(set(present))


def latest_row(video):
    """Authoritative saved Jellyfin/Sublarr metadata, not filename guessing."""
    files = sorted(JA_ROOT.glob("ja-intake-*.json"))
    if not files:
        raise RuntimeError("japanese_intake_manifest_missing")
    newest = files[-1]
    if newest.is_symlink() or newest.stat().st_mode & 0o077:
        raise RuntimeError("japanese_manifest_unsafe")
    if time.time() - newest.stat().st_mtime > 72 * 3600:
        raise RuntimeError("japanese_manifest_stale_refresh_first")
    blob = json.loads(newest.read_text("utf-8"))
    if blob.get("schema") != 1:
        raise RuntimeError("unexpected_japanese_catalog_schema")
    rows = [row for row in blob.get("items", [])
            if isinstance(row, dict) and row.get("host_path") == str(video)]
    if len(rows) != 1 or rows[0].get("kind") != "Episode":
        raise RuntimeError("episode_missing_or_ambiguous_in_jellyfin_manifest")
    row = rows[0]
    tag = episode.episode_id(video)
    if not tag or (int(tag[1:3]), int(tag[4:])) != (
            row.get("season"), row.get("episode")):
        raise RuntimeError("jellyfin_filename_episode_number_conflict")
    if row.get("status") not in (
            "ready_ja_search", "review_missing_series_identity"):
        raise RuntimeError("jellyfin_item_not_safe_for_japanese_provider_query")
    return row


def cached_or_search_ja(video, row, ja_search):
    if row.get("status") != "ready_ja_search":
        raise RuntimeError("japanese_source_identity_not_verified__no_translation")
    request = ja_search.query_for(row)
    if request is None:
        raise RuntimeError("japanese_source_query_not_safe__no_translation")
    job = {"id": str(row["jellyfin_id"]), "row": row, "query": request}
    with ja_search.open_db() as db:
        cached = db.execute(
            "SELECT searched_at,outcome,results_json FROM searches WHERE jellyfin_id=?",
            (job["id"],),
        ).fetchone()
        if cached is not None and time.time() - int(cached[0]) < (
                86400 if cached[1] == "error" else 6*3600 if cached[1] == "in_progress"
                else 30*86400):
            if cached[1] not in ("in_progress", "error"):
                data = json.loads(cached[2])
                items = data.get("candidates") or []
                print("JA SOURCING: reuse cached provider search, outcome",
                      cached[1], "| candidates", len(items), flush=True)
                return [x for x in items if isinstance(x, dict)]
            raise RuntimeError("japanese_provider_prior_error_or_incomplete")
        print("JA SOURCING: searching existing Sublarr Japanese provider",
              episode.episode_id(video), flush=True)
        ja_search.save_attempt(db, job, "in_progress")
        command = ["docker", "exec", "-i", "-e", "PYTHONPATH=/app",
                   "sublarr-pilot", "python3", "-c", ja_search.CONTAINER_WORKER]
        try:
            run = subprocess.run(
                command, input=json.dumps([{"id":job["id"],"query":request}]),
                text=True, capture_output=True, timeout=110)
            if run.returncode:
                raise RuntimeError("native_sublarr_ja_search_failed")
            responses = [json.loads(s) for s in run.stdout.splitlines()
                         if s.startswith("{")]
            result = next((v for v in responses
                           if str(v.get("id")) == job["id"]), None)
            if result is None or not result.get("ok"):
                raise RuntimeError("native_sublarr_provider_error")
        except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired):
            ja_search.save_attempt(db, job, "error")
            raise RuntimeError("japanese_provider_unavailable__no_english_fallback_yet")
        options = result.get("results") or []
        rated = [(grade, item) for item in options if isinstance(item, dict)
                 for grade in [ja_search.candidate_grade(row, item)]
                 if grade != "reject"]
        grade = "plausible" if any(g == "plausible" for g, _ in rated) else (
            "review" if rated else "none")
        ja_search.save_attempt(db, job, grade, result.get("total"), rated)
        print("JA SOURCING:", grade, "identity-checked candidates", len(rated),
              flush=True)
        return [dict(item, grade=g) for g, item in rated]


def acquire_ja(video, row, ja_search, ja_stage, ja_publish, candidates):
    """Reuse existing independent downloader, alignment and publisher gates."""
    if not candidates:
        return False
    valid = [cand for cand in candidates
             if cand.get("grade") == "plausible"
             and ja_stage.identity_ok(row, cand)]
    valid.sort(key=lambda c:(-int(c.get("score") or 0),
                             str(c.get("subtitle_id") or "")))
    if not valid:
        print("JA SOURCING: no candidate passed the strict release identity gate.",
              flush=True)
        return False
    for cand in valid[:1]:  # At most ONE Japanese provider download.
        sid = str(cand["subtitle_id"])
        print("JA SOURCING: stage one likely matching Japanese subtitle",
              "| provider",cand.get("provider"),flush=True)
        try:
            with ja_stage.stage_db() as db:
                stage_row = db.execute(
                    "SELECT sha256,status FROM staged WHERE jellyfin_id=? AND subtitle_id=?",
                    (str(row["jellyfin_id"]),sid)).fetchone()
                if stage_row is None or stage_row[1] not in ("staged","published"):
                    ja_stage.run_one({"row":row,"candidate":cand}, db)
                staged = db.execute(
                    "SELECT sha256 FROM staged WHERE jellyfin_id=? AND subtitle_id=?",
                    (str(row["jellyfin_id"]),sid)).fetchone()
            if not staged:
                raise RuntimeError("native_ja_stage_record_missing")
            kind, _, selected = ja_publish.choose(
                str(row["jellyfin_id"]), [(sid,staged[0])])
            if kind in ("ready_ffsubsync","ready_direct","ready_corrected"):
                ja_publish.publish_selected(
                    str(row["jellyfin_id"]), kind, selected)
                ja_publish.mark_completed(str(row["jellyfin_id"]))
                print("JA READY: downloaded Japanese was synchronized and published;",
                      "no model required.",flush=True)
                return True
            if kind.startswith("published_"):
                print("JA READY: existing verified Japanese sidecar",flush=True)
                return True
        except (RuntimeError, ValueError, OSError, sqlite3.Error,
                subprocess.TimeoutExpired, subprocess.SubprocessError) as exc:
            print("JA SOURCE HELD: candidate not safely usable:",
                  type(exc).__name__, str(exc)[:100], flush=True)
    return False


def jellyfin_english_download(row, jellyfin):
    """One provider search. Only exact-VIDEO-hash-matched English SRT eligible."""
    jid = str(row.get("jellyfin_id") or "")
    if not re.fullmatch(r"[a-f0-9]{32}", jid):
        print("EN SOURCING: episode lacks verified Jellyfin item identity.",flush=True)
        return False
    saved = jellyfin.load_token()
    if saved is None:
        print("EN SOURCING: native Jellyfin token not present; no provider call.",
              flush=True)
        return False
    client = jellyfin.Jellyfin(token=saved["token"],device_id=saved["device_id"])
    try:
        results = client.get("/Items/"+jid+"/RemoteSearch/Subtitles/eng")
        if not isinstance(results, list):
            raise RuntimeError("jellyfin_english_search_not_list")
        acceptable=[]
        season, ep = int(row["season"]),int(row["episode"])
        for item in results:
            if not isinstance(item, dict):
                continue
            if item.get("IsHashMatch") is not True or not item.get("Id"):
                continue
            if str(item.get("Format") or "").casefold() not in {"srt","subrip"}:
                continue
            if str(item.get("ThreeLetterISOLanguageName") or "").casefold() not in ("eng","en"):
                continue
            name = str(item.get("Name") or "")
            numbers = re.findall(
                r"(?i)s(\d{1,2})[\s._-]*e(\d{1,3})",name)
            if numbers and any((int(a),int(b))!=(season,ep) for a,b in numbers):
                continue
            acceptable.append(item)
        if not acceptable:
            print("EN SOURCING: no exact-video-hash English SRT found;",
                  "audio transcription is a future fallback.",flush=True)
            return False
        acceptable.sort(key=lambda x:(-int(x.get("DownloadCount") or 0),
                                      str(x.get("ProviderName") or "")))
        top = acceptable[0]
        print("EN SOURCING: download one exact-video-hash English SRT via Jellyfin",
              flush=True)
        client.post("/Items/"+jid+"/RemoteSearch/Subtitles/"
                    +quote(str(top["Id"]),safe=""))
        return True
    except Exception as exc:
        print("EN SOURCING: Jellyfin provider unavailable:",
              type(exc).__name__,flush=True)
        return False


def validate_timing_source(video,raw,kind,ff_sync):
    before = ff_sync.parse_cues(raw)
    if not 150 <= len(before) <= 1500:
        raise RuntimeError("english_subtitle_count_invalid")
    if kind == "embedded":
        return raw, {"mode":"embedded_release_timing","cue_count":len(before)}
    print("EN TIMING: testing external English against actual audio using ffsubsync",
          flush=True)
    aligned=ff_sync.align_in_container(video,raw)
    after=ff_sync.parse_cues(aligned)
    if len(after)!=len(before) or [a["text"] for a in before]!=[b["text"] for b in after]:
        raise RuntimeError("english_synchronization_changed_dialogue")
    diffs=[(b["start"]-a["start"])/1000 for a,b in zip(before,after)]
    if max(map(abs,diffs))>30 or max(diffs)-min(diffs)>8:
        raise RuntimeError("english_synchronization_excessive_time_shift")
    if any(c["start"]<0 or c["end"]<=c["start"] for c in after):
        raise RuntimeError("invalid_english_synced_timestamps")
    return aligned, {
        "mode":"audio_verified_ffsubsync",
        "cue_count":len(after),
        "shift_range_seconds":[round(min(diffs),3),round(max(diffs),3)],
    }


def english_source(video, row, daily, ff_sync, jellyfin):
    info=daily.probe(video)
    if info["ja"] or daily.already_ja(video):
        raise RuntimeError("japanese_already_present__no_translation")
    if not info["audio_en"]:
        raise RuntimeError("english_primary_audio_not_verified")
    source_kind=None
    if info["embedded_en"] is not None:
        print("EN SOURCE: embedded English track in actual episode",flush=True)
        stream=info["embedded_en"]
        run=subprocess.run([
            "ffmpeg","-nostdin","-hide_banner","-loglevel","error",
            "-i",str(video),"-map",f"0:{stream}","-vn","-an",
            "-c:s","srt","-f","srt","pipe:1"],
            capture_output=True,timeout=180)
        if run.returncode:
            raise RuntimeError("embedded_english_srt_extraction_failed")
        raw=run.stdout
        source_kind="embedded"
        origin="embedded_english_from_same_file"
    else:
        external=daily.english_srt(video)
        if not external:
            print("EN SOURCE: no embedded/local English; searching download providers.",
                  flush=True)
            jellyfin_english_download(row, jellyfin)
            external=daily.english_srt(video)
        if not external:
            return None
        if external.is_symlink() or external.stat().st_size>2_000_000:
            raise RuntimeError("external_english_source_unsafe")
        raw=external.read_bytes()
        source_kind="external"
        origin="audio_aligned_external_english"
    aligned,timing=validate_timing_source(video,raw,source_kind,ff_sync)
    text=aligned.decode("utf-8-sig")
    cues=small.parse_srt(text, limit=1500)
    if not 150<=len(cues)<=1500:
        raise RuntimeError("unusable_english_cue_count")
    if [r["number"] for r in cues]!=list(range(1,len(cues)+1)):
        raise RuntimeError("noncontiguous_english_source_numbers")
    print("EN SOURCE READY:",len(cues),"cues |",origin,"|",timing,flush=True)
    return cues,origin,hashlib.sha256(raw).hexdigest(),timing


def process_one(args, daily,ja_search,ja_stage,ja_publish,ff_sync,jellyfin):
    if episode.MANIFEST.exists():
        # Interrupted translation may resume, but should NOT repeat provider
        # searches or move to a different episode in the middle of a run.
        saved=json.loads(real._private_path(episode.MANIFEST).read_text("utf-8"))
        print("RESUMING selected episode",saved["episode"],flush=True)
        episode.run(argparse.Namespace(episode=saved["episode"],
                                       install=True, port=args.port))
        return
    options,present=candidate_order(daily,args.episode)
    print("=== SUBHUB ONE-EPISODE SOURCE-FIRST ===",flush=True)
    print("Local/embedded Japanese already present on",
          len(present),"episodes; skipped.",flush=True)
    if args.episode in present:
        print("DONE: Requested episode already has Japanese subtitles.",
              flush=True)
        return
    if not options:
        print("STOP: no suitable unlocalized American Dad video with verified English audio.",
              flush=True)
        return
    for attempt,(_,tag,video,had_en) in enumerate(options[:MAX_CANDIDATES],1):
        print("=== CANDIDATE",attempt,"/",min(MAX_CANDIDATES,len(options)),
              tag,"| local English",had_en,"===",flush=True)
        info=daily.probe(video)
        if info["ja"] or daily.already_ja(video):
            print("DONE: Japanese appeared in the selected video.",flush=True)
            continue
        try:
            row=latest_row(video)
        except (OSError,RuntimeError,ValueError) as exc:
            print("SOURCE CATALOG HOLD:",type(exc).__name__,str(exc)[:100],
                  flush=True)
            # This is a missing evidence problem, not proof JP is unavailable;
            # do not silently skip acquisition and translate.
            continue
        try:
            ja_candidates=cached_or_search_ja(video,row,ja_search)
        except (OSError,RuntimeError,ValueError,sqlite3.Error) as exc:
            print("JAPANESE-FIRST HOLD:",type(exc).__name__,str(exc)[:125],
                  flush=True)
            continue
        if acquire_ja(video,row,ja_search,ja_stage,ja_publish,ja_candidates):
            return
        try:
            ready=english_source(video,row,daily,ff_sync,jellyfin)
        except (OSError,RuntimeError,ValueError,UnicodeError,
                subprocess.SubprocessError,subprocess.TimeoutExpired) as exc:
            print("EN SOURCE HELD:",type(exc).__name__,str(exc)[:125],flush=True)
            continue
        if ready is None:
            print("NO SUBS: English audio transcription deferred (future work).",
                  flush=True)
            continue
        cues,origin,source_hash,timing=ready
        episode.seed_verified_source(video,tag,cues,origin,source_hash,timing)
        print("JAPANESE SOURCE NOT USABLE: starting chosen PLaMo 8B for one episode",
              tag,flush=True)
        episode.run(argparse.Namespace(episode=tag,install=True,port=args.port))
        return
    print("NO USABLE EPISODE READY: Japanese/English sourcing exhausted or held.",
          flush=True)
    print("No model or audio transcription launched.",flush=True)


def self_test():
    assert MAX_CANDIDATES==6
    assert episode.episode_id(Path("/tv/American.Dad.S08E01.mkv"))=="S08E01"
    assert not episode.episode_id(Path("/tv/The.Simpsons.S08E01.mkv"))
    assert episode.GPU_LAYERS==28
    assert real.HISTORY==2
    print("SOURCE-FIRST AMERICAN DAD SELF-TEST PASSED (no network/media/AI)")


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--episode",help="optional actual S08E01-style episode")
    parser.add_argument("--install",action="store_true",
                        help="required to acquire and publish a real subtitle")
    parser.add_argument("--self-test",action="store_true")
    parser.add_argument("--port",type=int,default=18884)
    args=parser.parse_args()
    if args.self_test:
        return self_test()
    if not args.install:
        parser.error("actual source-first episode requires --install")
    if args.episode and not re.fullmatch(r"S\d{2}E\d{2,3}",args.episode):
        parser.error("--episode must be S08E01 etc")
    if not 1025<=args.port<=65535:
        parser.error("port must be unprivileged")
    daily,ja_search,ja_stage,ja_publish,ff_sync,jellyfin=helpers()
    process_one(args,daily,ja_search,ja_stage,ja_publish,ff_sync,jellyfin)


if __name__=="__main__":
    main()
