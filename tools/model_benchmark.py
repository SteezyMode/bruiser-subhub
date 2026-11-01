#!/usr/bin/env python3
"""Controlled PRIVATE local Ollama model x prompt experiment for EN->JA SRT.

Reads existing SQLite in query-only mode; never changes a queue, SRT or movie.
Use the same fixed, nonoverlapping English windows for every condition.
The output contains copyrighted EN/JA dialogue: never commit to GitHub.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import re
import statistics
import subprocess
import sys
import time

import service
try:
    from benchmark_localization import get_rows, windows, locked_idle, cps, save_private
except ModuleNotFoundError:
    from tools.benchmark_localization import get_rows, windows, locked_idle, cps, save_private

BENCHMARK_ID = 'primate-64cue-meaning-tone-v1'
JOB_ID = 'primate-2026-1080p-amzn-web--ad1c564197'
SOURCE_SHA = '8967cfea3f6552c0a6b1645da13e0d79e62be2decb95c02c653e6a345c3b645a'
CENTERS = (35, 71, 143, 207, 265, 380, 428, 465)
STYLES = ('baseline', 'faithful_8')


def sha(path):
    p = Path(path)
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None


def installed_models(run=subprocess.run):
    p = run(['ollama', 'list'], capture_output=True, text=True, timeout=15)
    if p.returncode:
        raise RuntimeError('ollama list failed; existing models could not be verified')
    found = {}
    for line in p.stdout.splitlines()[1:]:
        pieces = line.split()
        if len(pieces)>=2:
            found[pieces[0]] = pieces[1]
    return found


def resolve_models(found, baseline, challenger):
    if baseline not in found:
        raise ValueError('Baseline model is not installed: '+baseline+
                         '. Installed: '+', '.join(sorted(found)))
    if challenger == 'auto':
        names = [x for x in found if 'translate-gemma-4-sub' in x.casefold()
                 and 'e4b' in x.casefold()]
        if len(names)!=1:
            raise ValueError('Expected exactly one installed subtitle-tuned e4b model; '
                             'found '+str(len(names))+'. Candidates: '+repr(names)+
                             '. Pass --challenger-model NAME to select explicitly.')
        challenger = names[0]
    if challenger not in found:
        raise ValueError('Challenger model is not installed: '+challenger+
                         '. No automatic downloads will be attempted.')
    if baseline == challenger:
        raise ValueError('Need two genuinely different model IDs')
    return (baseline, challenger)


def checked_windows(root):
    job, rows = get_rows(root, JOB_ID)
    if job['source_sha'] != SOURCE_SHA:
        raise ValueError('Frozen English source SHA changed; refusing to compare')
    groups = windows(rows, CENTERS, size=8)
    if len(groups) != len(CENTERS) or any(len(g)!=8 for g in groups):
        raise ValueError('Frozen 8 x 8 English source windows do not match')
    for g in groups:
        if any(b['cue_id'] != a['cue_id']+1 for a,b in zip(g,g[1:])):
            raise ValueError('Nonconsecutive source cues in test window')
    return job, groups


def evaluate(base, root, conditions, groups, translator=service.translation_call,
             max_seconds=900):
    result = []
    calls = []
    start = time.monotonic()
    with locked_idle(base, root):
        for model in conditions:
            for wi, group in enumerate(groups):
                # Alternate style order to avoid uniformly favoring the warm model.
                styles = STYLES if wi % 2 == 0 else STYLES[::-1]
                memory = service.recall_memory(Path(base), 'horror', group)
                for style in styles:
                    if time.monotonic() - start >= max_seconds:
                        return result, calls, 'time_budget_exceeded'
                    stamp = time.monotonic()
                    error = None
                    try:
                        translated = translator(Path(base), group, memory,
                                                model=model, style=style)
                        if not isinstance(translated,dict):
                            raise TypeError('Translator returned non-dictionary')
                    except Exception as exc:
                        translated = {}
                        error = type(exc).__name__ + ': ' + str(exc)[:160]
                    elapsed = round(time.monotonic() - stamp, 2)
                    calls.append({'model':model,'style':style,
                                  'start_cue':group[0]['cue_id'],
                                  'end_cue':group[-1]['cue_id'],
                                  'returned':len(translated),
                                  'seconds':elapsed,'error':error})
                    for row in group:
                        candidate = translated.get(str(row['cue_id']))
                        result.append({
                            'cue_id':row['cue_id'],'timing':row['timing'],
                            'english':row['english'],
                            'previous_japanese':row['japanese'],
                            'model':model,'style':style,
                            'candidate_japanese':candidate,
                            'valid_japanese':service.acceptable_ja(candidate,row['english']),
                            'chars_per_second':cps(candidate,row),
                        })
    return result, calls, None


def metrics(results, calls, models):
    out = []
    for model in models:
        for style in STYLES:
            group = [r for r in results if r['model']==model and r['style']==style]
            trials = [x for x in calls if x['model']==model and x['style']==style]
            speeds = [r['chars_per_second'] for r in group if r['chars_per_second'] is not None]
            out.append({
                'model':model,'style':style,'attempted_cues':len(group),
                'valid_cues':sum(r['valid_japanese'] for r in group),
                'over_14_cps':sum(v>14 for v in speeds),
                'median_cps':round(statistics.median(speeds),2) if speeds else None,
                'model_calls':len(trials),
                'failed_model_calls':sum(x['error'] is not None for x in trials),
                'call_seconds':round(sum(x['seconds'] for x in trials),2),
                'semantic_quality':'NOT SCORED — requires manual EN/JA review',
            })
    return out


def run_benchmark(base, root, out, baseline, challenger, dry_run=False, max_seconds=900):
    if Path(out).exists() and not dry_run:
        raise FileExistsError('Refusing to overwrite private benchmark file')
    found = installed_models()
    models = resolve_models(found,baseline,challenger)
    job, groups = checked_windows(root)
    if dry_run:
        print('PREFLIGHT OK:',BENCHMARK_ID)
        for model in models:print('  INSTALLED:',model,'ID',found[model])
        print('  FROZEN: 8 x 8 = 64 cues, 2 models x 2 styles = 256 evaluated cue outputs')
        print('  Source SHA:',SOURCE_SHA)
        print('  No model calls or data writes performed in preflight.')
        return None
    rows,calls,stopped = evaluate(base,root,models,groups,max_seconds=max_seconds)
    meta={'schema':'bruiser-private-model-benchmark-v1',
          'benchmark_id':BENCHMARK_ID,
          'generated_utc':dt.datetime.now(dt.timezone.utc).isoformat(),
          'job_id':JOB_ID,'source_sha256':SOURCE_SHA,
          'selected_center_cues':list(CENTERS),'batch_size':8,
          'styles':list(STYLES),'models':list(models),
          'installed_model_ids':{m:found[m] for m in models},
          'code_hashes':{
              'candidate_service':sha(Path(service.__file__)),
              'localization_policy':sha(Path(service.__file__).with_name('localization_policy.py')),
              'legacy_adapter':sha(Path(base)/'bruiser_auto.py'),
          },
          'complete':stopped is None and len(rows)==len(CENTERS)*8*len(models)*len(STYLES),
          'stop_reason':stopped,'calls':calls,'structural_metrics':metrics(rows,calls,models),
          'entries':rows,
          'scoring_note':'Length and validity are diagnostics, not translation quality. Manually review meaning, tone, fluency, readability, and speaker completeness.'}
    save_private(out,meta)
    print('PRIVATE BENCHMARK:',out)
    print('Complete:',meta['complete'],'calls:',len(calls),
          'cue outputs:',len(rows),'stop:',stopped or 'none')
    for x in meta['structural_metrics']:
        print(f"  {x['model']} [{x['style']}]: {x['valid_cues']}/{x['attempted_cues']} "
              f"valid; {x['call_seconds']}s model time; "
              f"{x['over_14_cps']} >14 chars/s; failures={x['failed_model_calls']}")
    print('No subtitle, checkpoint, queue or movie files changed.')
    return meta


def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--base',type=Path,default=Path.home()/'bruiser-pilot')
    ap.add_argument('--root',type=Path,default=Path.home()/'bruiser-pilot/subhub1-state')
    ap.add_argument('--out',type=Path,required=True)
    ap.add_argument('--baseline-model',default=service.GEMMA)
    ap.add_argument('--challenger-model',default='auto')
    ap.add_argument('--dry-run',action='store_true')
    ap.add_argument('--max-seconds',type=int,default=900)
    args=ap.parse_args(argv)
    try:
        if not 60<=args.max_seconds<=3600:raise ValueError('Max seconds must be 60..3600')
        run_benchmark(args.base,args.root,args.out,
                      args.baseline_model,args.challenger_model,
                      args.dry_run,args.max_seconds)
    except (ValueError,OSError,RuntimeError,subprocess.TimeoutExpired) as exc:
        ap.error(str(exc))
    return 0


if __name__=='__main__':
    sys.exit(main())
