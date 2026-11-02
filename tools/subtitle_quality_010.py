#!/usr/bin/env python3
"""Generic, offline-safe subtitle cue isolation and post-generation QA.

Works with any series/movie, language-neutral source + Japanese target rows.
Does not discover media, call an LLM, persist files, or edit existing subtitles.
The caller owns model selection, source integrity, checkpoints and publication.
"""
from __future__ import annotations
import math
import re
import unicodedata

SCHEMA='bruiser-subtitle-quality-v010'
WARN_CPS=18.0
BLOCK_CPS=26.0
OVERLAP_MIN=9
MAX_PREVIOUS_EN=2
MAX_PREVIOUS_JA=1


def display_text(text):
    """Strip supported SRT tags and placement hints for reading estimates."""
    if not isinstance(text,str):
        return ''
    text=re.sub(r'<[^>]*>','',text)
    text=re.sub(r'\{\\(?:an\d|pos\([^)]*\))\}','',text)
    text=re.sub(r'\s+',' ',text).strip()
    return text


def visible_chars(text):
    return len(re.sub(r'\s+','',display_text(text)))


def normalized_japanese(text):
    """Only for duplicates, not for storage or semantic judgments."""
    source=unicodedata.normalize('NFKC',display_text(text))
    return ''.join(x for x in source
                   if not unicodedata.category(x).startswith(('P','Z','C'))
                   and not x.isspace())


def length_risk(text,start_ms,end_ms):
    """Warn rather than declare translation quality from read density alone.

    Extreme subtitles are blocking candidates only after a model retry;
    short cues and Japanese names need not be mistranslations.
    """
    count=visible_chars(text)
    duration=max(0.25,(end_ms-start_ms)/1000)
    cps=round(count/duration,2)
    invalid_time=end_ms<=start_ms
    hard=invalid_time or (count>=15 and cps>BLOCK_CPS)
    warning=count>=12 and cps>WARN_CPS
    return {'characters':count,'seconds':round(duration,3),
            'characters_per_second':cps,
            'high_density':warning,'severe_density':hard}


def future_overlap(current,next_text):
    """Suggest copied *future JA* embedded in the prior JA.

    Requires a long substantive span and earlier line to have extra text.
    Do not confuse 'はい' or 'スタン' repetition with leaking 3 later lines.
    A single returned True is an advisory review flag; not a semantic verdict.
    """
    left=normalized_japanese(current)
    right=normalized_japanese(next_text)
    if len(left)<OVERLAP_MIN+4 or len(right)<OVERLAP_MIN:
        return False
    if right in left and len(left)>=len(right)+4:
        return True
    max_overlap=min(len(left),len(right))
    for n in range(max_overlap,OVERLAP_MIN-1,-1):
        if n>=max(OVERLAP_MIN,math.ceil(0.75*len(right))):
            if left.endswith(right[:n]) and len(left)>=n+4:
                return True
    return False


def overlap_ids(rows,translations,lookahead=3):
    """Return cue IDs suspected of containing future translated dialogue."""
    flags=set()
    for index,row in enumerate(rows):
        cue_id=str(row[0])
        a=translations.get(cue_id)
        if not a:
            continue
        for future in rows[index+1:index+lookahead+1]:
            b=translations.get(str(future[0]))
            if b and future_overlap(a,b):
                flags.add(row[0])
                break
    return flags


def density_flags(rows,translations):
    result={}
    for row in rows:
        key=str(row[0])
        if key in translations:
            result[row[0]]=length_risk(translations[key],row[2],row[3])
    return result


def cue_messages(rows,index,previous_japanese,series_note='',title_note='',
                 series_bible='',style='natural conversational Japanese',
                 repair=False):
    """No lookahead, raw future text, or future JA in any generation prompt.

    A scene-level synopsis may help but is advisory. Only a CURRENT cue is
    translated. For targeted repair, strip all neighbor dialogue too.
    """
    if not 0<=index<len(rows):
        raise IndexError('Cue index outside source')
    english=str(rows[index][4])
    system=(
        'Translate ONLY CURRENT_ENGLISH into one concise, natural Japanese '
        'subtitle. Register: '+style[:100]+'. Preserve meaning, negative '
        'statements, speaker intent, jokes, idioms, insults and adult content. '
        'Do not sanitize or invent events. Translate show-specific proper '
        'names consistently. Natural localization is preferred to literal '
        'word matching. If the original is long, condense faithfully to one '
        'watchable subtitle. Never translate context or later dialogue. '
        'Return ONLY Japanese SRT-ready text; no headings, multiple versions, '
        'explanations, JSON, or Markdown.'
    )
    if repair:
        system+=(
            ' This is a targeted correction for an output that was too long '
            'or repeated other dialogue. Translate just the current subtitle '
            'without adding neighboring lines or changing its meaning.'
        )
    else:
        system+=(
            '\n[ADVISORY_SERIES_GUIDE]\n'+series_bible[:1600]+
            '\n[/ADVISORY_SERIES_GUIDE]'
            '\n[ADVISORY_SERIES_CONTEXT]\n'+series_note[:850]+
            '\n[/ADVISORY_SERIES_CONTEXT]'
            '\n[ADVISORY_TITLE_CONTEXT]\n'+title_note[:850]+
            '\n[/ADVISORY_TITLE_CONTEXT]'
        )
    segments=[]
    if not repair:
        prior=[str(row[4]) for row in rows[max(0,index-MAX_PREVIOUS_EN):index]]
        if prior:
            segments.append('[PRIOR_ENGLISH_CONTEXT]\n'+'\n'.join(prior)[-450:]+
                            '\n[/PRIOR_ENGLISH_CONTEXT]')
        if previous_japanese:
            segments.append('[PRIOR_JAPANESE_CONTEXT]\n'+
                            '\n'.join(previous_japanese[-MAX_PREVIOUS_JA:])[-130:]+
                            '\n[/PRIOR_JAPANESE_CONTEXT]')
    segments.append('[CURRENT_ENGLISH]\n'+english+'\n[/CURRENT_ENGLISH]')
    segments.append('Reply with only the Japanese for CURRENT_ENGLISH.')
    return [{'role':'system','content':system},
            {'role':'user','content':'\n\n'.join(segments)}]
