#!/usr/bin/env python3
"""Reversible, resumable readability repair of real American Dad S19E04.

Original existing v009 JA pilot is NEVER changed. Restore only risky cues
from their own English input (no future English in prompt), preserve all cue
IDs and timings, and create a separate versioned JA SRT ONLY if final numeric
reading/overlap QA passes.

All model calls run locally through the already-installed subtitle-tuned E4B.
The per-cue private checkpoints survive shutdown and reruns. No new prompts,
services, or system-wide configuration are installed.
"""
from __future__ import annotations

import argparse
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import time

import service
try:
    import american_dad_intake_009 as intake
    import american_dad_core_009 as core
    import subtitle_quality_010 as q
    import subtitle_publish_gate as gate
    import s19e04_recovery_v2 as recovery
except ModuleNotFoundError:
    from tools import american_dad_intake_009 as intake
    from tools import american_dad_core_009 as core
    from tools import subtitle_quality_010 as q
    from tools import subtitle_publish_gate as gate
    from tools import s19e04_recovery_v2 as recovery

SCHEMA='bruiser-american-dad-s19e04-readability-repair-v1'
STATE=core.BASE/'american-dad-s19e04-repair'
SEMANTIC_REVIEW={54}  # Real v009 paired audit: S19E04 idiom/joke not conveyed
MAX_REPAIRS=200
EPISODE=(19,4)
VERSION='Bruiser Readability Repair v1 Japanese.ja.srt'


def create_exact(path,data,mode=0o600):
    """Atomically create only; an interrupted write never becomes final."""
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    if path.is_symlink():
        raise RuntimeError('Unsafe symlinked private output path')
    if path.exists():
        if not path.is_file() or path.read_bytes()!=data:
            raise RuntimeError('Existing repair artifact differs; no overwrite')
        return False
    fd,name=tempfile.mkstemp(prefix='.'+path.name+'.stage-',suffix='.tmp',
                             dir=path.parent)
    temp=Path(name)
    try:
        with os.fdopen(fd,'wb') as out:
            os.fchmod(out.fileno(),mode)
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        try:
            os.link(temp,path,follow_symlinks=False)
        except FileExistsError:
            if path.is_symlink() or not path.is_file() or path.read_bytes()!=data:
                raise RuntimeError('New competing output appeared')
        dirfd=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(dirfd)
        finally:os.close(dirfd)
        return True
    finally:
        temp.unlink(missing_ok=True)


def save_json(path,data):
    create_exact(path,(json.dumps(data,ensure_ascii=False,
                                  sort_keys=True,indent=2)+'\n').encode())


def select_one(roots=intake.ROOTS):
    videos=[]
    for video in intake.discover(roots):
        match=intake.EPISODE.search(video.name)
        if not match or (int(match[1]),int(match[2]))!=EPISODE:
            continue
        source=intake.pilot_path(video)
        if source.is_file() and not source.is_symlink():
            videos.append(video)
    if len(videos)!=1:
        raise RuntimeError(
            'Require exactly one S19E04 video with existing v009 Pilot JA')
    return videos[0]


def read_pair(video,roots=intake.ROOTS,extract=intake.extract,
              tracks=intake.tracks):
    if not intake.safe_video(video,roots):
        raise RuntimeError('S19E04 video outside approved original roots')
    pilot=intake.pilot_path(video)
    if pilot.is_symlink() or not pilot.is_file():
        raise RuntimeError('Original published v009 JA track missing')
    source,rows=extract(video,tracks(video))
    ja_raw=pilot.read_bytes()
    ja=service.parse_srt(ja_raw)
    if len(rows)!=len(ja):
        raise RuntimeError('English/JA cue count mismatch')
    for en,jp in zip(rows,ja):
        if en[:4]!=jp[:4]:
            raise RuntimeError('English/JA numbering or timestamps mismatch')
    if not 130<=len(rows)<=1500:
        raise RuntimeError('Unexpected source episode cue count')
    return rows,{str(j[0]):j[4] for j in ja},source,ja_raw


def detected_ids(rows,translations):
    flagged=set()
    for id,_,start,end,_en in rows:
        text=translations[str(id)]
        risk=q.length_risk(text,start,end)
        lines=[q.display_text(line) for line in text.splitlines()
               if q.display_text(line)]
        if (risk['severe_density'] or
            risk['characters']>gate.MAX_CUE_CHARS or
            len(lines)>gate.MAX_LINES or
            any(q.visible_chars(line)>gate.MAX_LINE_CHARS for line in lines)):
            flagged.add(id)
    flagged.update(q.overlap_ids(rows,translations))
    return flagged


