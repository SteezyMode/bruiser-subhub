#!/usr/bin/env python3
"""Experiment 006: frozen unseen multi-title subtitle sweep, PRIVATE outputs.

Subcommands: prepare | arm MODEL | blind | status.
Every real generation requires a pre-existing immutable source manifest.
No production SQLite, movie, approved Japanese SRT, or queue updates.
"""
from __future__ import annotations
import argparse
import csv
import gc
import hashlib
import json
import os
from pathlib import Path
import random
import secrets
import sqlite3
import subprocess
import sys
import time

import service
try:
    from benchmark_localization import locked_idle, cps
    from benchmark_native_subtitles import native_call, native_messages
    from benchmark_translategemma_004 import google_prompt
    from model_sweep_005 import (
        ollama_post, HY_OPTIONS, HY_PROMPT, CAT_PROMPT, GOOGLE_OPTIONS
    )
    from model_benchmark import installed_models
    from analyze_model_benchmark import structural_flags
except ModuleNotFoundError:
    from tools.benchmark_localization import locked_idle, cps
    from tools.benchmark_native_subtitles import native_call, native_messages
    from tools.benchmark_translategemma_004 import google_prompt
    from tools.model_sweep_005 import (
        ollama_post, HY_OPTIONS, HY_PROMPT, CAT_PROMPT, GOOGLE_OPTIONS
    )
    from tools.model_benchmark import installed_models
    from tools.analyze_model_benchmark import structural_flags

ROOT=Path.home()/'bruiser-pilot/subhub1-state'
BASE=Path.home()/'bruiser-pilot'
OUT=Path.home()/'bruiser-pilot/subhub-benchmark-006'
OLD_SHA='8967cfea3f6552c0a6b1645da13e0d79e62be2decb95c02c653e6a345c3b645a'
VERSION='bruiser-006-new-titles-v1'
# FROZEN: names, directions, native prompting and candidate list.
ROSTER={
 'cat33':('hf','cyberagent/CAT-Translate-3.3b'),
 'cat7':('hf','cyberagent/CAT-Translate-7b'),
 'tuned_e4b':('native','hf.co/17slever17/translate-gemma-4-sub-e4b-GGUF:Q4_K_XL'),
 'tuned_e2b':('native','hf.co/17slever17/translate-gemma-4-sub-e2b-GGUF:Q4_K_XL'),
 'hy7':('hy','hf.co/tencent/Hy-MT2-7B-GGUF:Q4_K_M'),
 'hy18':('hy','hf.co/tencent/Hy-MT2-1.8B-GGUF:Q4_K_M'),
 'index2':('index','hf.co/IndexTeam/Index-Translate-2B-GGUF:Q4_K_M'),
 'google4':('google','translategemma:4b'),
 'google12':('google','translategemma:12b'),
 'generic_e4b':('native','gemma4:e4b-it-qat'),
}
# Frozen IDs from the already-observed original installation; never silently
# repull a changed control checkpoint.
PINNED={
 'tuned_e4b':'9ccfc3b07081',
 'tuned_e2b':'cf9660639cb8',
 'hy7':'c98ad63514f7',
 'google4':'c49d986b0764',
 'google12':'c2f9a9ca1ec7',
}
INDEX_HEADER='请将以下英语文本翻译为日语，直接输出翻译结果，不要进行任何解释。\n\n'
SCENE_MS=5*60*1000
MAX_SCENES=6
MIN_CUES=200


