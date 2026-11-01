#!/usr/bin/env python3
"""Read-only structural contamination scan of all translated SubHub checkpoints.

No model calls, no media reads, no writes or state changes. This is NOT a
semantic Japanese-quality assessment. Only prints job IDs and cue IDs.
"""
from __future__ import annotations
import argparse
from pathlib import Path
import sqlite3
import sys

ARTIFACTS=('<tool_call', chr(96)*3+'json', '"translations"', '<｜hy_', '[Translation note]',
           'As an AI', 'I translated', 'Explanation:')


def scan(root,service):
    db=(Path(root)/'jobs.sqlite3').resolve(strict=True)
    with sqlite3.connect(db.as_uri()+'?mode=ro',uri=True,timeout=10) as cn:
        cn.row_factory=sqlite3.Row
        cn.execute('PRAGMA query_only=ON')
        jobs=cn.execute('SELECT id,status,source_cues FROM jobs ORDER BY priority,created').fetchall()
        results=[]
        for job in jobs:
            invalid=[]; artifacts=[];total=0
            for cue in cn.execute('SELECT cue_id,english,japanese FROM cues WHERE job_id=? ORDER BY cue_id',(job['id'],)):
                ja=cue['japanese']
                if not ja:continue
                total+=1
                if not service.acceptable_ja(ja,cue['english']):invalid.append(cue['cue_id'])
                if any(marker.casefold() in ja.casefold() for marker in ARTIFACTS):artifacts.append(cue['cue_id'])
            results.append((job['id'],job['status'],total,job['source_cues'],invalid,artifacts))
        return results


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--service',type=Path,required=True)
    args=parser.parse_args(argv)
    # Load the installed validator, never a possibly different GitHub version.
    from diagnose_invalid_ja import load_service
    try:
        data=scan(args.root,load_service(args.service))
    except (ValueError,sqlite3.Error,OSError) as exc:
        parser.error(str(exc))
    suspicious=0
    for jid,state,done,n,invalid,artifacts in data:
        suspicious+=len(set(invalid)|set(artifacts))
        print(f'{jid}: {state}, {done}/{n} translated, '
              f'{len(invalid)} invalid, {len(artifacts)} artifact marker(s)')
        if invalid:print('  Invalid cue IDs:', ','.join(str(x) for x in invalid[:50]))
        if artifacts:print('  Artifact cue IDs:', ','.join(str(x) for x in artifacts[:50]))
    print(f'READ-ONLY SCAN: {len(data)} jobs; {suspicious} potentially contaminated cue(s). '
          'No translation quality judgment or files changed.')
    return 0

if __name__=='__main__':
    sys.exit(main())
