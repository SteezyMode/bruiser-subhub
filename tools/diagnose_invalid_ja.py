#!/usr/bin/env python3
"""Read-only check for already-translated cues rejected by the live JA validator.

Runs on the OptiPlex without a worker lock, model request, state migration,
media scan, or subtitle write. Loads the INSTALLED service.py validator so
the result exactly matches the publisher's acceptability check.
"""
from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path
import sqlite3


def load_service(path):
    spec = importlib.util.spec_from_file_location("live_subhub_validator", path)
    if spec is None or spec.loader is None:
        raise ValueError("Cannot load installed service.py")
    service = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(service)
    return service


def invalid_cues(db_path, service, job_id):
    p = Path(db_path).resolve(strict=True)
    with sqlite3.connect(p.as_uri() + "?mode=ro", uri=True, timeout=10) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only=ON")
        job = conn.execute(
            "SELECT id,status,source_cues,last_error FROM jobs WHERE id=?", (job_id,)
        ).fetchone()
        if job is None:
            raise ValueError("Unknown job: " + job_id)
        invalid = []
        translated = 0
        for row in conn.execute(
            "SELECT cue_id,english,japanese FROM cues WHERE job_id=? ORDER BY cue_id",
            (job_id,),
        ):
            if row["japanese"] is not None:
                translated += 1
            if not row["japanese"] or not service.acceptable_ja(row["japanese"], row["english"]):
                invalid.append(dict(row))
        return dict(job), translated, invalid


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--service", type=Path, required=True)
    parser.add_argument("--job", required=True)
    parser.add_argument("--show-text", action="store_true",
                        help="Print short private English/Japanese excerpts to the terminal")
    args = parser.parse_args(argv)
    try:
        job, translated, invalid = invalid_cues(
            args.root / "jobs.sqlite3", load_service(args.service), args.job
        )
    except (OSError, ValueError, sqlite3.Error) as exc:
        parser.error(str(exc))

    print(f"{job['id']} [{job['status']}]: {translated}/{job['source_cues']} "
          f"translated, {len(invalid)} publisher-invalid cue(s)")
    print("Stored hold reason:", job["last_error"] or "(none)")
    for row in invalid[:50]:
        print(f"  INVALID cue {row['cue_id']}")
        if args.show_text:
            print("    EN:", repr(row["english"][:300]))
            print("    JA:", repr((row["japanese"] or "")[:300]))
    if len(invalid) > 50:
        print(f"  ... plus {len(invalid)-50} additional invalid cues")
    print("Read-only inspection complete; nothing changed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
