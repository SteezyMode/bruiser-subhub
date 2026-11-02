#!/usr/bin/env python3
"""Deterministic, no-model Japanese subtitle watchability publication gate.

Protects future auto-published American Dad Japanese tracks. Uses the existing
v010 context-leakage/reading-speed heuristics rather than inventing a second
model or editing an accepted cue. No video, SRT, or SQLite mutations here.

A held candidate remains in SubHub's SQLite checkpoint queue. Review/repair
must produce a separate versioned track; never truncate dialogue blindly.
"""
from __future__ import annotations

from collections import Counter
import os
from pathlib import Path
import re
import tempfile

try:
    import subtitle_quality_010 as q
except ModuleNotFoundError:
    from tools import subtitle_quality_010 as q

# Broad, deliberately easy-to-explain readability ceiling:
# - no more than two visible lines,
# - no more than 18 visible Japanese code-points per line,
# - no more than 32 visible code-points in one cue regardless of duration,
# - additionally enforce the existing severe read-speed and future-leak flags.
# This is a *prepublication hold*, not a translation or an editorial score.
MAX_LINES=2
MAX_LINE_CHARS=18
MAX_CUE_CHARS=32
MAX_EXAMPLE_IDS=12
SHOW=re.compile(r'american[\s._!()-]*dad',re.I)


def is_american_dad(video):
    return bool(SHOW.search(str(video)))


def audit(rows):
    """Return private numeric QA only; never log subtitle dialogue or paths.

    Rows can be sqlite3.Row instances or any mappings with the canonical
    existing SubHub 1.0 cue fields: cue_id/start_ms/end_ms/english/japanese.
    """
    items=[]
    translations={}
    reasons={}
    warnings=Counter()
    for cue in rows:
        number=int(cue['cue_id'])
        start,end=int(cue['start_ms']),int(cue['end_ms'])
        japanese=cue['japanese']
        if not isinstance(japanese,str) or not japanese.strip():
            raise ValueError('Cannot QA uncompleted Japanese cues')
        items.append((number,cue['timing'],start,end,cue['english']))
        translations[str(number)]=japanese
        risk=q.length_risk(japanese,start,end)
        fields=[]
        if risk['severe_density']:
            fields.append('severe_reading_speed')
        elif risk['high_density']:
            warnings['fast']+=1
        if risk['characters']>MAX_CUE_CHARS:
            fields.append('too_many_visible_characters')
        # Work on actual screen lines, not a whitespace-collapsed string.
        visible_lines=[
            q.display_text(line)
            for line in japanese.replace('\r\n','\n').replace('\r','\n').split('\n')
        ]
        visible_lines=[line for line in visible_lines if line.strip()]
        if len(visible_lines)>MAX_LINES:
            fields.append('too_many_lines')
        if any(q.visible_chars(line)>MAX_LINE_CHARS for line in visible_lines):
            fields.append('long_screen_line')
        if fields:
            reasons[number]=fields
    for number in q.overlap_ids(items,translations):
        reasons.setdefault(number,[]).append('possible_future_dialogue_leak')
    kinds=Counter(reason for labels in reasons.values() for reason in labels)
    blocked=bool(reasons)
    return {
        'schema':'bruiser-ja-publish-readability-v1',
        'cues_checked':len(items),
        'publication_held':blocked,
        'flagged_cues':len(reasons),
        'reasons':dict(sorted(kinds.items())),
        'first_flagged_cue_ids':sorted(reasons)[:MAX_EXAMPLE_IDS],
        'warnings':dict(warnings),
        'limits':{
            'lines':MAX_LINES,'characters_per_line':MAX_LINE_CHARS,
            'characters_per_cue':MAX_CUE_CHARS,
            'severe_characters_per_second':q.BLOCK_CPS,
        },
    }


def assert_publishable(rows):
    """Raise before the original publisher creates any target JA file."""
    report=audit(rows)
    if report['publication_held']:
        ids=','.join(map(str,report['first_flagged_cue_ids']))
        issues=','.join(
            f'{name}={count}' for name,count in report['reasons'].items())
        raise RuntimeError(
            f'Japanese subtitle readability QA hold: '
            f'{report["flagged_cues"]}/{report["cues_checked"]} cues; '
            f'{issues}; first_ids={ids}')
    return report



def publish_atomically(store,job,original_publisher,service_module,apply):
    """Retain native preflight yet make final create-only JA crash-safe.

    Native SubHub 1.0 currently opens final .ja.srt with O_EXCL and streams
    bytes to it. A power loss during that write could leave an incomplete
    file that blocks subsequent retries. Stage and fsync a hidden tempfile,
    then hard-link it into place as a single create-only directory operation.
    SQLite job is marked published ONLY after full file availability.
    Existing approved/legacy JA protection is validated by native service.
    """
    if not apply:
        return original_publisher(store,job,apply=False)
    # This executes all existing source/audio/JA-media-sidecar protections.
    target,_=original_publisher(store,job,apply=False)
    target=Path(target)
    rows=store.rows(job['id'])
    result=service_module.render_srt(
        [(r['cue_id'],r['timing'],r['start_ms'],r['end_ms'],r['english'])
         for r in rows],
        {str(r['cue_id']):r['japanese'] for r in rows},
    )
    if target.is_symlink():
        raise RuntimeError('Refuse symlinked Japanese target')
    if not target.exists():
        fd,tmp=tempfile.mkstemp(
            prefix='.'+target.name+'.staging-',suffix='.tmp',
            dir=str(target.parent))
        tmp=Path(tmp)
        try:
            with os.fdopen(fd,'wb') as handle:
                handle.write(result)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(tmp,0o644)
            try:
                os.link(tmp,target,follow_symlinks=False)
            except FileExistsError:
                if target.is_symlink() or not target.is_file() or target.read_bytes()!=result:
                    raise RuntimeError('Concurrent Japanese target differs; no overwrite')
            # Directory entry durability before the database says published.
            with os.fdopen(os.open(target.parent,os.O_RDONLY|os.O_DIRECTORY)) as directory:
                os.fsync(directory.fileno())
        finally:
            tmp.unlink(missing_ok=True)
    elif not target.is_file() or target.read_bytes()!=result:
        raise RuntimeError('Existing Japanese target differs; no overwrite')

    store.cn.execute(
        'UPDATE jobs SET published_sha=?,status=?,updated=? WHERE id=?',
        (service_module.sha(result),'published',
         service_module.stamp(),job['id']))
    store.event(job['id'],'published',
                'QA-verified, create-only, atomic Japanese sidecar; '
                'existing subtitles preserved')
    return target,'published'
