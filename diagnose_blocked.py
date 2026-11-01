#!/usr/bin/env python3
"""Read-only status for SubHub publishing holds and exhausted cue retries.

No inference, source file/media reads, database writes, or publication.
The default prints only job IDs, cue IDs, retry counts, and error messages.
Use --show-text for short English context excerpts in private diagnostics.
"""
from __future__ import annotations
import argparse
from pathlib import Path
import sqlite3


def blocked(db: Path, show_text=False):
    db = db.resolve(strict=True)
    cn = sqlite3.connect(db.as_uri() + '?mode=ro', uri=True, timeout=5)
    cn.row_factory = sqlite3.Row
    try:
        cn.execute('PRAGMA query_only=ON')
        jobs = [dict(x) for x in cn.execute("""
          SELECT id,status,source_cues,last_error FROM jobs
          WHERE status IN ('needs_review','publish_hold','hold')
          ORDER BY priority,created""")]
        results = []
        for job in jobs:
            cues = [dict(r) for r in cn.execute("""
              SELECT cue_id,failed,last_error,english FROM cues
              WHERE job_id=? AND japanese IS NULL ORDER BY cue_id""",(job['id'],))]
            done = cn.execute('SELECT COUNT(*) FROM cues WHERE job_id=? AND japanese IS NOT NULL',
                              (job['id'],)).fetchone()[0]
            entry = {'job':job['id'],'status':job['status'],
                     'translated':done,'total':job['source_cues'],
                     'last_error':job['last_error'] or '',
                     'missing':len(cues),'exhausted':sum(r['failed']>=5 for r in cues),
                     'failed_cues':[]}
            for cue in cues:
                if cue['failed'] == 0 and job['status'] == 'publish_hold':
                    continue
                r = {'id':cue['cue_id'],'attempts':cue['failed'],
                     'error':cue['last_error'] or ''}
                if show_text:
                    r['english'] = cue['english'][:400]
                    neighbors = [dict(n) for n in cn.execute("""
                      SELECT cue_id,english,japanese FROM cues
                      WHERE job_id=? AND cue_id BETWEEN ? AND ? ORDER BY cue_id""",
                      (job['id'],cue['cue_id']-2,cue['cue_id']+2))]
                    r['context'] = [{'id':x['cue_id'],'en':x['english'][:200],
                                     'ja':(x['japanese'] or '')[:200]} for x in neighbors]
                entry['failed_cues'].append(r)
            results.append(entry)
        return results
    finally:
        cn.close()


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',required=True,type=Path,help='Existing subhub1-state directory')
    p.add_argument('--show-text',action='store_true',help='Show private subtitle excerpts around missing cues')
    args=p.parse_args(argv)
    try:
        data=blocked(args.root/'jobs.sqlite3',args.show_text)
    except (OSError,sqlite3.Error,ValueError) as exc:
        p.error(str(exc))
    if not data:
        print('No blocked jobs in current database snapshot')
    for job in data:
        print(f"{job['job']} [{job['status']}] {job['translated']}/{job['total']} translated; "
              f"{job['missing']} missing; {job['exhausted']} exhausted")
        if job['last_error']:
            print('  Job hold reason:',job['last_error'][:260])
        for cue in job['failed_cues']:
            print(f"  Cue {cue['id']}: {cue['attempts']} failed singleton(s); {cue['error'][:220]}")
            if args.show_text:
                for line in cue['context']:
                    print(f"    {line['id']}: EN {line['en']!r} / JA {line['ja']!r}")
    print('Read-only inspection complete; no translations or files modified.')
    return 0

if __name__=='__main__':
    raise SystemExit(main())
