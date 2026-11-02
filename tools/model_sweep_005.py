#!/usr/bin/env python3
"""Benchmark 005: repeatable model-native EN->JA translation on 64 NEW cues.

Read only: the frozen Primate English source in jobs.sqlite3 (SQLite mode=ro).
Output: one create-only PRIVATE JSON per model. No queue/SRT/media writes.
Use one --model at a time so failed/slow large models cannot erase results.
"""
from __future__ import annotations
import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import statistics
import subprocess
import sys
import time
from urllib.request import Request, urlopen

import service
try:
    from benchmark_localization import get_rows, windows, locked_idle, cps, save_private
    from model_benchmark import SOURCE_SHA, JOB_ID, sha, installed_models
    from benchmark_native_subtitles import (
        MODEL as SUB_MODEL, MODEL_ID as SUB_MODEL_ID,
        native_call, native_messages,
    )
    from benchmark_translategemma_004 import google_prompt
    from analyze_model_benchmark import structural_flags
except ModuleNotFoundError:
    from tools.benchmark_localization import get_rows, windows, locked_idle, cps, save_private
    from tools.model_benchmark import SOURCE_SHA, JOB_ID, sha, installed_models
    from tools.benchmark_native_subtitles import (
        MODEL as SUB_MODEL, MODEL_ID as SUB_MODEL_ID,
        native_call, native_messages,
    )
    from tools.benchmark_translategemma_004 import google_prompt
    from tools.analyze_model_benchmark import structural_flags

BENCHMARK_ID='primate-64-new-cues-native-model-sweep-v1'
# Registered BEFORE model installation. Eight contiguous 8-cue groups, disjoint
# from all 001–004 benchmark sets including 511–518 and 621–628.
CENTERS=(91,127,175,235,303,343,543,691)
FAMILY={
    'tuned':{'model':SUB_MODEL,'kind':'native','quant':'Q4_K_XL','download_gb':0},
    'cat7':{'model':'hf.co/mradermacher/CAT-Translate-7b-GGUF:Q4_K_M',
            'kind':'cat','quant':'Q4_K_M','download_gb':4.6},
    'hy7':{'model':'hf.co/tencent/Hy-MT2-7B-GGUF:Q4_K_M',
           'kind':'hy','quant':'Q4_K_M','download_gb':4.62},
    'google12':{'model':'translategemma:12b',
                'kind':'google','quant':'Q4_K_M','family':'gemma3',
                'download_gb':8.1},
}
EXCLUDED_IDS=set()
for anchor in (35,71,143,207,265,380,428,465,515,625):
    EXCLUDED_IDS.update(range(anchor-4,anchor+4))
# Explanation: prior windows for center 35 are 31..38, and so on.

CAT_PROMPT='Translate the following English text into Japanese.\n\n'
HY_PROMPT=('Translate the following text into Japanese. Note that you should '
           'only output the translated result without any additional explanation:\n')
# Author recommended for Hy-MT2 1.8B/7B; Ollama uses 'repeat_penalty'
# in place of the GGUF card's 'repetition_penalty'.
HY_OPTIONS={'temperature':0.7,'top_p':0.6,'top_k':20,
            'repeat_penalty':1.05,'num_ctx':4096,'num_predict':256}
CAT_OPTIONS={'num_ctx':4096,'num_predict':256}
GOOGLE_OPTIONS={'num_ctx':4096,'num_predict':256}


def dataset(root):
    job,all_rows=get_rows(root,JOB_ID)
    if job['source_sha']!=SOURCE_SHA:
        raise ValueError('English source SHA changed; do NOT benchmark mismatched text')
    groups=windows(all_rows,CENTERS,size=8)
    if len(groups)!=8 or any(len(g)!=8 for g in groups):
        raise ValueError('Exactly 8 disjoint windows of 8 required')
    ids=[]
    for g in groups:
        ids.extend(r['cue_id'] for r in g)
        if any(b['cue_id']!=a['cue_id']+1 for a,b in zip(g,g[1:])):
            raise ValueError('Nonconsecutive source cues')
    if len(ids)!=64 or len(set(ids))!=64 or set(ids)&EXCLUDED_IDS:
        raise ValueError('Reused a cue from earlier benchmarks')
    return groups


