#!/usr/bin/env python3
"""Benchmark 002: subtitle-tuned e4b model using its documented native prompt.

64 frozen English cues, one CURRENT_SOURCE per Ollama /api/chat request.
PREVIOUS_SOURCE / PREVIOUS_TRANSLATION include only earlier successful
translations generated in THIS isolated benchmark window. No existing
published Japanese is injected as context. No job/SRT/DB/media modifications.
Private results only: never commit output to a public repository.
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
    from model_benchmark import checked_windows, installed_models, SOURCE_SHA, JOB_ID, CENTERS, sha
    from benchmark_localization import locked_idle, cps, save_private
    from analyze_model_benchmark import structural_flags
except ModuleNotFoundError:
    from tools.model_benchmark import checked_windows, installed_models, SOURCE_SHA, JOB_ID, CENTERS, sha
    from tools.benchmark_localization import locked_idle, cps, save_private
    from tools.analyze_model_benchmark import structural_flags

BENCHMARK_ID = 'primate-64cue-native-sub-e4b-v1'
MODEL = 'hf.co/17slever17/translate-gemma-4-sub-e4b-GGUF:Q4_K_XL'
MODEL_ID = '9ccfc3b07081'
MODEL_CARD = 'https://huggingface.co/17slever17/translate-gemma-4-sub-e4b-GGUF'

# Mirrors the developer's source/previous-context/current-source layout
# without injecting the generic multi-cue JSON adapter.
SYSTEM = (
    'TASK: Translate English subtitles into Japanese.\n'
    'STYLE: neutral, natural spoken Japanese appropriate for adult horror.\n'
    'Translate only CURRENT_SOURCE. PREVIOUS_SOURCE and PREVIOUS_TRANSLATION '
    'are context only. Preserve meaning, tone, slang, profanity, uncertainty, '
    'repetitions and incomplete speech. Return only the final translation '
    'without labels or commentary.'
)


def native_messages(current, history):
    """Only earlier cue pairs from THIS run may be previous translations."""
    chunks = []
    if history:
        prior = history[-2:]
        chunks.append('[PREVIOUS_SOURCE]\n' + '\n'.join(x['english'] for x in prior))
        chunks.append('[PREVIOUS_TRANSLATION]\n' +
                      '\n'.join(x['candidate_japanese'] for x in prior))
    chunks.append('[CURRENT_SOURCE]\n' + current['english'])
    return [
        {'role':'system','content':SYSTEM},
        {'role':'user','content':'\n\n'.join(chunks)},
    ]


def native_call(model, messages, timeout=120, opener=urlopen):
    request = Request(
        service.OLLAMA + '/api/chat',
        data=json.dumps({
            'model':model,
            'messages':messages,
            'stream':False,
            'think':False,
            'options':{
                'temperature':0,
                'num_ctx':4096,
                'num_predict':320,
            },
            'keep_alive':'5m',
        },ensure_ascii=False).encode('utf-8'),
        headers={'Content-Type':'application/json'}
    )
    with opener(request,timeout=timeout) as response:
        payload=json.load(response)
    if payload.get('done_reason')=='length':
        raise ValueError('Native model output truncated by num_predict')
    answer=payload.get('message',{}).get('content')
    if not isinstance(answer,str) or not answer.strip():
        raise ValueError('Empty native model answer')
    # No sanitizing/trimming model hallucinations beyond surrounding whitespace:
    # structural artifacts must be observed, not silently hidden from the test.
    return answer.strip()


def preflight(root, installed):
    job, groups = checked_windows(root)
    if installed.get(MODEL) != MODEL_ID:
        raise ValueError(
            'Frozen subtitle model was changed or is absent; expected ' +
            MODEL + ' ID ' + MODEL_ID + '; available ' +
            repr({name:ident for name,ident in installed.items()
                  if 'translate-gemma-4-sub' in name})
        )
    return job,groups


def run_calls(base,root,groups,call=native_call,max_seconds=1200):
    outputs=[]
    calls=[]
    started=time.monotonic()
    stop_reason=None
    with locked_idle(base,root):
        for group in groups:
            # No context from historical published Japanese and no bleeding from
            # different scenes. Only prior successful native outputs in this window.
            history=[]
            for row in group:
                if time.monotonic()-started >= max_seconds:
                    stop_reason='time_budget_exceeded'
                    break
                stamp=time.monotonic()
                messages=native_messages(row,history)
                error=None
                try:
                    answer=call(MODEL,messages,timeout=min(120,max_seconds))
                except Exception as exc:
                    answer=None
                    error=type(exc).__name__+': '+str(exc)[:160]
                elapsed=round(time.monotonic()-stamp,2)
                flags=structural_flags(answer)
                valid=service.acceptable_ja(answer,row['english'])
                outputs.append({
                    'cue_id':row['cue_id'],
                    'timing':row['timing'],
                    'english':row['english'],
                    'historical_japanese':row['japanese'],
                    'candidate_japanese':answer,
                    'valid_japanese':valid,
                    'structural_flags':flags,
                    'chars_per_second':cps(answer,row),
                    'previous_successful_context_cues':[h['cue_id'] for h in history[-2:]],
                })
                calls.append({'cue_id':row['cue_id'],'seconds':elapsed,
                              'error':error,'valid_japanese':valid,
                              'flags':flags})
                if valid and not flags:
                    history.append({'cue_id':row['cue_id'],
                                    'english':row['english'],
                                    'candidate_japanese':answer})
            if stop_reason:
                break
    return outputs,calls,stop_reason


def summary(outputs,calls):
    speeds=[x['chars_per_second'] for x in outputs
            if x['chars_per_second'] is not None]
    return {
        'attempted_cues':len(outputs),
        'valid_japanese':sum(bool(x['valid_japanese']) for x in outputs),
        'format_suspicions':sum(bool(x['structural_flags']) for x in outputs),
        'format_suspicion_cue_ids':[x['cue_id'] for x in outputs if x['structural_flags']],
        'over_14_cps':sum(x>14 for x in speeds),
        'median_cps':round(statistics.median(speeds),2) if speeds else None,
        'model_call_seconds':round(sum(c['seconds'] for c in calls),2),
        'calls_failed':sum(c['error'] is not None for c in calls),
        'semantic_quality':'NOT SCORED: manual Japanese-language review required',
    }


def execute(base,root,out,dry_run=False,max_seconds=1200):
    out=Path(out)
    if out.exists() and not dry_run:
        raise FileExistsError('Refusing to overwrite private benchmark results')
    installed=installed_models()
    _,groups=preflight(root,installed)
    if dry_run:
        print('PREFLIGHT OK:',BENCHMARK_ID)
        print('  Model:',MODEL, 'ID:',installed[MODEL])
        print('  Source:',SOURCE_SHA)
        print('  Frozen: 8 groups x 8 cues = 64 native calls')
        print('  Prompt: current segment only, up to 2 previous generated pairs')
        print('  No model calls or changes during preflight')
        return None
    outputs,calls,stopped=run_calls(base,root,groups,max_seconds=max_seconds)
    result={
        'schema':'bruiser-private-native-subtitle-benchmark-v1',
        'benchmark_id':BENCHMARK_ID,
        'generated_utc':dt.datetime.now(dt.timezone.utc).isoformat(),
        'source_sha256':SOURCE_SHA,
        'job_id':JOB_ID,
        'model':MODEL,'installed_model_id':installed[MODEL],
        'model_card':MODEL_CARD,'protocol':'native-current-source-with-past-pairs',
        'system_prompt_sha256':hashlib.sha256(SYSTEM.encode()).hexdigest(),
        'code_hashes':{
            'native_benchmark':sha(__file__),
            'candidate_service':sha(service.__file__),
        },
        'selected_center_cues':list(CENTERS),
        'batch_size':8,'context_window':2,
        'complete':stopped is None and len(outputs)==64,
        'stop_reason':stopped,
        'metrics':summary(outputs,calls),
        'calls':calls,'entries':outputs,
        'notes':'Structural checks are not Japanese language grades. Native prompt format differs from Benchmark 001 generic batch JSON. One call per cue; time is not directly comparable.'
    }
    save_private(out,result)
    print('PRIVATE NATIVE RESULTS:',out)
    print('Completed:',result['complete'], 'outputs:',len(outputs))
    print('Metrics:',json.dumps(result['metrics'],ensure_ascii=False))
    print('No source subtitles, published tracks or database checkpoints modified.')
    return result


def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--base',type=Path,default=Path.home()/'bruiser-pilot')
    ap.add_argument('--root',type=Path,default=Path.home()/'bruiser-pilot/subhub1-state')
    ap.add_argument('--out',type=Path,required=True)
    ap.add_argument('--dry-run',action='store_true')
    ap.add_argument('--max-seconds',type=int,default=1200)
    args=ap.parse_args(argv)
    try:
        if not 60<=args.max_seconds<=3600:
            raise ValueError('Max seconds must be between 60 and 3600')
        execute(args.base,args.root,args.out,args.dry_run,args.max_seconds)
    except (ValueError,OSError,RuntimeError) as exc:
        ap.error(str(exc))
    return 0

if __name__=='__main__':
    sys.exit(main())