def manifest(video,rows,translations,source,original):
    st=video.stat()
    original_ids=sorted(detected_ids(rows,translations)|SEMANTIC_REVIEW)
    if len(original_ids)>MAX_REPAIRS:
        raise RuntimeError('Unexpected excessive repair scope; stop for review')
    return {'schema':SCHEMA,'video':str(video),'size':st.st_size,
            'mtime_ns':st.st_mtime_ns,
            'source_sha':intake.sha(source),
            'pilot_sha':intake.sha(original),
            'cue_count':len(rows),'repair_ids':original_ids,
            'model':core.MODEL,'model_id':core.MODEL_ID,
            'quality_sha':hashlib.sha256(
                Path(q.__file__).read_bytes()).hexdigest()}


def verify_frozen(root,data):
    path=Path(root)/'manifest.json'
    if path.is_symlink():
        raise RuntimeError('Unsafe repair manifest')
    if path.exists() and json.loads(path.read_text(encoding='utf8'))!=data:
        raise RuntimeError('Original source/pilot/model/quality identity changed')
    save_json(path,data)


def checkpoint(root,id,baseline):
    path=Path(root)/'cues'/f'{id:05d}.json'
    if not path.exists():
        return None
    if path.is_symlink():
        raise RuntimeError('Unsafe repair cue checkpoint')
    item=json.loads(path.read_text(encoding='utf8'))
    if item.get('cue_id')!=id or item.get('manifest_sha')!=baseline:
        raise RuntimeError('Existing saved repair cue identity mismatch')
    return item.get('japanese')


def messages(rows,index,attempt):
    messages=q.cue_messages(
        rows,index,[],repair=True,
        style='concise Japanese television captions for adult comedy')
    if attempt==2:
        messages[0]['content']+=(
            ' Strict display limit: at most two lines, each no more than '
            '16 Japanese characters. Omit redundant subjects, NEVER omit '
            'essential meaning or the joke. Do not include future speech.'
        )
    return messages


def acceptable(candidate,english,start,end,later):
    text=core.normalized_srt_markup(candidate,english)
    if text is None or not core.valid(text,english):
        return None
    risk=q.length_risk(text,start,end)
    lines=[q.display_text(x) for x in text.splitlines()
           if q.display_text(x)]
    if (risk['severe_density'] or risk['characters']>gate.MAX_CUE_CHARS
        or len(lines)>gate.MAX_LINES
        or any(q.visible_chars(x)>gate.MAX_LINE_CHARS for x in lines)):
        return None
    if any(q.future_overlap(text,x) for x in later):
        return None
    return text


def output(video):
    return video.with_name(video.stem+'.'+VERSION)


