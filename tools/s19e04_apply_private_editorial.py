#!/usr/bin/env python3
"""Apply a privately delivered 27-cue S19E04 editorial review, create-only.

The private payload is deliberately NOT kept in this public repository.
This tool validates SHA256 of each cue's original English and prior Japanese
against the real video/pilot, overlays accepted v1/v2 private checkpoints,
and makes a separate versioned Japanese subtitle only on full-episode QA PASS.

No Ollama calls, no source media modification, no checkpoint writes, no delete.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

import service
try:
    import repair_s19e04 as repair
    import subtitle_publish_gate as gate
    import american_dad_core_009 as core
except ModuleNotFoundError:
    from tools import repair_s19e04 as repair
    from tools import subtitle_publish_gate as gate
    from tools import american_dad_core_009 as core

SCHEMA='bruiser-s19e04-private-editorial-v1'
OUTPUT_SUFFIX='Bruiser Curated Japanese v2.ja.srt'
REQUIRED_CUES=frozenset((
    7,8,52,53,57,58,76,77,88,96,108,117,122,145,152,157,
    192,205,225,226,230,254,274,292,302,338,364
))
CUES_EXPECTED=392


def sha(s):
    return hashlib.sha256(s.encode('utf8')).hexdigest()


def validate_payload(payload):
    if not isinstance(payload,dict):
        raise ValueError('Private editorial payload must be an object')
    if (payload.get('schema')!=SCHEMA or
        payload.get('episode')!='S19E04' or
        payload.get('total_cues')!=CUES_EXPECTED or
        payload.get('reviewed_cues')!=len(REQUIRED_CUES)):
        raise ValueError('Unexpected private S19E04 editorial schema or scope')
    items=payload.get('entries')
    if not isinstance(items,list) or len(items)!=len(REQUIRED_CUES):
        raise ValueError('Private editorial entries must contain 27 distinct cues')
    entries={}
    for item in items:
        if not isinstance(item,dict):
            raise ValueError('Malformed private editorial cue')
        number=item.get('cue_id')
        if not isinstance(number,int) or isinstance(number,bool) or number in entries:
            raise ValueError('Duplicate or invalid private editorial cue ID')
        for field in ('english_sha256','original_japanese_sha256'):
            value=item.get(field)
            if not isinstance(value,str) or len(value)!=64 or any(
                    c not in '0123456789abcdef' for c in value):
                raise ValueError('Invalid original cue fingerprint')
        japanese=item.get('japanese')
        if (not isinstance(japanese,str) or not japanese.strip() or
            len(japanese)>400 or '\x00' in japanese or
            '\r' in japanese or len(japanese.splitlines())>2):
            raise ValueError('Invalid private Japanese correction')
        entries[number]=item
    if frozenset(entries)!=REQUIRED_CUES:
        raise ValueError('Private cue ID set differs from reviewed 27')
    return entries


def review_full_episode(payload, state=repair.STATE,
                        roots=repair.intake.ROOTS,
                        selector=repair.select_one,
                        pair_loader=repair.read_pair):
    entries=validate_payload(payload)
    video=selector(roots)
    rows,original,en_bytes,old_ja_bytes=pair_loader(video,roots)
    if len(rows)!=CUES_EXPECTED:
        raise RuntimeError('Episode has changed: expected precisely 392 cues')
    frozen=repair.manifest(video,rows,original,en_bytes,old_ja_bytes)
    # Verify against the original immutable v1 manifest and accepted checkpoint
    # identity. Its only permitted side effect is creating an absent private
    # manifest for an otherwise legitimate first-time run.
    repair.verify_frozen(state,frozen)
    baseline_sha=repair.intake.sha(
        json.dumps(frozen,sort_keys=True).encode('utf8'))
    final=dict(original)
    for row in rows:
        recovered=repair.checkpoint(state,row[0],baseline_sha)
        if recovered is not None:
            final[str(row[0])]=recovered
    for number,item in entries.items():
        row=rows[number-1]
        if row[0]!=number:
            raise RuntimeError('Original cue IDs no longer sequential')
        if sha(row[4])!=item['english_sha256']:
            raise RuntimeError('English input fingerprint mismatch for cue '+str(number))
        if sha(original[str(number)])!=item['original_japanese_sha256']:
            raise RuntimeError('Original Japanese fingerprint mismatch for cue '+str(number))
        correction=item['japanese']
        if not core.valid(correction,row[4]):
            raise RuntimeError('Invalid editorial Japanese for cue '+str(number))
        final[str(number)]=correction
    qa_rows=[
        {'cue_id':num,'timing':timing,'start_ms':start,
         'end_ms':end,'english':english,'japanese':final[str(num)]}
        for num,timing,start,end,english in rows]
    result=gate.audit(qa_rows)
    return video,rows,original,en_bytes,old_ja_bytes,final,result


def publish(payload,state=repair.STATE,roots=repair.intake.ROOTS,
            selector=repair.select_one,pair_loader=repair.read_pair,
            apply=False,log=print):
    """Publish versioned track after private preview and full QA, or hold."""
    with core.locks():
        (video,rows,original,source,pilot,final,report)=review_full_episode(
            payload,state,roots,selector,pair_loader)
        log('S19E04_EDITORIAL_AUDIT',json.dumps({
            'cues':len(rows),'overrides':len(REQUIRED_CUES),
            'still_flagged':report['flagged_cues'],
            'reasons':report['reasons'],
            'first_flagged_ids':report['first_flagged_cue_ids']},
            sort_keys=True),flush=True)
        if report['publication_held']:
            log('S19E04_EDITORIAL_HOLD',
                'no_new_subtitle_published',flush=True)
            return 'held'
        raw=service.render_srt(rows,final)
        if len(service.parse_srt(raw))!=len(rows):
            raise RuntimeError('Final editorial JA subtitle is not a valid complete SRT')
        state=Path(state)
        state.mkdir(mode=0o700,parents=True,exist_ok=True)
        # The checkpointed 365 other cue translations can legitimately
        # advance after an earlier private preview. Version the preview by
        # BOTH private correction payload AND the actual complete SRT bytes.
        fingerprint=sha(json.dumps(payload,ensure_ascii=False,
                                   sort_keys=True)+hashlib.sha256(raw).hexdigest())
        preview=state/('editorial-preview-'+fingerprint[:16]+'.ja.srt')
        repair.create_exact(preview,raw,mode=0o600)
        log('S19E04_EDITORIAL_PRIVATE_PREVIEW','qa_pass',True,
            'cues',len(rows),flush=True)
        if not apply:
            return 'private_ready'
        # Detect changes to the original source between review and
        # create-only publication; do not attempt any in-place promotion.
        check_rows,check_orig,check_source,check_pilot=pair_loader(video,roots)
        if (check_rows!=rows or
            check_orig!=original or check_source!=source or
            check_pilot!=pilot):
            raise RuntimeError('S19E04 source changed during editorial approval')
        target=video.with_name(video.stem+'.'+OUTPUT_SUFFIX)
        repair.create_exact(target,raw,mode=0o644)
        log('S19E04_EDITORIAL_PUBLISHED','new_separate_versioned_track',
            'cues',len(rows),'original_unchanged',True,
            'original_repair_checkpoints_preserved',True,flush=True)
        return 'published'


def cli(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('payload',type=Path)
    p.add_argument('--publish',action='store_true')
    args=p.parse_args(argv)
    try:
        if args.payload.is_symlink() or not args.payload.is_file():
            raise RuntimeError('Private payload missing or symlink')
        data=json.loads(args.payload.read_text(encoding='utf8'))
        status=publish(data,apply=args.publish)
        print('S19E04_EDITORIAL_RESULT',status,
              'published',status=='published',flush=True)
        # Held is valid review result, not a model/system failure; caller
        # must inspect S19E04_EDITORIAL_RESULT, never exit-code-only.
        return 0
    except Exception as exc:
        print('S19E04_EDITORIAL_BLOCKED',type(exc).__name__,
              str(exc)[:130],file=sys.stderr)
        return 1


if __name__=='__main__':
    os.umask(0o077)
    raise SystemExit(cli())
