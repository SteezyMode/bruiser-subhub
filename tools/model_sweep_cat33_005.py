#!/usr/bin/env python3
"""Benchmark 005 final CyberAgent CAT-Translate-3.3b (not beta).

Requires isolated venv with CUDA torch, transformers, accelerate, bitsandbytes.
Runs author's native chat template on EXACT SAME 64 frozen source cues as other
arms. Uses 4bit NF4 dynamic quantization due to RTX 3050 6GB; it is not GGUF.
Private output only. Does not write to movie, SRT, queue or checkpoint database.
"""
from __future__ import annotations
import argparse
import datetime as dt
import hashlib
import importlib
import json
from pathlib import Path
import statistics
import sys
import time

import service
try:
    from model_sweep_005 import dataset, BENCHMARK_ID, CENTERS, SOURCE_SHA, JOB_ID, \
        CAT_PROMPT, metrics as ollama_metrics
    from benchmark_localization import locked_idle, cps, save_private
    from analyze_model_benchmark import structural_flags
    from model_benchmark import sha
except ModuleNotFoundError:
    from tools.model_sweep_005 import dataset, BENCHMARK_ID, CENTERS, SOURCE_SHA, JOB_ID, \
        CAT_PROMPT, metrics as ollama_metrics
    from tools.benchmark_localization import locked_idle, cps, save_private
    from tools.analyze_model_benchmark import structural_flags
    from tools.model_benchmark import sha

MODEL='cyberagent/CAT-Translate-3.3b'
QUANT='bitsandbytes_nf4_4bit_float16'
MAX_NEW_TOKENS=512


def tokenizer_dependency_versions(importer=importlib.import_module):
    """Fail early on tokenizer dependencies before HF downloads or CUDA loading.

    The final CAT tokenizer's Llama fast/slow conversion requires sentencepiece
    AND Google's protobuf. Both are installed only in the isolated CAT venv.
    """
    versions={}
    for name, module_name in (
        ('sentencepiece','sentencepiece'),
        ('protobuf','google.protobuf'),
    ):
        try:
            module=importer(module_name)
        except (ImportError,ModuleNotFoundError) as exc:
            raise RuntimeError(
                'Missing CAT tokenizer dependency '+name+
                ' in isolated venv; reinstall tools/cat33_requirements_005.txt'
            ) from exc
        versions[name]=getattr(module,'__version__','unknown')
    return versions


def preflight(root):
    groups=dataset(root)
    try:
        import torch
        import transformers
        import accelerate
        import bitsandbytes
        import huggingface_hub
    except ImportError as exc:
        raise RuntimeError('Missing isolated Transformers/torch/bitsandbytes dependency: '+str(exc))
    tokenizer_versions=tokenizer_dependency_versions()
    if not torch.cuda.is_available():
        raise RuntimeError('CUDA GPU not available; do not run slow unquantized CPU fallback')
    free,total=torch.cuda.mem_get_info()
    if free < 3_000_000_000:
        raise RuntimeError('Under 3GB free VRAM; stop competing inference before CAT 3.3B')
    versions={
        'torch':torch.__version__,
        'transformers':transformers.__version__,
        'accelerate':accelerate.__version__,
        'bitsandbytes':bitsandbytes.__version__,
        'huggingface_hub':huggingface_hub.__version__,
        **tokenizer_versions,
    }
    return groups,versions,{'free_before_bytes':free,'total_bytes':total}


def load_model():
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
    from huggingface_hub import HfApi
    revision=HfApi().model_info(MODEL).sha
    if not revision or len(revision)<20:
        raise ValueError('Could not pin final CAT model commit SHA')
    tokenizer=AutoTokenizer.from_pretrained(MODEL,revision=revision)
    quant=BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type='nf4',
        bnb_4bit_use_double_quant=True,
        bnb_4bit_compute_dtype=torch.float16,
    )
    model=AutoModelForCausalLM.from_pretrained(
        MODEL,revision=revision,quantization_config=quant,
        device_map={'':0},dtype=torch.float16,low_cpu_mem_usage=True,
    )
    model.eval()
    return model,tokenizer,revision


