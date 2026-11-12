#!/usr/bin/env python3
"""Unified, bounded Japanese subtitle publication queue.

Processes host-staged OpenSubtitles candidates as ONE item per Jellyfin ID.
Selects either:
  * Preferred standalone alass correction for splits and framerate differences,
    with existing source identity/health validation and create-only publication.
  * Existing ffsubsync fallback for candidates alass cannot safely prepare.
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
try:
    from . import ja_first_movie_scope as movie_scope
except ImportError:
    import ja_first_movie_scope as movie_scope
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
import ja_first_alass as alass
import ja_first_priority as priorities
import ja_first_candidate_progress as progress
import ja_first_stage_saved_batch as staging

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


def queued_staged_titles(records, *, queue_reader=priorities.active_coverage_queue):
    """Filter ONLY unresolved, on-disk staged JA tasks from Bruiser queue.

    Read-only. Does not cause a provider search, queue-state transition, or
    automatic model launch. A missing/unsafe queue blocks this explicit mode.
    """
    queue = queue_reader()
    if queue is None:
        raise RuntimeError("bruiser_coverage_queue_not_installed")
    eligible = {jid for jid, (action, state, _, _) in queue.items()
                if action == "align_existing_staged_ja" and state == "pending"}
    return [row for row in records if str(row[0]) in eligible]


def select_staged_series(records, rows, series, season=None):
    """Filter existing staged files by Jellyfin's canonical series identity.

    No discovery, no new staging, and no changes to the catalog. One generic
    selector works for every series; the publisher still enforces its own
    source identity, timing and existing-subtitle protections.
    """
    eligible = {
        str(row.get("jellyfin_id")) for row in rows
        if isinstance(row, dict)
        and row.get("kind") == "Episode"
        and row.get("series_title") == series
        and (season is None or row.get("season") == season)
        and row.get("status") == "ready_ja_search"
    }
    return [record for record in records if str(record[0]) in eligible]


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
    filename = jid + "." + direct.source_label(jid,sid) + "." + sid + ".ja.shifted.srt"
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
        if alass.provenance_matches(jid, sid, recorded_hash, existing_hash):
            return "published_alass", row
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


def choose(jid, candidates, *, intensive_only=False, record_failures=False):
    published_state, row = existing_verdict(jid, candidates)
    if published_state != "absent":
        return published_state, row, None
    if intensive_only:
        # Keep explicit diagnostic mode separate from the daily pipeline.
        if not alass.available():
            raise RuntimeError("intensive_alass_unavailable")
        tried_hashes=set()
        for sid,digest in candidates[:3]:
            if digest in tried_hashes:
                print("  ALASS INTENSIVE SKIP:",sid,
                      "identical_saved_subtitle",flush=True)
                continue
            tried_hashes.add(digest)
            try:
                ready=alass.intensive_prepare(jid,sid)
                print("  ALASS INTENSIVE:",sid,
                      json.dumps(ready["assessment"]),flush=True)
                return "ready_alass",row,ready
            except (ValueError,OSError,RuntimeError,KeyError,sqlite3.Error,
                    subprocess.CalledProcessError,subprocess.TimeoutExpired) as exc:
                print("  ALASS INTENSIVE HELD:",sid,type(exc).__name__,
                      str(exc)[:140],flush=True)
        raise RuntimeError("intensive_candidates_unverified")

    # One durable title-level receipt prevents redundant direct/offset probes
    # as well as redundant ALASS work. Adding a new staged release changes the
    # fingerprint automatically; so does an actual media or code change.
    combined=progress.group_digest(candidates)
    final_key=progress.fingerprint(row["host_path"],combined,"final")
    old=progress.known(jid,"final","final",final_key)
    if old:
        print("  UNCHANGED_FAILURE_SKIPPED:",jid,old[:110],flush=True)
        return "held_unchanged",row,None

    def cached_attempt(engine,sid,digest,func):
        key=progress.fingerprint(row["host_path"],digest,engine)
        prior=progress.known(jid,sid,engine,key)
        if prior:
            print("  KNOWN_CANDIDATE_FAILURE_SKIPPED:",engine,sid,
                  prior[:95],flush=True)
            return None
        try:
            return func()
        except (ValueError,OSError,RuntimeError,KeyError,sqlite3.Error,
                subprocess.CalledProcessError,subprocess.TimeoutExpired) as exc:
            if record_failures:
                progress.remember(jid,sid,engine,key,exc)
            print("  "+engine.upper()+" HELD:",sid,
                  type(exc).__name__,str(exc)[:105],flush=True)
            return None

    # Previously held candidates never crowd a newer release out of the
    # bounded budget. The ledger skips identical bytes against unchanged
    # media/implementation, while allowing a different staged subtitle.
    if alass.available():
        attempts=0
        hashes=set()
        for sid,digest in candidates:
            if digest in hashes:
                print("  DUPLICATE_STAGE_SKIPPED:",sid,flush=True)
                continue
            hashes.add(digest)
            key=progress.fingerprint(row["host_path"],digest,"alass")
            if progress.known(jid,sid,"alass",key):
                print("  KNOWN_CANDIDATE_FAILURE_SKIPPED: alass",sid,flush=True)
                continue
            if attempts>=3:
                break
            attempts+=1
            ready=cached_attempt("alass",sid,digest,
                                 lambda sid=sid:alass.prepare(jid,sid))
            if ready is not None:
                print("  ALASS:",sid,json.dumps(ready["assessment"]),flush=True)
                return "ready_alass",row,ready
    else:
        print("  ALASS unavailable: ffsubsync fallback only",flush=True)

    attempts=0
    hashes=set()
    for sid,digest in candidates:
        if digest in hashes:
            continue
        hashes.add(digest)
        key=progress.fingerprint(row["host_path"],digest,"ffsubsync")
        if progress.known(jid,sid,"ffsubsync",key):
            print("  KNOWN_CANDIDATE_FAILURE_SKIPPED: ffsubsync",sid,flush=True)
            continue
        if attempts>=3:
            break
        attempts+=1
        ready=cached_attempt("ffsubsync",sid,digest,
                             lambda sid=sid:ff.prepare(jid,sid))
        if ready is not None:
            print("  FFSUBSYNC:",sid,json.dumps(ready["assessment"]),flush=True)
            return "ready_ffsubsync",row,ready

    # Existing trusted-reference and small-offset paths are preserved.
    # Record only deterministic complete holds, never transient I/O errors.
    result=direct_candidate(jid,candidates)
    if result is not None:
        return "ready_direct",row,result
    print("  NO DIRECT FIT; evaluating trusted small-offset correction",flush=True)
    try:
        selected=shifted.preparation(jid)
        return "ready_corrected",row,selected
    except (ValueError,OSError,RuntimeError,KeyError,sqlite3.Error) as exc:
        if record_failures:
            progress.remember(jid,"final","final",final_key,exc)
        raise


def report_next_action(jid,candidates):
    """Report actionable source state; never run a model or spend quota."""
    try:
        row=direct.read_inventory(jid,allow_existing_ja=True)
        action=progress.next_action(
            jid,(sid for sid,_ in candidates),
            accept_candidate=lambda c:staging.identity_ok(row,c))
    except (ValueError,OSError,RuntimeError,KeyError,sqlite3.Error):
        action="review_candidate_and_source_state"
    print("NEXT_ACTION:",json.dumps({
        "jellyfin_id":jid,"action":action,
        "owner_approval_required":action.startswith("offer_owner"),
        "english_validation_required":action.startswith("offer_owner")
    },sort_keys=True),flush=True)


def publish_selected(jid, kind, chosen):
    """Recalculate all gates immediately before the only permitted write."""
    if kind == "ready_alass":
        alass.preserve(chosen)
        direct.publish(chosen["row"], chosen["video"],
                       chosen["target"], chosen["chosen"])
        return
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
    assert callable(alass.prepare)
    assert callable(alass.preserve)
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
    parser.add_argument("--intensive-only", action="store_true",
                        help="second pass for already-held staged candidates; compare ALASS"
                             " settings and independent references before any publication")
    parser.add_argument("--queue-staged-only", action="store_true",
                        help="only titles with pending staged-JA work in Bruiser coverage queue")
    parser.add_argument("--jellyfin-id", default="",
                        help="restrict work to ONE exact catalog item, not other staged titles")
    parser.add_argument("--series", default="",
                        help="publish already-staged JA only for this Jellyfin series")
    parser.add_argument("--season", type=int, default=None,
                        help="optional season number; requires --series")
    parser.add_argument("--scope",choices=movie_scope.SCOPES,default="all",
                        help="filter staged publication to selected movie folders")
    args = parser.parse_args()
    if args.jellyfin_id and not direct.EXPECTED_ID_PATTERN.fullmatch(args.jellyfin_id):
        parser.error("--jellyfin-id must be one exact 32-hex Jellyfin media ID")
    if args.series and (not 1 <= len(args.series) <= 160 or args.jellyfin_id):
        parser.error("--series must be 1..160 chars, cannot combine with --jellyfin-id")
    if args.season is not None and (not args.series or not 1 <= args.season <= 99):
        parser.error("--season needs --series and a valid season 1..99")
    if args.self_test:
        self_test()
        return
    if not (1 <= args.limit <= MAX_NEW_PUBLISH
            and 1 <= args.max_titles <= MAX_TITLES):
        parser.error("limit must be 1..200, max-titles 1..1000")
    records = stages()
    if args.scope != "all":
        from benchmark_subtitle_search_paths import load_latest_manifest
        eligible = {str(row.get("jellyfin_id")) for row in
                    load_latest_manifest() if movie_scope.matches(row,args.scope)}
        records = [record for record in records if str(record[0]) in eligible]
        print("SELECTED_STAGED_SCOPE:", args.scope,
              "eligible_catalog_titles:", len(eligible), flush=True)
    if args.jellyfin_id:
        records = [record for record in records if record[0] == args.jellyfin_id]
        print("EXACT_JELLYFIN_ITEM_FILTER:",args.jellyfin_id,
              "matching_stage_rows:",len(records),flush=True)
    if args.series:
        from benchmark_subtitle_search_paths import load_latest_manifest
        records = select_staged_series(
            records, load_latest_manifest(), args.series, args.season)
        print("SELECTED_STAGED_SERIES:", args.series,
              "season:", args.season or "all",
              "staged_items:", len({str(r[0]) for r in records}), flush=True)
    if args.queue_staged_only:
        records = queued_staged_titles(records)
        print("BRUISER_PENDING_STAGED_TITLES:",
              len({str(item[0]) for item in records}), flush=True)
    title_groups = unique_titles(records, args.max_titles)
    print("=== UNIFIED JAPANESE SUBTITLE PUBLISH QUEUE ===", flush=True)
    if args.intensive_only:
        print("RECOVERY: intensive ALASS second pass; cached stages only;"
              " each failed candidate isolated; require independent timing agreement",
              flush=True)
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
            kind, row, value = (choose(jid, candidates, intensive_only=True)
                                if args.intensive_only else choose(
                                    jid,candidates,record_failures=args.apply))
            print("RESULT:", report_title(row), "|", kind, flush=True)
            counts[kind] += 1
            if kind=="held_unchanged":
                report_next_action(jid,candidates)
                continue
            if kind.startswith("published_"):
                if args.apply:
                    mark_completed(jid)
                    counts["retired_completed"] += 1
                print("BRUISER_PUBLISH_ITEM:", json.dumps({
                    "jellyfin_id": jid, "result": "already_published",
                    "proof": kind}, sort_keys=True), flush=True)
                continue
            if kind.startswith("ready_"):
                seen_ready += 1
                if args.apply:
                    publish_selected(jid, kind, value)
                    # Mark only after successful create-only host publication.
                    mark_completed(jid)
                    counts["published_new"] += 1
                    print("BRUISER_PUBLISH_ITEM:", json.dumps({
                        "jellyfin_id": jid, "result": "published",
                        "proof": kind}, sort_keys=True), flush=True)
        except (ValueError, RuntimeError, OSError, KeyError, sqlite3.Error) as exc:
            counts["held"] += 1
            print("HELD:", jid, type(exc).__name__, str(exc)[:135], flush=True)
            print("BRUISER_PUBLISH_ITEM:", json.dumps({
                "jellyfin_id": jid, "result": "held",
                "reason": type(exc).__name__ + ": " + str(exc)[:120]
            }, sort_keys=True), flush=True)
            if not args.intensive_only:
                report_next_action(jid,candidates)
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
