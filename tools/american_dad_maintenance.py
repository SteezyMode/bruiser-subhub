#!/usr/bin/env python3
"""Conservative American Dad watchability maintenance: one ASR then Gemma.

Executed once immediately by optional user-service, then nightly. Scans real
file coverage; selects the best viable season, or falls back to a source-poor
season (S08 if present). A selected season remains sticky until completed.
At most ONE CPU-only English transcription per run; existing multi-episode
Gemma campaign remains bounded and resumes checkpoints, never unrelated media.
An ASR failure cannot overwrite anything or create an infinite retry storm.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

try:
    import daily_japanese as intake
    import american_dad_seasons as seasons
    import american_dad_autopilot as auto
except ModuleNotFoundError:
    from tools import daily_japanese as intake
    from tools import american_dad_seasons as seasons
    from tools import american_dad_autopilot as auto

FAILED='american-dad-asr-retry.json'
ASR_ENV=Path.home()/'bruiser-pilot/american-dad-asr-venv/bin/python'
ASR_SCRIPT=Path(__file__).resolve().parent/'english_asr_fallback.py'
ASR_COOLDOWN=3*86400


def fallback(coverage):
    """If no season has EN, prefer original S08; never choose absent season."""
    existing=[x for x in coverage if x['total']>=6 and x['blocked']>=1]
    if not existing:return None
    first=next((x for x in existing if x['season']==8),None)
    if first:return first
    return sorted(existing,key=lambda x:(
        -x['viewable_with_translation'],-x['total'],x['season']))[0]


def choose_and_persist(coverage,root):
    selected,reason=auto.select(coverage,root,save=False)
    if not selected:
        selected=fallback(coverage)
        reason='no_provider_sources_fallback_s08' if selected else 'none'
    if selected and selected['season']!=auto.current(root):
        auto.persist_choice(root,selected['season'],reason)
    return selected,reason


def failure_path(root):
    return Path(root)/FAILED


def failures(root):
    path=failure_path(root)
    if path.is_symlink():raise RuntimeError('Unsafe failure state')
    if not path.is_file():return {}
    data=json.loads(path.read_text(encoding='utf8'))
    return data if isinstance(data,dict) else {}


def record_failure(root,video,now):
    path=failure_path(root)
    state=failures(root)
    key=hashlib.sha256(str(video.resolve()).encode('utf8')).hexdigest()
    state[key]=now+ASR_COOLDOWN
    tmp=path.with_name(path.name+'.tmp-'+str(os.getpid()))
    with tmp.open('x',encoding='utf8') as out:
        os.chmod(tmp,0o600)
        json.dump(state,out,sort_keys=True)
        out.write('\n')
        out.flush()
        os.fsync(out.fileno())
    os.replace(tmp,path)


def next_missing(catalog,selected,root,now,probe_fn=intake.probe):
    cooldown=failures(root)
    jobs=seasons.queue_jobs(root)
    for (s,e),copies in catalog.items():
        if s!=selected:continue
        classified=auto.classify(copies,jobs,probe_fn=probe_fn)
        if classified!='needs_english_or_review':
            continue
        for video in copies:
            key=hashlib.sha256(str(video.resolve()).encode('utf8')).hexdigest()
            if cooldown.get(key,0)>now:
                continue
            if intake.already_ja(video) or intake.english_srt(video):
                continue
            try:
                info=probe_fn(video)
                if info.get('ja') or not info.get('audio_en'):
                    continue
                if info.get('embedded_en') is not None:
                    continue
                intake.service.secure_video(video)
            except (OSError,RuntimeError,ValueError,subprocess.SubprocessError):
                continue
            return (s,e),video
    return None


def asr_subprocess(video,executable=ASR_ENV,script=ASR_SCRIPT,
                   runner=subprocess.run,log=print):
    if not Path(executable).is_file():
        log('ASR_UNAVAILABLE','isolated_python_environment_missing')
        return False
    cmd=[str(executable),str(script),'--video',str(video)]
    try:
        proc=runner(cmd,capture_output=True,text=True,timeout=7200)
    except (OSError,subprocess.SubprocessError):
        log('ASR_ERROR','worker_failed_or_timed_out')
        return False
    # Never log media paths or raw speech from subprocess.
    status='published_en_draft' if proc.returncode==0 and (
        'ASR_READY' in proc.stdout) else 'blocked'
    log('ASR_WORKER',status)
    return status=='published_en_draft'


def run_once(roots,root,now=None,iter_videos=intake.video_files,
             probe_fn=intake.probe,asr_run=asr_subprocess,
             launch=seasons.start_background,log=print):
    """Do not overlap with active season worker, pause marker or a second self."""
    now=int(now or time.time())
    root=Path(root)
    root.mkdir(mode=0o700,parents=True,exist_ok=True)
    if (root/'PAUSE').exists():
        log('AUTO_MAINTENANCE_PAUSED','owner_pause_marker')
        return 'paused'
    with seasons.campaign_lock(root):
        covers=auto.coverage(roots,root,iter_videos=iter_videos,
                             probe_fn=probe_fn,log=log)
        chosen,why=choose_and_persist(covers,root)
        if chosen is None:
            log('AUTO_MAINTENANCE_NO_SEASON','no_tagged_unfinished_seasons')
            return 'no_season'
        s=chosen['season']
        log('AUTO_MAINTENANCE_SELECTION','S%02d'%s,'reason',why,
            'ready',chosen['new'],'resume',chosen['resume'],
            'missing',chosen['blocked'])
        catalog=auto.discover(roots,iter_videos=iter_videos)
        candidate=next_missing(catalog,s,root,now,probe_fn=probe_fn)
        if candidate:
            episode,video=candidate
            log('ASR_CANDIDATE','S%02dE%02d'%episode,
                'cpu_only','max_this_run',1)
            # Hold the season lock through ASR to avoid concurrent Gemma jobs.
            success=asr_run(video)
            if not success:
                record_failure(root,video,now)
                log('ASR_DEFERRED','S%02dE%02d'%episode,
                    'retry_after_days',3)
            else:
                log('ASR_SOURCE_READY','S%02dE%02d'%episode)
        # Refresh availability after possible ASR; skips all already-published JA.
        updated=auto.coverage(roots,root,iter_videos=iter_videos,
                              probe_fn=probe_fn,log=lambda *x:None)
        active=next((c for c in updated if c['season']==s),None)
        ready=active and (active['new']+active['resume'])
    # Release lock BEFORE invoking start_background, which takes it itself.
    if ready:
        try:
            job=launch(root,(s,),50,480)
            log('AUTO_MAINTENANCE_TRANSLATION_STARTED',json.dumps(job,sort_keys=True))
            return 'started'
        except (RuntimeError,OSError) as exc:
            log('AUTO_MAINTENANCE_TRANSLATION_HELD',type(exc).__name__)
            return 'deferred'
    log('AUTO_MAINTENANCE_NO_ENGLISH','waiting_for_verified_source')
    return 'no_english'


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,default=intake.DEFAULT_STATE)
    p.add_argument('--media-root',type=Path,action='append',default=None)
    args=p.parse_args(argv)
    try:
        roots=intake.ensure_roots(args.media_root or intake.service.SOURCE_ROOTS)
        result=run_once(roots,args.root)
        print('AUTO_MAINTENANCE_RESULT',result,flush=True)
    except Exception as exc:
        # Active translation lock is a normal condition, not an error storm.
        if isinstance(exc,RuntimeError) and 'campaign' in str(exc).lower():
            print('AUTO_MAINTENANCE_DEFERRED','existing_worker_active')
            return 0
        print('AUTO_MAINTENANCE_BLOCKED',type(exc).__name__,file=sys.stderr)
        return 1
    return 0


if __name__=='__main__':
    os.umask(0o077)
    raise SystemExit(main())
