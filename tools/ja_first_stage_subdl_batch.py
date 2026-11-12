#!/usr/bin/env python3
"""Bounded, general-purpose SubDL staging from the existing Japanese search DB.

Used by the standard source cycle after OpenSubtitles staging. SubDL has its
own allowance: an OpenSubtitles cooldown does not block SubDL ZIP recovery.
No live provider searches, translation, subtitle replacement or media writes.
The normal ALASS/ffsubsync publisher is still the only publication path.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import re
from urllib.error import HTTPError
import zipfile

try:
    from . import ja_first_stage_saved_batch as stage
    from . import ja_first_stage_subdl as subdl
except ImportError:
    import ja_first_stage_saved_batch as stage
    import ja_first_stage_subdl as subdl

MAX_ATTEMPTS=200


def select(inventory, searches, already, budget, scope="all"):
    """One saved release per uncovered title, with the normal backlog priority."""
    if not 1<=budget<=MAX_ATTEMPTS:
        raise ValueError("subdl_stage_budget_out_of_range")
    active=stage.priorities.active_coverage_queue()
    already=set(already)|stage.rejected_duration_candidates()
    eligible=[]
    for jid, raw in searches:
        jid=str(jid)
        row=inventory.get(jid)
        if (not isinstance(row,dict) or row.get("status")!="ready_ja_search"
                or row.get("kind") not in ("Movie","Episode")
                or not stage.movie_scope.matches(row,scope)):
            continue
        priority=stage.priorities.queue_position(row,"stage",active)
        if priority is None:
            continue
        try:
            history=json.loads(raw)
        except (ValueError,TypeError):
            continue
        if not isinstance(history,dict):
            continue
        candidates=[]
        for candidate in history.get("candidates") or []:
            if not subdl.identity_ok(row,candidate):
                continue
            sid,_=subdl.numeric_id(str(candidate["subtitle_id"]))
            if (jid,sid) in already:
                continue
            candidates.append(candidate)
        if not candidates:
            continue
        video=Path(str(row.get("host_path") or ""))
        # Never spend an allowance for a title covered since the last intake.
        if (video.is_file() and not video.is_symlink()
                and stage.japanese_sidecar_exists(video)):
            continue
        # Do not stage a second release before testing the first; a persisted
        # final alignment hold unlocks the alternate on a later source cycle.
        if not stage.alternate_ready(row):
            continue
        candidates.sort(key=lambda item:(
            -stage.candidate_progress.release_match(row,item),
            -int(item.get("score") or 0),
            str(item["subtitle_id"])))
        chosen=candidates[0]
        eligible.append((priority,str(row.get("title") or
                    row.get("series_title") or jid).casefold(),jid,row,chosen))
    eligible.sort(key=lambda entry:(entry[0],entry[1],entry[2]))
    return [(row,candidate) for _,_,_,row,candidate in eligible[:budget]]


def run(*,budget=20,scope="all",apply=False):
    inventory=stage.read_inventory()
    searches=stage.read_saved_searches()
    already=stage.read_staged()
    chosen=select(inventory,searches,already,budget,scope)
    print("=== SUBDL SAVED JAPANESE STAGING BATCH ===",flush=True)
    print("Saved searches:",len(searches),"| candidates:",len(chosen),
          "| attempt budget:",budget,"| scope:",scope,
          "| mode:","APPLY" if apply else "READ ONLY",flush=True)
    if not apply:
        print("No provider GET, private stage, or media write.",flush=True)
        return {}
    counts=Counter()
    for index,(row,candidate) in enumerate(chosen,1):
        label=str(row.get("title") or row.get("series_title") or
                  row["jellyfin_id"])[:100]
        print(f"[{index}/{len(chosen)}] SUBDL STAGING: {label}",flush=True)
        try:
            duration=stage.duration_if_safe(row)
            subdl.stage_one(row,candidate,duration)
            counts["staged_or_cached"]+=1
        except HTTPError as exc:
            if exc.code in (406,429):
                counts["provider_limited"]+=1
                print("SUBDL_PROVIDER_LIMIT_REACHED: HTTP_"+str(exc.code),
                      "| saved stages retained",flush=True)
                break
            counts["held"]+=1
            print("SUBDL_HELD: HTTP_"+str(exc.code),flush=True)
        except (RuntimeError,OSError,ValueError,zipfile.BadZipFile) as exc:
            counts["held"]+=1
            reason=str(exc).split(":",1)[0]
            if not re.fullmatch(r"[a-zA-Z0-9_]{1,90}",reason):
                reason=type(exc).__name__
            print("SUBDL_HELD:",reason,flush=True)
    print("SUBDL_BATCH_RESULT:",dict(counts),flush=True)
    print("PRIVATE STAGING ONLY: published media unchanged.",flush=True)
    return dict(counts)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--budget",type=int,default=20)
    parser.add_argument("--scope",choices=stage.movie_scope.SCOPES,default="all")
    parser.add_argument("--apply",action="store_true")
    args=parser.parse_args()
    if not 1<=args.budget<=MAX_ATTEMPTS:
        parser.error("--budget must be 1..200")
    run(budget=args.budget,scope=args.scope,apply=args.apply)


if __name__=="__main__":
    main()
