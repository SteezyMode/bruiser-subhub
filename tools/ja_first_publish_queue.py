#!/usr/bin/env python3
"""Unified, bounded Japanese subtitle publication queue.

Processes host-staged OpenSubtitles candidates as ONE item per Jellyfin ID.
Selects either:
  * Direct publication through existing ja_first_publish_staged.preflight,
    requiring a trusted embedded subtitle and matching cue starts.
  * Constant-offset correction through ja_first_publish_shifted.preparation,
    requiring >=95% trusted alignment before and after adjustment.

Prior published files are recognized only when byte-identical to:
  * an authenticated original stage file, OR
  * a derived timing-adjusted file with independently verified provenance.
Unknown/conflicting existing JA subtitles are HELD, never overwritten.

Default: READ-ONLY. --apply permits at most --limit create-only sidecars.
No provider calls, downloads, AI, automatic job scheduling or existing-file edits.

Sibling modules required: ja_first_stage_saved_batch.py,
ja_first_stage_timing_audit.py, ja_first_publish_staged.py,
ja_first_publish_shifted.py.
"""
from __future__ import annotations

import argparse
from collections import OrderedDict, Counter
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
from urllib.parse import quote

import ja_first_publish_staged as direct
import ja_first_publish_shifted as shifted
import ja_first_ffsubsync as ff

MAX_ROWS = 3000
MAX_TITLES = 1000
MAX_NEW_PUBLISH = 200


def stages():
    uri = direct.db_uri(direct.STAGE_DB)
    with sqlite3.connect(uri, uri=True, timeout=10) as connection:
        return connection.execute(
            """SELECT jellyfin_id, subtitle_id, sha256
               FROM staged WHERE status='staged'
               ORDER BY staged_at, jellyfin_id, subtitle_id LIMIT ?""",
            (MAX_ROWS,)
        ).fetchall()


def mark_completed(jid):
    """Retire a verified or newly published title from future pending runs.

    Retain its staged bytes and SHA for provenance/repeated-run recognition.
    A failed DB update leaves publication intact and can be retried safely.
    """
    if not direct.EXPECTED_ID_PATTERN.fullmatch(jid):
        raise RuntimeError("invalid_completed_media_id")
    direct.private_file(direct.STAGE_DB, "staging_database")
    with sqlite3.connect(direct.STAGE_DB, timeout=15) as connection:
        connection.execute(
            "UPDATE staged SET status='published' "
            "WHERE jellyfin_id=? AND status='staged'", (jid,))
        connection.commit()


def unique_titles(records, max_titles):
    grouping = OrderedDict()
    for jid, sid, digest in records:
        if jid not in grouping:
            if len(grouping) >= max_titles:
                break
            grouping[jid] = []
        grouping[jid].append((str(sid), str(digest)))
    return grouping


def corrected_provenance_file(jid, sid):
    root = direct.STAGED
    if (not root.is_dir() or root.is_symlink()
            or root.stat().st_mode & 0o077):
        raise RuntimeError("unsafe_staging_folder")
    folder = root / "timing-adjusted"
    if not folder.is_dir() or folder.is_symlink() or folder.stat().st_mode & 0o077:
        return None
    filename = jid + ".opensubtitles." + sid + ".ja.shifted.srt"
    return folder / filename


def matches_corrected(jid, sid, original_hash, published_hash):
    """Only recognize an existing corrected track with full verifiable lineage."""
    path = corrected_provenance_file(jid, sid)
    if path is None:
        return False
    record_path = path.with_name(path.name + ".json")
    if not path.exists() or not record_path.exists():
        return False
    direct.private_file(path, "shifted_artifact")
    direct.private_file(record_path, "shifted_provenance")
    if path.stat().st_size > 2_000_000 or record_path.stat().st_size > 30_000:
        raise RuntimeError("provenance_or_adjusted_file_too_large")
    record = json.loads(record_path.read_text("utf-8"))
    if not isinstance(record, dict) or not all((
        record.get("schema") == "subhub-ja-timing-correction-v1",
        record.get("jellyfin_id") == jid,
        str(record.get("subtitle_id")) == sid,
        record.get("source_sha256") == original_hash,
        record.get("adjusted_sha256") == published_hash,
        record.get("file_name") == path.name,
        isinstance(record.get("before"), dict),
        isinstance(record.get("after"), dict),
    )):
        raise RuntimeError("corrected_provenance_identity_mismatch")
    if (record["before"].get("reference_trust") != "trusted_embedded"
            or record["after"].get("reference_trust") != "trusted_embedded"
            or record["after"].get("status") != "fit"):
        raise RuntimeError("corrected_provenance_trust_invalid")
    if hashlib.sha256(path.read_bytes()).hexdigest() != published_hash:
        raise RuntimeError("corrected_provenance_file_hash_mismatch")
    # The original must also still match its recorded hash.
    _, content, _ = direct.read_staging(jid, sid)
    if hashlib.sha256(content).hexdigest() != original_hash:
        raise RuntimeError("corrected_provenance_original_hash_mismatch")
    return True


