#!/usr/bin/env python3
"""Read-only IASIP Japanese sourcing forensics: why are 78 still uncovered?

Consumes only existing coverage-queue and Japanese-search SQLite data and the
EXACT sidecar paths already used by SubHub dashboard. No providers, edits, GPU,
downloads, or server requests. Does not print credentials or Japanese dialogue.
"""
from __future__ import annotations
from collections import Counter, defaultdict
import json
from pathlib import Path
import re
import sqlite3

HOME=Path.home()
MEDIA=HOME/"bruiser-pilot/coverage-queue/coverage.sqlite3"
SEARCH=HOME/"bruiser-pilot/ja-first-inventory/japanese-search.sqlite3"
LANGS={"ja","jp","jpn","japanese"}
EXTS={".srt",".ass",".ssa",".vtt"}

def existing_ja(v,recorded):
    if recorded:return True
    path=Path(str(v or ""))
    if not path.is_file() or path.is_symlink():return False
    try:
        for p in path.parent.iterdir():
            if not p.is_file() or p.is_symlink() or p.suffix.lower() not in EXTS:
                continue
            if not p.name.casefold().startswith(path.stem.casefold()+"."):
                continue
            tags=set(re.findall(r"[a-z0-9]+",p.name[len(path.stem):].casefold()))
            if tags & LANGS and not tags & {"forced","signs"} and 0<p.stat().st_size<=2000000:
                return True
    except OSError:
        return False
    return False

def ro(path):
    if not path.is_file() or path.is_symlink():
        raise SystemExit(f"Missing or symlinked database: {path}")
    return sqlite3.connect(f"file:{path}?mode=ro",uri=True)

def ep(s,e):
    try:return f"S{int(s):02}E{int(e):02}"
    except (TypeError,ValueError):return f"{s}/{e}"

def parse_json(v):
    try:
        obj=json.loads(v or "{}")
        return obj if isinstance(obj,dict) else {}
    except (TypeError,ValueError):return {}

def main():
    with ro(MEDIA) as db:
        rows=db.execute("""
          SELECT m.jellyfin_id,m.path,m.season,m.episode,m.ja_present,m.en_text,
                 t.action,t.state,t.reason,t.note
          FROM media m LEFT JOIN tasks t ON t.path=m.path
                 AND t.target IN ('ja','review') AND t.active=1
          WHERE m.kind='Episode' AND
                m.series="It's Always Sunny in Philadelphia"
          ORDER BY CAST(m.season AS INTEGER),CAST(m.episode AS INTEGER)
        """).fetchall()
    if SEARCH.is_file():
        with ro(SEARCH) as db:
            history={str(id_):{"outcome":outcome,"raw":parse_json(blob),
                                "time":timestamp}
                     for id_,outcome,blob,timestamp in db.execute(
                         "SELECT jellyfin_id,outcome,results_json,searched_at FROM searches")}
    else:history={}
    missing=[r for r in rows if not existing_ja(r[1],r[4])]
    print("IASIP:",len(rows),"files;",
          len(rows)-len(missing),"Japanese sidecars/flags;",
          len(missing),"uncovered")
    totals=Counter(); providers=Counter(); blocked=Counter(); source_states=Counter()
    examples=defaultdict(list)
    for r in missing:
        jid,path,season,episode,_,en,action,state,reason,note=r
        label=ep(season,episode)
        h=history.get(str(jid))
        status=str((h or {}).get("outcome") or "no_search_record")
        source_states[(action or "none",state or "none")]+=1
        payload=(h or {}).get("raw",{})
        candidates=[c for c in payload.get("candidates",[]) if isinstance(c,dict)]
        rejects=[c for c in payload.get("rejected_candidates",[]) if isinstance(c,dict)]
        total=payload.get("provider_total")
        if status=="no_search_record":
            category="never_saved_search"
        elif total is None:
            category="provider_total_missing"
        elif type(total) is not int:
            category="provider_total_unreadable"
        elif total==0 and not candidates and not rejects:
            category="actual_zero_returned_in_saved_search"
        elif total==0:
            category="zero_total_but_candidates_preserved"
        elif rejects and not candidates:
            category="results_rejected_by_filter"
        elif candidates:
            category="candidate_saved_for_review_or_staging"
        else:
            category="provider_returned_results_but_not_preserved"
        totals[(status,category)]+=1
        for c in candidates+rejects:
            providers[str(c.get("provider") or "unspecified")]+=1
        if status in ("none","plausible","review"):
            examples[category].append((label,total,len(candidates),len(rejects),en,action or "-",state or "-"))
        if action=="align_existing_staged_ja":
            blocked[(label,status)]+=1
    print("\nSAVED SEARCH OUTCOMES x EVIDENCE")
    for (status,category),num in sorted(totals.items(),key=lambda kv:(-kv[1],kv[0])):
        print(f"{num:3}  {status:16} {category}")
    print("\nPROVIDER NAMES IN RETAINED OR REJECTED CANDIDATES")
    for provider,n in providers.most_common():
        print(f"{n:3} {provider}")
    if not providers:print("(none recorded)")
    print("\nCURRENT QUEUE STATES (uncovered only)")
    for (a,s),n in source_states.most_common():
        print(f"{n:3} {a} / {s}")
    print("\nEPISODES BY EVIDENCE CLASS (up to 20/class)")
    for category in sorted(examples):
        rows_in=examples[category]
        print(f"{category}: {len(rows_in)}")
        for label,total,accepted,rejected,en,action,state in rows_in[:20]:
            print(f"  {label} provider_total={total} retained={accepted} rejected={rejected} EN={int(bool(en))} {action}/{state}")
        if len(rows_in)>20:print("  ...",len(rows_in)-20,"more")
    print("\nSTAGED JA REPAIR CANDIDATES")
    for label,status in sorted(blocked):
        print(label,"saved_search="+status)
    print("\nIMPORTANT: Raw result counts show what the configured providers returned then,")
    print("not whether subtitles exist elsewhere. A title can also have unindexed")
    print("embedded Japanese; this report uses the dashboard's external-sidecar test.")
    print("READ ONLY: no provider calls, subtitle downloads, translation or writes.")

if __name__=="__main__":main()
