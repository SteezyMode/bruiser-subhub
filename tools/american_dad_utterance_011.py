#!/usr/bin/env python3
"""Fresh, isolated American Dad trial of generic utterance-aware translation.

Unmodified source timestamps, immutable group checkpoints, bounded retries,
private QA, create-only media sidecars. NOT the live SubHub SQLite worker.
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
    import semantic_groups_011 as semantic
except ModuleNotFoundError:
    from tools import american_dad_intake_009 as intake
    from tools import american_dad_core_009 as core
    from tools import american_dad_pilot_009 as old
    from tools import subtitle_quality_010 as quality
    from tools import semantic_groups_011 as semantic

SCHEMA = 'bruiser-utterance-pilot-v011'
STATE = core.BASE / 'american-dad-utterance-011'
PROFILE = core.PROFILE
DEFAULT_EPISODES = 3
MAX_ATTEMPTS = 3


def sidecar(video):
    return video.with_name(video.stem + '.Bruiser Utterance v3 Japanese.ja.srt')


def pipeline_sha():
    sources = (Path(__file__), Path(semantic.__file__), Path(quality.__file__))
    return hashlib.sha256(b''.join(Path(p).read_bytes() for p in sources)).hexdigest()


def freeze(limit=DEFAULT_EPISODES, roots=intake.ROOTS, state=STATE, profile=PROFILE):
    if not 1 <= limit <= 8:
        raise ValueError('Pilot permits 1..8 episodes')
    state = Path(state)
    manifest = state / 'manifest.json'
    profile_sha = intake.sha(Path(profile).read_bytes())
    code_sha = pipeline_sha()
    if manifest.exists() or manifest.is_symlink():
        if manifest.is_symlink():
            raise RuntimeError('Unsafe frozen manifest symlink')
        data = core.load(manifest)
        if any((data.get(key) != val) for key,val in (
                ('schema',SCHEMA),('model',core.MODEL),('model_id',core.MODEL_ID),
                ('profile_sha',profile_sha),('pipeline_sha',code_sha),
                ('limit',limit))):
            raise RuntimeError('Immutable v011 manifest/code/model identity mismatch')
        return data
    candidates,skips = intake.catalog(roots,limit)
    if not candidates:
        raise RuntimeError('No eligible NEW episodes with verified EN and no JA: '+
                           json.dumps(skips)[:700])
    selected = []
    for candidate in candidates:
        record = dict(candidate)
        raw = record.pop('raw')
        source = state / 'episodes' / record['episode'] / 'source.en.srt'
        if source.exists() or source.is_symlink():
            if source.is_symlink() or intake.sha(source.read_bytes()) != record['source_sha']:
                raise RuntimeError('Private English source collides with existing file')
        else:
            core.create(source,raw)
        record['source_path'] = str(source)
        selected.append(record)
    data = {'schema':SCHEMA,'model':core.MODEL,'model_id':core.MODEL_ID,
            'profile_sha':profile_sha,'pipeline_sha':code_sha,'limit':limit,
            'episodes':selected,'skipped':skips}
    core.save(manifest,data)
    print('UTTERANCE_011_FROZEN',[(x['episode'],x['count']) for x in selected],
          'skips',skips,flush=True)
    return data


def accepted(text,english):
    if not isinstance(text,str):
        return None
    clean = core.normalized_srt_markup(text,english)
    if clean is None or not core.valid(clean,english):
        return None
    return clean


def optional_note(kind,title,sources,state,ask):
    """One strict JSON-format retry; failure leaves NO inferred context cached."""
    def query(messages,model):
        last = None
        for attempt in (1,2):
            request = list(messages)
            if attempt == 2:
                request += [{'role':'system','content':
                    'SCHEMA CORRECTION: JSON object with exactly names, terms, '
                    'notes, caveats. EACH MUST BE AN ARRAY of at most 8 short '
                    'plain-English strings, never a string or dictionary. '
                    'Return JSON ONLY; leave unknown fields as [].'}]
            try:
                raw = ask(request,json_mode=True)
                value = json.loads(raw) if isinstance(raw,str) else raw
                return core.context.check_note(value)
            except (ValueError,TypeError,KeyError,json.JSONDecodeError) as exc:
                last = exc
        raise ValueError('Context schema failed twice: '+type(last).__name__)
    try:
        return core.context.cached_context(kind,title,sources,
                                           cache=Path(state)/'context',
                                           ask=query,model=core.MODEL)
    except (OSError,ValueError,RuntimeError,KeyError,TypeError) as exc:
        print('OPTIONAL_CONTEXT_UNAVAILABLE',kind,type(exc).__name__,
              str(exc)[:100],flush=True)
        return None


def unit_file(folder, group, subdir='units'):
    return folder / subdir / ('%05d-%05d.json'%(group[0][0],group[-1][0]))


def checkpoint(path, entry, group):
    if not path.exists() and not path.is_symlink():
        return None
    if path.is_symlink() or not path.is_file():
        raise RuntimeError('Unsafe/non-file unit checkpoint')
    data = core.load(path)
    if any((data.get(key)!=value) for key,value in (
            ('schema',SCHEMA),('source_sha',entry['source_sha']),
            ('model_id',core.MODEL_ID),('pipeline_sha',pipeline_sha()),
            ('unit_sha',semantic.unit_sha(group)),
            ('ids',[r[0] for r in group]))):
        raise RuntimeError('Saved v011 unit identity mismatch; never overwrite')
    translations=data.get('translations')
    # All saved Japanese must still pass the frozen mechanical validator.
    if len(group)>1:
        return semantic.parse_unit_reply(translations,group,accepted)
    if not isinstance(translations,dict) or set(translations)!={str(group[0][0])}:
        raise RuntimeError('Corrupt singleton unit checkpoint')
    ja=accepted(translations[str(group[0][0])],group[0][4])
    if (ja is None or not semantic.valid_speakers(group[0][4],ja)
        or quality.length_risk(ja,group[0][2],group[0][3])['severe_density']):
        raise RuntimeError('Invalid singleton checkpoint')
    return {str(group[0][0]):ja}


def messages_for(rows,group,previous,profile,series_note,episode_note,attempt):
    i=next(i for i,r in enumerate(rows) if r[0]==group[0][0])
    if len(group)==1:
        messages=quality.cue_messages(rows,i,previous,
            series_note=core.note_text(series_note),
            title_note=core.note_text(episode_note),
            series_bible=core.compact_profile(profile),
            style='idiomatic unsanitized Japanese for adult animation',
            repair=attempt>1)
        if semantic.speaker_turn_count(group[0][4])>=2:
            messages[0]['content']+=(
                ' IMPORTANT: CURRENT_ENGLISH contains two explicitly dashed '
                'speakers. Preserve BOTH distinct turns, in source order, '
                'as two separate short Japanese lines, each beginning "- ". '
                'Do not fuse two speakers into one Japanese sentence.')
        return messages
    prior_en = [r[4] for r in rows[max(0,i-2):i]]
    return semantic.unit_messages(
        group,prior_en=prior_en,prior_ja=previous[-1:],
        series_bible=core.compact_profile(profile),
        series_note=core.note_text(series_note),
        title_note=core.note_text(episode_note),attempt=attempt)


def validate_answer(reply,group):
    if len(group)>1:
        return semantic.parse_unit_reply(reply,group,accepted)
    row=group[0]
    ja=accepted(reply,row[4])
    if ja is None or not semantic.valid_speakers(row[4],ja):
        raise ValueError('Invalid singleton Japanese/speaker turns')
    if quality.length_risk(ja,row[2],row[3])['severe_density']:
        raise ValueError('Unwatchably dense singleton Japanese')
    return {str(row[0]):ja}


def generate_episode(entry,profile,series_note,state=STATE,roots=intake.ROOTS,
                     ask=core.call,publish=False,deadline=None):
    state=Path(state)
    folder=state/'episodes'/entry['episode']
    video=Path(entry['video'])
    target=sidecar(video)
    draft=folder/'pilot-v3.ja.srt'
    if target.exists() or target.is_symlink():
        if (not target.is_symlink() and target.is_file() and
                draft.is_file() and draft.read_bytes()==target.read_bytes()):
            return {'episode':entry['episode'],'state':'already_published_identical'}
        raise RuntimeError('Existing Japanese preview differs; NEVER overwrite')
    video,rows=old.verify(entry,roots)
    ep_note=optional_note('title','American Dad '+entry['episode'],
                          [Path(entry['source_path'])],state,ask)
    groups=semantic.plan(rows)
    accepted_map={}
    missing=[]
    for number,group in enumerate(groups):
        path=unit_file(folder,group)
        current=checkpoint(path,entry,group)
        if current is None:
            if deadline is not None and time.monotonic()>=deadline:
                break
            previous=[accepted_map[str(x[0])] for x in rows
                      if x[0]<group[0][0] and str(x[0]) in accepted_map][-1:]
            for attempt in range(1,MAX_ATTEMPTS+1):
                fail=unit_file(folder,group,'attempts') .with_name(
                    '%05d-%05d-%d.json'%(group[0][0],group[-1][0],attempt))
                if fail.exists() or fail.is_symlink():
                    continue
                if deadline is not None and time.monotonic()>=deadline:
                    break
                error=None
                try:
                    prompt=messages_for(rows,group,previous,profile,series_note,
                                        ep_note,attempt)
                    reply=ask(prompt,json_mode=len(group)>1)
                    current=validate_answer(reply,group)
                except Exception as exc:
                    error=type(exc).__name__+': '+str(exc)[:120]
                if current is not None:
                    core.save(path,{
                        'schema':SCHEMA,'source_sha':entry['source_sha'],
                        'model_id':core.MODEL_ID,'pipeline_sha':pipeline_sha(),
                        'unit_sha':semantic.unit_sha(group),
                        'ids':[x[0] for x in group],'translations':current,
                        'attempt':attempt})
                    break
                core.save(fail,{'ids':[x[0] for x in group],
                                'error':error or 'Unusable model output'})
        if current is None:
            missing.extend(x[0] for x in group)
            if len(missing)>=12:
                break
        else:
            accepted_map.update(current)
        if number%75==0 or number+1==len(groups):
            print('UTTERANCE_PROGRESS',entry['episode'],number+1,'/',len(groups),
                  'cues',len(accepted_map),'/',len(rows),flush=True)
    if len(accepted_map)!=len(rows):
        remaining=[x[0] for x in rows if str(x[0]) not in accepted_map]
        return {'episode':entry['episode'],'state':'incomplete',
                'accepted_cues':len(accepted_map),'source_cues':len(rows),
                'missing_ids':remaining[:20]}
    flags=semantic.quality_flags(rows,accepted_map)
    bad=flags['overlap']|flags['repeated']|flags['speakers']|flags['severe']
    first_counts={k:len(v) for k,v in flags.items()}
    final=dict(accepted_map)
    repairs=[]
    unresolved=[]
    for group in groups:
        group_ids={x[0] for x in group}
        if not group_ids & bad:
            continue
        existing=unit_file(folder,group,'repairs')
        revision=checkpoint(existing,entry,group)
        if revision is None:
            for attempt in (4,5):
                fail=unit_file(folder,group,'repair-attempts').with_name(
                    '%05d-%05d-%d.json'%(group[0][0],group[-1][0],attempt))
                if fail.exists() or fail.is_symlink():
                    continue
                if deadline is not None and time.monotonic()>=deadline:
                    break
                error=None
                try:
                    prompt=messages_for(rows,group,[],profile,series_note,
                                        ep_note,attempt)
                    guess=ask(prompt,json_mode=len(group)>1)
                    revised=validate_answer(guess,group)
                    candidate=dict(final)
                    candidate.update(revised)
                    risks=semantic.quality_flags(rows,candidate)
                    blocking=risks['overlap']|risks['repeated']|risks['speakers']|risks['severe']
                    if blocking & group_ids or (blocking-bad):
                        raise ValueError('QA flags remain or new QA problems introduced')
                    revision=revised
                except Exception as exc:
                    error=type(exc).__name__+': '+str(exc)[:120]
                if revision is not None:
                    core.save(existing,{
                        'schema':SCHEMA,'source_sha':entry['source_sha'],
                        'model_id':core.MODEL_ID,'pipeline_sha':pipeline_sha(),
                        'unit_sha':semantic.unit_sha(group),
                        'ids':[x[0] for x in group],'translations':revision,
                        'repair_attempt':attempt})
                    break
                core.save(fail,{'ids':[x[0] for x in group],
                                'error':error or 'Repair invalid'})
        if revision is None:
            unresolved.extend(sorted(group_ids))
        else:
            final.update(revision)
            repairs.extend(sorted(group_ids))
    after=semantic.quality_flags(rows,final)
    remaining=after['overlap']|after['repeated']|after['speakers']|after['severe']
    unresolved=sorted(set(unresolved)|remaining)
    report={'schema':SCHEMA,'episode':entry['episode'],'source_cues':len(rows),
            'unit_count':len(groups),'multi_cue_units':sum(len(g)>1 for g in groups),
            'grouped_cues':sum(len(g) for g in groups if len(g)>1),
            'first_pass_flags':first_counts,
            'repaired_cues':len(repairs),'remaining_flags':
             {key:len(value) for key,value in after.items()},
            'unresolved_ids':unresolved}
    payload=json.dumps(report,ensure_ascii=False,sort_keys=True).encode('utf8')
    report_path=folder/('quality-v3-'+hashlib.sha256(payload).hexdigest()[:14]+'.json')
    if report_path.exists():
        if core.load(report_path)!=report:
            raise RuntimeError('Existing quality report changed')
    else:
        core.save(report_path,report)
    print('UTTERANCE_QUALITY',json.dumps(report,ensure_ascii=False),flush=True)
    if unresolved:
        return {'episode':entry['episode'],'state':'held_for_quality',
                'unresolved_ids':unresolved}
    output=service.render_srt(rows,final)
    if draft.exists():
        if draft.read_bytes()!=output:
            raise RuntimeError('Frozen private Japanese draft changed')
    else:
        core.create(draft,output)
    if not publish:
        return {'episode':entry['episode'],'state':'private_complete',
                'accepted_cues':len(rows)}
    # Mandatory second check protects an old Japanese track added since freeze.
    old.verify(entry,roots)
    if target.exists() or target.is_symlink():
        raise RuntimeError('Create-only target appeared during translation')
    core.create(target,output,mode=0o644)
    return {'episode':entry['episode'],'state':'published_new_utterance',
            'accepted_cues':len(rows),'sidecar_name':target.name}


def run(limit=DEFAULT_EPISODES,minutes=420,publish=False,
        roots=intake.ROOTS,state=STATE,profile=PROFILE,ask=core.call,base=core.BASE):
    manifest=freeze(limit,roots,state,profile)
    profile_text=Path(profile).read_text(encoding='utf8')
    deadline=time.monotonic()+minutes*60
    results=[]
    with core.locks(base):
        if ask is core.call:
            core.preflight()
        series=optional_note('series','American Dad',
                            [Path(x['source_path']) for x in manifest['episodes'][:3]],
                            state,ask)
        for entry in manifest['episodes']:
            if time.monotonic()>=deadline:
                break
            try:
                result=generate_episode(entry,profile_text,series,state,roots,
                                        ask,publish,deadline)
            except Exception as exc:
                result={'episode':entry['episode'],'state':'held',
                        'error':type(exc).__name__+': '+str(exc)[:160]}
            print('UTTERANCE_EPISODE_RESULT',json.dumps(result,ensure_ascii=False),flush=True)
            results.append(result)
    print('UTTERANCE_SUMMARY',json.dumps(results,ensure_ascii=False),flush=True)
    return results


def status(state=STATE):
    path=Path(state)/'manifest.json'
    if not path.is_file():
        return {'state':'not_prepared'}
    data=core.load(path)
    return {'schema':data['schema'],'episodes':[
        {'episode':x['episode'],
         'saved_unit_files':len(list((Path(state)/'episodes'/x['episode']/'units').glob('*.json'))),
         'source_cues':x['count'],
         'published':sidecar(Path(x['video'])).is_file()}
         for x in data['episodes']]}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('prepare','run','status'))
    parser.add_argument('--episodes',type=int,default=DEFAULT_EPISODES)
    parser.add_argument('--minutes',type=int,default=420)
    parser.add_argument('--publish',action='store_true')
    args=parser.parse_args(argv)
    if not 1<=args.episodes<=8 or not 1<=args.minutes<=1440:
        parser.error('Episodes 1..8 and minutes 1..1440')
    if args.action=='prepare':
        freeze(args.episodes)
    elif args.action=='status':
        print(json.dumps(status(),ensure_ascii=False,indent=2))
    else:
        run(args.episodes,args.minutes,args.publish)
    return 0


if __name__=='__main__':
    raise SystemExit(main())