def ollama_post(endpoint,payload,timeout=180,opener=urlopen):
    req=Request(service.OLLAMA+endpoint,
                data=json.dumps(payload,ensure_ascii=False).encode('utf-8'),
                headers={'Content-Type':'application/json'})
    with opener(req,timeout=timeout) as handle:
        obj=json.load(handle)
    if not isinstance(obj,dict):
        raise ValueError('Ollama returned non-object')
    return obj


def model_metadata(key,found,post=ollama_post):
    spec=FAMILY[key]
    name=spec['model']
    if name not in found:
        raise ValueError('Not installed: '+name+'; model download is a separate operation')
    if key=='tuned' and found[name]!=SUB_MODEL_ID:
        raise ValueError('Original tuned control digest changed: '+found[name])
    obj=post('/api/show',{'model':name},timeout=30)
    details=obj.get('details') or {}
    q=details.get('quantization_level')
    if q!=spec['quant']:
        raise ValueError('Quantization mismatch for '+name+': '+str(q))
    if spec.get('family') and details.get('family')!=spec['family']:
        raise ValueError('Wrong model architecture: '+str(details.get('family')))
    return {
        'name':name,'ollama_id':found[name],'family':details.get('family'),
        'parameter_size':details.get('parameter_size'),'quantization':q,
        'template_sha256':hashlib.sha256(str(obj.get('template','')).encode()).hexdigest(),
        'parameters':obj.get('parameters'),
    }


def source_prompt(kind,english):
    if kind=='cat':
        return CAT_PROMPT+english
    if kind=='hy':
        return HY_PROMPT+english
    if kind=='google':
        return google_prompt(english)
    raise ValueError('Unknown prompt: '+kind)


def generate(key,english,history,post=ollama_post,tuned_call=native_call):
    spec=FAMILY[key]
    if key=='tuned':
        return tuned_call(spec['model'],native_messages(
            {'english':english},history),timeout=180),{}
    prompt=source_prompt(spec['kind'],english)
    opts={'cat':CAT_OPTIONS,'hy':HY_OPTIONS,'google':GOOGLE_OPTIONS}[spec['kind']]
    if spec['kind']=='google':
        payload={'model':spec['model'],'prompt':prompt,
                 'stream':False,'options':opts,'keep_alive':'5m'}
        obj=post('/api/generate',payload,timeout=300)
        result=obj.get('response')
    else:
        payload={'model':spec['model'],
                 'messages':[{'role':'user','content':prompt}],
                 'stream':False,'think':False,
                 'options':opts,'keep_alive':'5m'}
        obj=post('/api/chat',payload,timeout=300)
        result=(obj.get('message') or {}).get('content')
    if obj.get('done_reason')=='length':
        raise ValueError('Model reached the 256-token output cap')
    if not isinstance(result,str) or not result.strip():
        raise ValueError('Model returned no translation')
    stats={k:obj.get(k) for k in (
        'total_duration','load_duration','prompt_eval_count',
        'prompt_eval_duration','eval_count','eval_duration'
    ) if obj.get(k) is not None}
    return result.strip(),stats


def run_one(key,base,root,groups,translate=generate,max_seconds=1800):
    start=time.monotonic()
    entries=[];calls=[];stopped=None
    consecutive_failures=0
    with locked_idle(base,root):
        for group in groups:
            history=[]
            for row in group:
                if time.monotonic()-start >= max_seconds:
                    stopped='time_budget_exceeded'
                    break
                tick=time.monotonic()
                error=None;answer=None;stats={}
                try:
                    answer,stats=translate(key,row['english'],history)
                except Exception as exc:
                    error=type(exc).__name__+': '+str(exc)[:180]
                elapsed=round(time.monotonic()-tick,2)
                consecutive_failures=consecutive_failures+1 if error else 0
                flags=structural_flags(answer)
                valid=service.acceptable_ja(answer,row['english'])
                entries.append({
                    'cue_id':row['cue_id'],'timing':row['timing'],
                    'english':row['english'],'candidate_japanese':answer,
                    'valid_japanese':bool(valid),'flags':flags,
                    'chars_per_second':cps(answer,row),
                    'context_from_cues':[x['cue_id'] for x in history[-2:]]
                         if key=='tuned' else [],
                })
                calls.append({'cue_id':row['cue_id'],
                              'wall_seconds':elapsed,'error':error,
                              'ollama_stats':stats})
                if key=='tuned' and valid and not flags:
                    history.append({'cue_id':row['cue_id'],'english':row['english'],
                                    'candidate_japanese':answer})
                if consecutive_failures>=3:
                    stopped='three_consecutive_model_errors'
                    break
            if stopped:
                break
    return entries,calls,stopped