def canonical(data):
    return json.dumps(data,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')


def digest(data):
    return hashlib.sha256(canonical(data)).hexdigest()


def store_exclusive(path, obj):
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w',encoding='utf-8') as fp:
        json.dump(obj,fp,ensure_ascii=False,indent=2)
        fp.write('\n')
        fp.flush()
        os.fsync(fp.fileno())


def store_text_exclusive(path, text):
    """Write actual .srt bytes privately; never replace an existing review file."""
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w',encoding='utf-8') as fp:
        fp.write(text)
        fp.flush()
        os.fsync(fp.fileno())


def fetch_sources(root=ROOT):
    db=(Path(root)/'jobs.sqlite3').resolve(strict=True)
    with sqlite3.connect(db.as_uri()+'?mode=ro',uri=True,timeout=10) as cn:
        cn.row_factory=sqlite3.Row
        cn.execute('PRAGMA query_only=ON')
        jobs=[dict(x) for x in cn.execute(
            "SELECT id,source_sha,status,audio_lang,scope FROM jobs "
            "WHERE status IN ('published','queued','translated') ORDER BY id"
        )]
        sources=[]
        for j in jobs:
            if j['source_sha']==OLD_SHA or j['audio_lang']!='eng':
                continue
            rows=[dict(x) for x in cn.execute(
                "SELECT cue_id,english,timing,start_ms,end_ms FROM cues "
                "WHERE job_id=? ORDER BY start_ms,cue_id",(j['id'],))]
            if len(rows)<100 or sum(bool(x['english'].strip()) for x in rows)<100:
                continue
            if rows[-1]['end_ms']-rows[0]['start_ms']<40*60*1000:
                continue
            sources.append({'job_id':j['id'],'source_sha':j['source_sha'],'rows':rows})
    return sources


def ranked(seed, values, key):
    return sorted(values,key=lambda x: hashlib.sha256(
        (seed+'|'+key(x)).encode('utf-8')).hexdigest())


def candidate_windows(source, seed):
    rows=source['rows']
    lo=rows[0]['start_ms']+4*60*1000
    hi=rows[-1]['end_ms']-SCENE_MS-4*60*1000
    result=[]
    if hi<=lo:
        return []
    for offset in range((lo//SCENE_MS)*SCENE_MS,hi,SCENE_MS):
        if offset<lo:
            continue
        candidates=[r for r in rows
                    if offset<=r['start_ms']<offset+SCENE_MS and
                    r['english'].strip()]
        if len(candidates)<25:
            continue
        result.append({
            'job_id':source['job_id'],'source_sha':source['source_sha'],
            'start_ms':offset,'end_ms':offset+SCENE_MS,
            'cues':candidates,
        })
    return ranked(seed,result,lambda s:s['job_id']+':'+str(s['start_ms']))


def choose_scenes(sources, seed):
    eligible=ranked(seed,sources,lambda s:s['source_sha'])
    if len(eligible)<4:
        raise ValueError('Need 4 different English subtitle sources (3 test + 1 sealed holdout)')
    # Three test titles, ONE completely unused title (no generated outputs).
    test=eligible[:3]
    holdout=eligible[3]
    windows={s['job_id']:candidate_windows(s,seed) for s in test}
    if any(not windows[s['job_id']] for s in test):
        raise ValueError('Chosen test title lacks a 5-minute dialogue window; no cherry-picked replacement')
    chosen=[]
    # Two scenes from the first title; one each from the other two.
    for i,source in enumerate(test):
        for w in windows[source['job_id']][:2 if i==0 else 1]:
            chosen.append(w)
    used={(s['job_id'],s['start_ms']) for s in chosen}
    while sum(len(s['cues']) for s in chosen)<MIN_CUES and len(chosen)<MAX_SCENES:
        available=[]
        for source in test:
            for w in windows[source['job_id']]:
                if (w['job_id'],w['start_ms']) in used:
                    continue
                if any(w['job_id']==c['job_id'] and
                       abs(w['start_ms']-c['start_ms'])<SCENE_MS
                       for c in chosen):
                    continue
                available.append(w)
                break
        if not available:
            break
        nxt=ranked(seed,available,lambda x:x['job_id']+':'+str(x['start_ms']))[0]
        chosen.append(nxt)
        used.add((nxt['job_id'],nxt['start_ms']))
    if len(chosen)<4 or sum(len(s['cues']) for s in chosen)<MIN_CUES:
        raise ValueError('Not enough frozen new dialogue: >=4 five-minute scenes and >=200 cues required')
    # Deterministic scene order; no results have been generated yet.
    chosen.sort(key=lambda x:(x['job_id'],x['start_ms']))
    for i,scene in enumerate(chosen,1):
        scene['scene_id']=f's{i:02d}'
    return chosen,{'job_id':holdout['job_id'],'source_sha':holdout['source_sha']}


def prepare(root=ROOT, out=OUT):
    out=Path(out)
    manifest=out/'manifest.json'
    if manifest.exists():
        data=load_manifest(out)
        print('REUSING FROZEN MANIFEST:',data['manifest_sha256'])
        return data
    sources=fetch_sources(root)
    seed=secrets.token_hex(16)
    scenes,holdout=choose_scenes(sources,seed)
    payload={
        'schema':VERSION,'selection_seed':seed,
        'source':'SQLite read only; no prior Japanese, no Primate',
        'holdout_reserved':holdout,
        'roster':{k:{'kind':kind,'model':name} for k,(kind,name) in ROSTER.items()},
        'scenes':scenes,
    }
    data={'manifest_sha256':digest(payload),'payload':payload}
    store_exclusive(manifest,data)
    print('FROZEN MANIFEST SHA:',data['manifest_sha256'])
    print('FROZEN SCENES:',len(scenes),
          'SOURCE CUES:',sum(len(s['cues']) for s in scenes),
          'TEST TITLES:',len(set(s['job_id'] for s in scenes)),
          'HOLDOUT TITLES:',1)
    print('PRIVATE source text in manifest; never commit.')
    return data


def load_manifest(out=OUT):
    data=json.loads((Path(out)/'manifest.json').read_text(encoding='utf-8'))
    if data['manifest_sha256']!=digest(data['payload']):
        raise RuntimeError('Frozen dataset manifest digest changed; refusing to translate')
    p=data['payload']
    if p['schema']!=VERSION or set(p['roster'])!=set(ROSTER):
        raise RuntimeError('Dataset/roster definition differs from frozen runner')
    if [(p['roster'][k]['kind'],p['roster'][k]['model']) for k in ROSTER] != \
       [ROSTER[k] for k in ROSTER]:
        raise RuntimeError('Model roster silently changed')
    if len(p['scenes']) not in (4,5,6) or sum(len(s['cues']) for s in p['scenes'])<MIN_CUES:
        raise RuntimeError('Incomplete or nonconforming frozen dataset')
    return data


def verify_sources(payload, root=ROOT):
    db=(Path(root)/'jobs.sqlite3').resolve(strict=True)
    with sqlite3.connect(db.as_uri()+'?mode=ro',uri=True) as cn:
        for scene in payload['scenes']:
            row=cn.execute('SELECT source_sha FROM jobs WHERE id=?',(scene['job_id'],)).fetchone()
            if not row or row[0]!=scene['source_sha']:
                raise RuntimeError('Frozen source SHA mismatch')
            for cue in scene['cues']:
                current=cn.execute(
                    'SELECT english,timing,start_ms,end_ms FROM cues '
                    'WHERE job_id=? AND cue_id=?',
                    (scene['job_id'],cue['cue_id'])).fetchone()
                if not current or tuple(current)!=tuple(cue[k] for k in
                        ('english','timing','start_ms','end_ms')):
                    raise RuntimeError('Frozen English/timing cue changed')
        reserved=cn.execute(
            'SELECT source_sha FROM jobs WHERE id=?',
            (payload['holdout_reserved']['job_id'],)).fetchone()
        if not reserved or reserved[0]!=payload['holdout_reserved']['source_sha']:
            raise RuntimeError('Reserved holdout source changed')


def record_path(out, arm, scene_id, cue_id):
    return Path(out)/'arms'/arm/scene_id/f'{cue_id}.json'


def summarize(out=OUT):
    data=load_manifest(out)
    scenes=data['payload']['scenes']
    expected=sum(len(s['cues']) for s in scenes)
    summary={}
    for arm in ROSTER:
        good=0
        accepted=0
        flags=0
        errors=0
        slow=0
        seconds=0.0
        for scene in scenes:
            for cue in scene['cues']:
                file=record_path(out,arm,scene['scene_id'],cue['cue_id'])
                if file.is_file():
                    try:
                        obj=json.loads(file.read_text(encoding='utf-8'))
                        if (obj['cue_id']==cue['cue_id'] and
                            obj['scene_id']==scene['scene_id'] and
                            obj['manifest_sha256']==data['manifest_sha256']):
                            good+=1
                            accepted+=bool(obj.get('valid_japanese'))
                            flags+=bool(obj.get('flags'))
                            errors+=bool(obj.get('error'))
                            slow+=bool((obj.get('chars_per_second') or 0)>14)
                            seconds+=float(obj.get('wall_seconds') or 0)
                    except (OSError,ValueError,KeyError,TypeError):
                        pass
        blocked=(Path(out)/'arms'/arm/'blocked.json').exists()
        summary[arm]={
            'recorded':good,'expected':expected,
            'complete':good==expected and not blocked,
            'blocked':blocked,'accepted_japanese':accepted,
            'format_flagged':flags,'model_call_errors':errors,
            'over_14_cps':slow,
            'sum_generation_wall_seconds':round(seconds,2),
            'quality':'NOT JUDGED. Native Japanese blinded viewer required.',
        }
    return summary


def ensure_ollama_model(arm, out):
    name=ROSTER[arm][1]
    found=installed_models()
    if name not in found:
        if arm in PINNED:
            raise RuntimeError('Pinned original model absent; cannot repull or substitute: '+arm)
        print('DOWNLOADING NEW CANDIDATE:',arm,flush=True)
        subprocess.run(['ollama','pull',name],check=True,timeout=2400)
        found=installed_models()
    actual=found.get(name)
    if not actual:
        raise RuntimeError('Model not visible after pull')
    if arm in PINNED and actual!=PINNED[arm]:
        raise RuntimeError('Original model ID changed; failing closed '+arm)
    show=ollama_post('/api/show',{'model':name},timeout=30)
    spec={
        'model_name':name,'ollama_id':actual,
        'backend':'ollama','quantization':(show.get('details') or {}).get('quantization_level'),
        'architecture':(show.get('details') or {}).get('family'),
        'template_sha256':hashlib.sha256(str(show.get('template','')).encode()).hexdigest(),
    }
    # The CAT7 model MUST use its original special 7B chat template. We use HF
    # final weights for CAT7 instead; Ollama third-party GGUF was contaminated.
    return spec,None


def ensure_hf_model(arm):
    import torch
    from huggingface_hub import HfApi
    from transformers import AutoTokenizer, AutoModelForCausalLM, BitsAndBytesConfig
    model_name=ROSTER[arm][1]
    free,_=torch.cuda.mem_get_info()
    if free<3_000_000_000:
        raise RuntimeError('Insufficient FREE GPU memory for CAT native HF model; no other services stopped')
    revision=HfApi().model_info(model_name).sha
    if arm=='cat33' and revision!='47e382331d005acd54a42cdf088a76aa88788e0c':
        raise RuntimeError('Previously pinned CAT3.3 final HF commit changed; no silent switch')
    tokenizer=AutoTokenizer.from_pretrained(model_name,revision=revision)
    quant=BitsAndBytesConfig(load_in_4bit=True,bnb_4bit_quant_type='nf4',
                             bnb_4bit_use_double_quant=True,
                             bnb_4bit_compute_dtype=torch.float16)
    model=AutoModelForCausalLM.from_pretrained(
        model_name,revision=revision,quantization_config=quant,
        device_map={'':0},dtype=torch.float16,low_cpu_mem_usage=True)
    model.eval()
    spec={'model_name':model_name,'hf_revision':revision,
          'backend':'transformers+bitsandbytes','quantization':'NF4_4bit_fp16',
          'chat_template_sha256':hashlib.sha256(
              str(tokenizer.chat_template).encode()).hexdigest()}
    return spec,(model,tokenizer)


def translate(arm, english, history, hf=None):
    kind, name=ROSTER[arm]
    if kind=='native':
        return native_call(name,native_messages({'english':english},history),timeout=240)
    if kind=='google':
        result=ollama_post('/api/generate',{
            'model':name,'prompt':google_prompt(english),'stream':False,
            'options':GOOGLE_OPTIONS,'keep_alive':'5m'},timeout=360)
        if result.get('done_reason')=='length':
            raise RuntimeError('Google output length cap')
        text=result.get('response')
    elif kind in ('hy','index'):
        prompt=(HY_PROMPT if kind=='hy' else INDEX_HEADER)+english
        options=HY_OPTIONS if kind=='hy' else {
            'temperature':0,'num_ctx':4096,'num_predict':256}
        result=ollama_post('/api/chat',{
            'model':name,'messages':[{'role':'user','content':prompt}],
            'think':False,'stream':False,'options':options,'keep_alive':'5m'
        },timeout=360)
        if result.get('done_reason')=='length':
            raise RuntimeError('Ollama output length cap')
        text=(result.get('message') or {}).get('content')
        if kind=='index' and isinstance(text,str) and '</think>' in text:
            # Thinking tokens may be emitted, but must be preserved in raw data.
            # Do NOT silently replace corrupt outputs; reviewer should see them.
            pass
    elif kind=='hf':
        import torch
        model,tokenizer=hf
        prompt=CAT_PROMPT+english
        tokens=tokenizer.apply_chat_template(
            [{'role':'user','content':prompt}],tokenize=True,
            add_generation_prompt=True,return_tensors='pt')
        if not isinstance(tokens,torch.Tensor):
            raise RuntimeError('CAT HF chat template did not return token tensor')
        tokens=tokens.to('cuda:0')
        # Fix 005's logged attention_mask warning before first 006 generation.
        mask=torch.ones_like(tokens)
        with torch.inference_mode():
            result=model.generate(input_ids=tokens,attention_mask=mask,
                do_sample=False,max_new_tokens=512,
                pad_token_id=tokenizer.eos_token_id)
        text=tokenizer.decode(result[0,tokens.shape[-1]:],
                              skip_special_tokens=True)
    else:
        raise RuntimeError('Unknown model kind')
    if not isinstance(text,str) or not text.strip():
        raise RuntimeError('Blank model output')
    return text.strip()


def run_arm(arm, out=OUT, root=ROOT, base=BASE, max_seconds=7200):
    if arm not in ROSTER:
        raise ValueError('Unknown candidate: '+arm)
    frozen=load_manifest(out)
    payload=frozen['payload']
    verify_sources(payload,root)
    arm_dir=Path(out)/'arms'/arm
    arm_dir.mkdir(parents=True,exist_ok=True,mode=0o700)
    blocked=arm_dir/'blocked.json'
    started=time.monotonic()
    done_count=0
    errors=0
    hf=None
    try:
        with locked_idle(base,root):
            if ROSTER[arm][0]=='hf':
                meta,hf=ensure_hf_model(arm)
            else:
                meta,hf=ensure_ollama_model(arm,out)
            meta['manifest_sha256']=frozen['manifest_sha256']
            meta['candidate_id']=arm
            if (arm_dir/'model_meta.json').exists():
                old=json.loads((arm_dir/'model_meta.json').read_text())
                if old!=meta:
                    raise RuntimeError('Pinned candidate metadata differs from resume file')
            else:
                store_exclusive(arm_dir/'model_meta.json',meta)
            for scene in payload['scenes']:
                history=[]
                for cue in scene['cues']:
                    file=record_path(out,arm,scene['scene_id'],cue['cue_id'])
                    if file.exists():
                        item=json.loads(file.read_text(encoding='utf-8'))
                        if item.get('cue_id')!=cue['cue_id'] or \
                           item.get('scene_id')!=scene['scene_id'] or \
                           item.get('manifest_sha256')!=frozen['manifest_sha256']:
                            raise RuntimeError('Existing cue result identity changed')
                        text=item.get('candidate_japanese')
                        if ROSTER[arm][0]=='native' and text and \
                           item.get('valid_japanese') and not item.get('flags'):
                            history.append({'cue_id':cue['cue_id'],
                                            'english':cue['english'],
                                            'candidate_japanese':text})
                        done_count+=1
                        continue
                    if time.monotonic()-started>max_seconds:
                        raise TimeoutError('Per-arm wall budget reached; results are resume-safe')
                    t=time.monotonic()
                    error=None
                    text=None
                    try:
                        text=translate(arm,cue['english'],history,hf)
                    except Exception as exc:
                        error=type(exc).__name__+': '+str(exc)[:240]
                        errors+=1
                    flags=structural_flags(text)
                    valid=bool(service.acceptable_ja(text,cue['english']))
                    item={
                        'manifest_sha256':frozen['manifest_sha256'],
                        'scene_id':scene['scene_id'],'cue_id':cue['cue_id'],
                        'timing':cue['timing'],'english':cue['english'],
                        'candidate_japanese':text,'valid_japanese':valid,
                        'flags':flags,'error':error,
                        'chars_per_second':cps(text,cue),
                        'wall_seconds':round(time.monotonic()-t,2),
                    }
                    store_exclusive(file,item)
                    done_count+=1
                    if ROSTER[arm][0]=='native' and valid and not flags:
                        history.append({'cue_id':cue['cue_id'],
                                        'english':cue['english'],
                                        'candidate_japanese':text})
                    if errors>=3 and not text:
                        raise RuntimeError('At least three failed calls in arm; refusing blind continuation')
                print(f'{arm}: {scene["scene_id"]} complete, {done_count} cue records, {errors} call errors',flush=True)
        if blocked.exists():
            blocked.unlink()
        print('ARM COMPLETE:',arm,'CUES:',done_count,'ERRORS:',errors,flush=True)
        return 0
    except Exception as exc:
        message={'candidate':arm,'type':type(exc).__name__,
                 'reason':str(exc)[:500],
                 'recorded_cues':done_count,
                 'resumable':True}
        # Logs are private; failed models are NEVER assigned a language score.
        if not blocked.exists():
            store_exclusive(blocked,message)
        else:
            print('PREVIOUS BLOCK:',blocked.read_text()[:300],flush=True)
        print('ARM BLOCKED:',arm,type(exc).__name__,str(exc)[:300],flush=True)
        return 1
    finally:
        if hf is not None:
            del hf
            gc.collect()
            try:
                import torch
                torch.cuda.empty_cache()
            except ImportError:
                pass


def blind(out=OUT):
    data=load_manifest(out)
    summary=summarize(out)
    complete=[k for k in ROSTER if summary[k]['complete'] and not summary[k]['blocked']]
    if len(complete)<2:
        print('At least 2 FULL model outputs needed; no blind pack yet.')
        return 1
    folder=Path(out)/'blind'
    # Never include the answer key in the folder sent to the Japanese viewer.
    keyfile=Path(out)/'IDENTITY_KEY_PRIVATE.json'
    if keyfile.exists():
        print('Existing frozen blind key retained; no reblinding.')
        return 0
    rng=random.Random(data['payload']['selection_seed']+'|review-v1')
    key={}
    ratings=[]
    for scene in data['payload']['scenes']:
        scene_dir=folder/scene['scene_id']
        labels=list(complete)
        rng.shuffle(labels)
        key[scene['scene_id']]={}
        store_exclusive(scene_dir/'SCENE_PRIVATE.json',{
            'scene_id':scene['scene_id'],'job_id':scene['job_id'],
            'start_seconds':round(scene['start_ms']/1000,1),
            'end_seconds':round(scene['end_ms']/1000,1),
            'note':'Model identities are hidden; use original film audio and this SRT',
        })
        for index,arm in enumerate(labels):
            label=chr(ord('A')+index)
            key[scene['scene_id']][label]=arm
            parts=[]
            for i,cue in enumerate(scene['cues'],1):
                record=json.loads(record_path(out,arm,scene['scene_id'],
                                               cue['cue_id']).read_text())
                value=record['candidate_japanese'] or '[NO SUBTITLE]'
                parts.append(str(i)+'\n'+cue['timing']+'\n'+value+'\n')
            store_text_exclusive(scene_dir/(f'option_{label}.srt'),
                                 '\n'.join(parts))
            ratings.append({
                'scene':scene['scene_id'],'option':label,
                'watchability_1to5':'','natural_japanese_1to5':'',
                'comprehension_1to5':'','reading_comfort_1to5':'',
                'critical_errors':'','notes':'',
            })
    store_exclusive(keyfile,{'manifest_sha256':data['manifest_sha256'],
                             'mapping':key})
    # Reviewer should only access option files, not the private key.
    with (folder/'REVIEW_SCORES_PRIVATE.csv').open('x',newline='',encoding='utf-8') as fp:
        writer=csv.DictWriter(fp,fieldnames=ratings[0].keys())
        writer.writeheader();writer.writerows(ratings)
    print('BLIND PACK READY:',folder,'COMPLETE MODELS:',len(complete))
    print('KEY IS SEPARATE:',keyfile,'— DO NOT SHARE WITH REVIEWER.')
    print('Only send blind/ folder to the Japanese viewer. Lock scores first.')
    return 0


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',choices=('prepare','arm','blind','status'))
    p.add_argument('arm_name',nargs='?')
    p.add_argument('--root',type=Path,default=ROOT)
    p.add_argument('--base',type=Path,default=BASE)
    p.add_argument('--out',type=Path,default=OUT)
    p.add_argument('--max-seconds',type=int,default=7200)
    args=p.parse_args(argv)
    if args.command=='prepare':
        prepare(args.root,args.out)
    elif args.command=='arm':
        if not args.arm_name:p.error('arm requires candidate id')
        return run_arm(args.arm_name,args.out,args.root,args.base,args.max_seconds)
    elif args.command=='blind':
        return blind(args.out)
    else:
        print(json.dumps(summarize(args.out),indent=2))
    return 0


if __name__=='__main__':
    sys.exit(main())
