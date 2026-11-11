#!/usr/bin/env python3
"""Read-only audit of a series' unfilled Japanese subtitles.

Compare Jellyfin manifest file tags, completed job, provider candidates, and
saved staging receipts. No remote requests, downloads, or database writes.
"""
import json
import re
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path.home() / "bruiser-pilot/ja-first-inventory"
SERIES = "It's Always Sunny in Philadelphia"


def entries(filename, statement):
    path = ROOT / filename
    if not path.is_file():
        return {}
    with sqlite3.connect("file:" + str(path) + "?mode=ro", uri=True) as con:
        found = con.execute(statement).fetchall()
    grouped = defaultdict(list)
    for record in found:
        grouped[str(record[0])].append(record[1:])
    return grouped


def tag(name):
    for pattern in (
        r"(?<![a-z0-9])s(\d{1,2})[. _-]*e(\d{1,3})(?!\d)",
        r"(?<!\d)(\d{1,2})x(\d{1,3})(?!\d)",
    ):
        hit = re.search(pattern, name, re.I)
        if hit:
            return int(hit.group(1)), int(hit.group(2))
    return None


def main():
    manifests = sorted(ROOT.glob("ja-intake-*.json"))
    if not manifests:
        raise RuntimeError("Missing intake manifest")
    rows = [
        r for r in json.loads(manifests[-1].read_text())["items"]
        if isinstance(r, dict) and r.get("kind") == "Episode"
        and r.get("series_title") == SERIES
    ]
    job_path = ROOT / "jellyfin-source-batch.json"
    job = json.loads(job_path.read_text()) if job_path.is_file() else {}
    jobs = {str(x["id"]): x for x in job.get("items", []) if isinstance(x, dict)}
    search = entries("japanese-search.sqlite3",
                     "SELECT jellyfin_id,outcome,results_json FROM searches")
    stages = entries("japanese-stage.sqlite3",
                     "SELECT jellyfin_id,status,host_path FROM staged")

    def inspect(row):
        jid = str(row["jellyfin_id"])
        video = Path(str(row.get("host_path") or ""))
        wanted = row.get("season"), row.get("episode")
        filename_tag = tag(video.stem)
        filename_state = ("OK" if filename_tag == wanted
                          else "NO_TAG" if filename_tag is None
                          else "WRONG_" + str(filename_tag))
        state = jobs.get(jid, {})
        outcome, raw = search.get(jid, [("unsearched", "{}")])[-1]
        try:
            details = json.loads(raw or "{}")
        except (ValueError, TypeError):
            details = {}
        kept = details.get("candidates") or []
        rejected = details.get("rejected_candidates") or []
        example = (kept or rejected or [{}])[0]
        return {
            "file": video.name, "tag": filename_state,
            "job": state.get("status", "not_in_job"),
            "reason": state.get("reason", ""),
            "search": outcome, "hits": details.get("provider_total", "?"),
            "kept": len(kept), "rejected": len(rejected),
            "candidate": str(example.get("filename") or "")[:120],
            "provider": str(example.get("provider") or ""),
            "stage": dict(Counter(x[0] for x in stages.get(jid, []))),
            "blocks": details.get("incomplete_providers") or [],
        }

    target = sorted((r for r in rows if r.get("season") == 9),
                    key=lambda r: r.get("episode") or 0)
    print("=== SEASON 09: every Jellyfin episode ===")
    for row in target:
        d = inspect(row)
        print(f"S09E{row['episode']:02d}: filename={d['tag']} "
              f"job={d['job']} search={d['search']} hits={d['hits']} "
              f"retained={d['kept']} rejected={d['rejected']} "
              f"staged={d['stage']}")
        print("  VIDEO:", d["file"][:130])
        if d["reason"]:
            print("  JOB REASON:", d["reason"][:110])
        if d["candidate"]:
            print("  CANDIDATE:", d["provider"], d["candidate"])
        if d["blocks"]:
            print("  PROVIDER BLOCKS:", ", ".join(d["blocks"]))

    print("\n=== OTHER UNRESOLVED EPISODES: common patterns ===")
    by_season = defaultdict(Counter)
    for row in rows:
        if row.get("season") == 9:
            continue
        d = inspect(row)
        if d["job"] not in ("held", "no_match", "deferred"):
            continue
        by_season[row["season"]][
            (d["job"], d["tag"], d["search"])
        ] += 1
    for season in sorted(by_season):
        print(f"Season {season:02d}:", dict(by_season[season]))
    print("\nRead-only audit finished. No provider calls, staging, or media changes.")


if __name__ == "__main__":
    main()
