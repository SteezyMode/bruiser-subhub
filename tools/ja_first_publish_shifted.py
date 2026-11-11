#!/usr/bin/env python3
"""Correct a VERIFIED constant subtitle offset without modifying its source.

Use when a SubHub staged Japanese SRT has:
- exact Jellyfin episode/movie identity and native OpenSubtitles history,
- a trusted embedded English subtitle reference from the SAME video,
- >=95% cue-start alignment at one constant offset within +/-2 seconds,
- a clean full-dialogue Japanese SRT.

Default: read-only evaluation. --apply: preserve a separate corrected copy
under private HOST staging, verify its new cue alignment, and invoke the
existing create-only Japanese publisher. Never change staged originals,
overwrite a sidecar, run translation, or use provider download allowances.

Requires sibling scripts:
    ja_first_stage_saved_batch.py
    ja_first_stage_timing_audit.py
    ja_first_publish_staged.py
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import tempfile
from urllib.parse import quote

import ja_first_publish_staged as gate
import ja_first_stage_timing_audit as audit

MIN_MATCH = 0.95
MAX_SHIFT = 2.0
AFTER_OFFSET_MAX = 0.20
MAX_CANDIDATES = 8
ID = re.compile(r"[a-f0-9]{32}\Z")
SRT_TIMESTAMP = re.compile(
    r"(?m)^(?P<start>\d{2}:\d{2}:\d{2}[,.]\d{3})"
    r"(?P<arrow>[ \t]*-->[ \t]*)"
    r"(?P<end>\d{2}:\d{2}:\d{2}[,.]\d{3})"
    r"(?P<tail>[ \t]*)(?=\r?$)"
)


def milliseconds(clock):
    hh, mm, ss, frac = re.split(r"[:,.]", clock)
    if int(mm) > 59 or int(ss) > 59:
        raise RuntimeError("invalid_srt_clock_fields")
    return ((int(hh) * 3600 + int(mm) * 60 + int(ss)) * 1000 + int(frac))


def stamp(value_ms):
    if value_ms < 0 or value_ms >= 100 * 3600 * 1000:
        raise RuntimeError("shift_would_move_cue_outside_valid_time")
    hours, remain = divmod(value_ms, 3600000)
    minutes, remain = divmod(remain, 60000)
    seconds, ms = divmod(remain, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{ms:03d}"


def shift_srt(raw, offset_seconds):
    """Shift candidate by -offset_seconds; preserve EVERY dialogue line.

    A positive alignment offset means the JA cue begins later than English.
    A 0.7s late JA track receives a -0.7s shift. Never clamp negative starts,
    truncate cues, or modify the original stage content.
    """
    if not 0.5 < abs(offset_seconds) <= MAX_SHIFT:
        raise RuntimeError("shift_outside_conservative_policy")
    try:
        source = raw.decode("utf-8-sig")
    except UnicodeError:
        raise RuntimeError("source_not_valid_utf8") from None
    delta = round(offset_seconds * 1000)
    replacements = 0

    def edit(m):
        nonlocal replacements
        before = milliseconds(m["start"])
        after = milliseconds(m["end"])
        if before < delta or after - delta <= before - delta:
            raise RuntimeError("shift_would_invalidate_cue")
        replacements += 1
        return (stamp(before - delta) + m["arrow"] +
                stamp(after - delta) + m["tail"])

    changed = SRT_TIMESTAMP.sub(edit, source)
    if replacements < 75:
        raise RuntimeError("too_few_srt_timestamps_for_safe_shift")
    if SRT_TIMESTAMP.sub("<timing>", source) != SRT_TIMESTAMP.sub("<timing>", changed):
        raise RuntimeError("non_timing_subtitle_text_changed")
    return changed.encode("utf-8"), replacements


def corrected_timing_approved(result):
    """Require an explicit numeric offset; zero is a valid perfect match.

    Do not use "value or fallback" for timestamps: 0.0 is falsy but must
    not be mistaken for missing/invalid data.
    """
    if (result.get("status") != "fit"
            or result.get("reference_trust") != "trusted_embedded"):
        return False
    try:
        fraction = float(result["matching_start_fraction"])
        offset = float(result["best_offset_seconds"])
    except (KeyError, TypeError, ValueError):
        return False
    import math
    return (math.isfinite(fraction) and MIN_MATCH <= fraction <= 1.0
            and math.isfinite(offset) and abs(offset) <= AFTER_OFFSET_MAX)


def staged_rows(jid):
    uri = gate.db_uri(gate.STAGE_DB)
    with sqlite3.connect(uri, uri=True, timeout=10) as db:
        return db.execute(
            """SELECT subtitle_id FROM staged
               WHERE jellyfin_id=? AND status='staged'
               ORDER BY subtitle_id LIMIT ?""",
            (jid, MAX_CANDIDATES + 1)
        ).fetchall()


def preparation(jid):
    if not ID.fullmatch(jid):
        raise RuntimeError("invalid_jellyfin_id")
    row = gate.read_inventory(jid)
    video = gate.safe_media_path(str(row.get("host_path") or ""))
    streams, failure = gate.ffprobe_streams(video)
    if failure or not isinstance(streams, list):
        raise RuntimeError("ffprobe_could_not_verify_existing_subtitles")
    # Fail if another file is already published; never propose overwriting.
    gate.check_no_existing_ja(video, streams)

    records = staged_rows(jid)
    if len(records) > MAX_CANDIDATES:
        raise RuntimeError("too_many_staged_candidates_need_manual_review")
    if not records:
        raise RuntimeError("no_staged_candidates_for_requested_media")

    print("TITLE:", gate.metadata_label(row), flush=True)
    print("STAGED CANDIDATES:", len(records), flush=True)
    scored = []

    for (sid,) in records:
        sid = str(sid)
        try:
            gate.verify_search_identity(row, jid, sid)
            _, raw, metrics = gate.read_staging(jid, sid)
            runtime = float(metrics.get("video_seconds") or 0)
            if not 600 <= runtime <= 4*3600:
                raise RuntimeError("invalid_original_video_duration")
            if abs(gate.subprocess_duration(video) - runtime) > 0.5:
                raise RuntimeError("video_duration_changed_since_staging")
            initial_qa = gate.validate_srt(raw, runtime)
            if initial_qa["cues"] != int(metrics.get("cues") or -1):
                raise RuntimeError("original_staged_cue_count_changed")
            before = audit.inspect(row, raw)
            detail = {
                "subtitle_id": sid,
                "original_timing": {
                    "status": before.get("status"),
                    "match": before.get("matching_start_fraction"),
                    "offset_seconds": before.get("best_offset_seconds"),
                    "reference": before.get("reference_trust"),
                }
            }
            print("CANDIDATE:", json.dumps(detail), flush=True)
            if (before.get("status") != "shift_needed"
                    or before.get("reference_trust") != "trusted_embedded"
                    or float(before.get("matching_start_fraction") or 0) < MIN_MATCH):
                continue
            offset = float(before.get("best_offset_seconds") or 0)
            if not 0.5 < abs(offset) <= MAX_SHIFT:
                continue
            shifted, num = shift_srt(raw, offset)
            if num != initial_qa["cues"]:
                raise RuntimeError("shift_did_not_rewrite_all_srt_timestamps")
            corrected_qa = gate.validate_srt(shifted, runtime)
            if corrected_qa != initial_qa:
                raise RuntimeError("cue_or_japanese_text_changed_in_correction")
            after = audit.inspect(row, shifted)
            if not corrected_timing_approved(after):
                print("CORRECTION HELD:", sid, json.dumps(after), flush=True)
                continue
            print("CORRECTION VERIFIED:", json.dumps({
                "subtitle_id": sid,
                "before_match": before["matching_start_fraction"],
                "before_offset_seconds": offset,
                "after_match": after["matching_start_fraction"],
                "after_offset_seconds": after["best_offset_seconds"],
                "japanese_cues": corrected_qa["cues"],
                "source_sha256": hashlib.sha256(raw).hexdigest(),
                "adjusted_sha256": hashlib.sha256(shifted).hexdigest(),
            }), flush=True)
            scored.append({
                "sid": sid, "row": row, "video": video,
                "target": gate.video_target(video),
                "before": before, "after": after,
                "raw": raw, "adjusted": shifted,
            })
        except (OSError, RuntimeError, ValueError, sqlite3.Error) as exc:
            print("CANDIDATE HELD:", sid, type(exc).__name__,
                  str(exc)[:120], flush=True)

    if not scored:
        raise RuntimeError("no_candidate_passed_trusted_sync_correction")
    scored.sort(key=lambda result: (
        -result["after"]["matching_start_fraction"],
        abs(result["after"]["best_offset_seconds"]),
        result["sid"]
    ))
    if (len(scored) > 1 and
            scored[0]["after"]["matching_start_fraction"] -
            scored[1]["after"]["matching_start_fraction"] < 0.02):
        raise RuntimeError("multiple_equally_strong_candidates_need_manual_review")
    return scored[0]


def save_derived(best):
    """Save adjusted bytes + source lineage privately using create-only writes."""
    stage = audit.STAGED
    if not stage.is_dir() or stage.is_symlink() or stage.stat().st_mode & 0o077:
        raise RuntimeError("private_staging_directory_unsafe")
    folder = stage / "timing-adjusted"
    folder.mkdir(mode=0o700, exist_ok=True)
    if folder.is_symlink() or folder.stat().st_mode & 0o077:
        raise RuntimeError("timing_adjustment_folder_unsafe")
    name = (best["row"]["jellyfin_id"] + "." +
            gate.source_label(best["row"]["jellyfin_id"],best["sid"]) +
            "." + best["sid"] + ".ja.shifted.srt")
    output = folder / name
    body = best["adjusted"]
    digest = hashlib.sha256(body).hexdigest()

    record = {
        "schema": "subhub-ja-timing-correction-v1",
        "jellyfin_id": best["row"]["jellyfin_id"],
        "subtitle_id": best["sid"],
        "source_sha256": hashlib.sha256(best["raw"]).hexdigest(),
        "adjusted_sha256": digest,
        "offset_applied_seconds": -best["before"]["best_offset_seconds"],
        "before": best["before"],
        "after": best["after"],
        "file_name": name,
    }
    details = folder / (name + ".json")
    payload = (json.dumps(record, sort_keys=True, indent=2,
                          ensure_ascii=False) + "\n").encode("utf-8")
    for target, data in ((output, body), (details, payload)):
        if target.is_symlink():
            raise RuntimeError("unsafe_symlinked_corrected_artifact")
        if target.exists():
            if not target.is_file() or target.read_bytes() != data:
                raise RuntimeError("existing_derived_artifact_differs")
            continue
        fd, tmpname = tempfile.mkstemp(prefix=".pending-", dir=folder)
        tmp = Path(tmpname)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(tmp, 0o600)
            try:
                os.link(tmp, target, follow_symlinks=False)
            except FileExistsError:
                if target.is_symlink() or target.read_bytes() != data:
                    raise RuntimeError("corrected_artifact_raced")
        finally:
            tmp.unlink(missing_ok=True)
    print("DERIVED COPY:", output, flush=True)
    print("PROVENANCE:", details, flush=True)


def self_test():
    # A perfectly aligned corrected track has an offset of exactly 0.0.
    verified = {
        "status": "fit", "reference_trust": "trusted_embedded",
        "matching_start_fraction": 0.999, "best_offset_seconds": 0.0,
    }
    assert corrected_timing_approved(verified)
    assert corrected_timing_approved(dict(verified, best_offset_seconds=-0.1))
    assert not corrected_timing_approved(dict(verified, best_offset_seconds=0.25))
    assert not corrected_timing_approved(dict(verified, best_offset_seconds=None))
    assert not corrected_timing_approved(dict(verified, matching_start_fraction=0.90))
    assert not corrected_timing_approved(dict(verified, reference_trust="untrusted_sidecar"))
    assert not corrected_timing_approved(dict(verified, status="uncertain"))
    # Test the *production* 75-cue minimum with a realistic 90-cue fixture.
    # The prior two-cue fixture incorrectly failed its own safety gate.
    blocks = [
        "1\r\n00:00:01,700 --> 00:00:03,700\r\nこんにちは",
        "2\r\n00:00:05,700 --> 00:00:06,700\r\nありがとう",
    ]
    for number in range(3, 91):
        start_ms = 10_700 + (number - 3) * 3_000
        blocks.append(
            f"{number}\r\n{stamp(start_ms)} --> {stamp(start_ms + 1_500)}"
            "\r\n字幕テスト"
        )
    original = ("\r\n\r\n".join(blocks) + "\r\n").encode("utf-8")
    updated, count = shift_srt(original, 0.7)
    assert count == 90, count
    assert b"00:00:01,000 --> 00:00:03,000" in updated
    assert b"00:00:05,000 --> 00:00:06,000" in updated
    assert "こんにちは" in updated.decode("utf-8")
    assert "ありがとう" in updated.decode("utf-8")
    assert "字幕テスト" in updated.decode("utf-8")
    reversed_content, reverse_count = shift_srt(updated, -0.7)
    assert reverse_count == 90, reverse_count
    assert reversed_content == original
    try:
        shift_srt(
            b"1\n00:00:00,300 --> 00:00:01,200\nTest\n",
            0.7
        )
    except RuntimeError as exc:
        assert str(exc) == "shift_would_invalidate_cue", exc
    else:
        raise AssertionError("negative cue start was not rejected")
    try:
        shift_srt(b"1\n00:00:01,700 --> 00:00:03,700\nTest\n", 0.7)
    except RuntimeError as exc:
        assert str(exc) == "too_few_srt_timestamps_for_safe_shift", exc
    else:
        raise AssertionError("75-cue minimum was not enforced")
    print(
        "SELF-TEST PASSED: 90 cue round-trip, dialogue preserved, "
        "negative time and sparse subtitles refused; no writes",
        flush=True
    )


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--jellyfin-id", required=False, default="")
    cli.add_argument("--self-test", action="store_true")
    cli.add_argument("--apply", action="store_true",
                     help="persist derived subtitle and publish exactly one create-only sidecar")
    args = cli.parse_args()
    if args.self_test:
        self_test()
        return
    if not args.jellyfin_id:
        cli.error("--jellyfin-id is required")
    best = preparation(args.jellyfin_id)
    print("BEST CANDIDATE:", best["sid"], flush=True)
    print("PUBLISH TARGET:", best["target"], flush=True)
    if not args.apply:
        print("DRY RUN ONLY: no saved corrections, no sidecars published.", flush=True)
        print("Apply only after checking that the selected candidate is correct.", flush=True)
        return

    # Re-run source/identity/timing checks immediately before writing.
    best = preparation(args.jellyfin_id)
    save_derived(best)
    gate.publish(best["row"], best["video"], best["target"],
                 best["adjusted"])
    print("Published derived, re-verified Japanese SRT. Original staged candidate preserved.")
    print("No translation models or provider requests used.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("TIMING CORRECTION HELD:", type(exc).__name__, str(exc)[:150],
              file=sys.stderr)
        raise SystemExit(1) from None
