#!/usr/bin/env python3
"""Apply explicitly reviewed, source-verified corrections to an idle SubHub 1.0.

No inference, media scans, or edits to existing subtitle files. Preserves every
checkpoint except the exact cues listed in a PRIVATE manifest. Dry run is default.
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
import sys


def load_service(base:Path):
    sys.path.insert(0,str(base/'subhub1'))
    import service
    return service


@contextlib.contextmanager
def worker_locks(base,root):
    with contextlib.ExitStack() as stack:
        for p in (root/'run.lock',base/'subhub-household/.runner.lock'):
            p.parent.mkdir(parents=True,exist_ok=True)
            h=stack.enter_context(p.open('a+b'))
            try:fcntl.flock(h,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:raise RuntimeError('Worker active; no correction applied: '+str(p))
            stack.callback(fcntl.flock,h.fileno(),fcntl.LOCK_UN)
        yield


def verified_corrections(store,manifest,s):
    if manifest.get('schema')!='bruiser-private-cue-fixes-v1':
        raise ValueError('Wrong private manifest schema')
    rows=manifest.get('edits')
    if not isinstance(rows,list) or not rows or len(rows)>50:
        raise ValueError('Manifest needs 1..50 explicitly reviewed cue corrections')
    verified=[];seen=set()
    for entry in rows:
        if not isinstance(entry,dict) or not isinstance(entry.get('job_id'),str):
            raise ValueError('Invalid cue correction item')
        jid=entry['job_id'];ident=entry.get('cue_id')
        if not isinstance(ident,int) or isinstance(ident,bool) or ident<1:
            raise ValueError('Bad cue ID')
        if (jid,ident) in seen:raise ValueError('Repeated cue edit')
        seen.add((jid,ident))
        job=store.cn.execute('SELECT * FROM jobs WHERE id=?',(jid,)).fetchone()
        if job is None:raise RuntimeError('Unknown job: '+jid)
        if job['status'] in ('published','hold'):
            raise RuntimeError('Refusing to edit a protected or already published job: '+jid)
        repairing_corrupt_hold = job['status']=='publish_hold'
        if repairing_corrupt_hold and job['last_error'] != 'Incomplete or malformed Japanese':
            raise RuntimeError('Protected publication hold is not an invalid-Japanese hold: '+jid)
        if s.sha(Path(job['source_path']).read_bytes())!=job['source_sha']:
            raise RuntimeError('Source subtitle changed since checkpoint: '+jid)
        cue=store.cn.execute('SELECT * FROM cues WHERE job_id=? AND cue_id=?',(jid,ident)).fetchone()
        if cue is None:raise RuntimeError('Missing cue record: '+jid+' '+str(ident))
        if cue['english']!=entry.get('english'):
            raise RuntimeError('English cue mismatch; manifest is stale: '+jid+' '+str(ident))
        if repairing_corrupt_hold:
            # A machine-contaminated cue may be much longer than terminal
            # output, so require both a nontrivial verified prefix and a
            # specific artifact marker; never rely on the marker alone.
            prefix=entry.get('previous_japanese_prefix')
            marker=entry.get('corruption_marker')
            old_text=cue['japanese']
            if (not isinstance(prefix,str) or len(prefix)<12
                or not isinstance(marker,str) or marker not in ('<tool_call|>','<tool_call>')):
                raise RuntimeError('Invalid explicit corrupt-output evidence: '+jid+' '+str(ident))
            if (not isinstance(old_text,str) or not old_text.startswith(prefix)
                or marker not in old_text or s.acceptable_ja(old_text,cue['english'])):
                raise RuntimeError('Stored Japanese does not match reviewed corruption: '+jid+' '+str(ident))
            # Only repair a hold with exactly the one known malformed cue.
            invalid=[r['cue_id'] for r in store.rows(jid)
                     if not r['japanese'] or not s.acceptable_ja(r['japanese'],r['english'])]
            if invalid != [ident]:
                raise RuntimeError('Other invalid cues require review before repair: '+repr(invalid[:8]))
        elif cue['japanese']!=entry.get('previous_japanese'):
            raise RuntimeError('Japanese cue changed since review: '+jid+' '+str(ident))
        translated=entry.get('japanese')
        if not s.acceptable_ja(translated,cue['english']):
            raise ValueError('Japanese candidate failed validation: '+jid+' '+str(ident))
        verified.append((jid,ident,translated))
    return verified


def apply(store,verified,s,root,publish=False):
    timestamp=dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    backup=root/'backups'/f'manual-cue-repair-{timestamp}.sqlite3'
    backup.parent.mkdir(parents=True,exist_ok=True)
    if backup.exists():raise RuntimeError('Backup filename collision; abort')
    with sqlite3.connect(backup) as snapshot:
        store.cn.backup(snapshot)
    os.chmod(backup,0o600)
    print('SQLite backup:',backup,flush=True)
    touched=sorted({jid for jid,_,_ in verified})
    store.cn.execute('BEGIN IMMEDIATE')
    try:
        for jid,ident,japanese in verified:
            store.cn.execute('UPDATE cues SET japanese=?,failed=0,last_error=NULL WHERE job_id=? AND cue_id=?',
                             (japanese,jid,ident))
            store.event(jid,'editorial_cue_repair',f'Approved local correction at cue {ident}; private manifest')
        for jid in touched:
            job=store.cn.execute('SELECT COUNT(*) FROM cues WHERE job_id=? AND japanese IS NULL',(jid,)).fetchone()
            remaining=job[0]
            state='queued' if remaining else 'translated'
            store.cn.execute('UPDATE jobs SET status=?,last_error=NULL,updated=? WHERE id=?',
                             (state,s.stamp(),jid))
        store.cn.execute('COMMIT')
    except Exception:
        store.cn.execute('ROLLBACK');raise
    for jid in touched:
        job=next(j for j in store.jobs() if j['id']==jid)
        print(f"REPAIRED {jid}: {job['ja']}/{job['n']} cues, {job['status']}",flush=True)
        if publish and job['ja']==job['n']:
            try:
                dest,result=s.publish_job(store,job,apply=True)
                print(f'PUBLISHED {jid}: {dest}',flush=True)
            except Exception as e:
                store.state(jid,'publish_hold',str(e)[:220])
                print('PUBLISH HOLD '+jid+': '+str(e)[:220],flush=True)
    return backup


def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--base',type=Path,default=Path.home()/'bruiser-pilot')
    ap.add_argument('--root',type=Path,default=Path.home()/'bruiser-pilot/subhub1-state')
    ap.add_argument('--manifest',default='-',help='PRIVATE JSON path or - for stdin')
    ap.add_argument('--apply',action='store_true',help='Back up and apply exact reviewed cue edits')
    ap.add_argument('--publish',action='store_true',help='Publish fully translated films if sidecars are safe')
    args=ap.parse_args(argv)
    if args.publish and not args.apply:ap.error('--publish requires --apply')
    raw=sys.stdin.read() if args.manifest=='-' else Path(args.manifest).read_text(encoding='utf-8')
    manifest=json.loads(raw)
    with worker_locks(args.base,args.root):
        s=load_service(args.base)
        st=s.Store(args.root)
        try:
            verified=verified_corrections(st,manifest,s)
            print('Validated',len(verified),'source-matched local subtitle corrections',flush=True)
            for jid,ident,ja in verified:print(f'  {jid} cue {ident}: {ja}',flush=True)
            if args.apply:apply(st,verified,s,args.root,args.publish)
            else:print('DRY RUN: no database, media or subtitle changes',flush=True)
        finally:st.cn.close()
    return 0


if __name__=='__main__':raise SystemExit(main())
