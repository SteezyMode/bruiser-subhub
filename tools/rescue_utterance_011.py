#!/usr/bin/env python3
"""Resume the frozen v011 utterance pilot without changing its code/checkpoints.

Reads ORIGINAL v011 outputs and source manifest. Writes ONLY separate, versioned
recovery checkpoints, QA and create-only JA sidecars; leaves all old attempts,
accepted units, source videos, SQLite and v009/v010 sidecars untouched.

Already-failed groups go directly to bounded, current-cue-only rescue. New
groups get ONE structured group call, then bounded singleton fallback.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

# The original host runner MUST retain the bytes pinned by its private manifest.
# We do not stage/rewrite any of these modules in the frozen v011 code directory.
ORIGINAL_CODE = Path.home() / 'bruiser-pilot/utterance-011-code'
if ORIGINAL_CODE.is_dir():
    sys.path.insert(0, str(ORIGINAL_CODE))
import service
try:
    import american_dad_utterance_011 as original
    import american_dad_core_009 as core
    import american_dad_intake_009 as intake
    import semantic_groups_011 as semantic
    import subtitle_quality_010 as quality
except ModuleNotFoundError:
    from tools import american_dad_utterance_011 as original
    from tools import american_dad_core_009 as core
    from tools import american_dad_intake_009 as intake
    from tools import semantic_groups_011 as semantic
    from tools import subtitle_quality_010 as quality

SCHEMA = 'bruiser-utterance-recovery-v011r1'
STATE = core.BASE / 'american-dad-utterance-011-recovery'
OLD_STATE = core.BASE / 'american-dad-utterance-011'
BUDGET_SINGLETON = 2
BUDGET_QA = 2


def sidecar(video):
    return video.with_name(video.stem + '.Bruiser Utterance Recovery v3 Japanese.ja.srt')


def version_sha():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def read_regular(path):
    path=Path(path)
    if path.is_symlink() or not path.is_file():
        raise RuntimeError('Missing or unsafe recovery file')
    return core.load(path)


def frozen(old_state=OLD_STATE, state=STATE, profile=core.PROFILE):
    """Verify original state and lock a separate versioned recovery identity."""
    old_state, state=Path(old_state), Path(state)
    manifest_path=old_state/'manifest.json'
    old=read_regular(manifest_path)
    if (old.get('schema') != original.SCHEMA or
        old.get('pipeline_sha') != original.pipeline_sha() or
        old.get('model') != core.MODEL or
        old.get('model_id') != core.MODEL_ID or
        old.get('profile_sha') != intake.sha(Path(profile).read_bytes())):
        raise RuntimeError('Frozen v011 source, model or installed code has changed')
    entries=old.get('episodes')
    if not isinstance(entries,list) or not 1<=len(entries)<=8:
        raise RuntimeError('Invalid frozen episode selection')
    identity={
        'schema':SCHEMA,
        'original_manifest_sha':intake.sha(manifest_path.read_bytes()),
        'original_pipeline_sha':old['pipeline_sha'],
        'recovery_code_sha':version_sha(),
        'model_id':core.MODEL_ID,
        'profile_sha':old['profile_sha'],
        'episode_source_hashes':[
            [x['episode'],x['source_sha']] for x in entries],
    }
    path=state/'manifest.json'
    if path.exists() or path.is_symlink():
        if read_regular(path)!=identity:
            raise RuntimeError('Recovery identity/code/source mismatch; no resume')
    else:
        core.save(path,identity)
    return old, identity


def unit_path(state, eid, group):
    return Path(state)/'episodes'/eid/'units'/('%05d-%05d.json'%
                                              (group[0][0],group[-1][0]))


def cue_path(state, eid, row, subdir='cues'):
    return Path(state)/'episodes'/eid/subdir/('%05d.json'%row[0])


def load_cue(path,entry,row,identity):
    if not path.exists() and not path.is_symlink():
        return None
    data=read_regular(path)
    fields={
        'schema':SCHEMA,'source_sha':entry['source_sha'],
        'model_id':core.MODEL_ID,'recovery_code_sha':identity['recovery_code_sha'],
        'unit_sha':semantic.unit_sha((row,)),'cue_id':row[0]
    }
    if any(data.get(k)!=v for k,v in fields.items()):
        raise RuntimeError('Existing recovery cue identity differs')
    ja=original.accepted(data.get('japanese'),row[4])
    if (ja is None or not semantic.valid_speakers(row[4],ja)
        or quality.length_risk(ja,row[2],row[3])['severe_density']):
        raise RuntimeError('Saved recovery cue failed validation')
    return ja


def save_cue(path,entry,row,identity,japanese,origin):
    core.save(path,{
        'schema':SCHEMA,'source_sha':entry['source_sha'],
        'model_id':core.MODEL_ID,'recovery_code_sha':identity['recovery_code_sha'],
        'unit_sha':semantic.unit_sha((row,)),'cue_id':row[0],
        'japanese':japanese,'origin':origin,
    })


def load_unit(path,entry,group,identity):
    if not path.exists() and not path.is_symlink():
        return None
    data=read_regular(path)
    fields={'schema':SCHEMA,'source_sha':entry['source_sha'],
            'model_id':core.MODEL_ID,'recovery_code_sha':identity['recovery_code_sha'],
            'unit_sha':semantic.unit_sha(group),'ids':[r[0] for r in group]}
    if any(data.get(k)!=v for k,v in fields.items()):
        raise RuntimeError('Existing recovery unit identity differs')
    return original.validate_answer(data.get('translations'),group) if len(group)>1 else {
        str(group[0][0]):load_single_from_unit(data,group[0])}


def load_single_from_unit(data,row):
    ja=original.accepted(data['translations'][str(row[0])],row[4])
    if ja is None or not semantic.valid_speakers(row[4],ja):
        raise RuntimeError('Saved singleton unit invalid')
    if quality.length_risk(ja,row[2],row[3])['severe_density']:
        raise RuntimeError('Saved singleton too dense')
    return ja


def save_unit(path,entry,group,identity,values,mode):
    core.save(path,{
        'schema':SCHEMA,'source_sha':entry['source_sha'],
        'model_id':core.MODEL_ID,'recovery_code_sha':identity['recovery_code_sha'],
        'unit_sha':semantic.unit_sha(group),'ids':[r[0] for r in group],
        'translations':values,'recovery_mode':mode,
    })


def category(exc):
    s=str(exc).lower()
    if 'length cap' in s or 'output length' in s:
        return 'model_length_cap'
    if 'json' in s or 'keys' in s:
        return 'invalid_group_json_or_keys'
    if 'speaker' in s:
        return 'speaker_layout'
    if 'dense' in s:
        return 'reading_density'
    if 'repeated' in s or 'copied' in s:
        return 'duplicate_content'
    if 'timed out' in s or 'timeout' in s:
        return 'model_timeout'
    return 'other_'+type(exc).__name__


def first_attempt_already_failed(old_state,entry,group):
    folder=Path(old_state)/'episodes'/entry['episode']/'attempts'
    label='%05d-%05d'%(group[0][0],group[-1][0])
    found=0
    for n in (1,2,3):
        path=folder/(label+'-'+str(n)+'.json')
        if path.exists() or path.is_symlink():
            data=read_regular(path)
            if data.get('ids')!=[r[0] for r in group]:
                raise RuntimeError('Original failed-attempt identity changed')
            found+=1
    return found>0


def translate_unit(group,rows,staged,profile,entry,state,identity,ask,original_state=OLD_STATE):
    """Recover without ever repeating a known failed original group attempt."""
    eid=entry['episode']
    path=unit_path(state,eid,group)
    cached=load_unit(path,entry,group,identity)
    if cached is not None:
        return cached,'reused_recovery'
    previous=[staged[str(x[0])] for x in rows
              if x[0]<group[0][0] and str(x[0]) in staged][-1:]
    was_failed=first_attempt_already_failed(original_state,entry,group)
    if len(group)>1 and not was_failed:
        # Only one normal structured group call for groups never previously tried.
        # A length-cap or mapping error immediately falls back to isolated cues.
        fail=Path(state)/'episodes'/eid/'attempts'/(
            '%05d-%05d-group.json'%(group[0][0],group[-1][0]))
        if not fail.exists() and not fail.is_symlink():
            try:
                msg=original.messages_for(rows,group,previous,profile,
                                          None,None,1)
                answer=ask(msg,json_mode=True)
                result=original.validate_answer(answer,group)
                save_unit(path,entry,group,identity,result,'grouped')
                return result,'grouped'
            except Exception as exc:
                core.save(fail,{'ids':[r[0] for r in group],
                                'error_category':category(exc)})
        else:
            data=read_regular(fail)
            if data.get('ids') != [r[0] for r in group]:
                raise RuntimeError('Recovery grouped failure identity mismatch')

    # Fall back to CURRENT ENGLISH ONLY, with no future raw target fragments.
    # Each accepted cue persists individually even if another cue later fails.
    recovered={}
    for row in group:
        target=cue_path(state,eid,row)
        ja=load_cue(target,entry,row,identity)
        if ja is None:
            index=rows.index(row)
            context=[staged.get(str(r[0])) for r in rows[:index]
                     if str(r[0]) in staged][-1:]
            for attempt in range(1,BUDGET_SINGLETON+1):
                fail=Path(state)/'episodes'/eid/'attempts'/(
                    '%05d-single-%d.json'%(row[0],attempt))
                if fail.exists() or fail.is_symlink():
                    rec=read_regular(fail)
                    if rec.get('cue_id') != row[0]:
                        raise RuntimeError('Recovery singleton attempt identity mismatch')
                    continue
                try:
                    msg=original.messages_for(rows,(row,),context,profile,
                                              None,None,attempt)
                    answer=ask(msg,json_mode=False)
                    ja=original.validate_answer(answer,(row,))[str(row[0])]
                    save_cue(target,entry,row,identity,ja,'current_cue_fallback')
                    break
                except Exception as exc:
                    core.save(fail,{'cue_id':row[0],
                                    'error_category':category(exc)})
        if ja is not None:
            recovered[str(row[0])]=ja
            staged[str(row[0])]=ja
    if len(recovered)==len(group):
        save_unit(path,entry,group,identity,recovered,'isolated_singletons')
        return recovered,'isolated_singletons'
    return None,'held_missing_cue'


def post_quality(rows,original_map,profile,entry,state,identity,ask,deadline):
    """Repair only flagged cue output in the separate v011r1 namespace."""
    repaired=dict(original_map)
    initial=semantic.quality_flags(rows,repaired)
    initial_bad=(initial['overlap']|initial['repeated']|
                 initial['speakers']|initial['severe'])
    changed=[]
    for row in rows:
        if row[0] not in initial_bad:
            continue
        path=cue_path(state,entry['episode'],row,subdir='repairs')
        existing=load_cue(path,entry,row,identity)
        if existing is not None:
            repaired[str(row[0])]=existing
            changed.append(row[0])
            continue
        for attempt in range(1,BUDGET_QA+1):
            if deadline is not None and time.monotonic()>=deadline:
                break
            fail=Path(state)/'episodes'/entry['episode']/'repair-attempts'/(
                '%05d-%d.json'%(row[0],attempt))
            if fail.exists() or fail.is_symlink():
                rec=read_regular(fail)
                if rec.get('cue_id')!=row[0]:
                    raise RuntimeError('Repair attempt identity differs')
                continue
            try:
                index=rows.index(row)
                # Strict current English only. Unlike v009, never prompt with
                # raw following dialogue during a repair.
                msg=original.messages_for(rows,(row,),[],profile,
                                           None,None,2)
                answer=ask(msg,json_mode=False)
                proposed=original.validate_answer(answer,(row,))[str(row[0])]
                candidate=dict(repaired)
                candidate[str(row[0])]=proposed
                risks=semantic.quality_flags(rows,candidate)
                bad=(risks['overlap']|risks['repeated']|
                     risks['speakers']|risks['severe'])
                if row[0] in bad or bad-initial_bad:
                    raise ValueError('Repaired subtitle still fails cross-cue QA')
                save_cue(path,entry,row,identity,proposed,'postpass_qa')
                repaired[str(row[0])]=proposed
                changed.append(row[0])
                break
            except Exception as exc:
                core.save(fail,{'cue_id':row[0],
                                'error_category':category(exc)})
    after=semantic.quality_flags(rows,repaired)
    unresolved=(after['overlap']|after['repeated']|
                after['speakers']|after['severe'])
    return repaired,initial,after,sorted(unresolved),changed


def run_episode(entry,profile,state,identity,roots,ask,publish,deadline,
                original_state=OLD_STATE):
    eid=entry['episode']
    state=Path(state)
    video=Path(entry['video'])
    target=sidecar(video)
    draft=state/'episodes'/eid/'pilot-recovered.ja.srt'
    if target.exists() or target.is_symlink():
        if (target.is_file() and not target.is_symlink() and
            draft.is_file() and draft.read_bytes()==target.read_bytes()):
            return {'episode':eid,'state':'already_published_identical'}
        raise RuntimeError('Conflicting recovered Japanese track; cannot overwrite')
    _,rows=original.old.verify(entry,roots)
    groups=semantic.plan(rows)
    results={}
    counts={'original_units':0,'recovery_units':0,'new_group_units':0,
            'fallback_units':0,'held_units':0}
    for ix,group in enumerate(groups):
        if deadline is not None and time.monotonic()>=deadline:
            break
        oldpath=original.unit_file(Path(original_state)/'episodes'/eid,group)
        previous=original.checkpoint(oldpath,entry,group)
        if previous is not None:
            counts['original_units']+=1
            results.update(previous)
        else:
            recovered,mode=translate_unit(group,rows,results,profile,entry,
                                         state,identity,ask,original_state)
            if recovered is None:
                counts['held_units']+=1
            else:
                counts['recovery_units']+=1
                counts['new_group_units']+=mode=='grouped'
                counts['fallback_units']+=mode=='isolated_singletons'
                results.update(recovered)
        if ix % 75 == 0 or ix + 1==len(groups):
            print('RECOVERY_PROGRESS',eid,ix+1,'/',len(groups),
                  'cues',len(results),'/',len(rows),flush=True)
    if len(results)!=len(rows):
        missing=[r[0] for r in rows if str(r[0]) not in results]
        print('RECOVERY_INCOMPLETE',eid,
              'missing_cue_count',len(missing),'first_ids',missing[:20],
              'unit_counts',counts,flush=True)
        return {'episode':eid,'state':'incomplete',
                'accepted_cues':len(results),'source_cues':len(rows),
                'missing_ids':missing[:20], 'missing_total':len(missing),
                'units':counts}
    final,first,after,unresolved,changed=post_quality(
        rows,results,profile,entry,state,identity,ask,deadline)
    report={'schema':SCHEMA,'episode':eid,'source_cues':len(rows),
            'units':counts, 'qa_repairs':len(changed),
            'pre_qa':{k:len(v) for k,v in first.items()},
            'post_qa':{k:len(v) for k,v in after.items()},
            'unresolved_ids':unresolved}
    report_raw=(json.dumps(report,ensure_ascii=False,sort_keys=True,
                           indent=2)+'\n').encode()
    report_path=state/'episodes'/eid/(
        'quality-recovery-'+hashlib.sha256(report_raw).hexdigest()[:14]+'.json')
    if report_path.exists() or report_path.is_symlink():
        if report_path.is_symlink() or report_path.read_bytes()!=report_raw:
            raise RuntimeError('Conflicting saved recovery QA report')
    else:
        core.create(report_path,report_raw)
    print('RECOVERY_QUALITY',json.dumps(report,ensure_ascii=False),flush=True)
    if unresolved:
        return {'episode':eid,'state':'held_for_quality',
                'unresolved_ids':unresolved,'units':counts}
    output=service.render_srt(rows,final)
    # An English SRT may contain an empty numbered placeholder. The shared
    # renderer renumbers rows, so explicitly verify every ID and timestamp
    # BEFORE either saving a draft or publishing. No silent off-by-one drift.
    rendered=service.parse_srt(output)
    if (len(rendered)!=len(rows) or
        any(a[:4]!=b[:4] for a,b in zip(rows,rendered))):
        raise RuntimeError('Rendered JA cue IDs/timestamps drifted; no publication')
    if draft.exists() or draft.is_symlink():
        if draft.is_symlink() or draft.read_bytes()!=output:
            raise RuntimeError('Private recovered JA differs from saved draft')
    else:
        core.create(draft,output)
    if not publish:
        return {'episode':eid,'state':'private_complete',
                'accepted_cues':len(rows),'units':counts}
    original.old.verify(entry,roots)
    if target.exists() or target.is_symlink():
        raise RuntimeError('Create-only recovered JA target appeared')
    core.create(target,output,mode=0o644)
    return {'episode':eid,'state':'published_new_recovery',
            'accepted_cues':len(rows),'sidecar_name':target.name,'units':counts}


def run(minutes=420,publish=False,state=STATE,original_state=OLD_STATE,
        roots=intake.ROOTS,profile=core.PROFILE,ask=core.call,base=core.BASE):
    old,identity=frozen(original_state,state,profile)
    profile_text=Path(profile).read_text(encoding='utf8')
    deadline=time.monotonic()+minutes*60
    results=[]
    with core.locks(base):
        if ask is core.call:
            core.preflight()
        for entry in old['episodes']:
            if time.monotonic()>=deadline:
                break
            try:
                data=run_episode(entry,profile_text,state,identity,
                                 roots,ask,publish,deadline,original_state)
            except Exception as exc:
                data={'episode':entry['episode'],'state':'held',
                      'error_category':category(exc)}
            results.append(data)
            print('RECOVERY_EPISODE_RESULT',json.dumps(data,ensure_ascii=False),
                  flush=True)
    print('RECOVERY_SUMMARY',json.dumps(results,ensure_ascii=False),flush=True)
    return results


def status(state=STATE,original_state=OLD_STATE):
    manifest=Path(original_state)/'manifest.json'
    if manifest.is_symlink() or not manifest.is_file():
        return {'state':'original_manifest_missing'}
    original_data=core.load(manifest)
    episodes=[]
    for entry in original_data['episodes']:
        eid=entry['episode']
        folder=Path(state)/'episodes'/eid
        episodes.append({
            'episode':eid,'original_saved_units':len(list(
                (Path(original_state)/'episodes'/eid/'units').glob('*.json'))),
            'recovery_saved_units':len(list((folder/'units').glob('*.json'))),
            'recovery_saved_cues':len(list((folder/'cues').glob('*.json'))),
            'source_cues':entry['count'],
            'published':sidecar(Path(entry['video'])).is_file(),
        })
    return {'schema':SCHEMA,'episodes':episodes}


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=('run','status'))
    p.add_argument('--minutes',type=int,default=420)
    p.add_argument('--publish',action='store_true')
    args=p.parse_args(argv)
    if not 1<=args.minutes<=1440:
        p.error('Minutes must be 1..1440')
    if args.action=='status':
        print(json.dumps(status(),ensure_ascii=False,indent=2))
    else:
        run(args.minutes,args.publish)
    return 0


if __name__=='__main__':
    raise SystemExit(main())
