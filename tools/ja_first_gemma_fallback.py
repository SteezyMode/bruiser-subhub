#!/usr/bin/env python3
"""Japanese-first -> existing Gemma fallback bridge for Bruiser SubHub.

Only consider a Jellyfin-authoritative title after the Japanese provider search
has saved an explicit 'none' outcome. Before handing it to the installed
SubHub 1.0 Gemma job queue, check the real video, English-default audio,
existing Japanese tracks/sidecars, exact episode numbering, provider search
history, existing staged candidates, and a validated English SRT source.

DEFAULT IS READ ONLY. --queue-one explicitly queues ONE title using the
existing daily_japanese.queue_one() and existing SubHub checkpoint database.
No downloads, model runs, transcript rewriting, container changes, or
publication from this script. Starting the existing Gemma worker remains a
separate explicit operation, after a real queued job is confirmed.

Requires sibling ja_first_stage_saved_batch.py, ja_first_stage_timing_audit.py
and daily_japanese.py; on OptiPlex, existing ~/bruiser-pilot/subhub1 service.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import time
from urllib.parse import quote

from ja_first_stage_saved_batch import (
    SEARCH_DB, STAGE_DB, ROOT, read_inventory, named_episode,
)
from ja_first_stage_timing_audit import safe_media_path, ffprobe_streams

IMDB = re.compile(r"tt\d{5,12}\Z", re.IGNORECASE)
JA = {"ja", "jp", "jpn", "japanese"}
SUBS = {".srt", ".ass", ".ssa", ".vtt", ".sub", ".sup"}
MAX_SCAN = 20
SEARCH_AGE_S = 35 * 86400


def read_only_db(path):
    if not path.is_file() or path.is_symlink() or path.stat().st_mode & 0o077:
        raise RuntimeError("missing_or_unsafe_private_database")
    return "file:" + quote(str(path.resolve()), safe="/") + "?mode=ro"


def japanese_search_misses():
    """Only real misses, never provider errors or manual-review candidates."""
    with sqlite3.connect(read_only_db(SEARCH_DB), uri=True, timeout=10) as db:
        return db.execute(
            """SELECT jellyfin_id,kind,title,searched_at
               FROM searches WHERE outcome='none' AND plausible_count=0
               ORDER BY searched_at ASC,jellyfin_id ASC"""
        ).fetchall()


def staged_ids():
    if not STAGE_DB.exists():
        return set()
    with sqlite3.connect(read_only_db(STAGE_DB), uri=True, timeout=10) as db:
        return {str(x[0]) for x in db.execute(
            "SELECT DISTINCT jellyfin_id FROM staged WHERE status='staged'"
        )}


def has_existing_ja(video, streams):
    """Conservative: count any Japanese track, even forced, as a blocker."""
    name_prefix = video.stem.casefold() + "."
    for file in video.parent.iterdir():
        if not file.name.casefold().startswith(name_prefix):
            continue
        if file.is_symlink():
            raise RuntimeError("symlinked_subtitle_neighbor")
        if file.suffix.casefold() not in SUBS:
            continue
        suffix = file.name.casefold()[len(name_prefix):-len(file.suffix)]
        tokens = set(re.findall(r"[a-z0-9]+", suffix))
        if tokens & JA:
            return True
    for stream in streams:
        if stream.get("codec_type") != "subtitle":
            continue
        lang = str((stream.get("tags") or {}).get("language") or "").casefold()
        if lang.split("-")[0] in JA:
            return True
    return False


def identity_safe(row, video):
    kind = row.get("kind")
    if kind == "Movie":
        return (IMDB.fullmatch(str(row.get("imdb_id") or "")) is not None
                and type(row.get("year")) is int
                and 1900 <= row["year"] <= 2100
                and bool(row.get("title")))
    if kind == "Episode":
        sn, ep = row.get("season"), row.get("episode")
        if (type(sn) is not int or type(ep) is not int
                or not 1 <= sn <= 99 or not 1 <= ep <= 999
                or not row.get("series_title")
                or not any(row.get(k) for k in (
                    "series_imdb_id", "series_tvdb_id", "series_tmdb_id"
                ))):
            return False
        actual = named_episode(video.stem)
        return not actual or actual == {(sn, ep)}
    return False


def label(row):
    if row.get("kind") == "Episode":
        return f'{row.get("series_title")} S{row.get("season"):02d}E{row.get("episode"):02d}'
    return f'{row.get("title")} ({row.get("year")})'


def summarize(inventory, searches, staged):
    count = Counter(str(row.get("status") or "unknown") for row in inventory.values())
    search_count = Counter()
    for _, _, _, _ in searches:
        search_count["none"] += 1
    return {
        "inventory_items": len(inventory),
        "ready_ja_search_catalog": count.get("ready_ja_search", 0),
        "recorded_ja_search_misses": search_count["none"],
        "titles_with_staged_ja_candidates": len(staged),
        "note": "A Japanese search miss is not permission to translate unless source and media safety checks pass.",
    }


def find_candidate(scan_budget=8, allow_queue=False):
    # This scan reads existing media and EN tracks, but never uses a provider.
    import daily_japanese as intake

    inventory = read_inventory()
    misses = japanese_search_misses()
    staged = staged_ids()
    print("=== JAPANESE-FIRST GEMMA FALLBACK ===", flush=True)
    print("CATALOG:", json.dumps(summarize(inventory, misses, staged)),
          flush=True)
    print("MODE:", "QUEUE ONE VERIFIED SOURCE" if allow_queue else "READ-ONLY PREVIEW",
          flush=True)

    state = intake.DEFAULT_STATE
    pending = intake.pending_daily(state)
    if pending:
        print("EXISTING DAILY GEMMA JOB:", pending["id"], pending["status"],
              "(will not queue another)", flush=True)
        if allow_queue:
            return "existing_job_pending"
    active_videos = intake.existing_jobs(state)
    if allow_queue:
        # Use established native SubHub media-root policy; never widen it.
        roots = intake.ensure_roots(intake.service.SOURCE_ROOTS)
    else:
        roots = ()

    scanned = 0
    reasons = Counter()
    now = int(time.time())
    for jid, kind, title, when in misses:
        if scanned >= scan_budget:
            break
        row = inventory.get(str(jid))
        if not row or row.get("status") != "ready_ja_search":
            reasons["not_in_current_eligible_inventory"] += 1
            continue
        if row.get("kind") != kind:
            reasons["catalog_identity_changed"] += 1
            continue
        if jid in staged:
            reasons["already_has_staged_japanese_candidate"] += 1
            continue
        if now - int(when or 0) > SEARCH_AGE_S:
            reasons["search_history_too_old"] += 1
            continue
        scanned += 1
        try:
            video = safe_media_path(str(row.get("host_path") or ""))
            if not identity_safe(row, video):
                raise RuntimeError("metadata_or_episode_identity_unsafe")
            if str(video) in active_videos:
                raise RuntimeError("already_in_gemma_checkpoint_queue")
            streams, err = ffprobe_streams(video)
            if err or not streams:
                raise RuntimeError("media_track_probe_failed")
            if has_existing_ja(video, streams):
                raise RuntimeError("already_has_japanese_subtitles")
            meta = intake.probe(video)
            if meta.get("ja") or not meta.get("audio_en"):
                raise RuntimeError("not_confirmed_english_primary_audio")
            data, cues, origin = intake.source(video, meta)
            stat = video.stat()
            record = {
                "video": video, "raw": data, "cues": cues,
                "origin": origin, "mtime_ns": stat.st_mtime_ns,
                "size": stat.st_size, "source_sha": intake.digest(data),
                "id": intake.job_id(video),
            }
            print("READY:", label(row), flush=True)
            print("ENGLISH SOURCE:", origin, "|", cues, "cues", flush=True)
            print("SOURCE SHA256:", record["source_sha"], flush=True)
            print("SOURCE STATUS: verified text, not translated", flush=True)
            if not allow_queue:
                print("NEXT STEP: --queue-one enters exactly this title into "
                      "the existing Gemma job checkpoint queue.", flush=True)
                return "source_ready"
            # Rechecks are delegated to existing, native SubHub intake.
            if not intake.queue_one(record, roots, state):
                print("QUEUE RESULT: already queued, no duplicate", flush=True)
                return "already_queued"
            print("QUEUED:", record["id"], flush=True)
            print("NO MODEL STARTED: this tool never translates or publishes.",
                  flush=True)
            return "queued"
        except (OSError, RuntimeError, ValueError, UnicodeError) as exc:
            reasons[str(exc)[:72]] += 1
            print("SKIP:", label(row), type(exc).__name__,
                  str(exc)[:105], flush=True)
    print("NO READY ENGLISH SOURCE IN BOUNDED SCAN", scanned,
          "candidates considered", flush=True)
    print("BLOCKERS:", json.dumps(dict(reasons), sort_keys=True), flush=True)
    return "no_ready"


def self_test():
    movie = {"kind": "Movie", "imdb_id": "tt0116282",
             "year": 1996, "title": "Fargo"}
    episode = {"kind": "Episode", "series_title": "Example",
               "series_imdb_id": "tt0123456", "season": 3, "episode": 5}
    assert identity_safe(movie, Path("/tmp/Fargo.1996.mkv"))
    assert not identity_safe(dict(movie, imdb_id=""), Path("/tmp/x.mkv"))
    assert identity_safe(episode, Path("/tmp/Example.S03E05.mkv"))
    assert not identity_safe(episode, Path("/tmp/Example.S03E06.mkv"))
    assert not identity_safe(dict(episode, series_imdb_id=None),
                             Path("/tmp/Example.S03E05.mkv"))
    assert label(episode) == "Example S03E05"
    print("SELF-TEST PASSED: identity and no-translation safety; "
          "no network, media probes, or writes", flush=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--self-test", action="store_true")
    p.add_argument("--probe-budget", type=int, default=8,
                   help="maximum existing titles to check for EN text, 1..20")
    p.add_argument("--queue-one", action="store_true",
                   help="queue one verified EN source for existing Gemma worker; no translation")
    args = p.parse_args()
    if args.self_test:
        self_test()
        return
    if not 1 <= args.probe_budget <= MAX_SCAN:
        p.error("probe budget must be between 1 and 20")
    result = find_candidate(args.probe_budget, args.queue_one)
    print("FALLBACK RESULT:", result, flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("FALLBACK HELD:", type(exc).__name__,
              str(exc)[:130] if isinstance(exc, (RuntimeError, ValueError))
              else "", file=sys.stderr)
        raise SystemExit(1) from None
