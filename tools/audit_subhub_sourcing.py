#!/usr/bin/env python3
"""Read-only one-shot audit of SubHub source searching. No provider calls."""
from collections import Counter
from pathlib import Path
import json
import re
import sqlite3
import subprocess

HOME=Path.home()
ROOT=HOME/"bruiser-pilot/ja-first-inventory"
DB=ROOT/"japanese-search.sqlite3"
WORKER=HOME/"bruiser-pilot/subhub-control/ja_first_search_pilot.py"
SVC="bruiser-ja-source-autofill.service"

CHECK=r'''
import json
from urllib.request import Request,urlopen
from config import get_settings
cfg=get_settings()
headers={"X-Api-Key":cfg.api_key}
base="http://127.0.0.1:5765/api/v1"
out={"budget_pacing":getattr(cfg,"provider_budget_stretch_mode","unknown"),
     "safety_margin_pct":getattr(cfg,"provider_budget_safety_margin_pct","unknown")}
for path,key in (("/providers/health","health"),("/system/budget","budget")):
    try:
        with urlopen(Request(base+path,headers=headers),timeout=15) as r:
            data=json.load(r)
        out[key]=[p for p in data.get("providers",[])
                  if p.get("name") in ("opensubtitles","subdl")]
        if key=="health":
            out[key]=[{k:p.get(k) for k in ("name","gate","enabled",
              "initialized","total_searches","successful_searches")}
              for p in out[key]]
        else:
            out[key]=[{k:p.get(k) for k in
               ("name","usage","limits","reset_seconds")} for p in out[key]]
    except Exception as exc:
        out[key]={"error":type(exc).__name__}
print(json.dumps(out))
'''

def subprocess_output(cmd,timeout=25):
    try:
        p=subprocess.run(cmd,capture_output=True,text=True,timeout=timeout,
                         check=False)
        return p.stdout if p.returncode==0 else ""
    except (OSError,subprocess.TimeoutExpired):
        return ""

def journal_report():
    raw=subprocess_output(["journalctl","--user","-u",SVC,
        "-o","cat","-n","20000","--no-pager"])
    lines=raw.splitlines()
    markers=[i for i,s in enumerate(lines) if "RUNNING_SOURCES_ONLY_CYCLE" in s]
    if not markers:
        return {"error":"no_recent_source_cycle_in_journal"}
    lines=lines[markers[-1]:]
    recent=[(int(m.group(1)),m.group(3)) for line in lines
        if (m:=re.search(r"\[(\d+)/(\d+)\] (PLAUSIBLE|NONE|REVIEW|ERROR|DEFERRED):",line))]
    return {"plan":next((s[:175] for s in lines if "Search requests planned:" in s),""),
        "search_outcomes":dict(Counter(kind for _,kind in recent)),
        "last_search_index":recent[-1][0] if recent else 0,
        "pipeline_completed":any("AUTOFILL_CYCLE_COMPLETE" in s for s in lines),
        "deferred_or_limit_events":[s.strip()[-180:] for s in lines
            if "DEFERRED:" in s or "PROVIDER_LIMIT_REACHED" in s][-10:]}

def saved_report():
    if not DB.is_file() or DB.is_symlink():
        return {"error":"no_private_search_db"}
    with sqlite3.connect("file:"+str(DB)+"?mode=ro",uri=True,timeout=12) as conn:
        rows=conn.execute("""SELECT kind,title,outcome,results_json
            FROM searches ORDER BY searched_at DESC LIMIT 100""").fetchall()
    counts=Counter(); versions=Counter(); examples=[]
    for kind,title,outcome,raw in rows:
        try: obj=json.loads(raw or "{}")
        except (ValueError,TypeError):obj={}
        if not isinstance(obj,dict):obj={}
        counts[str(outcome)]+=1
        versions[str(obj.get("strategy_version") or "unknown")]+=1
        if len(examples)<12:
            examples.append({"title":str(title)[:55],"kind":kind,"outcome":outcome,
                "reported_hits":obj.get("provider_total"),
                "saved_candidates":len(obj.get("candidates") or []),
                "rejected":len(obj.get("rejected_candidates") or []),
                "variant":obj.get("query_variant"),
                "gates":obj.get("provider_gates")})
    return {"records":len(rows),"outcomes":dict(counts),
            "strategy_versions":dict(versions),"latest_titles":examples}

def installed_version():
    if not WORKER.is_file() or WORKER.is_symlink():
        return "missing"
    source=WORKER.read_text(encoding="utf-8")
    m=re.search(r'["\']strategy_version["\']\s*:\s*(\d+)',source)
    return m.group(1) if m else "unknown"

def main():
    raw=subprocess_output(["docker","exec","-i","-e","PYTHONPATH=/app",
               "sublarr-pilot","python3","-c",CHECK],timeout=40)
    try: provider=json.loads(raw)
    except ValueError: provider={"error":"container_read_only_probe_failed"}
    print(json.dumps({
        "installed_source_strategy":installed_version(),
        "last_source_cycle":journal_report(),
        "latest_100_saved_searches":saved_report(),
        "sublarr_status":provider
    },ensure_ascii=False,indent=2))
    print("READ ONLY: no provider searches, subtitle downloads or file changes.")

if __name__=="__main__":
    main()
