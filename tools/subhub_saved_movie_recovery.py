#!/usr/bin/env python3
"""Recover saved Japanese movie candidates, without any new provider searches.

Run from the OptiPlex host with existing installed SubHub tools on PYTHONPATH.
Default is read-only; --apply may download SAVED Japanese candidate IDs and
use the existing strict ALASS/ffsubsync create-only publisher. No PLaMO.
"""
from __future__ import annotations

import argparse
from collections import Counter
import os
from pathlib import Path
import re
import subprocess
import sys

try:
    from . import ja_first_autofill as autofill
    from . import ja_first_movie_scope as movie_scope
    from . import ja_first_stage_saved_batch as stage
    from . import ja_first_stage_subdl as subdl
    from . import subhub_deep_source as deep
except ImportError:
    import ja_first_autofill as autofill
    import ja_first_movie_scope as movie_scope
    import ja_first_stage_saved_batch as stage
    import ja_first_stage_subdl as subdl
    import subhub_deep_source as deep

HERE = Path(__file__).resolve().parent
# Installed tools, not a freshly downloaded script, own all provider and
# publisher calls. They enforce existing media, identity and timing checks.
WORKER = Path.home() / "bruiser-pilot/subhub-control"
BUSY_UNITS = (
    "bruiser-ja-source-autofill.service",
    "bruiser-subhub-jellyfin-source.service",
    "bruiser-subhub-finish-scope.service",
    "bruiser-subhub-season-sources.service",
    "bruiser-subhub-batch.service",
    "bruiser-subhub-translation-batch.service",
    "bruiser-subhub-movie-ja.service",
)
QUOTA = re.compile(r"(?i)(?:PROVIDER_LIMIT_REACHED|quota.{0,45}exhausted|"
                   r"rate[_ -]?limit|rate limit|HTTP[ _]?(?:406|429)|"
                   r"budget_exhausted|download_limit)")
OPEN_ID = re.compile(r"[1-9][0-9]{3,13}\Z")


def check_idle():
    for name in BUSY_UNITS:
        result = subprocess.run(["systemctl", "--user", "is-active", name],
                                capture_output=True, text=True,
                                stdin=subprocess.DEVNULL, timeout=10)
        state = result.stdout.strip()
        if state in ("active", "activating", "reloading"):
            raise RuntimeError("stop_active_subtitle_worker_first:"+name)
        if result.returncode not in (0, 3, 4):
            raise RuntimeError("cannot_confirm_worker_idle:"+name)


def candidate_key(jid, candidate):
    remote = str(candidate["subtitle_id"])
    if candidate["provider"] == "opensubtitles":
        if not OPEN_ID.fullmatch(remote):
            raise ValueError("invalid_saved_opensubtitles_id")
        return jid, remote
    if candidate["provider"] == "subdl":
        return jid, subdl.numeric_id(remote)[0]
    raise ValueError("unsupported_saved_provider")


def fresh_candidates(row, document, staged, rejected, *, rejected_check=None):
    """Only identity-verified, untried saved releases; no new searches."""
    rejected_check = stage.known_rejected_download if rejected_check is None else rejected_check
    result = []
    skipped = Counter()
    for candidate in deep.candidates_for(row, document):
        try:
            key = candidate_key(row["jellyfin_id"], candidate)
        except (ValueError, KeyError):
            skipped["bad_candidate_id"] += 1
            continue
        if key in staged:
            skipped["already_staged"] += 1
            continue
        if key in rejected:
            skipped["known_duration_mismatch"] += 1
            continue
        if (candidate["provider"] == "opensubtitles" and
                rejected_check(row, candidate)):
            skipped["known_invalid_download"] += 1
            continue
        result.append(candidate)
    return result, skipped


def saved_work(rows, *, skip_titles=(), search_reader=None,
               staged=None, rejected=None, rejected_check=None):
    search_reader = deep.search_record if search_reader is None else search_reader
    staged = stage.read_staged() if staged is None else staged
    rejected = stage.rejected_duration_candidates() if rejected is None else rejected
    jobs = []
    counts = Counter()
    samples = []
    for row in sorted(rows, key=lambda x: (
            str(x.get("title") or "").casefold(),
            str(x.get("jellyfin_id") or ""))):
        if row.get("kind") != "Movie" or not movie_scope.matches(
                row, "horror-drama-folders"):
            continue
        if row.get("status") != "ready_ja_search":
            continue
        jid = str(row.get("jellyfin_id") or "")
        if not deep.JID.fullmatch(jid):
            counts["invalid_catalog_id"] += 1
            continue
        document = search_reader(jid)
        if not document or document.get("_outcome") not in ("review", "plausible"):
            continue
        counts["saved_review_or_plausible"] += 1
        if str(row.get("title") or "").casefold() in skip_titles:
            counts["owner_skipped"] += 1
            continue
        try:
            candidates, ignored = fresh_candidates(
                row, document, staged, rejected, rejected_check=rejected_check)
        except (ValueError, OSError, RuntimeError, KeyError) as exc:
            counts["candidate_audit_error"] += 1
            samples.append((str(row.get("title")),type(exc).__name__))
            continue
        counts.update({"skipped_"+k:v for k,v in ignored.items()})
        if candidates:
            jobs.append((row, candidates))
            counts["titles_with_new_verified_candidates"] += 1
            counts["new_candidate_releases"] += len(candidates)
        else:
            counts["titles_without_new_verified_candidates"] += 1
            if len(samples)<15:
                samples.append((str(row.get("title")),document["_outcome"]))
    return jobs, counts, samples


