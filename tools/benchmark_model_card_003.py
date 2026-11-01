#!/usr/bin/env python3
"""Benchmark 003: exact model-card-style prompt vs SAME prompt with context-gap gating.

ONE installed subtitle-tuned Ollama model. Same 64 frozen English cues as tests
001/002. Two arms differ only in whether previous-pair context is dropped
after >8 seconds of silence. Neither arm uses previously published Japanese.
All translations remain PRIVATE and no SQLite/media/SRT files are modified.
"""
from __future__ import annotations
import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import statistics
import sys
import time
from urllib.request import Request, urlopen

import service
try:
    from model_benchmark import checked_windows, installed_models, CENTERS, JOB_ID, SOURCE_SHA, sha
    from benchmark_localization import locked_idle, cps, save_private
    from benchmark_native_subtitles import MODEL, MODEL_ID
    from analyze_model_benchmark import structural_flags
except ModuleNotFoundError:
    from tools.model_benchmark import checked_windows, installed_models, CENTERS, JOB_ID, SOURCE_SHA, sha
    from tools.benchmark_localization import locked_idle, cps, save_private
    from tools.benchmark_native_subtitles import MODEL, MODEL_ID
    from tools.analyze_model_benchmark import structural_flags

ID = 'primate-model-card-one-prev-gap-v1'
ARMS = ('card_previous', 'card_previous_gap8')
GAP_LIMIT_SECONDS = 8.0
SYSTEM = (
    'TASK: Translate English subtitles into Japanese.\n'
    'STYLE: neutral.\n'
    'Translate only CURRENT_SOURCE. PREVIOUS_SOURCE and PREVIOUS_TRANSLATION '
    'are context only. Preserve meaning, tone, slang, profanity, uncertainty, '
    'repetitions and incomplete speech. Return only the final translation '
    'without labels or commentary.'
)
# The model card's llama-cpp-python example specifies n_ctx=1344, max_tokens
# 256 and temperature=0. We use the already installed Ollama backend, not
# llama.cpp. Runtime equivalence is NOT claimed.
OPTIONS = {'temperature':0, 'num_ctx':1344, 'num_predict':256}


def gap_seconds(previous,current):
    return round(max(0, current['start_ms'] - previous['end_ms']) / 1000, 3)


def context_for(previous,current,arm):
    """Immediate previous generated cue only; never reach farther back."""
    if arm not in ARMS:
        raise ValueError('Unknown experiment arm: '+str(arm))
    if previous is None:
        return None
    # Both items must be consecutive in the frozen source, not merely close.
    if previous['cue_id']+1 != current['cue_id']:
        return None
    if arm == 'card_previous_gap8' and gap_seconds(previous,current) > GAP_LIMIT_SECONDS:
        return None
    if not previous.get('clean'):
        return None
    return previous


def messages(row,previous=None):
    parts=[]
    if previous is not None:
        parts=['[PREVIOUS_SOURCE]\n'+previous['english'],
               '[PREVIOUS_TRANSLATION]\n'+previous['candidate_japanese']]
    parts.append('[CURRENT_SOURCE]\n'+row['english'])
    return [{'role':'system','content':SYSTEM},
            {'role':'user','content':'\n\n'.join(parts)}]


def query(model,prompt,timeout=120,opener=urlopen):
    request = Request(
        service.OLLAMA+'/api/chat',
        data=json.dumps({
            'model':model,'messages':prompt,'stream':False,'think':False,
            'options':OPTIONS,'keep_alive':'5m'
        },ensure_ascii=False).encode(),
        headers={'Content-Type':'application/json'}
    )
    with opener(request,timeout=timeout) as response:
        parsed=json.load(response)
    if parsed.get('done_reason')=='length':
        raise ValueError('Model ran out of generation tokens')
    content=parsed.get('message',{}).get('content')
    if not isinstance(content,str) or not content.strip():
        raise ValueError('No generated Japanese')
    return content.strip()


def preflight(root,found):
    if found.get(MODEL)!=MODEL_ID:
        raise ValueError('Installed model ID mismatch or model absent: expected '+
                         MODEL_ID+', found '+str(found.get(MODEL)))
    return checked_windows(root)[1]


