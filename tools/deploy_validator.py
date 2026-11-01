#!/usr/bin/env python3
"""Guarded atomic SubHub validator upgrade; no Ollama or queue mutations."""
from __future__ import annotations
import argparse
import contextlib
import fcntl
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

# GitHub blob SHA of already-deployed November 1 batch-fix service.py.
EXPECTED_OLD_GIT_BLOB='691286b716a28eecddb368e05dd1433bc92a9053'


def blob(p):
    return subprocess.check_output(['git','hash-object',str(p)],text=True).strip()


def install(base,root,live,candidate):
    if candidate.is_symlink() or not candidate.is_file():raise RuntimeError('Staged candidate missing or symlink')
    if live.is_symlink() or not live.is_file():raise RuntimeError('Live service missing or symlink')
    with contextlib.ExitStack() as stack:
        for p in (root/'run.lock',base/'subhub-household/.runner.lock'):
            p.parent.mkdir(parents=True,exist_ok=True)
            h=stack.enter_context(p.open('a+b'))
            try:fcntl.flock(h.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:raise RuntimeError('Active worker, no upgrade applied')
            stack.callback(fcntl.flock,h.fileno(),fcntl.LOCK_UN)
        actual=blob(live)
        if actual==blob(candidate):
            print('Validator already installed; no change')
            return
        if actual!=EXPECTED_OLD_GIT_BLOB:
            raise RuntimeError('Live service.py differs from known installed version ('+actual+'); refusing overwrite')
        compile(candidate.read_bytes(),str(candidate),'exec')
        # Validate targeted semantics without reading private media or running Ollama.
        import importlib.util
        spec=importlib.util.spec_from_file_location('candidate_ja_validator',candidate)
        mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
        for ja,en,expected in [('３、２…','Three, two...',True),('RC！','RC!',True),('B.','B.',True),
                               ('EMS!','EMS!',False),('I O.D.','I O.D.',False),
                               ('I am sorry','I am sorry',False),('救急隊！','EMS!',True)]:
            if mod.acceptable_ja(ja,en)!=expected:
                raise RuntimeError('Candidate validator failed safety smoke check')
        stamp=time.strftime('%Y%m%dT%H%M%SZ',time.gmtime())
        backup=live.with_name('service.py.before-validator-'+stamp)
        if backup.exists():raise RuntimeError('Backup exists; no change')
        shutil.copy2(live,backup)
        os.replace(candidate,live)
        print('Validator installed; previous source backup:',backup)
        print('No active workers interrupted; no checkpoints or media modified')


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    base=Path.home()/'bruiser-pilot'
    parser.add_argument('--base',type=Path,default=base)
    parser.add_argument('--root',type=Path,default=base/'subhub1-state')
    parser.add_argument('--live',type=Path,default=base/'subhub1/service.py')
    parser.add_argument('--candidate',type=Path,default=base/'subhub1/service.candidate.py')
    args=parser.parse_args(argv)
    try:install(args.base,args.root,args.live,args.candidate)
    except Exception as e:
        print('SAFE ABORT:',type(e).__name__,str(e),file=sys.stderr);return 2
    return 0

if __name__=='__main__':raise SystemExit(main())