def existing_verdict(jid, candidates):
    """Recognize only byte-verified prior publications, even after catalog refresh.

    A refreshed Jellyfin inventory now correctly marks our previously published
    subtitles as existing_japanese_subtitle. The check below may look up that
    identity for recognition ONLY; every new publication still requires
    ready_ja_search and passes the existing no-overwrite gate.
    """
    row = direct.read_inventory(jid, allow_existing_ja=True)
    video = direct.safe_media_path(str(row.get("host_path") or ""))
    target = direct.video_target(video)
    if target.is_symlink():
        raise RuntimeError("existing_japanese_subtitle_is_symlink")
    if not target.exists():
        return "absent", row
    if not target.is_file() or not 0 < target.stat().st_size <= 2_000_000:
        raise RuntimeError("existing_japanese_subtitle_unexpected_type_or_size")
    existing_hash = hashlib.sha256(target.read_bytes()).hexdigest()
    for sid, recorded_hash in candidates:
        if existing_hash == recorded_hash:
            # Confirm registered file still matches; not just the saved hash.
            direct.read_staging(jid, sid)
            return "published_original", row
    for sid, recorded_hash in candidates:
        if matches_corrected(jid, sid, recorded_hash, existing_hash):
            return "published_corrected", row
        if ff.provenance_matches(jid, sid, recorded_hash, existing_hash):
            return "published_ffsubsync", row
    raise RuntimeError("existing_japanese_subtitle_not_matching_saved_provenance")


def direct_candidate(jid, candidates):
    """Select the highest-trusted-timing direct candidate; hold ties."""
    eligible = []
    for sid, _ in candidates:
        try:
            row, video, target, data = direct.preflight(jid, sid)
            timing = direct.inspect(row, data)
            score = float(timing["matching_start_fraction"])
            eligible.append((score, sid, row, video, target, data))
        except (ValueError, OSError, RuntimeError, KeyError, sqlite3.Error) as exc:
            print("  DIRECT HELD:", sid, type(exc).__name__, str(exc)[:95],
                  flush=True)
    if not eligible:
        return None
    eligible.sort(key=lambda x: (-x[0], x[1]))
    if len(eligible) > 1 and eligible[0][0] - eligible[1][0] < 0.02:
        raise RuntimeError("multiple_equivalent_direct_candidates")
    return eligible[0]


def report_title(row):
    """Label existing JA titles even if refreshed catalog omitted episode metadata."""
    if (row.get("kind") == "Episode" and row.get("series_title")
            and type(row.get("season")) is int
            and type(row.get("episode")) is int):
        return direct.metadata_label(row)
    title = str(row.get("title") or "").strip()
    return title if title else "media " + str(row.get("jellyfin_id") or "unknown")


def choose(jid, candidates):
    published_state, row = existing_verdict(jid, candidates)
    if published_state != "absent":
        return published_state, row, None
    # First use audio-derived ffsubsync to test every candidate selected
    # for possible publication, including titles without embedded English.
    for sid, _ in candidates[:3]:
        try:
            ready = ff.prepare(jid, sid)
            print("  FFSUBSYNC:", sid, json.dumps(ready["assessment"]),
                  flush=True)
            return "ready_ffsubsync", row, ready
        except (ValueError, OSError, RuntimeError, KeyError, sqlite3.Error,
                subprocess.CalledProcessError,
                subprocess.TimeoutExpired) as exc:
            print("  FFSUBSYNC HELD:", sid, type(exc).__name__,
                  str(exc)[:95], flush=True)
    # The pre-existing trusted embedded-English alignment remains a
    # conservative independent fallback when audio matching cannot conclude.
    result = direct_candidate(jid, candidates)
    if result is not None:
        return "ready_direct", row, result
    print("  NO DIRECT FIT; evaluating trusted small-offset correction", flush=True)
    selected = shifted.preparation(jid)
    return "ready_corrected", row, selected


