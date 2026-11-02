#!/usr/bin/env python3
"""Five-episode American Dad viewing pilot, separate from the production worker.

Freeze English sources, run locally, resume at cue boundaries, publish only
complete CREATE-ONLY pilot SRTs alongside approved media. No database edits.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import time

import service
try:
    import american_dad_intake_009 as intake
    import american_dad_core_009 as core
except ModuleNotFoundError:
    from tools import american_dad_intake_009 as intake
    from tools import american_dad_core_009 as core

SCHEMA='american-dad-viewing-pilot-009-v1'


def freeze(episodes=5,roots=intake.ROOTS,state=core.STATE,profile=core.PROFILE):
    state=Path(state)
    manifest=state/'manifest.json'
    profile_sha=intake.sha(Path(profile).read_bytes())
    if manifest.exists():
        old=core.load(manifest)
        if (old.get('schema')!=SCHEMA or old.get('model')!=core.MODEL
            or old.get('model_id')!=core.MODEL_ID
            or old.get('profile_sha')!=profile_sha or old.get('limit')!=episodes):
            raise RuntimeError('Pilot manifest identity changed; refuse resume')
        return old
    candidates,skips=intake.catalog(roots,episodes)
    if not candidates:
        raise RuntimeError('No eligible American Dad episodes: '+json.dumps(skips)[:800])
    selected=[]
    for candidate in candidates:
        entry=dict(candidate)
        raw=entry.pop('raw')
        source=state/'episodes'/entry['episode']/'source.en.srt'
        if source.exists():
            if intake.sha(source.read_bytes())!=entry['source_sha']:
                raise RuntimeError('Frozen private English source differs')
        else:
            core.create(source,raw)
        entry['source_path']=str(source)
        selected.append(entry)
    result={'schema':SCHEMA,'model':core.MODEL,'model_id':core.MODEL_ID,
            'profile_sha':profile_sha,'limit':episodes,
            'episodes':selected,'skipped':skips}
    core.save(manifest,result)
    print('FROZEN',len(selected),'American Dad episodes',
          [(x['episode'],x['count']) for x in selected],flush=True)
    if len(selected)<episodes:
        print('Only',len(selected),'episodes eligible; no invented titles',flush=True)
    return result


def verify(entry,roots=intake.ROOTS):
    video=Path(entry['video'])
    if not intake.safe_video(video,roots):
        raise RuntimeError('Unsafe or missing video')
    st=video.stat()
    if st.st_size!=entry['video_size'] or st.st_mtime_ns!=entry['video_mtime_ns']:
        raise RuntimeError('Original video changed since frozen intake')
    if intake.existing_ja(video):
        raise RuntimeError('Already has Japanese sidecar; cannot publish')
    track=intake.tracks(video)
    if track!=entry['track']:
        raise RuntimeError('Subtitle stream/audio changed after intake')
    current_english,_=intake.extract(video,track)
    if intake.sha(current_english)!=entry['source_sha']:
        raise RuntimeError('Original English subtitles changed since intake')
    data=Path(entry['source_path']).read_bytes()
    if intake.sha(data)!=entry['source_sha']:
        raise RuntimeError('Frozen source SHA changed')
    rows=service.parse_srt(data)
    if len(rows)!=entry['count']:
        raise RuntimeError('Frozen English cue count changed')
    return video,rows


def translate(entry,curated,series_note,state=core.STATE,roots=intake.ROOTS,
              ask=core.call,publish=False,deadline=None):
    state=Path(state)
    episode=entry['episode']
    folder=state/'episodes'/episode
    video=Path(entry['video'])
    dest=intake.pilot_path(video)
    if dest.is_file() or dest.is_symlink() or dest.exists():
        draft=folder/'pilot.ja.srt'
        if not dest.is_symlink() and dest.is_file() and draft.is_file() and dest.read_bytes()==draft.read_bytes():
            return {'episode':episode,'state':'already_published_identical'}
        raise RuntimeError('Existing Japanese pilot file differs: do not replace')
    video,rows=verify(entry,roots)
    episode_note=core.note('title','American Dad '+episode,
                           [Path(entry['source_path'])],state,ask)
    previous=[]
    accepted={}
    failures=0
    for index,row in enumerate(rows):
        cue_id,_,_,_,english=row
        folder_cues=folder/'cues'
        good=folder_cues/('%05d.json'%cue_id)
        if good.is_file():
            item=core.load(good)
            if (item.get('cue_id')!=cue_id or item.get('source_sha')!=entry['source_sha']
                or item.get('model_id')!=core.MODEL_ID or not item.get('valid')):
                raise RuntimeError('Existing checkpoint incompatible or invalid')
        else:
            if deadline is not None and time.monotonic()>=deadline:
                break
            item=None
            # Attempts 1-2: original frozen pilot prompt.
            # Attempts 3-6: smaller, context-light rescue prompts.
            # Each attempt is create-only and prior failures are retained.
            # Resuming after the first full run skips 1-2 and works ONLY
            # on cues with no accepted Japanese checkpoint.
            for attempt in (1,2,3,4,5,6):
                error_file=folder/'errors'/('%05d-%d.json'%(cue_id,attempt))
                if error_file.exists():
                    continue
                if deadline is not None and time.monotonic()>=deadline:
                    break
                started=time.monotonic()
                text=None
                error=None
                try:
                    request=(core.prompt(rows,index,previous,curated,
                                          core.note_text(series_note),
                                          core.note_text(episode_note))
                             if attempt<=2
                             else core.recovery_prompt(rows,index,previous,attempt))
                    text=ask(request)
                    if not core.valid(text,english):
                        error='Invalid Japanese/format'
                except Exception as exc:
                    error=type(exc).__name__+': '+str(exc)[:180]
                if error is None:
                    item={'cue_id':cue_id,'source_sha':entry['source_sha'],
                          'model_id':core.MODEL_ID,'japanese':text,
                          'valid':True,'seconds':round(time.monotonic()-started,2),
                          'attempt':attempt}
                    core.save(good,item)
                    if attempt>2:
                        print('RECOVERED',episode,'cue',cue_id,
                              'on rescue attempt',attempt,flush=True)
                    break
                core.save(error_file,{'cue_id':cue_id,'error':error,
                                      'reply':text})
            if item is None:
                failures+=1
                if failures>=12:
                    print('STOP',episode,'12 failed cues; no publication',flush=True)
                    break
                continue
        accepted[str(cue_id)]=item['japanese']
        previous.append(item['japanese'])
        if index%100==0 or index+1==len(rows):
            print(episode,str(index+1)+'/'+str(len(rows)),
                  'unaccepted='+str(failures),flush=True)
    if len(accepted)!=len(rows):
        # No copyrighted dialogue, only numerical cue identifiers. This
        # makes a future owner log actionable without private-file archaeology.
        remaining=[row[0] for row in rows if str(row[0]) not in accepted]
        return {'episode':episode,'state':'incomplete',
                'accepted':len(accepted),'expected':len(rows),
                'missing_cue_ids':remaining[:20],
                'missing_total':len(remaining)}
    output=service.render_srt(rows,accepted)
    draft=folder/'pilot.ja.srt'
    if draft.exists():
        if draft.read_bytes()!=output:
            raise RuntimeError('Private draft differs from stored accepted cues')
    else:
        core.create(draft,output)
    if not publish:
        return {'episode':episode,'state':'complete_private_draft',
                'accepted':len(rows)}
    verify(entry,roots)
    if dest.exists() or dest.is_symlink():
        raise RuntimeError('Japanese pilot target appeared; no overwrite')
    core.create(dest,output,mode=0o644)
    return {'episode':episode,'state':'published_new_pilot',
            'accepted':len(rows),'sidecar_name':dest.name}


def run(episodes=5,publish=False,minutes=420,state=core.STATE,
        roots=intake.ROOTS,profile=core.PROFILE,ask=core.call,base=core.BASE):
    manifest=freeze(episodes,roots,state,profile)
    curated=Path(profile).read_text(encoding='utf8')
    deadline=time.monotonic()+minutes*60
    finished=[]
    with core.locks(base):
        if ask is core.call:
            core.preflight()
        series=core.note('series','American Dad',
                         [Path(x['source_path']) for x in manifest['episodes'][:3]],
                         state,ask)
        for entry in manifest['episodes']:
            if time.monotonic()>=deadline:
                print('Wall budget reached; private cue checkpoints retained',flush=True)
                break
            try:
                result=translate(entry,curated,series,state,roots,ask,publish,deadline)
            except Exception as exc:
                result={'episode':entry['episode'],'state':'held',
                        'reason':type(exc).__name__+': '+str(exc)[:230]}
            finished.append(result)
            print('EPISODE_RESULT',json.dumps(result,ensure_ascii=False),flush=True)
    print('PILOT_SUMMARY',json.dumps(finished,ensure_ascii=False),flush=True)
    return finished


def status(state=core.STATE):
    manifest=Path(state)/'manifest.json'
    if not manifest.exists():
        return {'status':'not_prepared'}
    data=core.load(manifest)
    episodes=[]
    for entry in data['episodes']:
        folder=Path(state)/'episodes'/entry['episode']/'cues'
        done=len(list(folder.glob('*.json'))) if folder.is_dir() else 0
        episodes.append({'episode':entry['episode'],'accepted':done,
                         'total':entry['count'],'pilot_exists':
                         intake.pilot_path(Path(entry['video'])).is_file()})
    return {'model':data['model'],'episodes':episodes}


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=('prepare','run','status'))
    p.add_argument('--episodes',type=int,default=5)
    p.add_argument('--publish',action='store_true')
    p.add_argument('--minutes',type=int,default=420)
    args=p.parse_args(argv)
    if not 1<=args.episodes<=12 or not 1<=args.minutes<=1440:
        p.error('Episodes 1..12, minutes 1..1440')
    if args.action=='prepare':
        freeze(args.episodes)
    elif args.action=='status':
        print(json.dumps(status(),ensure_ascii=False,indent=2))
    else:
        run(args.episodes,args.publish,args.minutes)
    return 0


if __name__=='__main__':
    raise SystemExit(main())
