#!/usr/bin/env python3
"""Finish *requested* American Dad seasons, not arbitrary library movies.

Uses only the EXISTING SubHub 1.0 Gemma translator + cue checkpoints +
create-only sidecar publisher. Default Season 8; --seasons 8 9 for two.
No fresh translation model, dual-subs work, or hardcoded S19 experiments.

PLAN is read-only. START launches an isolated, bounded, detached batch process.
RUN sequentially processes only matched, eligible episodes of those seasons;
skips already-JA, existing queued legacy jobs, and unusable English sources.
Repeat START to resume unfinished daily-* jobs via existing cue checkpoints.

No scene/dialogue printed to terminal; no media files are modified.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import contextlib
import fcntl
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import time

try:
    import daily_japanese as intake
    import daily_worker
except ModuleNotFoundError:
    from tools import daily_japanese as intake, daily_worker
import service

DEFAULT_ROOT=intake.DEFAULT_STATE
SHOW=re.compile(r'american[\s._!()-]*dad',re.I)
SXXEXX=re.compile(r'(?<![a-z0-9])s(\d{1,2})[\s._-]*e(\d{1,3})(?!\d)',re.I)
XXxYY=re.compile(r'(?<!\d)(\d{1,2})x(\d{1,3})(?!\d)',re.I)
ACTIVE={'queued','translating','translated'}
HELD={'needs_review','hold','publish_hold'}
DEFAULT_MINUTES=480
DEFAULT_EPISODES=50


def validate_seasons(values):
    seasons=tuple(int(x) for x in values)
    if not 1<=len(seasons)<=2 or len(set(seasons))!=len(seasons):
        raise ValueError('Choose one or two distinct seasons')
    if not all(1<=x<=40 for x in seasons):
        raise ValueError('Season numbers must be 1..40')
    return seasons


def title(s,e):
    return 'S%02dE%02d'%(s,e)


def discover(roots,seasons,iter_videos=intake.video_files):
    """Match show + episode tag from actual filename; never invent episodes."""
    seasons=validate_seasons(seasons)
    results=defaultdict(list)
    for video in iter_videos(roots):
        if not SHOW.search(str(video)):
            continue
        match=SXXEXX.search(video.name) or XXxYY.search(video.name)
        if not match:
            continue
        season,ep=int(match[1]),int(match[2])
        if season in seasons and 1<=ep<=100:
            results[(season,ep)].append(video)
    return {key:sorted(val,key=str) for key,val in sorted(results.items())}


def queue_jobs(root):
    """Read the existing WAL snapshot without opening a writeable Store."""
    path=Path(root)/'jobs.sqlite3'
    if path.is_symlink():
        raise RuntimeError('Unsafe queue database symlink')
    if not path.is_file():
        return {}
    with sqlite3.connect('file:'+str(path)+'?mode=ro',
                         uri=True,timeout=10) as cn:
        cn.row_factory=sqlite3.Row
        rows=cn.execute(
            'SELECT j.id,j.video,j.status,j.source_cues,'
            '(SELECT COUNT(*) FROM cues c WHERE c.job_id=j.id '
            'AND c.japanese IS NOT NULL) ja FROM jobs j').fetchall()
    return {r['video']:dict(r) for r in rows}


def inspect(copies,known,fetch=False,
            probe_fn=intake.probe,source_fn=intake.source):
    """Avoid redundant JA across ANY copy, including embedded tracks.

    Scan ALL copies for existing JA before selecting one English source:
    otherwise a first English copy could hide a second already-Japanese copy.
    """
    for video in copies:
        if intake.already_ja(video):
            return {'kind':'already_japanese','video':video}
    metadata={}
    rejection=Counter()
    for video in copies:
        try:
            info=probe_fn(video)
            metadata[video]=info
            if info.get('ja'):
                return {'kind':'already_japanese_embedded','video':video}
        except (OSError,ValueError,RuntimeError,
                subprocess.SubprocessError,UnicodeError):
            rejection['source_or_metadata_error']+=1
    # Avoid translating alternate copies when any is already published.
    for video in copies:
        job=known.get(str(video))
        if job and job['status']=='published':
            return {'kind':'existing_job','video':video,'job':job}
    for video in copies:
        job=known.get(str(video))
        if job:
            return {'kind':'existing_job','video':video,'job':job}
    for video,info in metadata.items():
        try:
            if not info.get('audio_en'):
                rejection['audio_not_verified_english']+=1
                continue
            if not intake.english_srt(video) and info.get('embedded_en') is None:
                rejection['no_english_text']+=1
                continue
            if not fetch:
                return {'kind':'eligible','video':video}
            raw,n,origin=source_fn(video,info)
            st=video.stat()
            return {
                'kind':'ready','video':video,'raw':raw,'cues':n,
                'origin':origin,'size':st.st_size,'mtime_ns':st.st_mtime_ns,
                'source_sha':intake.digest(raw),'id':intake.job_id(video)}
        except (OSError,ValueError,RuntimeError,
                subprocess.SubprocessError,UnicodeError):
            rejection['source_or_metadata_error']+=1
    return {'kind':'needs_english_or_review',
            'reasons':dict(rejection)}

@contextlib.contextmanager
def campaign_lock(root):
    root=Path(root)
    root.mkdir(parents=True,exist_ok=True,mode=0o700)
    path=root/'american-dad-seasons.lock'
    if path.is_symlink():
        raise RuntimeError('Unsafe season campaign lock path')
    with path.open('a+b') as handle:
        try:
            fcntl.flock(handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError('An American Dad season campaign is already active') from exc
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(),fcntl.LOCK_UN)


def plan(roots,root,seasons,probe_fn=intake.probe,
         iter_videos=intake.video_files,print_fn=print):
    catalog=discover(roots,seasons,iter_videos)
    known=queue_jobs(root)
    counts=Counter()
    for (season,ep),copies in catalog.items():
        result=inspect(copies,known,fetch=False,probe_fn=probe_fn)
        what=result['kind']
        if what=='existing_job':
            what='existing_job_'+result['job']['status']
        counts[what]+=1
        print_fn('SEASON_PLAN',title(season,ep),what,'copies',len(copies))
    print_fn('SEASON_PLAN_SUMMARY',json.dumps({
        'requested_seasons':list(seasons),'found_episode_ids':len(catalog),
        'categories':dict(sorted(counts.items()))},sort_keys=True))
    return counts


def single_episode(key,copies,roots,root,known,
                   probe_fn=intake.probe,source_fn=intake.source,
                   translate=daily_worker.run_one,print_fn=print):
    tag=title(*key)
    record=inspect(copies,known,fetch=True,
                   probe_fn=probe_fn,source_fn=source_fn)
    kind=record['kind']
    if kind in ('already_japanese','already_japanese_embedded'):
        print_fn('SEASON_SKIP',tag,'japanese_already_available')
        return 'already_japanese'
    if kind=='existing_job':
        previous=record['job']
        state=previous['status']
        if state=='published':
            print_fn('SEASON_SKIP',tag,'published')
            return 'published'
        if not previous['id'].startswith('daily-'):
            print_fn('SEASON_REVIEW',tag,'previous_non_daily_job_not_overridden')
            return 'existing_other_queue'
        if state in HELD:
            print_fn('SEASON_REVIEW',tag,state,
                     str(previous['ja'])+'/'+str(previous['source_cues']))
            return state
        if state not in ACTIVE:
            print_fn('SEASON_REVIEW',tag,'unrecognized_job_state')
            return 'unrecognized_job_state'
        job_id=previous['id']
    elif kind=='ready':
        print_fn('SEASON_SOURCE',tag,record['cues'],
                 'english_cues',record['origin'])
        if not intake.queue_one(record,roots,root,probe_fn=probe_fn):
            print_fn('SEASON_REVIEW',tag,'queue_changed_during_import')
            return 'existing_other_queue'
        job_id=record['id']
        print_fn('SEASON_QUEUED',tag,job_id)
    else:
        print_fn('SEASON_NEEDS_SOURCE',tag,kind,
                 json.dumps(record.get('reasons',{}),sort_keys=True))
        return kind
    # Existing SubHub 1.0 worker, but the in-process filter permits
    # only this job; unrelated movies and other seasons cannot be touched.
    result=translate(root,job_id)
    print_fn('SEASON_RESULT',tag,result)
    return result


def execute(roots,root,seasons,max_episodes=DEFAULT_EPISODES,
            minutes=DEFAULT_MINUTES,probe_fn=intake.probe,
            source_fn=intake.source,translate=daily_worker.run_one,
            iter_videos=intake.video_files,print_fn=print,
            clock=time.monotonic):
    roots=intake.ensure_roots(roots)
    seasons=validate_seasons(seasons)
    if not 1<=max_episodes<=60 or not 1<=minutes<=720:
        raise ValueError('Unsafe episode/time budget')
    deadline=clock()+minutes*60
    finished=0
    outcomes=Counter()
    catalog=discover(roots,seasons,iter_videos)
    print_fn('SEASON_STARTED',','.join(str(x) for x in seasons),
             'episodes_found',len(catalog),'max_episode_attempts',max_episodes,
             'max_minutes',minutes)
    with campaign_lock(root):
        for key,copies in catalog.items():
            if clock()>deadline or (Path(root)/'PAUSE').exists():
                outcomes['paused_or_out_of_time']+=1
                break
            if finished>=max_episodes:
                outcomes['budget_exhausted']+=1
                break
            known=queue_jobs(root) # Never reuse stale status after a job.
            # Avoid consuming the episode budget on skips.
            will_run=inspect(copies,known,fetch=False,probe_fn=probe_fn)
            if will_run['kind']=='eligible':
                finished+=1
            elif will_run['kind']=='existing_job' and (
                    will_run['job']['status'] in ACTIVE and
                    will_run['job']['id'].startswith('daily-')):
                finished+=1
            try:
                state=single_episode(key,copies,roots,root,known,
                                     probe_fn=probe_fn,source_fn=source_fn,
                                     translate=translate,print_fn=print_fn)
            except Exception as exc:
                # Underlying preflight/lock/thermal failures are NOT a reason
                # to run more GPU jobs or conceal the failure.
                print_fn('SEASON_INTERRUPTED',title(*key),type(exc).__name__)
                outcomes['interrupted']+=1
                break
            outcomes[state]+=1
            # Timeout/thermal/idle means resume this episode next session;
            # do not automatically run the next one.
            if state in ACTIVE or state=='publish_hold':
                # Do not translate 21 more episodes after one finished JA
                # episode failed the readability gate. Preserve its complete
                # SQLite cue checkpoints for isolated editorial correction.
                print_fn('SEASON_DEFERRED',title(*key),state)
                break
    summary={'seasons':list(seasons),'episode_ids_found':len(catalog),
             'episode_attempts':finished,'outcomes':dict(sorted(outcomes.items()))}
    print_fn('SEASON_SUMMARY',json.dumps(summary,sort_keys=True))
    return summary


def start_background(root,seasons,max_episodes,minutes,
                     script=Path(__file__).resolve(),launcher=None):
    root=Path(root)
    if not 1<=max_episodes<=60 or not 1<=minutes<=720:
        raise ValueError('Unsafe episode/time budget')
    root.mkdir(parents=True,exist_ok=True,mode=0o700)
    # Refuse a duplicate running campaign immediately, rather than
    # spawning a process only to have its campaign lock fail.
    with campaign_lock(root):
        pass
    log=root/'american-dad-seasons.log'
    cmd=[sys.executable,str(script),'--root',str(root),
         'run','--seasons',*(str(x) for x in seasons),
         '--max-episodes',str(max_episodes),'--max-minutes',str(minutes)]
    with log.open('a',encoding='utf8') as out:
        out.write('\n=== '+service.stamp()+'; seasons '
                  +','.join(str(x) for x in seasons)+' ===\n')
        out.flush()
        if launcher is None:
            proc=subprocess.Popen(cmd,stdin=subprocess.DEVNULL,
                 stdout=out,stderr=subprocess.STDOUT,start_new_session=True,
                 cwd=str(Path(script).parent))
        else:
            proc=launcher(cmd,out)
    return {'pid':proc.pid,'log':str(log)}


def cli(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=DEFAULT_ROOT)
    parser.add_argument('--media-root',type=Path,action='append',default=None)
    sub=parser.add_subparsers(dest='action',required=True)
    for action in ('plan','start','run'):
        p=sub.add_parser(action)
        p.add_argument('--seasons',type=int,nargs='+',default=[8])
        if action!='plan':
            p.add_argument('--max-episodes',type=int,default=DEFAULT_EPISODES)
            p.add_argument('--max-minutes',type=int,default=DEFAULT_MINUTES)
    p=sub.add_parser('status')
    p.add_argument('--seasons',type=int,nargs='+',default=[8])
    args=parser.parse_args(argv)
    try:
        seasons=validate_seasons(args.seasons)
        roots=intake.ensure_roots(args.media_root or service.SOURCE_ROOTS)
        if args.action in ('plan','status'):
            plan(roots,args.root,seasons)
        elif args.action=='start':
            print('SEASON_LAUNCHED',json.dumps(start_background(
                args.root,seasons,args.max_episodes,args.max_minutes),
                sort_keys=True))
        else:
            execute(roots,args.root,seasons,args.max_episodes,args.max_minutes)
    except Exception as exc:
        # Avoid printing paths and private dialogue from unexpected exceptions.
        print('SEASON_BLOCKED',type(exc).__name__,file=sys.stderr)
        return 1
    return 0


if __name__=='__main__':
    raise SystemExit(cli())