def publish_selected(jid, kind, chosen):
    """Recalculate all gates immediately before the only permitted write."""
    if kind == "ready_ffsubsync":
        ff.preserve(chosen)
        direct.publish(chosen["row"], chosen["video"],
                       chosen["target"], chosen["chosen"])
        return
    if kind == "ready_direct":
        _, sid, _, _, _, _ = chosen
        row, video, target, data = direct.preflight(jid, sid)
        direct.publish(row, video, target, data)
        return
    if kind == "ready_corrected":
        fresh = shifted.preparation(jid)
        if fresh["sid"] != chosen["sid"]:
            raise RuntimeError("chosen_candidate_changed_between_preflight_and_apply")
        if hashlib.sha256(fresh["adjusted"]).digest() != hashlib.sha256(chosen["adjusted"]).digest():
            raise RuntimeError("corrected_bytes_changed_between_preflight_and_apply")
        shifted.save_derived(fresh)
        direct.publish(fresh["row"], fresh["video"], fresh["target"],
                       fresh["adjusted"])
        return
    raise RuntimeError("unsupported_publish_choice")


def self_test():
     # No FS operations: group exactly once per ID, bound title count.
    rows = [("a"*32, "1111", "x"*64),
            ("a"*32, "2222", "y"*64),
            ("b"*32, "3333", "z"*64)]
    grouped = unique_titles(rows, 1)
    assert list(grouped) == ["a"*32]
    assert len(grouped["a"*32]) == 2
    assert direct.TIMING_THRESHOLD >= 0.75
    assert shifted.MIN_MATCH >= 0.95
    assert callable(shifted.preparation)
    assert callable(ff.prepare)
    assert callable(ff.preserve)
    assert callable(direct.publish)
    print("SELF-TEST PASSED: grouped candidates, trusted thresholds and native publication hooks; no writes",
          flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--limit", type=int, default=3,
                        help="new publications permitted per run 1..200")
    parser.add_argument("--max-titles", type=int, default=300,
                        help="maximum distinct titles to examine 1..1000")
    parser.add_argument("--apply", action="store_true",
                        help="create at most --limit new Japanese subtitle sidecars")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    if not (1 <= args.limit <= MAX_NEW_PUBLISH
            and 1 <= args.max_titles <= MAX_TITLES):
        parser.error("limit must be 1..200, max-titles 1..1000")
    records = stages()
    title_groups = unique_titles(records, args.max_titles)
    print("=== UNIFIED JAPANESE SUBTITLE PUBLISH QUEUE ===", flush=True)
    print("Staged candidates:", len(records),
          "| unique titles:", len(title_groups),
          "| max new sidecars:", args.limit,
          "| mode:", "APPLY" if args.apply else "DRY RUN", flush=True)
    counts = Counter()
    seen_ready = 0
    for jid, candidates in title_groups.items():
        if seen_ready >= args.limit:
            break
        print("MEDIA:", jid, "| candidate IDs:",
              ",".join(sid for sid, _ in candidates), flush=True)
        try:
            kind, row, value = choose(jid, candidates)
            print("RESULT:", report_title(row), "|", kind, flush=True)
            counts[kind] += 1
            if kind.startswith("published_"):
                if args.apply:
                    mark_completed(jid)
                    counts["retired_completed"] += 1
                continue
            if kind.startswith("ready_"):
                seen_ready += 1
                if args.apply:
                    publish_selected(jid, kind, value)
                    # Mark only after successful create-only host publication.
                    mark_completed(jid)
                    counts["published_new"] += 1
        except (ValueError, RuntimeError, OSError, KeyError, sqlite3.Error) as exc:
            counts["held"] += 1
            print("HELD:", jid, type(exc).__name__, str(exc)[:135], flush=True)
    print("QUEUE SUMMARY:", json.dumps(dict(counts)), flush=True)
    print("No provider searches, downloads or translation jobs.", flush=True)
    if not args.apply:
        print("READ ONLY: No subtitle files created or replaced.", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("QUEUE STOPPED:", type(exc).__name__, str(exc)[:140],
              file=sys.stderr)
        raise SystemExit(1) from None
