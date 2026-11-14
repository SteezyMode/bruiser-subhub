#!/usr/bin/env python3
"""Movie-only Japanese subtitle census and bounded discovery completion.

Two independent questions are reported for EACH Jellyfin movie:
1. Is a Japanese subtitle presently recognized by the inventory / sidecar scan?
2. How far did Japanese sourcing get: not searched, incomplete search, saved
   candidates, or staged candidates?

A "hold" is only a historical publisher failure receipt. It is never proof
that no Japanese subtitle exists and never counts as an additional movie.

Report mode reads local catalog/search/stage/receipt data, never probes
providers, runs sync engines, modifies media, or launches translation.
Scan mode refreshes Jellyfin inventory, uses the EXISTING search transport
under the shared source lock, then writes a new private CSV/JSON census.
No stage, publication, AI, or daily timer changes.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
from urllib.parse import quote

try:
    from . import ja_first_movie_scope as movie_scope
    from . import subhub_library_coverage as coverage
except ImportError:
    import ja_first_movie_scope as movie_scope
    import subhub_library_coverage as coverage

ROOT=Path.home()/"bruiser-pilot/ja-first-inventory"
SEARCH=ROOT/"japanese-search.sqlite3"
STAGE=ROOT/"japanese-stage.sqlite3"
FAILURE=ROOT/"japanese-candidate-failures.sqlite3"
CODE=Path(__file__).resolve().parent
CORE=("opensubtitles","subdl")
MAX_HISTORY_AGE=30*86400
CSV_COLUMNS=(
    "jellyfin_id","title","year","host_path","inventory_status",
    "subtitle_coverage","source_bucket","search_evidence",
    "last_search_utc","search_age_days","opensubtitles_gate","subdl_gate",
    "candidate_plausible","candidate_review","candidate_total",
    "candidate_providers","staged_candidate_count",
    "last_publisher_result","last_publisher_reason","japanese_audio",
)

def _read_private_file(path,*,required=True):
    if not path.exists() and not path.is_symlink():
        if required:
            raise RuntimeError("missing_private_census_source:"+path.name)
        return False
    stat=path.stat() if not path.is_symlink() else None
    if (stat is None or not path.is_file() or stat.st_uid!=os.getuid()
            or stat.st_mode & 0o077):
        raise RuntimeError("unsafe_private_census_source:"+path.name)
    return True

def _open_db(path,*,required=True):
    if not _read_private_file(path,required=required):
        return None
    return sqlite3.connect(
        "file:"+quote(str(path.resolve()),safe="/")+"?mode=ro",
        uri=True,timeout=20)

def _rows_from_search(db):
    return {str(jid):(str(outcome),int(searched or 0),raw)
            for jid,outcome,searched,raw in db.execute(
                "SELECT jellyfin_id,outcome,searched_at,results_json FROM searches")}

def _rows_from_staged(db):
    return dict(db.execute(
        "SELECT jellyfin_id,count(*) FROM staged "
        "WHERE status IN ('staged','published') GROUP BY jellyfin_id").fetchall())

def _rows_from_outcomes(db):
    if db is None:
        return {}
    names={str(r[1]) for r in db.execute("PRAGMA table_info(movie_outcomes)")}
    if not {"jellyfin_id","result","reason"}.issubset(names):
        return {}
    return {str(jid):(str(result),str(reason or ""))
            for jid,result,reason in db.execute(
                "SELECT jellyfin_id,result,reason FROM movie_outcomes")}

def search_evidence(record,*,now=None):
    """Describe search history, not subtitle validity or provider exhaustion.

    The Sublarr API exposes core provider gates, not a per-provider
    participation receipt. 'core_gates_ok' therefore means the gates were
    reported open during this saved search; it does NOT prove the provider
    has no Japanese subtitles elsewhere.
    """
    if record is None:
        return "not_searched",{},0
    outcome,when,raw=record
    try:
        doc=json.loads(raw)
        if not isinstance(doc,dict):
            return "invalid_search_history",{},when
    except (ValueError,TypeError):
        return "invalid_search_history",{},when
    if outcome in {"in_progress","error"}:
        return "interrupted_or_error",doc,when
    gates=doc.get("provider_gates")
    if (outcome in {"partial","deferred"}
            or bool(doc.get("incomplete_providers"))
            or isinstance(gates,dict) and bool(gates)
            and any(v!="ok" for v in gates.values())):
        return "provider_incomplete",doc,when
    if (not isinstance(gates,dict)
            or any(gates.get(provider)!="ok" for provider in CORE)):
        return "provider_evidence_unverified",doc,when
    age=(time.time() if now is None else now)-when
    if age>MAX_HISTORY_AGE:
        return "search_stale_30d",doc,when
    return "core_gates_ok",doc,when

def classify(rows,searches,staged,outcomes,*,now=None,scope_match=movie_scope.matches,
             sidecar_check=coverage._sidecar):
    now=time.time() if now is None else now
    listing={}
    details=[]
    out_of_scope=0
    for row in rows:
        if not isinstance(row,dict) or row.get("kind")!="Movie":
            continue
        if not scope_match(row,"movies-all"):
            out_of_scope+=1
            continue
        jid=str(row.get("jellyfin_id") or "")
        if not jid:
            raise RuntimeError("movie_without_jellyfin_identity")
        status=str(row.get("status") or "")
        sidecar=sidecar_check(row.get("host_path"),listing)
        subtitle=("present" if status=="existing_japanese_subtitle" or sidecar
                  else "missing" if status in coverage.KNOWN_MISSING
                  else "unverified")
        search_state,doc,when=search_evidence(searches.get(jid),now=now)
        all_candidates=[
            c for c in doc.get("candidates",[]) if isinstance(c,dict)
            and c.get("grade") in ("plausible","review")
        ] if isinstance(doc.get("candidates",[]),list) else []
        plausible=sum(c["grade"]=="plausible" for c in all_candidates)
        review=sum(c["grade"]=="review" for c in all_candidates)
        stage_count=int(staged.get(jid,0))
        publisher_result,publisher_reason=outcomes.get(jid,("",""))
        audio_only=status=="japanese_audio" and subtitle!="present"
        if subtitle=="present":
            bucket="has_japanese_subtitle"
        elif subtitle=="unverified":
            bucket="inventory_needs_verification"
        elif audio_only:
            bucket="japanese_audio_no_subtitle"
        elif stage_count:
            bucket="staged_not_published"
        elif all_candidates:
            bucket="saved_candidates_not_staged"
        elif search_state=="core_gates_ok":
            bucket="searched_no_saved_candidate"
        elif status not in ("ready_ja_search","review_no_movie_imdb",
                            "review_audio_language_unverified"):
            bucket="not_source_ready"
        elif search_state=="not_searched":
            bucket="not_searched"
        else:
            bucket="search_needs_completion"
        dt=(datetime.fromtimestamp(when,timezone.utc).isoformat()
            if when>0 else "")
        details.append({
            "jellyfin_id":jid,"title":str(row.get("title") or ""),
            "year":str(row.get("year") or ""),
            "host_path":str(row.get("host_path") or ""),
            "inventory_status":status,
            "subtitle_coverage":subtitle,
            "source_bucket":bucket,
            "search_evidence":search_state,
            "last_search_utc":dt,
            "search_age_days":round((now-when)/86400,1) if when else "",
            "opensubtitles_gate":str((doc.get("provider_gates") or {}).get(
                "opensubtitles","unknown")) if isinstance(doc.get("provider_gates"),dict)
                else "unknown",
            "subdl_gate":str((doc.get("provider_gates") or {}).get(
                "subdl","unknown")) if isinstance(doc.get("provider_gates"),dict)
                else "unknown",
            "candidate_plausible":plausible,
            "candidate_review":review,
            "candidate_total":len(all_candidates),
            "candidate_providers":",".join(sorted(set(str(c.get("provider") or "")
                                                      for c in all_candidates))),
            "staged_candidate_count":stage_count,
            "last_publisher_result":publisher_result,
            "last_publisher_reason":publisher_reason[:240],
            "japanese_audio":audio_only,
        })
    details.sort(key=lambda r:(r["title"].casefold(),r["year"],r["jellyfin_id"]))
    ids=[r["jellyfin_id"] for r in details]
    if len(ids)!=len(set(ids)):
        raise RuntimeError("duplicate_movie_jellyfin_identity")
    by_coverage=Counter(r["subtitle_coverage"] for r in details)
    by_bucket=Counter(r["source_bucket"] for r in details)
    missing=[r for r in details if r["subtitle_coverage"]=="missing"]
    search_counts=Counter(r["search_evidence"] for r in missing)
    last_holds=Counter(r["last_publisher_result"] for r in missing
                       if r["last_publisher_result"] in ("held","held_unchanged"))
    eligible_ids={str(row.get("jellyfin_id")) for row in rows
                  if isinstance(row,dict)
                  and row.get("kind")=="Movie"
                  and scope_match(row,"movies-no-anime")}
    target=[r for r in details if r["jellyfin_id"] in eligible_ids]
    target_present=sum(r["subtitle_coverage"]=="present" for r in target)
    target_missing=sum(r["subtitle_coverage"]=="missing" for r in target)
    summary={
        "schema":"bruiser-movie-census-v1",
        "generated_utc":datetime.fromtimestamp(now,timezone.utc).isoformat(),
        "scope":"movies-all",
        "movies":len(details),
        "non_anime_target_movies":len(target),
        "non_anime_present":target_present,
        "non_anime_missing":target_missing,
        "anime_or_excluded_movie_entries":len(details)-len(target),
        "movie_entries_outside_known_roots":out_of_scope,
        "subtitle_coverage":dict(sorted(by_coverage.items())),
        "mutually_exclusive_source_buckets":dict(sorted(by_bucket.items())),
        "search_evidence_among_missing":dict(sorted(search_counts.items())),
        "last_publisher_hold_receipts_among_missing":dict(sorted(last_holds.items())),
        "movies_with_saved_candidates":sum(bool(r["candidate_total"]) for r in missing),
        "movies_with_staged_candidates":sum(bool(r["staged_candidate_count"]) for r in missing),
        "saved_candidate_releases":sum(r["candidate_total"] for r in missing),
        "review_grade_releases":sum(r["candidate_review"] for r in missing),
        "note":("Historical held receipts are not permanent blocks. Review is "
                "weak metadata, not a human task or a subtitle publication. "
                "Core provider gates reported OK do not prove each provider "
                "participated or that no other Japanese subtitle exists.")
    }
    assert sum(by_coverage.values())==len(details)
    assert sum(by_bucket.values())==len(details)
    assert sum(search_counts.values())==len(missing)
    return summary,details

def gather():
    path=coverage.latest_manifest(ROOT)
    if path is None:
        raise RuntimeError("no_current_private_movie_catalog")
    _read_private_file(path)
    manifest=json.loads(path.read_text("utf-8"))
    if manifest.get("schema")!=1 or not isinstance(manifest.get("items"),list):
        raise RuntimeError("unsupported_jellyfin_manifest")
    with _open_db(SEARCH) as db:
        searches=_rows_from_search(db)
    with _open_db(STAGE) as db:
        staged=_rows_from_staged(db)
    con=_open_db(FAILURE,required=False)
    if con is None:
        outcomes={}
    else:
        with con:
            outcomes=_rows_from_outcomes(con)
    summary,rows=classify(manifest["items"],searches,staged,outcomes)
    summary["catalog_generated_utc"]=str(manifest.get("generated_utc") or "")
    summary["catalog_file"]=path.name
    summary["catalog_age_hours"]=round(max(0,time.time()-path.stat().st_mtime)/3600,1)
    return summary,rows

def _atomic_private(path,content):
    if path.is_symlink():
        raise RuntimeError("census_export_symlink")
    if path.exists():
        _read_private_file(path)
    fd,name=tempfile.mkstemp(prefix=".movie-census-",dir=ROOT)
    try:
        os.fchmod(fd,0o600)
        with os.fdopen(fd,"wb") as file:
            file.write(content)
            file.flush()
            os.fsync(file.fileno())
        os.replace(name,path)
    finally:
        Path(name).unlink(missing_ok=True)

def report(*,export=False):
    summary,rows=gather()
    print("=== MOVIE-ONLY JAPANESE SUBTITLE CENSUS ===",flush=True)
    print("Catalog:",summary["catalog_file"],"age_hours:",
          summary["catalog_age_hours"],flush=True)
    print("MOVIES:",summary["movies"],
          "| outside configured movie roots:",
          summary["movie_entries_outside_known_roots"],flush=True)
    print("NON-ANIME MOVIE TARGET:",summary["non_anime_target_movies"],
          "| Japanese subtitles present:",summary["non_anime_present"],
          "| missing:",summary["non_anime_missing"],
          "| excluded movies:",summary["anime_or_excluded_movie_entries"],
          flush=True)
    print("SUBTITLE COVERAGE (ONE MOVIE = ONE COUNT):",flush=True)
    for name in ("present","missing","unverified"):
        print(" ",name+":",summary["subtitle_coverage"].get(name,0),flush=True)
    print("MOVIE-WIDE SOURCE DIVISION (MUTUALLY EXCLUSIVE):",flush=True)
    for kind,count in summary["mutually_exclusive_source_buckets"].items():
        print(" ",kind+":",count,flush=True)
    print("PROVIDER SEARCH EVIDENCE AMONG MISSING MOVIES:",flush=True)
    for kind,count in summary["search_evidence_among_missing"].items():
        print(" ",kind+":",count,flush=True)
    print("MOVIES WITH SAVED JAPANESE CANDIDATES:",
          summary["movies_with_saved_candidates"],
          "| movie IDs with staged subtitles:",
          summary["movies_with_staged_candidates"],flush=True)
    print("SAVED RELEASES:",summary["saved_candidate_releases"],
          "| review-grade releases:",summary["review_grade_releases"],flush=True)
    print("HISTORICAL PUBLISHER HOLDS (NOT EXTRA MISSING MOVIES):",
          json.dumps(summary["last_publisher_hold_receipts_among_missing"],
                     sort_keys=True),flush=True)
    print("HOLD = an attempted publication/validation was refused;"
          " not absence of Japanese subtitles.",flush=True)
    print("REVIEW = weak metadata match; not a manual-review obligation.",flush=True)
    print("GATE OK = provider health reported open; NOT proof of exhaustive"
          " per-provider participation.",flush=True)
    if summary["catalog_age_hours"]>20:
        print("WARNING: catalog snapshot is >20h old;"
              " use 'scan' to refresh against Jellyfin.",flush=True)
    if export:
        if not ROOT.is_dir() or ROOT.is_symlink() or ROOT.stat().st_mode & 0o077:
            raise RuntimeError("unsafe_private_census_directory")
        output=io.StringIO()
        writer=csv.DictWriter(output,fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
        _atomic_private(ROOT/"movie-census-latest.csv",output.getvalue().encode("utf-8"))
        _atomic_private(ROOT/"movie-census-latest.json",
                        (json.dumps(summary,ensure_ascii=False,indent=2,sort_keys=True)
                         +"\n").encode("utf-8"))
        print("PRIVATE PER-MOVIE CSV:",ROOT/"movie-census-latest.csv",flush=True)
        print("PRIVATE SUMMARY JSON:",ROOT/"movie-census-latest.json",flush=True)
    print("NO MEDIA WRITES; NO SUBTITLE DOWNLOADS OR PUBLICATIONS.",flush=True)
    return summary

def scan(budget):
    """Refresh inventory, then scan only unsurveyed or incomplete movies."""
    try:
        from . import ja_first_autofill as autofill
    except ImportError:
        import ja_first_autofill as autofill
    fd=autofill.lock()
    try:
        settings=autofill.config()
        autofill.safe_source_settings(settings)
        if not autofill.native_search_disabled(settings):
            raise RuntimeError("parallel_native_source_search_not_disabled")
        autofill.check_scheduler_idle()
        print("REFRESHING LIVE JELLYFIN MOVIE INVENTORY",flush=True)
        subprocess.run([sys.executable,"-B",str(CODE/"ja_first_catalog_manifest.py"),
                        "--save"],timeout=1200,check=True)
        print("=== BEFORE MOVIE SEARCH ===",flush=True)
        report(export=True)
        print("=== SOURCE DISCOVERY ONLY: MOVIES-ALL ===",flush=True)
        command=[sys.executable,"-B","-u",
                 str(CODE/"ja_first_search_pilot.py"),
                 "--coverage-census","--scope","movies-all",
                 "--budget",str(budget)]
        result=subprocess.run(command,stdin=subprocess.DEVNULL,
                              check=False,timeout=8*3600)
        print("=== AFTER MOVIE SEARCH ===",flush=True)
        report(export=True)
        print("MOVIE_SCAN_EXIT:",result.returncode,flush=True)
        return result.returncode
    finally:
        os.close(fd)

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode",choices=("report","scan"),nargs="?",
                        default="report")
    parser.add_argument("--budget",type=int,default=600,
                        help="scan only: maximum provider search requests (1..600)")
    parser.add_argument("--export",action="store_true",
                        help="report: write private per-movie CSV + JSON summary")
    args=parser.parse_args(argv)
    if args.mode=="report":
        if args.budget!=600:
            parser.error("--budget is for scan only")
        report(export=args.export)
        return 0
    if args.export:
        parser.error("scan already exports before and after reports")
    if not 1<=args.budget<=600:
        parser.error("--budget must be between 1 and 600")
    return scan(args.budget)

if __name__=="__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError,ValueError,OSError,sqlite3.Error,
            subprocess.SubprocessError) as exc:
        print("MOVIE_CENSUS_HELD:",type(exc).__name__,
              str(exc)[:190],file=sys.stderr,flush=True)
        raise SystemExit(1)
