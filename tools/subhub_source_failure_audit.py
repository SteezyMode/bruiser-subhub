#!/usr/bin/env python3
"""Read-only post-batch audit of JA source failures sent to PLaMO.

Reads: saved Jellyfin inventory, search/stage SQLite, source-exhaustion receipts,
       and the stopped Finish systemd journal.
Does NOT: contact any provider, modify databases, repair/publish a subtitle,
          start a model, or infer a video's spoken language from its title.

The report is an EXPERIMENTAL triage, NOT approval to translate.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import unicodedata

ROOT=Path.home()/"bruiser-pilot/ja-first-inventory"
SEARCH_DB=ROOT/"japanese-search.sqlite3"
STAGE_DB=ROOT/"japanese-stage.sqlite3"
EXHAUSTION=ROOT/"source-exhaustion"
STATE=ROOT/"finish-scope.json"
JID=re.compile(r"[a-f0-9]{32}\Z")
EVENT=re.compile(r"\bFINISH_(PLAMO_QUEUE|PLAMO_PUBLISHED|PLAMO_RETRY|"
                 r"SOURCE_REQUEUE|SOURCE_RETRY|COVERED):\s*([a-f0-9]{32})")


def read_json(path):
    if not path.is_file() or path.is_symlink():
        raise RuntimeError("audit_input_missing_or_symlink:"+path.name)
    return json.loads(path.read_text("utf-8"))


def manifest():
    matches=sorted(ROOT.glob("ja-intake-*.json"))
    if not matches:
        raise RuntimeError("no_saved_jellyfin_inventory")
    doc=read_json(matches[-1])
    return {str(row["jellyfin_id"]):row for row in doc["items"]
            if isinstance(row,dict) and JID.fullmatch(
                str(row.get("jellyfin_id") or ""))}


def read_db(path,sql):
    if not path.is_file() or path.is_symlink():
        raise RuntimeError("audit_database_missing_or_symlink:"+path.name)
    with sqlite3.connect("file:"+str(path.resolve())+"?mode=ro",
                         uri=True,timeout=20) as db:
        return db.execute(sql).fetchall()


def searches():
    result={}
    for jid,outcome,searched_at,raw in read_db(
        SEARCH_DB,"SELECT jellyfin_id,outcome,searched_at,results_json FROM searches"):
        try:
            data=json.loads(raw)
        except (TypeError,ValueError):
            data={}
        result[str(jid)]={
            "outcome":str(outcome),"when":int(searched_at or 0),
            "results":data if isinstance(data,dict) else {}}
    return result


def stages():
    result={}
    for jid,sid,status,raw in read_db(
        STAGE_DB,"SELECT jellyfin_id,subtitle_id,status,metrics_json FROM staged"):
        try:
            metrics=json.loads(raw)
        except (ValueError,TypeError):
            metrics={}
        if not isinstance(metrics,dict):
            metrics={}
        result.setdefault(str(jid),[]).append({
            "subtitle_id":str(sid),"status":str(status),
            "provider":str(metrics.get("provider") or "unknown")})
    return result


def journal_events(state):
    cmd=["journalctl","--user","-u",
         "bruiser-subhub-finish-scope.service",
         "--since","2026-11-11 00:00:00","--no-pager","-o","json"]
    run=subprocess.run(cmd,capture_output=True,text=True,check=True,timeout=90)
    events=[]
    for line in run.stdout.splitlines():
        if not line.strip():
            continue
        try:
            events.append(json.loads(line))
        except ValueError:
            pass
    starts=[]
    for i,event in enumerate(events):
        msg=str(event.get("MESSAGE") or "")
        if not msg.startswith("FINISH_BEGIN "):
            continue
        try:
            meta=json.loads(msg.partition("FINISH_BEGIN ")[2])
        except ValueError:
            continue
        if int(meta.get("total_exact_files") or 0)==int(
                state.get("total_exact_files") or 0):
            starts.append(i)
    if not starts:
        raise RuntimeError("finish_batch_start_missing_from_journal")
    return events[starts[-1]:]


def final_plamo(events):
    current={}
    for e in events:
        text=str(e.get("MESSAGE") or "")
        found=EVENT.search(text)
        if not found:
            continue
        action,jid=found.groups()
        current[jid]=action
    return {jid for jid,action in current.items()
            if action in ("PLAMO_QUEUE","PLAMO_RETRY")},current


def is_complete(search):
    doc=search.get("results") or {}
    gates=doc.get("provider_gates")
    return (search.get("outcome") in ("none","plausible","review")
            and isinstance(gates,dict)
            and gates.get("opensubtitles")=="ok"
            and gates.get("subdl")=="ok"
            and not doc.get("incomplete_providers"))


def describe(jid,row,search,stage_rows):
    status=str(row.get("status") or "")
    audio=str(row.get("audio_language") or "unknown")
    doc=search.get("results") or {}
    candidates=[c for c in doc.get("candidates") or [] if isinstance(c,dict)]
    rejected=[c for c in doc.get("rejected_candidates") or []
              if isinstance(c,dict)]
    complete=is_complete(search)
    if status in ("japanese_audio","existing_japanese_subtitle"):
        reason="already_covered_in_inventory"
    elif not complete:
        reason="provider_coverage_not_proven"
    elif candidates and stage_rows:
        reason="japanese_candidates_staged_but_unpublished"
    elif candidates:
        reason="japanese_candidates_found_not_staged"
    elif rejected:
        reason="only_provider_rejected_candidates"
    else:
        reason="no_saved_credible_japanese_results"
    return {
        "jellyfin_id":jid,"title":str(row.get("title") or jid),
        "year":row.get("year"),
        "audio_language":audio,"inventory_status":status,
        "reason":reason,"search_outcome":search.get("outcome","none_recorded"),
        "providers_complete":complete,
        "provider_gates":doc.get("provider_gates") or {},
        "candidate_count":len(candidates),"rejected_count":len(rejected),
        "stage_count":len(stage_rows),
        "stage_statuses":dict(Counter(str(x["status"]) for x in stage_rows)),
        "staged_release_ids":[x["subtitle_id"] for x in stage_rows[:10]],
        "candidate_releases":[{
            "provider":c.get("provider"),"subtitle_id":c.get("subtitle_id"),
            "filename":str(c.get("filename") or "")[:150],
            "score":c.get("score")} for c in candidates[:10]],
        "has_exhaustion_receipt":(EXHAUSTION/(jid+".json")).is_file(),
    }


def analyze(state,rows,searches_by_id,stages_by_id,events):
    ids,transition=final_plamo(events)
    results=[]
    for jid in ids:
        results.append(describe(jid,rows.get(jid,{}) or {},
                                searches_by_id.get(jid,{}) or {},
                                stages_by_id.get(jid,[])))
    results.sort(key=lambda r:(r["reason"],r["title"].casefold(),
                               r["jellyfin_id"]))
    return {
        "scope_total":state.get("total_exact_files"),
        "recorded_plamo_pending":state.get("plamo_pending"),
        "plamo_ids_reconstructed":len(ids),
        "journal_complete_for_queue":len(ids)==state.get("plamo_pending"),
        "counts":dict(Counter(x["reason"] for x in results)),
        "items":results,
    }




def _sample_srt(path):
    """Actual timed Japanese cues only, never fabricate or translate a line."""
    staged_root=ROOT/"staged"
    if (not path.is_file() or path.is_symlink()
            or not path.resolve().is_relative_to(staged_root.resolve())
            or not 0<path.stat().st_size<=2_000_000):
        return ["staged subtitle file unavailable or unsafe"]
    data=path.read_bytes()
    decoded=None
    for codec in ("utf-8-sig","utf-16","cp932","shift_jis"):
        try:
            decoded=data.decode(codec)
            break
        except UnicodeError:
            continue
    if decoded is None:
        return ["unable to decode staged subtitle"]
    chunks=re.split(r"\r?\n\s*\r?\n",decoded)
    cues=[]
    for block in chunks:
        lines=[x.strip() for x in block.strip().splitlines() if x.strip()]
        anchor=next((i for i,line in enumerate(lines) if "-->" in line),None)
        if anchor is None or anchor+1>=len(lines):
            continue
        text=" ".join(lines[anchor+1:])
        text=re.sub(r"<[^>]*>|\{\\[^}]*\}","",text)
        if not text:
            continue
        cues.append((lines[anchor][:90],text[:170]))
    if not cues:
        return ["no parseable SRT timestamps; may be ASS/SSA/VTT"]
    indices=list(dict.fromkeys((0,len(cues)//2,len(cues)-1)))
    return [f"cue {i+1}/{len(cues)} {cues[i][0]} | {cues[i][1]}"
            for i in indices]


def inspect_staged(results):
    """First development experiment: which of the six tracks actually failed?"""
    items=[x for x in results["items"]
           if x["reason"]=="japanese_candidates_staged_but_unpublished"]
    print("=== STORED JAPANESE SUBTITLE DIAGNOSTICS (READ ONLY) ===")
    print("Movies with staged database records:",len(items))
    if not items:
        return
    ids=[item["jellyfin_id"] for item in items]
    args=",".join("?" for _ in ids)
    db=sqlite3.connect("file:"+str(STAGE_DB.resolve())+"?mode=ro",
                       uri=True,timeout=12)
    with db:
        stages=db.execute(
            f"SELECT jellyfin_id,subtitle_id,host_path,status,metrics_json "
            f"FROM staged WHERE jellyfin_id IN ({args}) ORDER BY jellyfin_id,subtitle_id",
            ids).fetchall()
    failures_by_id={}
    failure_db=ROOT/"japanese-candidate-failures.sqlite3"
    if failure_db.is_file() and not failure_db.is_symlink():
        with sqlite3.connect("file:"+str(failure_db.resolve())+"?mode=ro",
                             uri=True,timeout=12) as con:
            try:
                rows=con.execute(
                    f"SELECT jellyfin_id,subtitle_id,engine,reason,recorded_at "
                    f"FROM failures WHERE jellyfin_id IN ({args}) "
                    f"ORDER BY recorded_at DESC",ids).fetchall()
                for jid,sid,engine,reason,at in rows:
                    failures_by_id.setdefault(jid,[]).append(
                        (sid,engine,reason,int(at or 0)))
            except sqlite3.OperationalError as exc:
                if "no such table" not in str(exc):
                    raise
    for item in items:
        jid=item["jellyfin_id"]
        print(f"\nMOVIE {item['title']} ({item.get('year')}) [{jid}]")
        print("Audio tag:",item.get("audio_language"),
              "| Candidate results:",item.get("candidate_count"))
        for sid,engine,reason,at in failures_by_id.get(jid,[])[:12]:
            print("  ALIGNMENT HOLD:",engine,"subtitle",sid,
                  "reason:",str(reason)[:185],
                  "timestamp:",at)
        for _,sid,filename,status,raw in (r for r in stages if r[0]==jid):
            try:
                metrics=json.loads(raw)
            except (ValueError,TypeError):
                metrics={}
            if not isinstance(metrics,dict):
                metrics={}
            print("  STAGE:",sid,"status:",status,
                  "source:",metrics.get("provider","unknown"))
            for key in ("cues","video_seconds","last_end_seconds",
                        "last_end_video_ratio","japanese_cue_fraction",
                        "duration_mismatch","timing_note"):
                if key in metrics:
                    print("    "+key+":",str(metrics[key])[:180])
            for sample in _sample_srt(Path(filename)):
                print("    SAMPLE:",sample)
    print("\nOnly saved staging and failure records were read; nothing was changed.")



def find_structural_defects(path):
    """Diagnose mismatches between staging's regex cue count and publisher's blocks.

    The inspection mirrors the strict publication parser without attempting to
    repair or write a single byte. Report genuine timestamp/empty/control
    defects in context; never automatically delete Japanese dialogue.
    """
    root=ROOT/"staged"
    if (not path.is_file() or path.is_symlink()
            or not path.resolve().is_relative_to(root.resolve())
            or not 0<path.stat().st_size<=2_000_000):
        return {"error":"unsafe_or_missing_staged_file"}
    raw=path.read_bytes()
    text=None
    for codec in ("utf-8-sig","utf-16","cp932","shift_jis"):
        try:
            text=raw.decode(codec)
            break
        except UnicodeError:
            pass
    if text is None:
        return {"error":"undecodable_staged_file"}
    blocks=re.split(r"\r?\n[ \t]*\r?\n",text.strip())
    strict_stamp=re.compile(
        r"^[ \t]*(?:\d{1,3}:)?\d{2}:\d{2}[,.]\d{2,3}[ \t]*-->"
        r"[ \t]*(?:\d{1,3}:)?\d{2}:\d{2}[,.]\d{2,3}[ \t]*$")
    full_stamp=re.compile(
        r"(?m)^[ \t]*(?:\d{1,3}:)?\d{2}:\d{2}[,.]\d{2,3}[ \t]*-->"
        r"[ \t]*(?:\d{1,3}:)?\d{2}:\d{2}[,.]\d{2,3}")
    problems=[]
    multi=0
    bad_stamps=0
    empty=0
    controls=0
    for index,block in enumerate(blocks,1):
        lines=block.splitlines()
        ix=1 if lines and lines[0].strip().isdigit() else 0
        timestamp_lines=[(i,line) for i,line in enumerate(lines)
                         if "-->" in line]
        if len(timestamp_lines)>1:
            multi+=1
            if len(problems)<16:
                problems.append({
                    "block":index,"type":"multiple_timestamps_in_one_block",
                    "timestamp_lines":[line.strip()[:95]
                                      for _,line in timestamp_lines[:4]],
                    "neighboring_text":repr(block[:250])})
        if len(lines)<ix+2 or not strict_stamp.fullmatch(
                lines[ix].strip() if len(lines)>ix else ""):
            bad_stamps+=1
            if len(problems)<16:
                problems.append({
                    "block":index,"type":"unparseable_srt_block",
                    "neighboring_text":repr(block[:250])})
        elif not "\n".join(lines[ix+1:]).strip():
            empty+=1
            if len(problems)<16:
                problems.append({"block":index,"type":"empty_dialogue",
                                 "neighboring_text":repr(block[:250])})
        for pos,char in enumerate(block):
            if unicodedata.category(char)=="Cc" and char not in "\t\n\r":
                controls+=1
                if len(problems)<16:
                    problems.append({
                        "block":index,"type":"unexpected_control_character",
                        "codepoint":"U+%04X"%ord(char),
                        "context":repr(block[max(0,pos-30):pos+31])})
    return {
        "bytes":len(raw),"blocks":len(blocks),
        "timestamp_lines":len(full_stamp.findall(text)),
        "blocks_with_multiple_timestamps":multi,
        "unparseable_blocks":bad_stamps,"empty_dialogue_blocks":empty,
        "control_character_occurrences":controls,
        "examples":problems
    }


def inspect_defects(results):
    items=[x for x in results["items"]
           if x["reason"]=="japanese_candidates_staged_but_unpublished"]
    print("=== EXACT STAGED SRT DEFECTS (READ ONLY) ===")
    print("Found",len(items),"movies with staged files")
    if not items:
        return
    ids=[x["jellyfin_id"] for x in items]
    qmarks=",".join("?" for _ in ids)
    with sqlite3.connect("file:"+str(STAGE_DB.resolve())+"?mode=ro",
                         uri=True,timeout=12) as db:
        rows=db.execute(
            f"SELECT jellyfin_id,subtitle_id,host_path,status,sha256 "
            f"FROM staged WHERE jellyfin_id IN ({qmarks}) "
            "ORDER BY jellyfin_id,subtitle_id",ids).fetchall()
    for item in items:
        jid=item["jellyfin_id"]
        print("\nMOVIE:",item["title"],item.get("year"),
              "| Jellyfin ID",jid)
        for _,sid,path,status,digest in (r for r in rows if r[0]==jid):
            details=find_structural_defects(Path(path))
            print("  Subtitle",sid,"stage status",status,
                  "sha256",str(digest)[:16],
                  "blocks",details.get("blocks"),
                  "timestamp lines",details.get("timestamp_lines"),
                  "multi-timestamp blocks",details.get(
                      "blocks_with_multiple_timestamps"),
                  "unparseable blocks",details.get("unparseable_blocks"),
                  "bad control chars",details.get(
                      "control_character_occurrences"))
            for issue in details.get("examples") or []:
                print("    ISSUE:",json.dumps(issue,ensure_ascii=False))
            if details.get("error"):
                print("    ERROR:",details["error"])
    print("\nNo subtitle, media, staging, or failure-receipt writes performed.")


def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--full",action="store_true",
                    help="print every PLaMO title, with per-provider candidate counts")
    ap.add_argument("--json",action="store_true",
                    help="print machine-readable audit for subsequent experiments")
    ap.add_argument("--inspect-staged",action="store_true",
                    help="show saved timing failure reasons and actual Japanese cue samples for staged PLaMO cases")
    ap.add_argument("--inspect-defects",action="store_true",
                    help="locate malformed SRT blocks and broken control characters without modifying subtitles")
    args=ap.parse_args(argv)
    data=analyze(read_json(STATE),manifest(),searches(),stages(),
                 journal_events(read_json(STATE)))
    if args.json:
        print(json.dumps(data,ensure_ascii=False,indent=2))
        return
    if args.inspect_staged:
        inspect_staged(data)
        return
    if args.inspect_defects:
        inspect_defects(data)
        return
    print("=== STOPPED SUBHUB BATCH: PLaMO SALVAGE AUDIT (READ ONLY) ===")
    print("Selected items:",data["scope_total"],
          "PLaMO queued in state:",data["recorded_plamo_pending"],
          "PLaMO names reconstructed:",data["plamo_ids_reconstructed"])
    if not data["journal_complete_for_queue"]:
        print("WARNING: Journal queue is incomplete; do not infer missing titles!")
    print("\nREASONS (not final quality judgments):")
    for reason,n in sorted(data["counts"].items(),
                           key=lambda x:(-x[1],x[0])):
        print(f"  {n:3} {reason}")
    print("\nEXPERIMENTAL PRIORITY:")
    order=("already_covered_in_inventory",
           "provider_coverage_not_proven",
           "japanese_candidates_staged_but_unpublished",
           "japanese_candidates_found_not_staged",
           "only_provider_rejected_candidates",
           "no_saved_credible_japanese_results")
    for reason in order:
        chosen=[x for x in data["items"] if x["reason"]==reason]
        if not chosen:
            continue
        print("\n"+reason.upper()+f" ({len(chosen)}):")
        for item in chosen if args.full else chosen[:12]:
            print("  "+item["title"]+
                  (f" ({item['year']})" if item["year"] else "")+
                  " ["+item["jellyfin_id"][:8]+"]"+
                  f" audio={item['audio_language']} "+
                  f"candidate={item['candidate_count']} staged={item['stage_count']} "+
                  f"rejected={item['rejected_count']}"+
                  (" PROOF" if item["has_exhaustion_receipt"] else ""))
        if not args.full and len(chosen)>12:
            print(f"  ... {len(chosen)-12} further titles (use --full)")
    print("\nREAD ONLY. All original SRTs, search history, staging,"
          " and media untouched.")
    print("Coverage classification is an audit lead, not proof of translation quality.")


if __name__=="__main__":
    main()