def metrics(rows,calls):
    speeds=[r['chars_per_second'] for r in rows if r['chars_per_second'] is not None]
    return {
        'attempted':len(rows),
        'valid_japanese':sum(r['valid_japanese'] for r in rows),
        'format_flagged':sum(bool(r['flags']) for r in rows),
        'over_14_cps':sum(v>14 for v in speeds),
        'median_cps':round(statistics.median(speeds),2) if speeds else None,
        'wall_seconds_sum':round(sum(x['wall_seconds'] for x in calls),2),
        'call_errors':sum(x['error'] is not None for x in calls),
        'semantic_quality':'NOT SCORED. Requires blinded EN/JA and viewer review.',
    }


def safe_sysinfo(run=subprocess.run):
    data={}
    for label,args in (
        ('ollama_version',['ollama','--version']),
        ('gpu',['nvidia-smi','--query-gpu=name,memory.total,memory.free',
                '--format=csv,noheader']),
    ):
        try:
            result=run(args,capture_output=True,text=True,timeout=8)
            data[label]=result.stdout.strip() if result.returncode==0 else None
        except (OSError,subprocess.TimeoutExpired):
            data[label]=None
    return data


def execute(key,root,base,out,dry_run=False,max_seconds=1800):
    if key not in FAMILY:
        raise ValueError('Unknown model arm: '+key)
    groups=dataset(root)
    if not dry_run and Path(out).exists():
        raise FileExistsError('Refusing to overwrite private result: '+str(out))
    found=installed_models()
    identity=model_metadata(key,found)
    if dry_run:
        print('PREFLIGHT:',key,identity['name'],identity['ollama_id'])
        print('  FAMILY:',identity['family'],'QUANT:',identity['quantization'])
        print('  SOURCE SHA:',SOURCE_SHA,'FROZEN:',len(groups),'x8 = 64 NEW cues')
        print('  No model inference or private output written.')
        return None
    entries,calls,stopped=run_one(key,base,root,groups,max_seconds=max_seconds)
    result={
        'schema':'bruiser-private-model-sweep-005-v1',
        'benchmark_id':BENCHMARK_ID,
        'generated_utc':dt.datetime.now(dt.timezone.utc).isoformat(),
        'source_sha256':SOURCE_SHA,'job_id':JOB_ID,
        'arm':key,'centers':list(CENTERS),
        'model':identity,'backend':'ollama',
        'prompt_spec':{'tuned':'Benchmark 002 native-current/previous pairs',
                       'cat7':'Official CAT source-language instruction + chat template',
                       'hy7':'Official Hy-MT2 English translation-only instruction',
                       'google12':'Official TranslateGemma single-user prompt, 2 blank lines'}[key],
        'runtime_options':{'tuned':'Benchmark 002 native default',
                           'cat7':CAT_OPTIONS,'hy7':HY_OPTIONS,
                           'google12':GOOGLE_OPTIONS}[key],
        'sysinfo':safe_sysinfo(),
        'code_sha256':sha(__file__),
        'complete':stopped is None and len(entries)==64,
        'stop_reason':stopped,
        'metrics':metrics(entries,calls),'calls':calls,'entries':entries,
        'quality_note':'Output is for private assessment only. Structural validity is not fidelity.',
    }
    save_private(out,result)
    print('PRIVATE OUTPUT:',out)
    print('COMPLETE:',result['complete'],'SUMMARY:',json.dumps(result['metrics']))
    print('No published subtitles, SQLite cues, media or queue changed.')
    return result


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--model',required=True,choices=sorted(FAMILY))
    p.add_argument('--base',type=Path,default=Path.home()/'bruiser-pilot')
    p.add_argument('--root',type=Path,default=Path.home()/'bruiser-pilot/subhub1-state')
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--dry-run',action='store_true')
    p.add_argument('--max-seconds',type=int,default=1800)
    args=p.parse_args(argv)
    try:
        if not 60<=args.max_seconds<=14400:raise ValueError('max-seconds must be 60..14400')
        result=execute(args.model,args.root,args.base,args.out,args.dry_run,args.max_seconds)
        if result is not None and not result['complete']:
            print('INCOMPLETE benchmark; preserved partial private results.',file=sys.stderr)
            return 1
    except (ValueError,OSError,RuntimeError) as err:
        p.error(str(err))
    return 0


if __name__=='__main__':
    sys.exit(main())
