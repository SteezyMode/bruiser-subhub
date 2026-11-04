#!/usr/bin/env python3
"""Bounded create-only publisher for previously staged Japanese subtitles.

Delegates every decision and actual sidecar write to ja_first_publish_staged,
which independently rechecks Jellyfin identity, exact source history,
SHA256, Japanese SRT text, missing-Japanese protections, original video
duration, and trusted embedded-reference subtitle alignment.

Without --apply: read-only preflight. With --apply: at most three new .ja.srt
sidecars, never overwrites. Already-published identical tracks are skipped.
No searches, downloads, translation, credential access, or provider requests.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
from urllib.parse import quote

import ja_first_publish_staged as gate


MAX_EVALUATED = 40


def stage_records():
    gate.db_uri(gate.STAGE_DB)  # validates privacy and link state
    uri = "file:" + quote(str(gate.STAGE_DB.resolve()), safe="/") + "?mode=ro"
    with sqlite3.connect(uri, uri=True, timeout=10) as conn:
        return conn.execute(
            """SELECT jellyfin_id,subtitle_id,host_path,sha256
               FROM staged WHERE status='staged'
               ORDER BY staged_at ASC,jellyfin_id ASC LIMIT ?""",
            (MAX_EVALUATED,)
        ).fetchall()


def already_published(jid, sid, hash_hex):
    """Verify a create-only published target matches the staged hash.

    Existing files with nonmatching data are conflicts, not success. Never
    use a title from search results to invent a target path.
    """
    row = gate.read_inventory(str(jid))
    video = gate.safe_media_path(str(row.get("host_path") or ""))
    target = gate.video_target(video)
    if target.is_symlink():
        raise RuntimeError("existing_publication_target_is_symlink")
    if not target.exists():
        return False
    if not target.is_file() or target.stat().st_size > 2_000_000:
        raise RuntimeError("existing_publication_target_unexpected")
    if hashlib.sha256(target.read_bytes()).hexdigest() != hash_hex:
        raise RuntimeError("existing_japanese_target_differs_no_overwrite")
    # A valid matching target is already published and should never be
    # rewritten or counted toward the new-publication budget.
    gate.read_staging(str(jid), str(sid))
    return True


def self_test():
    assert gate.TIMING_THRESHOLD >= 0.75
    assert MAX_EVALUATED == 40
    assert callable(gate.preflight) and callable(gate.publish)
    assert gate.video_target(Path("/mnt/BigDisk/Video/A.S01E02.mkv")).name == "A.S01E02.ja.srt"
    print("SELF-TEST PASSED: delegates to native safe publisher; no network or writes",
          flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--limit", type=int, default=1,
                        help="max new publications 1..3, default 1")
    parser.add_argument("--apply", action="store_true",
                        help="publish create-only after all per-title gates pass")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    if not 1 <= args.limit <= 3:
        parser.error("--limit must be 1..3")
    rows = stage_records()
    print("=== BOUNDED JA PUBLICATION ===", flush=True)
    print("Staged records considered:", len(rows),
          "| new publication limit:", args.limit,
          "| mode:", "APPLY" if args.apply else "DRY RUN",
          flush=True)
    summary = Counter()
    accepted = 0
    for jid, sid, staged, digest in rows:
        if accepted >= args.limit:
            break
        try:
            # Only treat existing target as complete if its actual content
            # hashes to the registered stage content.
            if already_published(jid, sid, digest):
                summary["already_published_identical"] += 1
                print("SKIP ALREADY PUBLISHED:", jid, flush=True)
                continue
            row, video, target, content = gate.preflight(str(jid), str(sid))
            print("READY:", gate.metadata_label(row), flush=True)
            accepted += 1
            if args.apply:
                gate.publish(row, video, target, content)
                summary["published"] += 1
            else:
                summary["ready_dry_run"] += 1
        except (RuntimeError, ValueError, OSError, sqlite3.Error) as exc:
            summary["held"] += 1
            print("HELD:", jid, type(exc).__name__, str(exc)[:110], flush=True)
    print("SUMMARY:", json.dumps(dict(summary), ensure_ascii=False), flush=True)
    print("No media files replaced, no download/AI/provider operations performed.",
          flush=True)
    if not args.apply:
        print("DRY RUN ONLY: use --apply to enable create-only publication.",
              flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("BATCH PUBLICATION STOPPED:", type(exc).__name__, str(exc)[:130],
              file=sys.stderr)
        raise SystemExit(1) from None
