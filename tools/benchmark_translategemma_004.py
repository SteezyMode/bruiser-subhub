#!/usr/bin/env python3
"""Benchmark 004: Google TranslateGemma 4B, as documented, on frozen EN->JA cues.

Read-only source: 64 shared anchors from 001-003 plus 16 preregistered unseen
holdout cues. For the holdout only, also run the already validated subtitle
Gemma E4B using its own native prompt, for a fresh model-native comparison.

Only private, create-only JSON is written; never change source/JA SRT, SQLite
checkpoints, translation queue, or running production service.
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
    from benchmark_localization import get_rows, windows, locked_idle, cps, save_private
    from benchmark_native_subtitles import MODEL as SUB_MODEL, MODEL_ID as SUB_MODEL_ID
    from benchmark_native_subtitles import native_call as sub_native_call, native_messages
    from analyze_model_benchmark import structural_flags
except ModuleNotFoundError:
    from tools.model_benchmark import checked_windows, installed_models, SOURCE_SHA, JOB_ID, CENTERS, sha
    from tools.benchmark_localization import get_rows, windows, locked_idle, cps, save_private
    from tools.benchmark_native_subtitles import MODEL as SUB_MODEL, MODEL_ID as SUB_MODEL_ID
    from tools.benchmark_native_subtitles import native_call as sub_native_call, native_messages
    from tools.analyze_model_benchmark import structural_flags

BENCHMARK_ID = 'translategemma4b-model-native-80-plus-16-v1'
GOOGLE_MODEL = 'translategemma:4b'
GOOGLE_EXPECTED_ID = 'c49d986b0764'  # Official Ollama model-library digest prefix (Nov 2026)
GOOGLE_FAMILY = 'gemma3'
GOOGLE_QUANT = 'Q4_K_M'
HOLDOUT_CENTERS = (515, 625)
ANCHOR_COUNT = 64
HOLDOUT_COUNT = 16

# Verbatim Ollama TranslateGemma Prompt Guide, instantiated for en -> ja.
# The THREE newline characters preceding TEXT give two actual blank lines.
PROMPT_HEADER = (
    'You are a professional English (en) to Japanese (ja) translator. '
    'Your goal is to accurately convey the meaning and nuances of the original '
    'English text while adhering to Japanese grammar, vocabulary, and cultural '
    'sensitivities.\n'
    'Produce only the Japanese translation, without any additional explanations '
    'or commentary. Please translate the following English text into Japanese:'
)
# Only operational limits: model's own top_k/top_p/temperature defaults remain.
GOOGLE_OPTIONS = {'num_ctx':4096, 'num_predict':256}


def google_prompt(source):
    if not isinstance(source,str) or not source.strip():
        raise ValueError('Missing English source')
    return PROMPT_HEADER + '\n\n\n' + source


def ollama_post(path,payload,timeout=120,opener=urlopen):
    req=Request(service.OLLAMA+path,
                data=json.dumps(payload,ensure_ascii=False).encode('utf-8'),
                headers={'Content-Type':'application/json'})
    with opener(req,timeout=timeout) as resp:
        data=json.load(resp)
    if not isinstance(data,dict):
        raise ValueError('Ollama returned non-object')
    return data


def model_details(model=GOOGLE_MODEL,post=ollama_post):
    data=post('/api/show',{'model':model},timeout=20)
    return {
        'family':data.get('details',{}).get('family'),
        'quantization_level':data.get('details',{}).get('quantization_level'),
        'parameter_size':data.get('details',{}).get('parameter_size'),
        'model_params':data.get('parameters'),
        'template_sha256':hashlib.sha256(str(data.get('template','')).encode()).hexdigest(),
    }


def translate_google(source,post=ollama_post):
    payload={
        'model':GOOGLE_MODEL,
        'prompt':google_prompt(source),
        'stream':False,
        # No system override, few-shot history, translate JSON, custom temperature,
        # top-k, top-p, stop tokens or model template override.
        'options':GOOGLE_OPTIONS,
        'keep_alive':'5m',
    }
    data=post('/api/generate',payload,timeout=120)
    if data.get('done_reason')=='length':
        raise ValueError('TranslateGemma ran into 256-token output limit')
    result=data.get('response')
    if not isinstance(result,str) or not result.strip():
        raise ValueError('TranslateGemma returned empty output')
    return result.strip()


def source_groups(root):
    # checked_windows verifies the job's exact English source SHA and all 64
    # fixed anchor cues; do not change these between trials.
    _,anchors=checked_windows(root)
    _,rows=get_rows(root,JOB_ID)
    holdout=windows(rows,HOLDOUT_CENTERS,size=8)
    if len(holdout)!=2 or any(len(g)!=8 for g in holdout):
        raise ValueError('Frozen holdout not present as two full eight-cue windows')
    for g in holdout:
        if any(b['cue_id']!=a['cue_id']+1 for a,b in zip(g,g[1:])):
            raise ValueError('Holdout English cue IDs not consecutive')
    existing={row['cue_id'] for group in anchors for row in group}
    unseen={row['cue_id'] for group in holdout for row in group}
    if existing & unseen or len(unseen)!=16 or len(existing)!=64:
        raise ValueError('Holdout overlaps frozen previous benchmark anchors')
    return anchors,holdout


def full_preflight(found,details):
    if GOOGLE_MODEL not in found:
        raise ValueError('Missing Google TranslateGemma. Explicitly install via '
                         'ollama pull translategemma:4b; never auto-substitute a model')
    if not found[GOOGLE_MODEL].startswith(GOOGLE_EXPECTED_ID):
        raise ValueError('Unexpected official TranslateGemma Ollama ID: '+
                         found[GOOGLE_MODEL]+' (expected '+GOOGLE_EXPECTED_ID+
                         '). Stop and review version before comparing.')
    if (details.get('family')!=GOOGLE_FAMILY or
            details.get('quantization_level')!=GOOGLE_QUANT):
        raise ValueError('Wrong TranslateGemma architecture or quantization: '+str(details))
    if found.get(SUB_MODEL)!=SUB_MODEL_ID:
        raise ValueError('Existing benchmark 002 subtitle model missing or changed: '+
                         repr(found.get(SUB_MODEL)))


def run_arms(base,root,anchors,holdout,google_call=translate_google,
             subtitle_call=sub_native_call,max_seconds=1200):
    outputs=[]; calls=[]
    started=time.monotonic()
    stopped=None
    with locked_idle(base,root):
        # First translate the 64 prior anchor cues AND 16 held-out with Google,
        # then compare both distinct models freshly on the held-out only.
        for label,groups in (
            ('google_card',anchors+holdout),
            ('tuned_native_holdout',holdout),
        ):
            for group in groups:
                history=[]
                for row in group:
                    if time.monotonic()-started>=max_seconds:
                        stopped='time_budget_exceeded'
                        break
                    start=time.monotonic()
                    error=None
                    try:
                        if label=='google_card':
                            answer=google_call(row['english'])
                        else:
                            answer=subtitle_call(SUB_MODEL,native_messages(row,history),
                                                 timeout=120)
                    except Exception as exc:
                        answer=None
                        error=type(exc).__name__+': '+str(exc)[:160]
                    elapsed=round(time.monotonic()-start,2)
                    flags=structural_flags(answer)
                    valid=service.acceptable_ja(answer,row['english'])
                    outputs.append({
                        'arm':label,'cue_id':row['cue_id'],
                        'dataset':'heldout' if group in holdout else 'anchor',
                        'timing':row['timing'],
                        'english':row['english'],
                        'historical_japanese':row['japanese'],
                        'candidate_japanese':answer,
                        'valid_japanese':valid,
                        'structural_flags':flags,
                        'chars_per_second':cps(answer,row),
                        'previous_native_context_ids':[r['cue_id'] for r in history[-2:]]
                             if label=='tuned_native_holdout' else [],
                    })
                    calls.append({'arm':label,'cue_id':row['cue_id'],
                                  'elapsed_seconds':elapsed,'error':error})
                    if label=='tuned_native_holdout' and valid and not flags:
                        history.append({'cue_id':row['cue_id'],'english':row['english'],
                                        'candidate_japanese':answer})
                if stopped:break
            if stopped:break
    return outputs,calls,stopped


def metrics(outputs,calls):
    summary=[]
    for label in ('google_card','tuned_native_holdout'):
        rows=[r for r in outputs if r['arm']==label]
        t=[c for c in calls if c['arm']==label]
        readings=[r['chars_per_second'] for r in rows if r['chars_per_second'] is not None]
        summary.append({
            'arm':label,'attempted':len(rows),
            'valid_japanese':sum(bool(r['valid_japanese']) for r in rows),
            'format_suspicions':sum(bool(r['structural_flags']) for r in rows),
            'over_14_cps':sum(x>14 for x in readings),
            'median_cps':round(statistics.median(readings),2) if readings else None,
            'total_model_call_seconds':round(sum(c['elapsed_seconds'] for c in t),2),
            'failed_calls':sum(c['error'] is not None for c in t),
            'semantic_quality':'NOT SCORED: independent EN/JA review required',
        })
    return summary


def execute(base,root,out,source_only=False,dry_run=False,max_seconds=1200):
    if not (source_only or dry_run) and Path(out).exists():
        raise FileExistsError('Refusing to replace existing private benchmark file')
    anchors,holdout=source_groups(root)
    if source_only:
        print('SOURCE PREFLIGHT OK:',SOURCE_SHA)
        print('64 frozen prior anchor cues + 16 unseen holdout cues')
        print('No model download, GPU call or file changes')
        return None
    found=installed_models()
    details=model_details()
    full_preflight(found,details)
    if dry_run:
        print('FULL PREFLIGHT OK: model-native TranslateGemma benchmark')
        print('  Official TranslateGemma',GOOGLE_MODEL,found[GOOGLE_MODEL],
              details['family'],details['quantization_level'])
        print('  Existing tuned',SUB_MODEL,found[SUB_MODEL])
        print('  80 Google outputs + 16 tuned native unseen = 96 outputs')
        print('  No model inference, media or subtitle changes')
        return None
    outputs,calls,stopped=run_arms(base,root,anchors,holdout,max_seconds=max_seconds)
    result={
        'schema':'bruiser-private-translategemma-model-native-benchmark-v1',
        'benchmark_id':BENCHMARK_ID,
        'generated_utc':dt.datetime.now(dt.timezone.utc).isoformat(),
        'job_id':JOB_ID,'source_sha256':SOURCE_SHA,
        'anchor_center_cues':list(CENTERS),
        'holdout_center_cues':list(HOLDOUT_CENTERS),
        'model_ids':{GOOGLE_MODEL:found[GOOGLE_MODEL],
                     SUB_MODEL:found[SUB_MODEL]},
        'google_model_metadata':details,
        'google_prompt_sha256':hashlib.sha256(PROMPT_HEADER.encode()).hexdigest(),
        'google_options':GOOGLE_OPTIONS,
        'google_sampling':'Model defaults: top_k/top_p/temperature not overridden',
        'native_tuned_control':'Benchmark 002 exact native_messages/native_call',
        'code_hashes':{'benchmark':sha(__file__),'service':sha(service.__file__)},
        'complete':stopped is None and len(outputs)==96,
        'stop_reason':stopped,
        'metrics':metrics(outputs,calls),
        'calls':calls,'entries':outputs,
        'caution':'Scores not yet adjudicated. 64 anchor cues are previously seen; 16 heldout native head-to-head cues are the primary new comparison.',
    }
    save_private(out,result)
    print('PRIVATE MODEL COMPARISON:',out)
    print('Complete:',result['complete'],'total outputs:',len(outputs))
    for row in result['metrics']:
        print(row['arm'],str(row['valid_japanese'])+'/'+str(row['attempted']),
              'valid; format suspects',row['format_suspicions'],
              'time',row['total_model_call_seconds'],'sec')
    print('No checkpoint, queued job, media or published subtitle changed.')
    return result


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--base',type=Path,default=Path.home()/'bruiser-pilot')
    p.add_argument('--root',type=Path,default=Path.home()/'bruiser-pilot/subhub1-state')
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--source-only',action='store_true')
    p.add_argument('--dry-run',action='store_true')
    p.add_argument('--max-seconds',type=int,default=1200)
    args=p.parse_args(argv)
    try:
        if not 60<=args.max_seconds<=3600:
            raise ValueError('max-seconds must be between 60 and 3600')
        execute(args.base,args.root,args.out,args.source_only,args.dry_run,
                args.max_seconds)
    except (ValueError,OSError,RuntimeError) as exc:
        p.error(str(exc))
    return 0


if __name__=='__main__':
    sys.exit(main())
