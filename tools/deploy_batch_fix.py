#!/usr/bin/env python3
"""Guarded one-time service.py update, with no worker restart or model call.

Run on OptiPlex. Validates the actual legacy SRT parser and holds BOTH worker
locks before atomically replacing service.py. Does not reset checkpoints or
modify media/subtitle files.
"""
from __future__ import annotations
import argparse
import contextlib
import fcntl
import hashlib
import importlib.util
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import time

EXPECTED_UNPATCHED = 'a47a197a3c1e5b32750e5a00d8eed08e1b3d904912cfabac76d69e98d3798566'


def hash_file(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def verify_candidate(candidate, root, base):
    """Parse a real SRT batch through the existing legacy parser; no Ollama."""
    spec=importlib.util.spec_from_file_location('service_candidate',candidate)
    if not spec or not spec.loader:
        raise RuntimeError('Invalid Python service candidate')
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    uri=(root/'jobs.sqlite3').resolve(strict=True).as_uri()+'?mode=ro'
    db=sqlite3.connect(uri,uri=True,timeout=10)
    db.row_factory=sqlite3.Row
    try:
        db.execute('PRAGMA query_only=ON')
        rows=db.execute("""SELECT cue_id,timing,english FROM cues
            WHERE job_id=(SELECT id FROM jobs ORDER BY created LIMIT 1)
            ORDER BY cue_id LIMIT 12""").fetchall()
    finally:
        db.close()
    if len(rows)<2:
        raise RuntimeError('Cannot verify: fewer than two real subtitle cues')
    data=mod.render_clip(rows)
    sys.path.insert(0,str(base))
    import bruiser_auto
    with tempfile.NamedTemporaryFile(suffix='.srt') as clip:
        clip.write(data);clip.flush()
        parsed=bruiser_auto.parse_srt(clip.name)
    expected_ids=list(range(1,len(rows)+1))
    got_ids=[c.id for c in parsed]
    if got_ids != expected_ids:
        raise RuntimeError(f'Legacy parser mismatch: {got_ids!r} instead of {expected_ids!r}')
    if any(not getattr(c,'text','').strip() for c in parsed):
        raise RuntimeError('Legacy parser returned empty dialogue')
    print(f'PASS: legacy parser accepted {len(rows)} real SQLite cues as a valid batch',flush=True)


def install(candidate, live, root, base):
    if not candidate.is_file() or candidate.is_symlink():
        raise RuntimeError('Staged source missing or a symlink')
    if not live.is_file() or live.is_symlink():
        raise RuntimeError('Live source missing or a symlink')
    with contextlib.ExitStack() as stack:
        for p in (root/'run.lock',base/'subhub-household/.runner.lock'):
            p.parent.mkdir(parents=True,exist_ok=True)
            handle=stack.enter_context(p.open('a+b'))
            try:fcntl.flock(handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:
                raise RuntimeError('ACTIVE WORKER: no source files changed. Retry after completion: '+str(p))
            stack.callback(fcntl.flock,handle.fileno(),fcntl.LOCK_UN)
        oldhash=hash_file(live)
        newhash=hash_file(candidate)
        if oldhash==newhash:
            print('Already installed: source hash matches. No action taken.')
            candidate.unlink()
            return
        if oldhash != EXPECTED_UNPATCHED:
            raise RuntimeError('Unexpected live service.py hash '+oldhash+'; refusing to overwrite custom changes')
        compile(candidate.read_bytes(),str(candidate),'exec')
        verify_candidate(candidate,root,base)
        backup=live.with_name('service.py.before-batchfix-'+time.strftime('%Y%m%dT%H%M%SZ',time.gmtime()))
        if backup.exists():raise RuntimeError('Backup path exists; refusing overwrite')
        shutil.copy2(live,backup)
        os.replace(candidate,live)
        print('INSTALLED service.py batch fix; backup:',backup,flush=True)
        print('Queue, checkpoints, media, dashboard, and running jobs unchanged.',flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    base=Path.home()/'bruiser-pilot'
    parser.add_argument('--base',type=Path,default=base)
    parser.add_argument('--root',type=Path,default=base/'subhub1-state')
    parser.add_argument('--live',type=Path,default=base/'subhub1/service.py')
    parser.add_argument('--candidate',type=Path,default=base/'subhub1/service.candidate.py')
    args=parser.parse_args()
    try:install(args.candidate,args.live,args.root,args.base)
    except Exception as e:
        print('DEPLOYMENT ABORTED SAFELY:',type(e).__name__,str(e),file=sys.stderr)
        return 2
    return 0


if __name__=='__main__':raise SystemExit(main())
