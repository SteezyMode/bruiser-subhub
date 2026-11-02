#!/usr/bin/env python3
"""Small, private, read-only-media grouped translation format experiment.

24 REAL frozen English utterances, selected 4 previously failed + 4 untouched
per episode, S19E10-E12. Compare minimal JSON vs ID|Japanese text output from
the SAME pinned Ollama E4B with the SAME 450 output token cap, temperature and
semantic prompt. Original SubHub state, translations and media are read-only.

Only new lab scratch state may be written; every attempted format is saved
create-only, so interruptions never repeat completed or failed model calls.
No subtitle publication, Jellyfin refresh, DB changes or model tournament.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import sys
import tarfile
import time
from urllib.request import Request, urlopen

ORIGINAL_CODE = Path.home()/'bruiser-pilot/utterance-011-code'
if ORIGINAL_CODE.is_dir():
    sys.path.insert(0,str(ORIGINAL_CODE))
import service
try:
    import american_dad_utterance_011 as original
    import american_dad_core_009 as core
    import semantic_groups_011 as semantic
    import subtitle_quality_010 as quality
except ModuleNotFoundError:
    from tools import american_dad_utterance_011 as original
    from tools import american_dad_core_009 as core
    from tools import semantic_groups_011 as semantic
    from tools import subtitle_quality_010 as quality

SCHEMA = 'bruiser-utterance-formatlab-v012'
LAB = core.BASE/'utterance-formatlab-012'
ORIGINAL = core.BASE/'american-dad-utterance-011'
RECOVERY = core.BASE/'american-dad-utterance-011-recovery'
EPISODES = ('S19E10','S19E11','S19E12')
PER_STRATUM = 4
OUTPUT_TOKENS = 450
VARIANTS = ('json','lines')
LINE = re.compile(r'^([1-9]\d*)\s*\|\s*(\S.*?)\s*$')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def source_file(path):
    if path.is_symlink() or not path.is_file():
        raise RuntimeError('Missing or unsafe frozen private file')
    return path.read_bytes()


def file_code_sha():
    return sha(Path(__file__).read_bytes())


def even_sample(values, n=PER_STRATUM):
    """Deterministic, spatially spread selection of exactly n unit candidates."""
    if len(values)<n:
        raise RuntimeError('Not enough eligible units in requested stratum')
    idx=[(i*(len(values)-1))//(n-1) for i in range(n)]
    if len(set(idx))!=n:
        raise RuntimeError('Sampling indices unexpectedly repeated')
    return [values[i] for i in idx]


def old_attempts(folder,group):
    first,last=group[0][0],group[-1][0]
    present=[]
    for attempt in range(1,4):
        path=folder/'attempts'/('%05d-%05d-%d.json'%(first,last,attempt))
        if path.exists() or path.is_symlink():
            item=json.loads(source_file(path))
            if item.get('ids')!=[x[0] for x in group]:
                raise RuntimeError('Frozen original failure IDs changed')
            present.append(item)
    return present


def verified_sources(original_state=ORIGINAL, profile=core.PROFILE):
    path=Path(original_state)/'manifest.json'
    manifest_bytes=source_file(path)
    manifest=json.loads(manifest_bytes)
    if (manifest.get('schema')!=original.SCHEMA or
        manifest.get('pipeline_sha')!=original.pipeline_sha() or
        manifest.get('model')!=core.MODEL or
        manifest.get('model_id')!=core.MODEL_ID or
        manifest.get('profile_sha')!=sha(Path(profile).read_bytes())):
        raise RuntimeError('Frozen v011 runner, model or profile identity changed')
    records={x['episode']:x for x in manifest['episodes']}
    if set(records)!=set(EPISODES):
        raise RuntimeError('Original frozen episodes changed')
    all_rows={}
    for episode in EPISODES:
        entry=records[episode]
        path=Path(original_state)/'episodes'/episode/'source.en.srt'
        if Path(entry.get('source_path',''))!=path:
            raise RuntimeError('Unexpected frozen English source location')
        content=source_file(path)
        if sha(content)!=entry['source_sha']:
            raise RuntimeError('English source hash mismatch')
        rows=service.parse_srt(content)
        if len(rows)!=entry['count']:
            raise RuntimeError('Frozen cue count mismatch')
        all_rows[episode]=rows
    return manifest, sha(manifest_bytes), all_rows


def freeze(state=LAB,original_state=ORIGINAL,profile=core.PROFILE):
    manifest,manifest_sha,all_rows=verified_sources(original_state,profile)
    chosen=[]
    for ep in EPISODES:
        groups=semantic.plan(all_rows[ep])
        folder=Path(original_state)/'episodes'/ep
        failed,fresh=[],[]
        for group in groups:
            if len(group)<2:
                continue
            good=folder/'units'/('%05d-%05d.json'%(group[0][0],group[-1][0]))
            if good.exists() or good.is_symlink():
                # Check immutable success rather than reinterpreting an old
                # accepted translated unit as a "fresh" test.
                original.checkpoint(good,next(x for x in manifest['episodes']
                                               if x['episode']==ep),group)
                continue
            attempted=old_attempts(folder,group)
            (failed if attempted else fresh).append(group)
        for stratum,candidates in (('formerly_failed',failed),
                                   ('never_attempted',fresh)):
            for group in even_sample(candidates):
                chosen.append({
                    'episode':ep,'stratum':stratum,
                    'cue_ids':[x[0] for x in group],
                    'unit_sha':semantic.unit_sha(group),
                    'source_sha':next(x['source_sha'] for x in manifest['episodes']
                                      if x['episode']==ep),
                })
    if len(chosen)!=24:
        raise RuntimeError('Expected exactly 24 selected utterances')
    identity={
        'schema':SCHEMA,
        'code_sha':file_code_sha(),
        'original_manifest_sha':manifest_sha,
        'original_pipeline_sha':manifest['pipeline_sha'],
        'model':core.MODEL,'model_id':core.MODEL_ID,
        'profile_sha':manifest['profile_sha'],
        'max_output_tokens_each_arm':OUTPUT_TOKENS,
        'selected':chosen
    }
    path=Path(state)/'selection.json'
    if path.exists() or path.is_symlink():
        if json.loads(source_file(path))!=identity:
            raise RuntimeError('Existing lab selection differs: refuse reset')
    else:
        core.save(path,identity)
    return identity,all_rows


def group_for(selection,rows):
    ids=selection['cue_ids']
    match={x[0]:x for x in rows}
    group=[match[n] for n in ids]
    if [x[0] for x in group]!=ids or semantic.unit_sha(group)!=selection['unit_sha']:
        raise RuntimeError('Frozen utterance identity changed')
    return group


def messages(group,mode,profile):
    if mode not in VARIANTS or not 2<=len(group)<=3:
        raise ValueError('Invalid target utterance or output format')
    system=(
        'Translate one connected English spoken utterance into natural, concise '
        'Japanese subtitles for an adult comedy. All target cues belong to the '
        'SAME utterance. Understand the complete thought first. Preserve meaning, '
        'negation, speaker intent, word senses, names, jokes, adult language and '
        'information order. Each Japanese caption must correspond ONLY to its '
        'own English cue; do not put a later reveal in an earlier cue and do not '
        'repeat the same idea twice. No explanations or invented facts. '
        'Return precisely one nonempty Japanese value for EACH cue ID in order.'
        '\n[NAME_GUIDE]\n'+core.compact_profile(profile)[:850]+
        '\n[/NAME_GUIDE]'
    )
    cues='\n'.join('%d | %s'%(r[0],re.sub(r'\s+',' ',r[4]).strip())
                   for r in group)
    if mode=='json':
        answer=('Return ONLY one JSON object mapping each ID string to its '
                'Japanese text. Example of required SHAPE (not translation): '
                '{"1":"日本語","2":"日本語"}. Keys MUST be exactly the IDs above. '
                'No code fences, comments or extra keys.')
    else:
        answer=('Return ONLY exactly one line per ID, formatted '
                'ID | Japanese subtitle. Use the SAME IDs and order above. '
                'No JSON, headings, code fences, extra lines or wrapped lines.')
    return [{'role':'system','content':system},
            {'role':'user','content':
             '[SOURCE_CUES]\n'+cues+'\n[/SOURCE_CUES]\n'+answer}]


def parse_lines(raw,group):
    if not isinstance(raw,str):
        raise ValueError('Non-text output')
    lines=raw.strip().splitlines()
    if len(lines)!=len(group):
        raise ValueError('Wrong output line count')
    results={}
    expected=[str(x[0]) for x in group]
    found=[]
    for line in lines:
        match=LINE.fullmatch(line.strip())
        if not match:
            raise ValueError('Malformed numbered subtitle line')
        key,text=match.groups()
        if key in results:
            raise ValueError('Duplicated numbered subtitle ID')
        results[key]=text
        found.append(key)
    if found!=expected:
        raise ValueError('Missing, extra, or reordered numbered subtitle IDs')
    return results


def accepted(text,english):
    return original.accepted(text,english)


def validate(raw,group,mode):
    if mode=='json':
        return semantic.parse_unit_reply(raw,group,accepted)
    return semantic.parse_unit_reply(parse_lines(raw,group),group,accepted)


def category(error):
    t=str(error).lower()
    if 'length cap' in t: return 'length_cap'
    if isinstance(error,json.JSONDecodeError):return 'invalid_json'
    if 'json' in t:return 'invalid_json'
    if 'keys' in t or 'line count' in t or 'reordered' in t or 'id' in t:
        return 'id_mapping_or_count'
    if 'numbered' in t:return 'invalid_line_format'
    if 'invalid japanese' in t or 'non-text' in t:return 'invalid_japanese'
    if 'dense' in t:return 'severe_density'
    if 'copied' in t or 'repeated' in t:return 'duplicate_dialogue'
    if 'timeout' in t or 'timed out' in t:return 'timeout'
    return 'other_'+type(error).__name__


def model_call(prompt,mode,opener=urlopen):
    """Same generation budget for each format; only JSON constrains format."""
    payload={'model':core.MODEL,'messages':prompt,'stream':False,'think':False,
             'options':{'temperature':0,'num_ctx':4096,'num_predict':OUTPUT_TOKENS},
             'keep_alive':'3m'}
    if mode=='json':
        payload['format']='json'
    request=Request(service.OLLAMA+'/api/chat',
                    data=json.dumps(payload,ensure_ascii=False).encode('utf8'),
                    headers={'Content-Type':'application/json'})
    with opener(request,timeout=240) as response:
        record=json.load(response)
    return {
        'content':str((record.get('message') or {}).get('content','')),
        'done_reason':record.get('done_reason'),
        'eval_count':record.get('eval_count'),
        'prompt_eval_count':record.get('prompt_eval_count'),
        'total_duration_ns':record.get('total_duration'),
    }


def result_path(state,item,mode):
    return Path(state)/'groups'/item['episode']/(
        '%05d-%05d-%s.json'%(item['cue_ids'][0],item['cue_ids'][-1],mode))


def run_one(state,item,group,mode,profile,ask=model_call):
    path=result_path(state,item,mode)
    if path.exists() or path.is_symlink():
        saved=json.loads(source_file(path))
        if any(saved.get(k)!=v for k,v in (
            ('schema',SCHEMA),('unit_sha',item['unit_sha']),
            ('episode',item['episode']),('ids',item['cue_ids']),('mode',mode))):
            raise RuntimeError('Saved lab response identity changed')
        return saved
    raw=''
    response={}
    translated=None
    failure=None
    try:
        response=ask(messages(group,mode,profile),mode)
        if not isinstance(response,dict):
            raise ValueError('Invalid local model return envelope')
        raw=response.get('content','')
        if not isinstance(raw,str):
            raise ValueError('Non-text model response')
        if response.get('done_reason')=='length':
            raise RuntimeError('Output length cap')
        translated=validate(raw,group,mode)
    except Exception as exc:
        failure=category(exc)
    data={
        'schema':SCHEMA,'episode':item['episode'],'stratum':item['stratum'],
        'unit_sha':item['unit_sha'],'ids':item['cue_ids'],'mode':mode,
        'status':'valid' if translated is not None else 'failed',
        'failure_category':failure,
        'translations':translated,
        'response':{
           'done_reason':response.get('done_reason'),
           'eval_count':response.get('eval_count'),
           'prompt_eval_count':response.get('prompt_eval_count'),
           'total_duration_ns':response.get('total_duration_ns'),
        },
        # Private diagnostic only; never included in console/status or GitHub.
        'raw_private':raw[:16000] if isinstance(raw,str) else '',
    }
    core.save(path,data)
    return data


def report(state=LAB,identity=None):
    if identity is None:
        identity=json.loads(source_file(Path(state)/'selection.json'))
    counts={}
    for stratum in ('formerly_failed','never_attempted'):
        counts[stratum]={}
        for mode in VARIANTS:
            subset=[x for x in identity['selected'] if x['stratum']==stratum]
            tally={'selected':len(subset),'attempted':0,'valid':0,'failed':0,
                   'failure_categories':{},'output_tokens_total':0}
            for item in subset:
                path=result_path(state,item,mode)
                if not path.is_file() or path.is_symlink(): continue
                data=json.loads(source_file(path))
                if data.get('unit_sha')!=item['unit_sha'] or data.get('mode')!=mode:
                    raise RuntimeError('Lab result identity mismatch')
                tally['attempted']+=1
                tally[data['status']]+=1
                if data['status']=='failed':
                    reason=data.get('failure_category') or 'unknown'
                    tally['failure_categories'][reason]=(
                        tally['failure_categories'].get(reason,0)+1)
                tally['output_tokens_total']+=int(
                    data.get('response',{}).get('eval_count') or 0)
            counts[stratum][mode]=tally
    return {'schema':SCHEMA,'completed_calls':sum(
       counts[s][m]['attempted'] for s in counts for m in VARIANTS),
       'expected_calls':len(identity['selected'])*len(VARIANTS),
       'by_stratum_and_format':counts}


def run(minutes=180,state=LAB,original_state=ORIGINAL,profile=core.PROFILE,
        ask=model_call,base=core.BASE):
    identity,source_rows=freeze(state,original_state,profile)
    profile_text=Path(profile).read_text(encoding='utf8')
    deadline=time.monotonic()+minutes*60
    with core.locks(base):
        if ask is model_call:
            core.preflight()
        for index,item in enumerate(identity['selected']):
            if time.monotonic()>=deadline:
                break
            group=group_for(item,source_rows[item['episode']])
            modes=VARIANTS if index%2==0 else tuple(reversed(VARIANTS))
            for mode in modes:
                if time.monotonic()>=deadline:
                    break
                saved=run_one(state,item,group,mode,profile_text,ask)
                print('FORMATLAB_RESULT',item['episode'],item['stratum'],
                      '%05d-%05d'%(group[0][0],group[-1][0]),
                      mode,saved['status'],
                      saved.get('failure_category') or 'ok',flush=True)
    result=report(state,identity)
    print('FORMATLAB_SUMMARY',json.dumps(result,sort_keys=True),flush=True)
    return result


def private_export(state=LAB,original_state=ORIGINAL,recovery_state=RECOVERY,
                   profile=core.PROFILE,output=None):
    identity,source_rows=freeze(state,original_state,profile)
    status=report(state,identity)
    if status['completed_calls']!=status['expected_calls']:
        raise RuntimeError('Format comparison incomplete; resume run first')
    baseline={}
    for ep in EPISODES:
        raw=source_file(Path(recovery_state)/'episodes'/ep/'pilot-recovered.ja.srt')
        english=source_rows[ep]
        japanese=service.parse_srt(raw)
        if len(japanese)!=len(english) or any(
                x[:4]!=y[:4] for x,y in zip(english,japanese)):
            raise RuntimeError('Existing recovered JA baseline timing differs')
        baseline[ep]={str(row[0]):row[4] for row in japanese}
    records=[]
    for item in identity['selected']:
        group=group_for(item,source_rows[item['episode']])
        outcomes={}
        for mode in VARIANTS:
            x=json.loads(source_file(result_path(state,item,mode)))
            if x.get('unit_sha')!=item['unit_sha'] or x.get('ids')!=item['cue_ids']:
                raise RuntimeError('Private result identity mismatch')
            outcomes[mode]={
              'status':x['status'],'failure_category':x['failure_category'],
              'japanese':x['translations'],'completion_tokens':
               x.get('response',{}).get('eval_count')}
        records.append({
            'episode':item['episode'],'stratum':item['stratum'],
            'cues':[{'id':r[0],'timing':r[1],'english':r[4],
                     'baseline_ja':baseline[item['episode']][str(r[0])]}
                    for r in group],
            'outputs':outcomes})
    payload={
       'schema':'bruiser-utterance-formatlab-private-review-v1',
       'model_id':identity['model_id'],
       'same_token_budget_each_format':OUTPUT_TOKENS,
       'summary':status,'groups':records,
    }
    content=(json.dumps(payload,ensure_ascii=False,indent=2)+'\n').encode()
    out=output or sys.stdout.buffer
    with tarfile.open(fileobj=out,mode='w|gz') as archive:
        info=tarfile.TarInfo('private_24_group_bilingual_review.json')
        info.size=len(content)
        info.mode=0o600
        archive.addfile(info,io.BytesIO(content))
    return status


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=('prepare','run','status','export'))
    p.add_argument('--minutes',type=int,default=180)
    args=p.parse_args(argv)
    if not 1<=args.minutes<=240:
        p.error('Minutes 1..240')
    try:
        if args.action=='prepare':
            identity,_=freeze()
            print('FORMATLAB_FROZEN',len(identity['selected']),
                  'groups; 4 failed + 4 untouched per episode')
        elif args.action=='run':
            run(minutes=args.minutes)
        elif args.action=='status':
            print(json.dumps(report(),indent=2,sort_keys=True))
        else:
            private_export()
    except Exception as exc:
        # No raw source/Japanese or private paths in terminal output.
        print('FORMATLAB_BLOCKED',type(exc).__name__,file=sys.stderr)
        return 1
    return 0


if __name__=='__main__':
    raise SystemExit(main())
