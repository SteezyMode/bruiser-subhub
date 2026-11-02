#!/usr/bin/env python3
"""Translate/publish ONLY one daily job using already-installed SubHub 1.0.

No monolithic worker deployment, new model, or unrelated legacy queue jobs.
The existing main.run supplies locks, preflight, thermal guards, per-cue
checkpoints, and create-only publisher. This wrapper restricts its job view
to exactly the requested daily job, even when other old titles are queued.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys

try:
    import subtitle_publish_gate as gate
except ModuleNotFoundError:
    from tools import subtitle_publish_gate as gate

HOST_CODE=Path.home()/'bruiser-pilot/subhub1'
if HOST_CODE.is_dir():
    sys.path.insert(0,str(HOST_CODE))
import main
import service


def run_one(root,job_id,base=None,worker=None):
    if not re.fullmatch(r'daily-[a-z0-9-]{1,95}',job_id):
        raise ValueError('Invalid daily job ID')
    root=Path(root)
    if root.is_symlink() or not (root/'jobs.sqlite3').is_file():
        raise RuntimeError('Existing SubHub 1.0 queue not found')
    store=service.Store(root)
    try:
        original_jobs=store.jobs
        selected=next((x for x in original_jobs() if x['id']==job_id),None)
        if not selected:
            raise RuntimeError('Requested daily job not present in queue')
        if selected['audio_lang']!='eng':
            raise RuntimeError('Daily job has unverified English audio')
        if selected['status']=='published':
            print('DAILY_ALREADY_PUBLISHED',job_id,flush=True)
            return 'published'
        # This is intentionally a fresh, narrow view on EVERY read, not a
        # stale snapshot. main.run() reads jobs multiple times after updates.
        store.jobs=lambda: [j for j in original_jobs() if j['id']==job_id]
        args=argparse.Namespace(
            max_minutes=120,max_titles=1,mode='translate',
            max_gpu_c=82,max_cpu_c=85,hy_sample=0,
            sample_seconds=15,publish=True,skip_hy=True)
        work=worker or main.run
        # The existing native SubHub 1.0 main.run invokes main.s.publish_job.
        # Interpose ONLY for this selected daily worker process, never edit
        # installed service.py or previously published sidecars.
        if main.s is not service:
            raise RuntimeError('Unexpected different SubHub service modules')
        original_publisher=service.publish_job
        def guarded_publish(active_store,active_job,apply=False):
            if active_job['id']!=job_id:
                raise RuntimeError('Publication scope widened beyond selected job')
            if apply and gate.is_american_dad(active_job['video']):
                _video,rows=service.validate_publish(active_store,active_job)
                report=gate.assert_publishable(rows)
                print('JA_READABILITY_GATE_PASS',job_id,
                      'cues',report['cues_checked'],
                      'speed_warnings',report['warnings'].get('fast',0),
                      flush=True)
            return original_publisher(active_store,active_job,apply=apply)
        try:
            service.publish_job=guarded_publish
            work(store,base or HOST_CODE,root,args)
        finally:
            service.publish_job=original_publisher
        current=store.jobs()[0]
        status=current['status']
        print('DAILY_SINGLE_JOB_RESULT',job_id,status,
              str(current['ja'])+'/'+str(current['n']),'cues',
              flush=True)
        return status
    finally:
        store.cn.close()


def main_cli(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--job-id',required=True)
    args=parser.parse_args(argv)
    try:
        run_one(args.root,args.job_id)
    except Exception as exc:
        print('DAILY_SINGLE_JOB_BLOCKED',type(exc).__name__,
              str(exc)[:130] if isinstance(exc,(RuntimeError,ValueError))
              else '',file=sys.stderr)
        return 1
    return 0


if __name__=='__main__':
    raise SystemExit(main_cli())