def stage_candidate(jid, candidate):
    remote = str(candidate["subtitle_id"])
    provider = candidate["provider"]
    if provider == "opensubtitles":
        command = [
            sys.executable, "-B", "-u", str(WORKER/"ja_first_stage_saved_batch.py"),
            "--jellyfin-id", jid, "--kind", "movie", "--budget", "1",
            "--subtitle-id", remote, "--exhaustive", "--apply"]
        success = "STAGED:"
    else:
        command = [
            sys.executable, "-B", "-u", str(WORKER/"ja_first_stage_subdl.py"),
            "--jellyfin-id", jid, "--subtitle-id", remote, "--apply"]
        success = "STAGED_SUBDL:"
    result = subprocess.run(command, capture_output=True, text=True,
                            stdin=subprocess.DEVNULL, timeout=900)
    output = result.stdout + "\n" + result.stderr
    if QUOTA.search(output):
        return "quota", "provider_download_limit"
    if result.returncode == 0 and any(
            line.startswith(success) for line in result.stdout.splitlines()):
        return "staged", "validated_private_stage"
    reason = next((line.strip()[:120] for line in
                   reversed(result.stdout.splitlines())
                   if line.startswith(("HELD:","SUBDL_REJECTED:",
                                       "SUBDL_HELD:","STAGED_HELD:"))),
                  "stage_not_accepted")
    return "held", reason


def run(args):
    check_idle()
    # The established source lock protects provider quotas and staging DB.
    fd = autofill.lock()
    try:
        stage.private_root()
        rows = list(stage.read_inventory().values())
        jobs, counts, samples = saved_work(
            rows, skip_titles={x.casefold() for x in args.skip_title})
        print("=== SAVED DRAMA/HORROR JAPANESE CANDIDATES ===", flush=True)
        for key,value in sorted(counts.items()):
            print(f"{key}: {value}", flush=True)
        print("Not-yet-validated examples:",samples,flush=True)
        print("Provider searches: ZERO; PLaMO: OFF; existing sidecars preserved",
              flush=True)
        if not args.apply:
            print("READ ONLY: use --apply for capped saved-release recovery",
                  flush=True)
            return 0
        print(f"APPLY: max {args.max_attempts} candidate staging attempts, "
              f"{args.max_per_title} per film",flush=True)
        result=Counter()
        blocked=set()
        attempts=0
        for index,(row,candidates) in enumerate(jobs,1):
            jid=row["jellyfin_id"]
            title=str(row.get("title") or jid)[:100]
            video=Path(row["host_path"])
            try:
                # Preflight first. Corrupt, missing and symlinked videos must
                # never consume a download or abort another movie's work.
                if not video.is_file() or video.is_symlink():
                    raise RuntimeError("video_missing_or_not_regular")
                if stage.japanese_sidecar_exists(video):
                    result["covered_since_intake"]+=1
                    continue
                stage.duration_if_safe(row)
            except (RuntimeError,OSError,ValueError,subprocess.TimeoutExpired) as exc:
                result["media_not_safe_to_source"]+=1
                print(f"[{index}/{len(jobs)}] SKIP {title}: "
                      f"{str(exc).split(':',1)[0]}",flush=True)
                continue
            print(f"[{index}/{len(jobs)}] {title} "
                  f"({len(candidates)} new identity-matching releases)",flush=True)
            for candidate in candidates[:args.max_per_title]:
                provider=candidate["provider"]
                if provider in blocked:
                    result["provider_limited_skipped"]+=1
                    continue
                if attempts>=args.max_attempts:
                    print("ATTEMPT CAP REACHED. Remaining titles untouched.",
                          flush=True)
                    break
                attempts+=1
                try:
                    outcome,reason=stage_candidate(jid,candidate)
                except (OSError,RuntimeError,ValueError,subprocess.TimeoutExpired) as exc:
                    outcome,reason="held",type(exc).__name__
                print(" ",provider,"stage:",outcome,reason,flush=True)
                result["stage_"+outcome]+=1
                if outcome=="quota":
                    blocked.add(provider)
                    continue  # Other provider remains independently usable
                if outcome!="staged":
                    continue
                # Only a newly staged release triggers publication; avoid
                # repeatedly rerunning 18 known failed staged movie groups.
                try:
                    published=deep.repair_staged(jid)
                except (OSError,RuntimeError,ValueError,subprocess.TimeoutExpired) as exc:
                    published="retry"
                    print("  PUBLISH HOLD:",type(exc).__name__,flush=True)
                if published=="covered" and stage.japanese_sidecar_exists(video):
                    result["published_new"]+=1
                    print("  PUBLISHED:",title,flush=True)
                    break
                result["publication_"+published]+=1
                print("  Publication:",published,flush=True)
            if attempts>=args.max_attempts:
                break
        print("=== RECOVERY SUMMARY ===",flush=True)
        print("New Japanese subtitle files:",result["published_new"],flush=True)
        print("Staging attempts:",attempts,flush=True)
        for key,value in sorted(result.items()):
            print(f"{key}: {value}",flush=True)
        print("Providers limited:",", ".join(sorted(blocked)) or "none",flush=True)
        print("Never requested fresh searches; never started PLaMO",flush=True)
        return 0
    finally:
        os.close(fd)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply",action="store_true")
    parser.add_argument("--max-attempts",type=int,default=25)
    parser.add_argument("--max-per-title",type=int,default=3)
    parser.add_argument("--skip-title",action="append",default=[])
    args=parser.parse_args(argv)
    if not 1<=args.max_attempts<=100 or not 1<=args.max_per_title<=8:
        parser.error("attempts must be 1..100, per-title must be 1..8")
    return run(args)


if __name__=="__main__":
    try:raise SystemExit(main())
    except (RuntimeError,OSError,ValueError,subprocess.TimeoutExpired) as exc:
        print("SAVED_RECOVERY_STOPPED:",type(exc).__name__,
              str(exc)[:155],file=sys.stderr,flush=True)
        raise SystemExit(1)
