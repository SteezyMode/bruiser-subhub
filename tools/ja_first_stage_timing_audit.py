#!/usr/bin/env python3
"""Read-only timing alignment audit for durably staged Japanese subtitles.

Compares an existing staged JA subtitle to a different-language embedded or
sidecar timing reference using Sublarr's OWN subtitle_timing.align() module.
No provider searches/downloads, translations, sidecar publication or media
writes. Sublarr may create/delete its normal temporary SRT reference in /tmp.

A lack of a reliable reference is 'unverified', NEVER 'aligned'.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
from urllib.parse import quote

ROOT = Path.home() / "bruiser-pilot/ja-first-inventory"
STAGE_DB = ROOT / "japanese-stage.sqlite3"
STAGED = ROOT / "staged"
SUPPORTED_EXT = {".srt", ".ass"}
ID = re.compile(r"[a-f0-9]{32}\Z")
STAGE_NAME = re.compile(r"([a-f0-9]{32})\.opensubtitles\.([1-9][0-9]{3,13})\.ja\.(srt|ass)\Z")

# All imports and subtitle alignment happen inside the existing Sublarr
# container, using a bounded single JSON job on stdin; no secrets involved.
WORKER = r'''
import base64
import json
import sys

def check(job):
    # Installed Sublarr versions may not contain these optional helper
    # modules. Resolve imports INSIDE the protected worker try block so a
    # missing module produces a useful structured hold, never an empty reply.
    from subtitle_dialogue import dialogue_starts
    from subtitle_timing import align, find_reference

    path = str(job.get("sublarr_path") or "")
    if not (path.startswith("/media/bigdisk-video/")
            or path.startswith("/media/expansion-video/")
            or path.startswith("/media/american-dad-main/")
            or path.startswith("/media/american-dad-2tb/")):
        raise RuntimeError("unapproved_container_media_path")
    if not job.get("filename", "").endswith((".srt", ".ass")):
        raise RuntimeError("unsupported_subtitle_format")
    content = base64.b64decode(job["subtitle_b64"], validate=True)
    if not 0 < len(content) <= 2_000_000:
        raise RuntimeError("invalid_subtitle_size")
    starts = dialogue_starts(content)
    if not starts or len(starts) < 40:
        raise RuntimeError("unreadable_or_short_subtitle")
    reference = find_reference(path, "ja")
    if reference is None:
        return {"status": "unverified_no_reference", "japanese_cues": len(starts)}
    if reference.source.startswith("embedded"):
        trust = "trusted_embedded"
    else:
        trust = "untrusted_sidecar"
    alignment = align(reference.starts, starts)
    if alignment is None:
        return {"status": "unverified_insufficient_alignment_data",
                "reference": reference.source,
                "reference_trust": trust, "japanese_cues": len(starts),
                "reference_cues": len(reference.starts)}
    return {"status": alignment.verdict,
            "reference": reference.source, "reference_trust": trust,
            "japanese_cues": len(starts),
            "reference_cues": len(reference.starts),
            "best_offset_seconds": alignment.offset_s,
            "matching_start_fraction": alignment.match}

try:
    job = json.load(sys.stdin)
    result = check(job)
    print("TIMING_RESULT_JSON:" + json.dumps(result, ensure_ascii=False), flush=True)
except Exception as exc:
    reason = ("missing_module:" + str(exc.name)
              if isinstance(exc, ModuleNotFoundError) and exc.name
              else type(exc).__name__ + ":" + str(exc)[:100])
    print("TIMING_RESULT_JSON:" + json.dumps({
        "status": "blocked", "error_type": type(exc).__name__,
        "error": reason
    }), flush=True)
    raise SystemExit(1)
'''


def private(path, description):
    if not path.is_file() or path.is_symlink() or (path.stat().st_mode & 0o077):
        raise RuntimeError(description + "_missing_or_unsafe")


def load():
    if not ROOT.is_dir() or ROOT.is_symlink() or ROOT.stat().st_mode & 0o077:
        raise RuntimeError("unsafe_private_root")
    private(STAGE_DB, "staging_database")
    if not STAGED.is_dir() or STAGED.is_symlink() or STAGED.stat().st_mode & 0o077:
        raise RuntimeError("unsafe_staging_directory")
    manifests = sorted(ROOT.glob("ja-intake-*.json"))
    if not manifests:
        raise RuntimeError("manifest_missing")
    private(manifests[-1], "intake_manifest")
    inventory = json.loads(manifests[-1].read_text())
    if inventory.get("schema") != 1:
        raise RuntimeError("unsupported_manifest_schema")
    items = {str(x["jellyfin_id"]): x for x in inventory["items"]
             if isinstance(x, dict) and x.get("jellyfin_id")}
    uri = "file:" + quote(str(STAGE_DB.resolve()), safe="/") + "?mode=ro"
    with sqlite3.connect(uri, uri=True, timeout=10) as db:
        rows = db.execute(
            """SELECT jellyfin_id,subtitle_id,host_path,sha256,status,metrics_json
               FROM staged WHERE status = 'staged'
               ORDER BY staged_at, jellyfin_id"""
        ).fetchall()
    return items, rows


def select(jid, sid, host, digest, state, metrics_json, inventory):
    if not ID.fullmatch(str(jid)):
        raise RuntimeError("invalid_jellyfin_id")
    if state != "staged":
        raise RuntimeError("not_staged")
    p = Path(host)
    match = STAGE_NAME.fullmatch(p.name)
    if not match or match.group(1) != str(jid) or match.group(2) != str(sid):
        raise RuntimeError("stage_filename_mismatch")
    if p.parent != STAGED:
        raise RuntimeError("stage_file_outside_private_directory")
    private(p, "staged_file")
    if not 0 < p.stat().st_size <= 2_000_000:
        raise RuntimeError("invalid_staged_file_size")
    content = p.read_bytes()
    if hashlib.sha256(content).hexdigest() != digest:
        raise RuntimeError("staged_file_hash_mismatch")
    metrics = json.loads(metrics_json)
    if metrics.get("format") != match.group(3) or metrics.get("bytes") != len(content):
        raise RuntimeError("staging_metrics_mismatch")
    row = inventory.get(str(jid))
    if not row or row.get("status") != "ready_ja_search":
        raise RuntimeError("staged_media_not_in_current_inventory")
    video_path = row.get("sublarr_path")
    if not isinstance(video_path, str):
        raise RuntimeError("missing_sublarr_media_path")
    if row.get("kind") not in {"Movie", "Episode"}:
        raise RuntimeError("unexpected_media_type")
    return row, p, content


def test():
    compile(WORKER, "<sublarr-ja-timing-worker>", "exec")
    assert STAGE_NAME.fullmatch("a"*32 + ".opensubtitles.11947715.ja.srt")
    assert not STAGE_NAME.fullmatch("../foo")
    assert "from subtitle_timing import align, find_reference" in WORKER
    assert WORKER.index("try:\\n    job = json.load") > WORKER.index("def check(job):")
    assert "TIMING_RESULT_JSON:" in WORKER
    print("SELF-TEST PASSED: worker syntax and staging IDs; no network or writes")


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--self-test", action="store_true")
    cli.add_argument("--limit", type=int, default=2, help="inspect 1..5 staged files")
    opts = cli.parse_args()
    if opts.self_test:
        test()
        return
    if not 1 <= opts.limit <= 5:
        cli.error("--limit must be 1..5")
    inventory, rows = load()
    print("=== JA STAGING TIMING AUDIT ===", flush=True)
    print("Durably staged entries:", len(rows), flush=True)
    for i, data in enumerate(rows[:opts.limit], 1):
        try:
            row, path, content = select(*data, inventory)
        except (OSError, ValueError, RuntimeError) as exc:
            print(f"[{i}] HELD: {type(exc).__name__} {str(exc)[:100]}", flush=True)
            continue
        name = (str(row.get("series_title")) +
                f' S{row["season"]:02d}E{row["episode"]:02d}'
                if row["kind"] == "Episode" else
                f'{row.get("title")} ({row.get("year")})')
        print(f"[{i}/{min(opts.limit,len(rows))}] CHECKING: {name}",
              flush=True)
        payload = {"filename": path.name,
                   "sublarr_path": row["sublarr_path"],
                   "subtitle_b64": base64.b64encode(content).decode("ascii")}
        command = ["docker", "exec", "-i", "-e", "PYTHONPATH=/app",
                   "sublarr-pilot", "python3", "-c", WORKER]
        try:
            proc = subprocess.run(command, input=json.dumps(payload),
                                  text=True, capture_output=True, timeout=105)
            replies = [x[len("TIMING_RESULT_JSON:"):]
                       for x in proc.stdout.splitlines()
                       if x.startswith("TIMING_RESULT_JSON:")]
            if not replies:
                # The worker had no opportunity to emit a structured result:
                # distinguish exit/signal from normal no-reference outcomes.
                print("WORKER EXIT:", proc.returncode, flush=True)
                raise RuntimeError("timing_worker_exited_without_result")
            report = json.loads(replies[-1])
            if proc.returncode != 0 or report.get("status") == "blocked":
                print("TIMING BLOCKED:", json.dumps(report, ensure_ascii=False),
                      flush=True)
                continue
            print("TIMING:", json.dumps(report, ensure_ascii=False), flush=True)
        except (subprocess.TimeoutExpired, OSError, ValueError, RuntimeError) as exc:
            print("TIMING HELD:", type(exc).__name__, str(exc)[:120], flush=True)
    print("AUDIT COMPLETE: No downloads, provider searches, staging changes or publication.",
          flush=True)
    print("A timing FIT is not a content-quality or publication approval.", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("TIMING AUDIT BLOCKED:", type(exc).__name__, str(exc)[:120],
              file=sys.stderr)
        raise SystemExit(1) from None
