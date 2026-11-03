#!/usr/bin/env python3
"""Finite second-pass recovery for previously held American Dad S19E04 cues.

Only cues missing from the *existing, immutable* v1 checkpoint directory are
eligible. No raw future dialogue or previous suspect Japanese enters prompts.
A cheap lossless line-break reflow is tried before local model inference.
Rejections are recorded once per v2 attempt, so repeated maintenance runs
do not spend more GPU time producing identical rejects.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re

try:
    import subtitle_quality_010 as q
    import subtitle_publish_gate as gate
except ModuleNotFoundError:
    from tools import subtitle_quality_010 as q
    from tools import subtitle_publish_gate as gate

PROFILE='s19e04-bounded-second-pass-v2'
ATTEMPTS=(3,4)
PUNCT_AT_START=set('、。，．！？!?：:；;）)]」』')
PUNCT_AT_END=set('（([「『')


def reflow_unaltered_japanese(text,english,start_ms,end_ms,later,acceptable):
    """Only insert/reposition line breaks, never delete Japanese characters.

    Avoid SRT tags and Latin/script mixing to prevent changing punctuation or
    words. A line break can fix long-line presentation, but NOT reading speed:
    if the existing cue exceeds the gate's total-char or CPS limit, return None.
    """
    if not isinstance(text,str) or not text.strip():
        return None
    if re.search(r'[<>{}\\]|[A-Za-z]',text):
        return None
    original=text.replace('\r\n','\n').replace('\r','\n').strip()
    words=original.replace('\n','')
    n=q.visible_chars(words)
    if not 1<=n<=gate.MAX_CUE_CHARS:
        return None
    if q.length_risk(words,start_ms,end_ms)['severe_density']:
        return None
    if any(q.future_overlap(words,other) for other in later):
        return None
    if n<=gate.MAX_LINE_CHARS:
        candidate=words
    else:
        candidates=[]
        for i in range(1,len(words)):
            a,b=words[:i],words[i:]
            if (not a.strip() or not b.strip() or
                a[-1] in PUNCT_AT_END or b[0] in PUNCT_AT_START):
                continue
            if (q.visible_chars(a)<=gate.MAX_LINE_CHARS and
                q.visible_chars(b)<=gate.MAX_LINE_CHARS):
                score=abs(q.visible_chars(a)-q.visible_chars(b))
                if a[-1] in '。！？!?、，':score-=0.5
                candidates.append((score,i))
        if not candidates:
            return None
        cut=min(candidates)[1]
        candidate=words[:cut]+'\n'+words[cut:]
    # This pass never changes textual content, just a physical line break.
    if candidate==text:
        return None
    if candidate.replace('\n','')!=words:
        raise RuntimeError('Reflow altered dialogue content')
    return acceptable(candidate,english,start_ms,end_ms,later)


def budget(start_ms,end_ms):
    """Advisory target, never truncates or automatically removes meaning."""
    seconds=max(0.25,(end_ms-start_ms)/1000.0)
    # The legacy length risk gates at >26cps for 15+ visible characters.
    # For very short cues, a simple ~10-14 character subtitle may still be
    # more natural than a 3-character literal.
    return min(gate.MAX_CUE_CHARS,max(10,math.floor(q.BLOCK_CPS*seconds)))


def messages(rows,index,attempt):
    if attempt not in ATTEMPTS:
        raise ValueError('Only declared v2 attempts 3 and 4 are valid')
    _,_,start_ms,end_ms,english=rows[index]
    prior=q.cue_messages(rows,index,[],repair=True,
        style='natural concise Japanese subtitles for an adult TV comedy')
    max_chars=budget(start_ms,end_ms)
    prior[0]['content']+=(
        '\nIMPORTANT READABILITY BUDGET: Output ONE Japanese subtitle '
        f'with at most {max_chars} visible Japanese characters total, '
        'no more than two lines, no more than 18 characters per line. '
        'Preserve the actual current English meaning, negation and punchline. '
        'Do not translate any other cue. If the line is long, use idiomatic '
        'Japanese compression and drop redundant phrasing, not story facts. '
        'No explanations, options, labels or punctuation filler.'
    )
    if attempt==4:
        prior[0]['content']+=(
            '\nFINAL REPHRASING: Prefer a shorter spoken Japanese idiom, '
            'keep the joke and speaker intent without repeated subjects. '
            'Do not include any lines from before or after this one.'
        )
    # Only CURRENT_ENGLISH is present; no suspicious old Japanese or
    # future English is revealed even on the second recovery prompt.
    assert '[CURRENT_ENGLISH]' in prior[1]['content']
    assert '[PRIOR_' not in prior[1]['content']
    return prior


def prompt_sha(messages):
    return hashlib.sha256(json.dumps(
        messages,ensure_ascii=False,sort_keys=True).encode('utf8')).hexdigest()


def rejection_file(state,number,attempt):
    return Path(state)/'attempts-v2'/f'{number:05d}-{attempt}.json'


def was_rejected(state,number,attempt,manifest_sha,prompt):
    path=rejection_file(state,number,attempt)
    if path.is_symlink():
        raise RuntimeError('Unsafe prior v2 attempt path')
    if not path.exists():
        return False
    record=json.loads(path.read_text(encoding='utf8'))
    if (record.get('profile')!=PROFILE or
        record.get('cue_id')!=number or
        record.get('attempt')!=attempt or
        record.get('manifest_sha')!=manifest_sha or
        record.get('prompt_sha')!=prompt_sha(prompt) or
        record.get('reason')!='unacceptable_japanese'):
        raise RuntimeError('Existing recovery attempt identity changed')
    return True


def record_rejection(state,number,attempt,manifest_sha,prompt,save_json):
    path=rejection_file(state,number,attempt)
    save_json(path,{
        'profile':PROFILE,'cue_id':number,'attempt':attempt,
        'manifest_sha':manifest_sha,
        'prompt_sha':prompt_sha(prompt),
        'reason':'unacceptable_japanese',
    })