def execute(state=STATE,roots=intake.ROOTS,ask=core.call,
            max_minutes=180,publish=False,selector=select_one,
            pair_loader=read_pair,log=print):
    if not 1<=max_minutes<=480:
        raise ValueError('Repair time must be 1..480 minutes')
    state=Path(state)
    video=selector(roots)
    rows,original,source,old_ja=pair_loader(video,roots)
    frozen=manifest(video,rows,original,source,old_ja)
    verify_frozen(state,frozen)
    # The real first pass already produced an immutable report and many
    # accepted cue checkpoints. On subsequent runs do NOT re-request the
    # same rejected two prompts; switch to a bounded new v2 recovery profile.
    second_pass=any(state.glob('report-*.json'))
    sha=intake.sha((json.dumps(frozen,sort_keys=True)).encode('utf8'))
    target=output(video)
    if target.is_symlink():
        raise RuntimeError('Unsafe existing repaired track symlink')
    planned=frozen['repair_ids']
    log('S19E04_REPAIR_PLAN','source_cues',len(rows),
        'flagged',len(planned),'original_preserved',True,
        'mode','bounded_v2' if second_pass else 'original_v1')
    final=dict(original)
    deadline=time.monotonic()+60*max_minutes
    unresolved=[]
    corrected=0
    index_of={r[0]:index for index,r in enumerate(rows)}
    with core.locks():
        if ask is core.call and planned and not target.exists():
            core.preflight()
        for id in planned:
            existing=checkpoint(state,id,sha)
            if existing is not None:
                final[str(id)]=existing
                corrected+=1
                continue
            if time.monotonic()>=deadline:
                unresolved.append(id)
                continue
            index=index_of[id]
            _,_,start,end,english=rows[index]
            later=[final[str(x[0])] for x in rows[index+1:index+4]]
            answer=None
            # A purely visual line-wrap correction never edits translated
            # words, removes jokes, or consumes any model/GPU time.
            if second_pass:
                answer=recovery.reflow_unaltered_japanese(
                    original[str(id)],english,start,end,later,acceptable)
                if answer is not None:
                    save_json(state/'cues'/f'{id:05d}.json',
                              {'cue_id':id,'manifest_sha':sha,
                               'japanese':answer,'attempt':'reflow-v2'})
                    final[str(id)]=answer
                    corrected+=1
                    log('S19E04_REFLOWED','cue',id,'unchanged_words',True)
                    continue
            for attempt in (recovery.ATTEMPTS if second_pass else (1,2)):
                if time.monotonic()>=deadline:
                    break
                prompt=(recovery.messages(rows,index,attempt)
                        if second_pass else messages(rows,index,attempt))
                if second_pass and recovery.was_rejected(
                        state,id,attempt,sha,prompt):
                    continue
                try:
                    proposal=ask(prompt)
                    answer=acceptable(proposal,english,start,end,later)
                except (RuntimeError,OSError,ValueError,KeyError,TypeError):
                    # A transient model/API failure is NOT recorded as a
                    # completed rejected answer; a future run can retry it.
                    answer=None
                    log('S19E04_INFERENCE_DEFERRED','cue',id,
                        'attempt',attempt)
                    break
                if answer is not None:
                    save_json(state/'cues'/f'{id:05d}.json',
                              {'cue_id':id,'manifest_sha':sha,
                               'japanese':answer,'attempt':attempt})
                    final[str(id)]=answer
                    corrected+=1
                    log('S19E04_REPAIRED','cue',id,'attempt',attempt)
                    break
                if second_pass:
                    # Persist only an identity and a rejection reason, never
                    # output text, to avoid burning GPU on identical prompts.
                    recovery.record_rejection(
                        state,id,attempt,sha,prompt,save_json)
            if answer is None:
                unresolved.append(id)
                log('S19E04_HELD','cue',id,
                    'bounded_v2' if second_pass else 'first_pass')
        report=gate.audit([
            {'cue_id':id,'timing':timing,'start_ms':start,'end_ms':end,
             'english':english,'japanese':final[str(id)]}
            for id,timing,start,end,english in rows
        ])
        data={'schema':SCHEMA,'source_cues':len(rows),
              'planned':len(planned),'corrected_or_reused':corrected,
              'unresolved_ids':unresolved,'readability':report,
              'mode':'bounded_v2' if second_pass else 'original_v1',
              'original_pilot_sha':frozen['pilot_sha']}
        digest=intake.sha(json.dumps(data,sort_keys=True).encode('utf8'))[:14]
        save_json(state/('report-'+digest+'.json'),data)
        if unresolved or report['publication_held']:
            log('S19E04_REPAIR_HOLD',json.dumps({
                'remaining_repair_attempts':len(unresolved),
                'remaining_quality_flags':report['flagged_cues'],
                'first_ids':report['first_flagged_cue_ids']},sort_keys=True))
            return 'held'
        completed=service.render_srt(rows,final)
        draft=state/'repaired.ja.srt'
        create_exact(draft,completed)
        if not publish:
            log('S19E04_REPAIR_READY_PRIVATE','cues',len(rows))
            return 'private_ready'
        # Re-read original source/pilot and validate fingerprints immediately
        # before writing the separate versioned track.
        check_rows,check_ja,check_en,check_pilot=pair_loader(video,roots)
        if (intake.sha(check_en)!=frozen['source_sha'] or
            intake.sha(check_pilot)!=frozen['pilot_sha'] or
            check_rows!=rows):
            raise RuntimeError('Original subtitle identity changed during repair')
        create_exact(target,completed,mode=0o644)
        log('S19E04_REPAIR_PUBLISHED','separate_versioned_ja_track',
            'cues',len(rows),'original_unchanged',True)
        return 'published'


def cli(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=('plan','run','status'))
    p.add_argument('--max-minutes',type=int,default=180)
    p.add_argument('--publish',action='store_true')
    args=p.parse_args(argv)
    try:
        if args.action=='status':
            files=sorted(STATE.glob('report-*.json'),key=lambda p:p.stat().st_mtime_ns)
            path=files[-1] if files else STATE/'missing-report.json'
            if path.is_file():
                info=json.loads(path.read_text(encoding='utf8'))
                print('S19E04_REPAIR_STATUS',
                      json.dumps({'planned':info['planned'],
                        'unresolved':len(info['unresolved_ids']),
                        'readability':info['readability']['flagged_cues']}))
            else:print('S19E04_REPAIR_STATUS','not_started')
            return 0
        if args.action=='plan':
            video=select_one()
            rows,translations,source,original=read_pair(video)
            print('S19E04_REPAIR_PREVIEW',len(rows),
                  'flagged',len(detected_ids(rows,translations)|SEMANTIC_REVIEW))
            return 0
        state=execute(max_minutes=args.max_minutes,publish=args.publish)
        # A QA hold is a successfully completed inspection, not a Python or
        # systemd runtime failure. Explicit log/state indicate NOT published.
        print('S19E04_REPAIR_RESULT',state,'published',state=='published',
              flush=True)
        return 0 if state in ('published','private_ready','held') else 1
    except Exception as exc:
        print('S19E04_REPAIR_BLOCKED',type(exc).__name__,file=sys.stderr)
        return 1


if __name__=='__main__':
    os.umask(0o077)
    raise SystemExit(cli())
