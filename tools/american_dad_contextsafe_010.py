#!/usr/bin/env python3
"""Second American Dad viewing pilot using a reusable cue-isolation quality gate.

Fresh previously untranslated episodes ONLY. No changes to pilot 009 state,
media videos, approved SRTs, or production SubHub database/service.
Produces new create-only ContextSafe v2 Japanese sidecars after full QA.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import time

import service
try:
    import american_dad_intake_009 as intake
    import american_dad_core_009 as core
    import american_dad_pilot_009 as old
    import subtitle_quality_010 as quality
except ModuleNotFoundError:
    from tools import american_dad_intake_009 as intake
    from tools import american_dad_core_009 as core
    from tools import american_dad_pilot_009 as old
    from tools import subtitle_quality_010 as quality

SCHEMA='bruiser-context-safe-v010'
STATE=core.BASE/'american-dad-contextsafe-010'
PROFILE=core.PROFILE
DEFAULT_EPISODES=3
MAX_ATTEMPTS=2


def sidecar(video):
    return video.with_name(video.stem+'.Bruiser ContextSafe v2 Japanese.ja.srt')


def module_hash():
    return hashlib.sha256(Path(quality.__file__).read_bytes()).hexdigest()


def freeze(limit=DEFAULT_EPISODES,roots=intake.ROOTS,state=STATE,
           profile=PROFILE):
    if not 1<=limit<=8:
        raise ValueError('Preview permits 1..8 episodes')
    state=Path(state)
    manifest=state/'manifest.json'
    profile_sha=intake.sha(Path(profile).read_bytes())
    gate_sha=module_hash()
    if manifest.exists():
        old_data=core.load(manifest)
        if (old_data.get('schema')!=SCHEMA or old_data.get('model')!=core.MODEL
            or old_data.get('model_id')!=core.MODEL_ID
            or old_data.get('profile_sha')!=profile_sha
            or old_data.get('quality_gate_sha')!=gate_sha
            or old_data.get('limit')!=limit):
            raise RuntimeError('Frozen preview/pipeline identity changed; refuse resume')
        return old_data
    videos,skips=intake.catalog(roots,limit)
    if not videos:
        raise RuntimeError('No fresh episodes with verified English and no existing Japanese: '
                           +json.dumps(skips)[:650])
    chosen=[]
    for item in videos:
        record=dict(item)
        source=record.pop('raw')
        original=state/'episodes'/record['episode']/'source.en.srt'
        if original.exists():
            if intake.sha(original.read_bytes())!=record['source_sha']:
                raise RuntimeError('Private source fingerprint mismatch')
        else:
            core.create(original,source)
        record['source_path']=str(original)
        chosen.append(record)
    out={'schema':SCHEMA,'model':core.MODEL,
         'model_id':core.MODEL_ID,'profile_sha':profile_sha,
         'quality_gate_sha':gate_sha,'limit':limit,'episodes':chosen,
         'skipped':skips}
    core.save(manifest,out)
    print('FROZEN FRESH CONTEXTSAFE',[(e['episode'],e['count']) for e in chosen],
          'skips',skips,flush=True)
    return out


def verify(record,roots=intake.ROOTS):
    video,rows=old.verify(record,roots)
    destination=sidecar(video)
    if destination.is_symlink():
        raise RuntimeError('Target is symlink')
    return video,rows


def checkpoint(path,entry,cue_id):
    if not path.is_file():
        return None
    data=core.load(path)
    if (data.get('cue_id')!=cue_id
        or data.get('source_sha')!=entry['source_sha']
        or data.get('model_id')!=core.MODEL_ID
        or data.get('pipeline')!=SCHEMA
        or not data.get('valid')):
        raise RuntimeError('Incompatible saved cue checkpoint; refuse replacement')
    return data['japanese']


def main_messages(rows,index,previous,profile,series,episode):
    return quality.cue_messages(
        rows,index,previous,
        series_note=core.note_text(series),
        title_note=core.note_text(episode),
        series_bible=core.compact_profile(profile),
        style='natural idiomatic Japanese for an adult animated sitcom',
        repair=False)


def rescue_messages(rows,index):
    return quality.cue_messages(
        rows,index,[],style='natural idiomatic Japanese for an adult sitcom',
        repair=True)


def accepted_japanese(text,english):
    clean=core.normalized_srt_markup(text,english)
    if clean is None or not core.valid(clean,english):
        return None
    return clean


def generate_episode(entry,profile,series_note,state=STATE,roots=intake.ROOTS,
                     ask=core.call,publish=False,deadline=None):
    state=Path(state)
    folder=state/'episodes'/entry['episode']
    video=Path(entry['video'])
    target=sidecar(video)
    if target.exists() or target.is_symlink():
        final=folder/'pilot-v2.ja.srt'
        if (not target.is_symlink() and target.is_file() and
            final.is_file() and final.read_bytes()==target.read_bytes()):
            return {'episode':entry['episode'],'state':'already_published_identical'}
        raise RuntimeError('Different existing JA preview; never overwrite')
    video,rows=verify(entry,roots)
    ep_note=core.note('title','American Dad '+entry['episode'],
                      [Path(entry['source_path'])],state,ask)
    staged={}
    previous=[]
    missing=[]
    for index,row in enumerate(rows):
        cue_id,timing,start_ms,end_ms,english=row
        path=folder/'cues'/('%05d.json'%cue_id)
        current=checkpoint(path,entry,cue_id)
        if current is None:
            if deadline is not None and time.monotonic()>=deadline:
                break
            for attempt in (1,2):
                failpath=folder/'attempts'/('%05d-%d.json'%(cue_id,attempt))
                if failpath.exists():
                    continue
                answer=None
                error=None
                try:
                    prompt=(main_messages(rows,index,previous,profile,series_note,ep_note)
                            if attempt==1 else rescue_messages(rows,index))
                    answer=ask(prompt)
                    current=accepted_japanese(answer,english)
                    if current is None:
                        error='Invalid JA/format'
                except Exception as exc:
                    error=type(exc).__name__+': '+str(exc)[:120]
                if current is not None:
                    core.save(path,{
                        'cue_id':cue_id,'source_sha':entry['source_sha'],
                        'model_id':core.MODEL_ID,'pipeline':SCHEMA,'valid':True,
                        'japanese':current,'initial_attempt':attempt})
                    break
                core.save(failpath,{'cue_id':cue_id,'error':error})
            if current is None:
                missing.append(cue_id)
                if len(missing)>=12:
                    break
                continue
        staged[str(cue_id)]=current
        if not quality.length_risk(current,start_ms,end_ms)['severe_density']:
            previous.append(current)
        if index%100==0 or index+1==len(rows):
            print('CUES',entry['episode'],index+1,'/',len(rows),
                  'missing',len(missing),flush=True)
    if len(staged)!=len(rows):
        return {'episode':entry['episode'],'state':'incomplete_source_pass',
                'accepted':len(staged),'total':len(rows),
                'missing_ids':missing[:12]}
    # Post-pass is essential: a future-cue duplication cannot be recognized
    # until its own Japanese text exists. Keep raw candidate checkpoints.
    flags=quality.overlap_ids(rows,staged)
    density=quality.density_flags(rows,staged)
    severe={cue for cue,stat in density.items() if stat['severe_density']}
    flagged=flags|severe
    final=dict(staged)
    unresolved=[]
    repaired=[]
    ids_to_index={row[0]:i for i,row in enumerate(rows)}
    for cue_id in sorted(flagged):
        index=ids_to_index[cue_id]
        row=rows[index]
        existing=folder/'repairs'/('%05d.json'%cue_id)
        revised=checkpoint(existing,entry,cue_id)
        if revised is None:
            for attempt in (1,2):
                retry=folder/'repair-attempts'/('%05d-%d.json'%(cue_id,attempt))
                if retry.exists():
                    continue
                if deadline is not None and time.monotonic()>=deadline:
                    break
                outcome=None
                err=None
                try:
                    guess=ask(rescue_messages(rows,index))
                    outcome=accepted_japanese(guess,row[4])
                    if outcome is None:
                        err='Invalid Japanese/format'
                    elif quality.length_risk(outcome,row[2],row[3])['severe_density']:
                        err='Severely overlong cue'
                    else:
                        later=[final.get(str(x[0]),'') for x in
                               rows[index+1:index+4]]
                        if any(quality.future_overlap(outcome,other) for other in later):
                            err='Contains upcoming translated cue'
                    if err:
                        outcome=None
                except Exception as exc:
                    err=type(exc).__name__+': '+str(exc)[:120]
                if outcome is not None:
                    revised=outcome
                    core.save(existing,{
                        'cue_id':cue_id,'source_sha':entry['source_sha'],
                        'model_id':core.MODEL_ID,'pipeline':SCHEMA,'valid':True,
                        'japanese':outcome,'attempt':attempt,'reason':
                        ['leakage' if cue_id in flags else '',
                         'density' if cue_id in severe else '']})
                    break
                core.save(retry,{'cue_id':cue_id,'error':err})
        if revised is not None:
            final[str(cue_id)]=revised
            repaired.append(cue_id)
        else:
            unresolved.append(cue_id)
    final_flags=quality.overlap_ids(rows,final)
    final_density=quality.density_flags(rows,final)
    still_severe=[cue for cue,info in final_density.items()
                  if info['severe_density']]
    for cue in sorted(final_flags|set(still_severe)):
        if cue not in unresolved:
            unresolved.append(cue)
    # Private metrics without copyright-bearing dialogue.
    report={'episode':entry['episode'],'source_cues':len(rows),
            'first_pass_leak_flags':len(flags),
            'first_pass_severe_density':len(severe),
            'repaired_cues':len(repaired),
            'unresolved_ids':sorted(unresolved),
            'remaining_leak_flags':len(final_flags),
            'remaining_severe_density':len(still_severe),
            'warning_over_18_cps':sum(x['high_density'] for x in final_density.values())}
    report_path=folder/'quality-v2.json'
    if report_path.exists():
        if core.load(report_path)!=report:
            raise RuntimeError('Frozen quality record changed; no silent rewrite')
    else:
        core.save(report_path,report)
    print('QUALITY',json.dumps(report,ensure_ascii=False),flush=True)
    if unresolved:
        return {'episode':entry['episode'],'state':'held_for_quality',
                'accepted':len(final),'unresolved_ids':sorted(unresolved)}
    text=service.render_srt(rows,final)
    draft=folder/'pilot-v2.ja.srt'
    if draft.exists():
        if draft.read_bytes()!=text:
            raise RuntimeError('Private complete subtitle bytes differ')
    else:
        core.create(draft,text)
    if not publish:
        return {'episode':entry['episode'],'state':'private_complete',
                'accepted':len(rows)}
    verify(entry,roots)
    if target.exists() or target.is_symlink():
        raise RuntimeError('Target appeared before create-only publication')
    core.create(target,text,mode=0o644)
    return {'episode':entry['episode'],'state':'published_new_contextsafe',
            'accepted':len(rows),'sidecar_name':target.name}


def run(limit=DEFAULT_EPISODES,minutes=420,publish=False,
        roots=intake.ROOTS,state=STATE,profile=PROFILE,ask=core.call,
        base=core.BASE):
    manifest=freeze(limit,roots,state,profile)
    guide=Path(profile).read_text(encoding='utf8')
    deadline=time.monotonic()+minutes*60
    results=[]
    with core.locks(base):
        if ask is core.call:
            core.preflight()
        series=core.note('series','American Dad',
                        [Path(x['source_path']) for x in manifest['episodes'][:3]],
                        state,ask)
        for entry in manifest['episodes']:
            if time.monotonic()>=deadline:
                break
            try:
                data=generate_episode(entry,guide,series,state,roots,ask,
                                      publish,deadline)
            except Exception as exc:
                data={'episode':entry['episode'],'state':'held',
                      'error':type(exc).__name__+': '+str(exc)[:175]}
            results.append(data)
            print('EPISODE_RESULT',json.dumps(data,ensure_ascii=False),flush=True)
    print('CONTEXTSAFE_SUMMARY',json.dumps(results,ensure_ascii=False),flush=True)
    return results


def status(state=STATE):
    path=Path(state)/'manifest.json'
    if not path.exists():
        return {'state':'not_prepared'}
    manifest=core.load(path)
    return {'model':manifest['model'],'episodes':[
        {'episode':x['episode'],'accepted':
            len(list((Path(state)/'episodes'/x['episode']/'cues').glob('*.json'))),
         'source_cues':x['count'],
         'published':sidecar(Path(x['video'])).is_file()}
        for x in manifest['episodes']]}


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=('prepare','run','status'))
    p.add_argument('--episodes',type=int,default=DEFAULT_EPISODES)
    p.add_argument('--minutes',type=int,default=420)
    p.add_argument('--publish',action='store_true')
    args=p.parse_args(argv)
    if not 1<=args.episodes<=8 or not 1<=args.minutes<=1440:
        p.error('episodes 1..8, minutes 1..1440')
    if args.action=='prepare':
        freeze(args.episodes)
    elif args.action=='status':
        print(json.dumps(status(),ensure_ascii=False,indent=2))
    else:
        run(limit=args.episodes,minutes=args.minutes,publish=args.publish)
    return 0


if __name__=='__main__':
    raise SystemExit(main())
