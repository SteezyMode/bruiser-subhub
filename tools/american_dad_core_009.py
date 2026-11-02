#!/usr/bin/env python3
"""Private checkpoints, local Ollama and prompt helpers for episode pilot 009."""
from __future__ import annotations
import contextlib
import fcntl
import json
import os
import re
from pathlib import Path
from urllib.request import Request,urlopen
import service
try:
    import context_engine_008 as context
except ModuleNotFoundError:
    from tools import context_engine_008 as context

MODEL='hf.co/17slever17/translate-gemma-4-sub-e4b-GGUF:Q4_K_XL'
MODEL_ID='9ccfc3b07081'
BASE=Path.home()/'bruiser-pilot'
STATE=BASE/'american-dad-pilot-009'
PROFILE=Path(__file__).resolve().parent/'series_profiles'/'american_dad.json'


def create(path,data,mode=0o600):
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,mode)
    with os.fdopen(fd,'wb') as writer:
        writer.write(data)
        writer.flush()
        os.fsync(writer.fileno())


def save(path,data):
    create(path,(json.dumps(data,ensure_ascii=False,indent=2)+'\n').encode())


def load(path):
    return json.loads(Path(path).read_text(encoding='utf8'))


@contextlib.contextmanager
def locks(base=BASE):
    with contextlib.ExitStack() as stack:
        for path in (Path(base)/'subhub1-state'/'run.lock',
                     Path(base)/'subhub-household'/'.runner.lock'):
            path.parent.mkdir(parents=True,exist_ok=True)
            handle=stack.enter_context(path.open('a+b'))
            try:fcntl.flock(handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise RuntimeError('Another subtitle worker active: no model call') from exc
            stack.callback(fcntl.flock,handle.fileno(),fcntl.LOCK_UN)
        yield


def preflight(opener=urlopen):
    with opener(service.OLLAMA+'/api/tags',timeout=12) as r:
        tags=json.load(r).get('models',[])
    model=next((x for x in tags if x.get('name')==MODEL),None)
    if not model or not str(model.get('digest','')).startswith(MODEL_ID):
        raise RuntimeError('Pinned subtitle E4B missing or changed')
    with opener(service.OLLAMA+'/api/ps',timeout=12) as r:
        resident=json.load(r).get('models',[])
    if any(x.get('name')!=MODEL for x in resident):
        raise RuntimeError('Other model resident; no forced eviction/offload')


def call(messages,model=MODEL,json_mode=False,opener=urlopen):
    payload={'model':model,'messages':messages,'stream':False,'think':False,
             'options':{'temperature':0,'num_ctx':4096,
                        'num_predict':450 if json_mode else 320},
             'keep_alive':'3m'}
    if json_mode:payload['format']='json'
    req=Request(service.OLLAMA+'/api/chat',
                data=json.dumps(payload,ensure_ascii=False).encode('utf8'),
                headers={'Content-Type':'application/json'})
    with opener(req,timeout=240) as r:
        answer=json.load(r)
    if answer.get('done_reason')=='length':
        raise RuntimeError('Output length cap')
    result=(answer.get('message') or {}).get('content','')
    if not isinstance(result,str) or not result.strip():
        raise RuntimeError('Empty model output')
    return result.strip()


def note(kind,title,english_sources,state=STATE,ask=call):
    def query(messages,model):
        return json.loads(ask(messages,model=MODEL,json_mode=True))
    try:
        return context.cached_context(
            kind,title,english_sources,cache=Path(state)/'context',
            ask=query,model=MODEL)
    except (OSError,ValueError,RuntimeError,KeyError,TypeError) as exc:
        print('CONTEXT UNAVAILABLE:',kind,type(exc).__name__,str(exc)[:100],flush=True)
        return None


def note_text(record):
    if not record:return ''
    data=record['note']
    return '\n'.join(k+': '+'; '.join(data.get(k,[]))
                     for k in ('names','terms','notes','caveats'))[:1250]


def compact_profile(profile):
    """Use a bounded readable character guide, never a truncated JSON fragment."""
    try:
        data=json.loads(profile)
        lines=[]
        for person in data.get('recurring_people',[])[:12]:
            name=str(person.get('name',''))[:50]
            kana=str(person.get('ja_hint',''))[:30]
            guide=str(person.get('guide',''))[:155]
            if name:
                lines.append(name+' / '+kana+': '+guide)
        return '\n'.join(lines)[:2200]
    except (ValueError,TypeError,AttributeError):
        return str(profile)[:2000]


def prompt(rows,index,previous,profile,series_note,episode_note):
    part=context.cue_context(rows,index)
    system=(
        'Localize ONLY CURRENT_ENGLISH into natural, concise spoken Japanese '
        'for the adult comedy American Dad. Keep jokes, sarcasm, swearing, sex, '
        'insults and real meaning; never sanitize, invent or add explanations. '
        'Natural nonliteral condensation is welcome. Show and episode notes '
        'are ADVISORY and can be mistaken; the actual English always wins. '
        'Never assume speaker identity without dialogue evidence. Earlier '
        'and future dialogue are context ONLY. Reply with ONLY the Japanese '
        'of CURRENT_ENGLISH; no labels, commentary or alternative versions.\n'
        '[CURATED_BIBLE]\n'+compact_profile(profile)+'\n[/CURATED_BIBLE]\n'
        '[AUTO_SHOW]\n'+series_note[:950]+'\n[/AUTO_SHOW]\n'
        '[AUTO_EPISODE]\n'+episode_note[:950]+'\n[/AUTO_EPISODE]'
    )
    user=(
        '[PREVIOUS_ENGLISH]\n'+'\n'.join(part['previous_english'])[-700:]+
        '\n[/PREVIOUS_ENGLISH]\n[PREVIOUS_JAPANESE]\n'+'\n'.join(previous[-2:])[-260:]+
        '\n[/PREVIOUS_JAPANESE]\n[CURRENT_ENGLISH]\n'+part['current_english']+
        '\n[/CURRENT_ENGLISH]\n[NEXT_ENGLISH]\n'+
        '\n'.join(part['following_english'])[:700]+
        '\n[/NEXT_ENGLISH]\nTranslate CURRENT_ENGLISH only.'
    )
    return [{'role':'system','content':system},{'role':'user','content':user}]



def recovery_prompt(rows,index,previous,mode=3):
    """Fresh, deliberately simpler prompt for previously failed current cue only.

    Modes 3-6 are a finite recovery budget, not a new benchmark/model switch.
    The source/clock and all previously accepted Japanese remain fixed.
    """
    part=context.cue_context(rows,index,before=2,after=2)
    current=part['current_english']
    basic=(
        'Translate the English subtitle CURRENT into one natural, concise Japanese '
        'subtitle. This is adult animated comedy. Preserve the actual meaning, '
        'speaker intent, numbers, jokes and vulgarity; no invented information. '
        'Names or tiny English fragments may require Japanese katakana or a '
        'natural equivalent. Output ONLY the translated CURRENT cue, not the '
        'surrounding dialogue, with no labels, quotes, JSON or explanations.'
    )
    if mode in (3,5):
        before=' / '.join(part['previous_english'])[-260:]
        after=' / '.join(part['following_english'])[:260]
        user=(
            'Previous English for context ONLY: '+before+'\n'
            'CURRENT: '+current+'\n'
            'Following English for context ONLY: '+after+'\n'
            'Japanese subtitle for CURRENT only:'
        )
    elif mode in (4,6):
        basic+=(
            ' If the line is an interjection, sound effect or standalone '
            'proper name, choose a short natural Japanese rendering. '
            'Never return untranslated English unless it is an appropriate '
            'short name/initial. Do not embellish.'
        )
        user='CURRENT ENGLISH SUBTITLE:\n'+current+'\nJAPANESE:'
    else:
        raise ValueError('Only predeclared recovery modes 3..6')
    return [{'role':'system','content':basic},{'role':'user','content':user}]


def normalized_srt_markup(text, english):
    """Preserve standard SRT italics ONLY, never accept arbitrary model HTML.

    The source must itself contain italic markup. A model-emitted
    <i lang="en"> marker can be reduced to valid SRT <i>, preserving
    the exact model wording, source timecode and italicized show name.
    """
    if not isinstance(text,str) or not isinstance(english,str):
        return None
    if '<' not in text and '>' not in text:
        return text
    if not re.search(r'<i(?:\\s|>)',english,re.IGNORECASE):
        return None
    text=re.sub(r'<i\\s+lang\\s*=\\s*(["\\\'])en\\1\\s*>',
                '<i>',text,flags=re.IGNORECASE)
    tags=re.findall(r'<[^>]*>',text)
    if not tags or any(tag not in ('<i>','</i>') for tag in tags):
        return None
    depth=0
    for tag in tags:
        depth+=1 if tag=='<i>' else -1
        if depth<0 or depth>1:
            return None
    if depth!=0:
        return None
    naked=re.sub(r'</?i>','',text)
    if '<' in naked or '>' in naked:
        return None
    return text


def valid(text,english):
    clean=normalized_srt_markup(text,english)
    if clean is None:
        return False
    visible=re.sub(r'</?i>','',clean)
    return (service.acceptable_ja(visible,english) and len(clean)<300 and
            not visible.lstrip().startswith((chr(96),'{','[CURRENT_','訳：','翻訳：')) and
            '<|' not in clean and '</' not in visible)
