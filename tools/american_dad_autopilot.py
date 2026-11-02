#!/usr/bin/env python3
"""Find the genuinely watchable American Dad season, then use existing Gemma.

Never assume a season number or that Jellyfin has English subtitles.
Inspect real video and source tracks across all seasons. Prefer seasons with
the highest complete viewing coverage and at least 3 translation candidates.
One bounded, resumable season campaign; no unrelated films or new prompts.
If no viable source season exists, stop with a specific fallback recommendation.

Read-only plan is default. The --start action persists a selected season and
uses the already deployed season runner; this does not run an ASR model.
"""
from __future__ import annotations

import argparse
from collections import Counter,defaultdict
from datetime import datetime,timezone
import json
from pathlib import Path
import os
import re
import sys

try:
    import american_dad_seasons as seasons
    import daily_japanese as intake
except ModuleNotFoundError:
    from tools import american_dad_seasons as seasons, daily_japanese as intake

SELECTION='american-dad-auto-selection.json'
TRANSLATABLE={'eligible','resume_daily'}
ALREADY={'already_japanese','already_japanese_embedded','existing_job_published'}
MIN_NEW_EPISODES=3
MIN_COVERAGE_EPISODES=6


def discover(roots,iter_videos=intake.video_files):
    """Scan filesystem once, identify actual tagged episodes, not metadata guesses."""
    catalog=defaultdict(list)
    for video in iter_videos(roots):
        if not seasons.SHOW.search(str(video)):
            continue
        tag=seasons.SXXEXX.search(video.name) or seasons.XXxYY.search(video.name)
        if not tag:continue
        s,e=int(tag[1]),int(tag[2])
        if 1<=s<=40 and 1<=e<=100:
            catalog[(s,e)].append(video)
    return {key:sorted(files,key=str) for key,files in sorted(catalog.items())}


def classify(copies,known,probe_fn=intake.probe):
    result=seasons.inspect(copies,known,fetch=False,probe_fn=probe_fn)
    kind=result['kind']
    if kind=='existing_job':
        job=result['job']
        if job['status']=='published':
            return 'existing_job_published'
        if job['status'] in seasons.ACTIVE and job['id'].startswith('daily-'):
            return 'resume_daily'
        return 'held_legacy_job'
    return kind


def coverage(roots,root,iter_videos=intake.video_files,
             probe_fn=intake.probe,log=print):
    catalog=discover(roots,iter_videos)
    known=seasons.queue_jobs(root)
    by_season=defaultdict(Counter)
    for (season,episode),copies in catalog.items():
        reason=classify(copies,known,probe_fn)
        by_season[season][reason]+=1
        by_season[season]['found']+=1
    results=[]
    for season,counts in sorted(by_season.items()):
        ready=sum(counts.get(x,0) for x in TRANSLATABLE)
        previous=sum(counts.get(x,0) for x in ALREADY)
        total=counts['found']
        results.append({
            'season':season,'total':total,'new':counts.get('eligible',0),
            'resume':counts.get('resume_daily',0),
            'already_japanese':previous,
            'blocked':total-ready-previous,
            'viewable_with_translation':ready+previous,
            'coverage_pct':round(100*(ready+previous)/total,1),
        })
    log('AUTO_SEASON_COVERAGE',json.dumps(results,sort_keys=True))
    return results


def rank(choices,min_new=MIN_NEW_EPISODES,min_viewable=MIN_COVERAGE_EPISODES):
    viable=[c for c in choices
            if c['new']+c['resume']>=min_new and
               c['viewable_with_translation']>=min_viewable]
    if not viable:return None
    # Prefer an entire usable season, not a long partial season with more
    # isolated episodes. Among similarly complete seasons, maximize new work.
    viable.sort(key=lambda c:(
        c['viewable_with_translation']/c['total'],
        c['viewable_with_translation'],
        c['new']+c['resume'],
        -c['season']
    ),reverse=True)
    return viable[0]


def choice_file(root):
    return Path(root)/SELECTION


def current(root):
    path=choice_file(root)
    if not path.is_file() or path.is_symlink():
        return None
    try:
        data=json.loads(path.read_text(encoding='utf8'))
        if data.get('schema')==1 and isinstance(data.get('season'),int):
            if 1<=data['season']<=40:
                return data['season']
    except (OSError,ValueError):
        return None
    return None


def select(choices,root,save=False):
    old=current(root)
    sticky=next((c for c in choices if c['season']==old),None)
    # Keep an in-progress season selected, even if only 1 last episode is
    # outstanding, until finished. Don't bounce between seasons on reruns.
    if sticky and sticky['new']+sticky['resume']>=1:
        selected=sticky
        why='resume_selected_season'
    else:
        selected=rank(choices)
        why='best_real_english_coverage' if selected else 'no_viable_season'
    if selected and save:
        root=Path(root)
        root.mkdir(mode=0o700,parents=True,exist_ok=True)
        path=choice_file(root)
        if path.is_symlink():raise RuntimeError('Unsafe selection path')
        data={'schema':1,'season':selected['season'],
              'selected_utc':datetime.now(timezone.utc).isoformat(),
              'reason':why}
        temporary=path.with_name(path.name+'.tmp-'+str(os.getpid()))
        flags=os.O_WRONLY|os.O_CREAT|os.O_EXCL
        fd=os.open(temporary,flags,0o600)
        try:
            with os.fdopen(fd,'w',encoding='utf8') as handle:
                json.dump(data,handle,sort_keys=True)
                handle.write('\n')
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary,path)
        finally:
            temporary.unlink(missing_ok=True)
    return selected,why


def autopilot(roots,root,start=False,iter_videos=intake.video_files,
              probe_fn=intake.probe,launcher=seasons.start_background,
              log=print):
    results=coverage(roots,root,iter_videos,probe_fn,log)
    selection,why=select(results,root,save=start)
    if selection:
        log('AUTO_SEASON_SELECTED',json.dumps({
            'season':selection['season'],'reason':why,
            'ready_new':selection['new'],
            'resume':selection['resume'],
            'already_japanese':selection['already_japanese'],
            'coverage_pct':selection['coverage_pct'],
            'missing':selection['blocked']},sort_keys=True))
        if start:
            if selection['new']+selection['resume']<=0:
                log('AUTO_SEASON_NOT_STARTED','already_fully_translated')
            else:
                job=launcher(root,(selection['season'],),50,480)
                log('AUTO_SEASON_TRANSLATION_STARTED',json.dumps(job,sort_keys=True))
    else:
        log('AUTO_SEASON_NOT_STARTED','no_viable_existing_english_season',
            'next_step','local_english_audio_transcription')
    return selection


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,default=intake.DEFAULT_STATE)
    p.add_argument('--media-root',action='append',type=Path,default=None)
    p.add_argument('--start',action='store_true')
    args=p.parse_args(argv)
    try:
        roots=intake.ensure_roots(args.media_root or intake.service.SOURCE_ROOTS)
        autopilot(roots,args.root,start=args.start)
    except Exception as exc:
        print('AUTO_SEASON_BLOCKED',type(exc).__name__,file=sys.stderr)
        return 1
    return 0


if __name__=='__main__':
    raise SystemExit(main())
