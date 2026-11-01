#!/usr/bin/env python3
"""Private, read-only A/B comparison of checkpoints and revised localization.

Reads a single existing SQLite job in mode=ro, then uses the local Ollama
model to translate a few CONTIGUOUS dialogue windows with the optional
natural_8 profile. Never edits, imports, checkpoints, publishes or restarts.
Writes a private, create-only JSON comparison when --out is specified.
"""
from __future__ import annotations
import argparse
import contextlib
import datetime as dt
import fcntl
import json
import os
from pathlib import Path
import sqlite3
import time

import service as subhub


def get_rows(root, job_id):
    db=(Path(root)/'jobs.sqlite3').resolve(strict=True)
    with sqlite3.connect(db.as_uri()+'?mode=ro',uri=True,timeout=8) as cn:
        cn.row_factory=sqlite3.Row
        cn.execute('PRAGMA query_only=ON')
        job=cn.execute('SELECT * FROM jobs WHERE id=?',(job_id,)).fetchone()
        if job is None:raise ValueError('Unknown job ID')
        if job['status'] not in ('published','translated','publish_hold'):
            raise ValueError('Use a completed existing job, not active unfinished translation')
        rows=[dict(r) for r in cn.execute(
            'SELECT cue_id,english,japanese,timing,start_ms,end_ms FROM cues '
            'WHERE job_id=? ORDER BY cue_id',(job_id,))]
        if not rows:raise ValueError('No source cues')
        return dict(job),rows


def windows(rows, centers, size=8):
    """Non-overlapping full contiguous source windows around selected IDs."""
    if size<2 or size>12:raise ValueError('Allowed batch size is 2..12')
    indices={r['cue_id']:i for i,r in enumerate(rows)}
    taken=set()
    output=[]
    for ident in centers:
        if ident not in indices:raise ValueError(f'Unknown selected cue {ident}')
        pos=indices[ident]
        start=max(0,min(pos-size//2,max(0,len(rows)-size)))
        selected=rows[start:start+size]
        ids={r['cue_id'] for r in selected}
        if ids & taken:
            continue
        taken|=ids
        output.append(selected)
    return output


@contextlib.contextmanager
def locked_idle(base,root):
    """Hold the two existing worker locks so no queue worker starts during A/B."""
    with contextlib.ExitStack() as stack:
        for path in (Path(root)/'run.lock',Path(base)/'subhub-household/.runner.lock'):
            path.parent.mkdir(parents=True,exist_ok=True)
            handle=stack.enter_context(path.open('a+b'))
            try:
                fcntl.flock(handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:
                raise RuntimeError('Subtitle worker is active: no A/B model calls made')
            stack.callback(fcntl.flock,handle.fileno(),fcntl.LOCK_UN)
        yield


def cps(text, row):
    if not text:return None
    seconds=max(.001,(row['end_ms']-row['start_ms'])/1000)
    return round(sum(not c.isspace() for c in text)/seconds,1)


def compare(base,root,job_id,centers,size=8,call=None):
    job,rows=get_rows(root,job_id)
    batches=windows(rows,centers,size)
    if not batches:raise ValueError('No non-overlapping source windows selected')
    call=call or subhub.translation_call
    outputs=[];attempts=[]
    with locked_idle(base,root):
        for group in batches:
            start=time.monotonic()
            error=None
            try:
                memory=subhub.recall_memory(Path(base),job['scope'],group)
                result=call(Path(base),group,memory,style='natural_8')
            except Exception as exc:
                result={}
                error=type(exc).__name__+': '+str(exc)[:180]
            attempts.append({'start_cue':group[0]['cue_id'],
                             'end_cue':group[-1]['cue_id'],
                             'elapsed_seconds':round(time.monotonic()-start,2),
                             'returned':len(result),'error':error})
            for row in group:
                candidate=result.get(str(row['cue_id']))
                outputs.append({
                    'cue_id':row['cue_id'],'timing':row['timing'],
                    'english':row['english'],'existing_japanese':row['japanese'],
                    'candidate_japanese':candidate,
                    'old_cps':cps(row['japanese'],row),
                    'new_cps':cps(candidate,row),
                })
    return {'schema':'bruiser-private-natural8-comparison-v1',
            'generated_utc':dt.datetime.now(dt.timezone.utc).isoformat(),
            'job_id':job_id,'model':subhub.GEMMA,
            'profile':'natural_8','notes':'Side-by-side review only. No quality approval.',
            'windows':attempts,'entries':outputs}


def save_private(path,data):
    fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w',encoding='utf-8') as dest:
        json.dump(data,dest,ensure_ascii=False,indent=2)
        dest.write('\n')
        dest.flush()
        os.fsync(dest.fileno())


def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--base',type=Path,default=Path.home()/'bruiser-pilot')
    ap.add_argument('--root',type=Path,default=Path.home()/'bruiser-pilot/subhub1-state')
    ap.add_argument('--job',required=True)
    ap.add_argument('--cue-ids',required=True,help='Comma-separated representative cue IDs')
    ap.add_argument('--size',type=int,default=8)
    ap.add_argument('--out',type=Path,required=True,help='PRIVATE JSON; must not already exist')
    args=ap.parse_args(argv)
    try:
        centers=[int(s.strip()) for s in args.cue_ids.split(',')]
        if not centers or len(centers)>8:raise ValueError('Select 1..8 cue centers')
        result=compare(args.base,args.root,args.job,centers,args.size)
        save_private(args.out,result)
    except (ValueError,OSError,RuntimeError) as err:
        ap.error(str(err))
    print('Local A/B comparison saved privately:',args.out)
    for w in result['windows']:
        print(f"  {w['start_cue']}-{w['end_cue']}: {w['returned']} result(s), "
              f"{w['elapsed_seconds']}s"+(' / '+w['error'] if w['error'] else ''))
    print('No translated checkpoints, published subtitles or videos modified.')
    return 0


if __name__=='__main__':
    raise SystemExit(main())