def translate(model,tokenizer,english):
    import torch
    prompt=CAT_PROMPT+english
    user=[{'role':'user','content':prompt}]
    # The CAT model card explicitly requires the sarashina 2.2 chat template.
    tokens=tokenizer.apply_chat_template(
        user,tokenize=True,add_generation_prompt=True,return_tensors='pt')
    if not isinstance(tokens,torch.Tensor):
        raise ValueError('CAT model chat template did not return a token tensor')
    tokens=tokens.to('cuda:0')
    with torch.inference_mode():
        output=model.generate(
            input_ids=tokens,do_sample=False,
            max_new_tokens=MAX_NEW_TOKENS,
            pad_token_id=tokenizer.eos_token_id,
        )
    new=output[0][tokens.shape[-1]:]
    decoded=tokenizer.decode(new,skip_special_tokens=True).strip()
    if not decoded:
        raise ValueError('CAT model output empty')
    return decoded,{'output_tokens':int(new.shape[-1])}


def run(base,root,groups,model,tokenizer,call=translate,max_seconds=3600):
    entries=[];calls=[];stopped=None;errors=0
    begun=time.monotonic()
    with locked_idle(base,root):
        for group in groups:
            for row in group:
                if time.monotonic()-begun >= max_seconds:
                    stopped='time_budget_exceeded'
                    break
                tick=time.monotonic()
                value=None;error=None;perf={}
                try:
                    value,perf=call(model,tokenizer,row['english'])
                except Exception as exc:
                    error=type(exc).__name__+': '+str(exc)[:180]
                errors=errors+1 if error else 0
                elapsed=round(time.monotonic()-tick,2)
                flags=structural_flags(value)
                valid=service.acceptable_ja(value,row['english'])
                entries.append({
                    'cue_id':row['cue_id'],'timing':row['timing'],
                    'english':row['english'],'candidate_japanese':value,
                    'valid_japanese':bool(valid),'flags':flags,
                    'chars_per_second':cps(value,row),'context_from_cues':[],
                })
                calls.append({'cue_id':row['cue_id'],'wall_seconds':elapsed,
                              'error':error,'other_stats':perf})
                if errors>=3:
                    stopped='three_consecutive_model_errors'
                    break
            if stopped:break
    return entries,calls,stopped


def execute(base,root,out,dry_run=False,max_seconds=3600):
    groups,versions,memory=preflight(root)
    if dry_run:
        print('SOURCE+ENV PREFLIGHT OK: final CyberAgent CAT-Translate-3.3b')
        print('  Source SHA',SOURCE_SHA,'64 frozen NEW English cues')
        print('  Runtime',versions,'CUDA',memory)
        print('  No model weights downloaded or output created')
        return None
    if Path(out).exists():
        raise FileExistsError('Refusing to overwrite private benchmark results')
    model,tokenizer,revision=load_model()
    entries,calls,stopped=run(base,root,groups,model,tokenizer,max_seconds=max_seconds)
    result={
        'schema':'bruiser-private-model-sweep-005-v1',
        'benchmark_id':BENCHMARK_ID,
        'generated_utc':dt.datetime.now(dt.timezone.utc).isoformat(),
        'source_sha256':SOURCE_SHA,'job_id':JOB_ID,
        'arm':'cat33_final','centers':list(CENTERS),
        'model':{
            'name':MODEL,'revision':revision,'quantization':QUANT,
            'backend':'transformers+bitsandbytes','runtime_versions':versions,
        },
        'prompt_spec':'Official CAT model card English to Japanese chat template',
        'runtime_options':{'do_sample':False,'max_new_tokens':MAX_NEW_TOKENS,
                           'nf4_double_quant':True,'compute_dtype':'float16'},
        'gpu_memory_at_preflight':memory,
        'code_sha256':sha(__file__),
        'complete':stopped is None and len(entries)==64,
        'stop_reason':stopped,
        'metrics':ollama_metrics(entries,calls),
        'calls':calls,'entries':entries,
        'quality_note':'Model-native final weights in dynamic 4bit NF4, NOT GGUF/Q4_K_M. Viewer semantic quality unscored.',
    }
    save_private(out,result)
    print('PRIVATE OUTPUT:',out)
    print('COMPLETE:',result['complete'],'SUMMARY:',json.dumps(result['metrics']))
    if not result['complete']:
        return 1
    return 0


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--base',type=Path,default=Path.home()/'bruiser-pilot')
    p.add_argument('--root',type=Path,default=Path.home()/'bruiser-pilot/subhub1-state')
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--dry-run',action='store_true')
    p.add_argument('--max-seconds',type=int,default=3600)
    args=p.parse_args(argv)
    try:
        if not 60<=args.max_seconds<=14400:
            raise ValueError('max seconds must be 60..14400')
        return execute(args.base,args.root,args.out,args.dry_run,args.max_seconds) or 0
    except (ValueError,OSError,RuntimeError) as exc:
        p.error(str(exc))
    return 1


if __name__=='__main__':
    sys.exit(main())
