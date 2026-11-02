#!/usr/bin/env python3
"""Private blind-review pack for all complete Benchmark 005 JSON outputs.

No network, source DB or Ollama. Reviews are independent of model names.
For each cue, permute candidate labels independently using a fixed seed.
Write two PRIVATE create-only JSONs: review pack + separate identity key.
DO NOT commit either output to public GitHub.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import random

ARMS=('tuned','cat33_final','cat7','hy7','google12')
LABELS=('A','B','C','D','E')


def collect(paths):
    data=[]
    for path in paths:
        x=json.loads(Path(path).read_text(encoding='utf-8'))
        if x.get('schema')!='bruiser-private-model-sweep-005-v1':
            raise ValueError('Not a Benchmark 005 file: '+str(path))
        if not x.get('complete') or len(x.get('entries',[]))!=64:
            raise ValueError('Arm incomplete: '+str(path))
        data.append(x)
    arms=[x['arm'] for x in data]
    if len(arms)!=len(set(arms)):
        raise ValueError('Duplicate arm')
    if not all(arm in ARMS for arm in arms):
        raise ValueError('Unknown model arm')
    sources={x['source_sha256'] for x in data}
    if len(sources)!=1:
        raise ValueError('English source SHA mismatch')
    ids=[[r['cue_id'] for r in x['entries']] for x in data]
    if any(x!=ids[0] for x in ids[1:]):
        raise ValueError('Cannot blind different cue selections')
    for idx in range(len(ids[0])):
        english={x['entries'][idx]['english'] for x in data}
        times={x['entries'][idx]['timing'] for x in data}
        if len(english)!=1 or len(times)!=1:
            raise ValueError('Source cue mismatch at position '+str(idx))
    return data


def build(data,seed='bruiser-005-precommitted'):
    arms=[x['arm'] for x in data]
    if len(arms)>len(LABELS):raise ValueError('Too many models for labels')
    rng=random.Random(int.from_bytes(hashlib.sha256(seed.encode()).digest(),'big'))
    pack=[];identity={}
    for i,base in enumerate(data[0]['entries']):
        permutation=list(range(len(data)))
        rng.shuffle(permutation)
        candidates=[]
        key={}
        for alias,j in zip(LABELS,permutation):
            text=data[j]['entries'][i]['candidate_japanese']
            if not text:raise ValueError('Missing Japanese; blind review cannot proceed')
            candidates.append({
                'label':alias,'japanese':text,
                'review':{
                    'semantic_fidelity_0_to_4':None,
                    'tone_intent_0_to_2':None,
                    'natural_japanese_0_to_2':None,
                    'readability_0_to_2':None,
                    'critical_error_ids':[],
                    'reviewer_note':None,
                },
            })
            key[alias]=arms[j]
        key_id=str(base['cue_id'])
        identity[key_id]=key
        pack.append({
            'cue_id':base['cue_id'],'english':base['english'],
            'timing':base['timing'],
            'candidates':candidates
        })
    return ({
        'schema':'bruiser-private-blind-review-005-v1',
        'source_sha256':data[0]['source_sha256'],
        'seed_sha256':hashlib.sha256(seed.encode()).hexdigest(),
        'arm_count':len(data),'cue_count':len(pack),
        'entries':pack,
    },{
        'schema':'bruiser-private-blind-key-005-v1',
        'source_sha256':data[0]['source_sha256'],
        'map_by_cue_id':identity,
    })


def private_create(path,thing):
    import json
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w',encoding='utf8') as f:
        json.dump(thing,f,ensure_ascii=False,indent=2)
        f.write('\n')


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('private_results',nargs='+',type=Path)
    p.add_argument('--out',required=True,type=Path)
    p.add_argument('--key',required=True,type=Path)
    args=p.parse_args(argv)
    try:
        if args.out==args.key:raise ValueError('Review and key paths cannot match')
        data=collect(args.private_results)
        review,key=build(data)
        private_create(args.out,review)
        private_create(args.key,key)
    except (ValueError,OSError) as exc:
        p.error(str(exc))
    print('PRIVATE blind review:',args.out)
    print('PRIVATE separate identity key:',args.key)
    print('Never commit these files. Reviewers should see the review ONLY.')
    return 0


if __name__=='__main__':
    raise SystemExit(main())
