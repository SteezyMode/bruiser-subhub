#!/usr/bin/env python3
"""Read-only *metadata* inventory of private English subtitle sources for clean 006.

No model calls, installs, writes, subtitle contents or paths exposed.
Does NOT select final evaluation scenes; that requires freezing exclusion list,
title diversity, review manifest, and holdout before inference.
Usage on OptiPlex: python3 - --root ~/bruiser-pilot/subhub1-state < inventory_sources_006.py
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
import sys

EXCLUDED_SHA={
    # Benchmarks 001–005 all use this same *Primate* source. NO reuse.
    '8967cfea3f6552c0a6b1645da13e0d79e62be2decb95c02c653e6a345c3b645a'
}


def inventory(root, min_cues=60, min_span_min=10, exclusions=None):
    """Open only SQLite mode=ro; returns metadata, no copyrighted dialogue."""
    root=Path(root)
    db=(root/'jobs.sqlite3').resolve(strict=True)
    excludes=EXCLUDED_SHA | set(exclusions or ())
    uri=db.as_uri()+'?mode=ro'
    with sqlite3.connect(uri, uri=True, timeout=10) as conn:
        conn.row_factory=sqlite3.Row
        conn.execute('PRAGMA query_only=ON')
        jobs=conn.execute("""
            SELECT j.id, j.source_sha, j.source_cues, j.status,
                   j.audio_lang, j.scope,
                   COUNT(c.cue_id) AS rows,
                   SUM(CASE WHEN length(trim(c.english)) > 0 THEN 1 ELSE 0 END)
                       AS english_cues,
                   MIN(c.start_ms) AS first_ms,
                   MAX(c.end_ms) AS last_ms
            FROM jobs j JOIN cues c ON c.job_id = j.id
            GROUP BY j.id
            ORDER BY j.id
        """).fetchall()
    out=[]
    for row in jobs:
        span_min=round(max(0,(row['last_ms'] or 0)-(row['first_ms'] or 0))/60000,1)
        source=row['source_sha']
        excluded=source in excludes
        cues=row['english_cues'] or 0
        reason=(
            'prior_benchmark_source' if excluded else
            'not_enough_english_cues' if cues<min_cues else
            'short_timeline' if span_min<min_span_min else
            None
        )
        out.append({
            'job_id':row['id'],
            'source_sha256':source,
            'status':row['status'],
            'source_cues':row['source_cues'],
            'english_cues':cues,
            'timeline_span_minutes':span_min,
            'scope':row['scope'],
            'audio_lang':row['audio_lang'],
            'eligible_for_manual_title_diversity_review':reason is None,
            'exclusion_reason':reason,
        })
    return {
        'schema':'bruiser-private-source-inventory-006-v1',
        'read_only':True,
        'source_db':'SQLite mode=ro',
        'eligible_count':sum(x['eligible_for_manual_title_diversity_review'] for x in out),
        'total_jobs':len(out),
        'excluded_known_source_count':sum(x['exclusion_reason']=='prior_benchmark_source' for x in out),
        'note':('This is ONLY an English-SRT inventory. It does not prove that '
                'titles are independent, unreviewed, playable or blind. '
                'No subtitles, prompts, translations or source manifest were written.'),
        'jobs':out,
    }


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,default=Path.home()/'bruiser-pilot/subhub1-state')
    p.add_argument('--min-cues',type=int,default=60)
    p.add_argument('--min-timeline-minutes',type=float,default=10)
    p.add_argument('--exclude-sha',action='append',default=[])
    args=p.parse_args(argv)
    if args.min_cues<1 or args.min_timeline_minutes<0:
        p.error('Minimum cue count/timeline must be nonnegative')
    try:
        data=inventory(args.root,args.min_cues,args.min_timeline_minutes,
                       exclusions=args.exclude_sha)
    except (sqlite3.Error,OSError,ValueError) as exc:
        p.error(str(exc))
    json.dump(data,sys.stdout,ensure_ascii=False,indent=2)
    sys.stdout.write('\n')
    return 0


if __name__=='__main__':
    sys.exit(main())