def run_arms(base,root,groups,call=query,max_seconds=1200):
    rows=[];stats=[]
    started=time.monotonic()
    stopped=None
    with locked_idle(base,root):
        for wi,group in enumerate(groups):
            # Rotate first arm between windows for better control of warmup.
            for arm in (ARMS if wi%2==0 else ARMS[::-1]):
                previous=None
                for row in group:
                    if time.monotonic()-started>=max_seconds:
                        stopped='time_budget_exceeded'
                        break
                    prior=context_for(previous,row,arm)
                    prompt=messages(row,prior)
                    start=time.monotonic()
                    failure=None
                    try:
                        translated=call(MODEL,prompt)
                    except Exception as exc:
                        translated=None
                        failure=type(exc).__name__+': '+str(exc)[:160]
                    seconds=round(time.monotonic()-start,2)
                    flags=structural_flags(translated)
                    valid=service.acceptable_ja(translated,row['english'])
                    rows.append({
                        'arm':arm,'cue_id':row['cue_id'],'timing':row['timing'],
                        'english':row['english'],
                        'candidate_japanese':translated,
                        'historical_japanese':row['japanese'],
                        'context_cue_id':prior['cue_id'] if prior else None,
                        'gap_from_previous_seconds':gap_seconds(previous,row) if previous else None,
                        'valid_japanese':valid,'structural_flags':flags,
                        'chars_per_second':cps(translated,row),
                    })
                    stats.append({'arm':arm,'cue_id':row['cue_id'],
                                  'seconds':seconds,'error':failure})
                    previous={'cue_id':row['cue_id'],'english':row['english'],
                              'end_ms':row['end_ms'],
                              'candidate_japanese':translated,
                              'clean':bool(valid and not flags)}
                if stopped:break
            if stopped:break
    return rows,stats,stopped


def overview(rows,calls):
    stats=[]
    for arm in ARMS:
        selected=[r for r in rows if r['arm']==arm]
        durations=[r['chars_per_second'] for r in selected if r['chars_per_second'] is not None]
        trial=[x for x in calls if x['arm']==arm]
        stats.append({
            'arm':arm,'attempted':len(selected),
            'valid_japanese':sum(r['valid_japanese'] for r in selected),
            'format_suspicions':sum(bool(r['structural_flags']) for r in selected),
            'context_used':sum(r['context_cue_id'] is not None for r in selected),
            'over_14_cps':sum(x>14 for x in durations),
            'median_cps':round(statistics.median(durations),2) if durations else None,
            'calls_failed':sum(x['error'] is not None for x in trial),
            'model_call_seconds':round(sum(x['seconds'] for x in trial),2),
            'semantic_quality':'NOT SCORED: human EN/JA review required',
        })
    return stats


def execute(base,root,out,dry_run=False,max_seconds=1200):
    out=Path(out)
    if out.exists() and not dry_run:
        raise FileExistsError('Refusing to overwrite private experiment output')
    found=installed_models()
    groups=preflight(root,found)
    if dry_run:
        print('PREFLIGHT OK:',ID)
        print('Model',MODEL,'ID',found[MODEL])
        print('English source SHA',SOURCE_SHA)
        print('64 frozen source cues; 2 x 64 = 128 calls')
        print('Arm 1: one previous generated source/JA pair')
        print('Arm 2: same prompt and options, omit prior pair if gap >8 sec')
        print('No Ollama inference or DB/media/subtitle changes in preflight')
        return None
    rows,calls,stopped=run_arms(base,root,groups,max_seconds=max_seconds)
    result={
        'schema':'bruiser-private-card-prompt-benchmark-v1',
        'benchmark_id':ID,
        'generated_utc':dt.datetime.now(dt.timezone.utc).isoformat(),
        'model':MODEL,'installed_model_id':found[MODEL],
        'job_id':JOB_ID,'source_sha256':SOURCE_SHA,
        'selected_center_cues':list(CENTERS),
        'arms':list(ARMS),'context_gap_threshold_seconds':GAP_LIMIT_SECONDS,
        'system_prompt_sha256':hashlib.sha256(SYSTEM.encode()).hexdigest(),
        'generation_options':OPTIONS,
        'backend':'Ollama /api/chat (NOT llama.cpp exact runtime)',
        'code_hashes':{
            'card_benchmark':sha(__file__),
            'service':sha(service.__file__),
        },
        'complete':stopped is None and len(rows)==2*64,
        'stop_reason':stopped,
        'metrics':overview(rows,calls),'calls':calls,'entries':rows,
        'notes':'Model-card-style prompt. Same frozen 64 cues. No Japanese quality claims; comparison to Benchmark 002 changes prompt, context count and generation limits.'
    }
    save_private(out,result)
    print('PRIVATE EXPERIMENT FILE:',out)
    print('Complete:',result['complete'],'outputs:',len(rows),
          'stop:',stopped or 'none')
    for m in result['metrics']:
        print(m['arm']+': '+str(m['valid_japanese'])+'/'+str(m['attempted'])+
              ' valid; formatting suspects='+str(m['format_suspicions'])+
              '; context used='+str(m['context_used'])+
              '; model seconds='+str(m['model_call_seconds']))
    print('No production Japanese, checkpoints, media or translation settings modified.')
    return result


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--base',type=Path,default=Path.home()/'bruiser-pilot')
    p.add_argument('--root',type=Path,default=Path.home()/'bruiser-pilot/subhub1-state')
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--dry-run',action='store_true')
    p.add_argument('--max-seconds',type=int,default=1200)
    args=p.parse_args(argv)
    try:
        if args.max_seconds<60 or args.max_seconds>3600:
            raise ValueError('max seconds must be between 60 and 3600')
        execute(args.base,args.root,args.out,args.dry_run,args.max_seconds)
    except (ValueError,OSError,RuntimeError) as error:
        p.error(str(error))
    return 0


if __name__=='__main__':
    sys.exit(main())
