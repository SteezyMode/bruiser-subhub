#!/usr/bin/env python3
"""v013: 9 private two-cue sentence-context experiments on one pinned Gemma E4B.

NO new whole-utterance inference. Reuse the nine clean, unnumbered, complete
single-sentence JA replies from frozen v012 formatlab. Translate each of their
18 original English cues once, with the whole EN + old JA as ADVISORY context,
but a SINGLE focus cue as the only target per model call.

Writes only a NEW code-hashed lab state; never alters media, SRTs, existing
v011/v012 attempts/checkpoints, Jellyfin, production SQLite or services.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import sys
import tarfile
import time

ORIGINAL_CODE = Path.home()/'bruiser-pilot/utterance-011-code'
FORMAT_CODE = Path.home()/'bruiser-pilot/utterance-formatlab-012-code'
# Keep original v011 importable by v012; separate old module versions are pinned.
for directory in (FORMAT_CODE, ORIGINAL_CODE):
    if directory.is_dir():
        sys.path.insert(0,str(directory))
import service
try:
    import american_dad_utterance_011 as old
    import american_dad_core_009 as core
    import semantic_groups_011 as semantic
    import utterance_formatlab_012 as lab
except ModuleNotFoundError:
    from tools import american_dad_utterance_011 as old
    from tools import american_dad_core_009 as core
    from tools import semantic_groups_011 as semantic
    from tools import utterance_formatlab_012 as lab

SCHEMA='bruiser-utterance-focuslab-v013'
LAB=core.BASE/'utterance-focuslab-013'
EXPECTED_GROUPS=9
MAX_CALLS=18
JP=re.compile(r'[\u3040-\u30ff\u3400-\u9fff]')
LEADING_ID=re.compile(r'^\s*\d{1,5}\s*[:|.-]')
GROUP_SEPARATOR=re.compile(r'\|')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def code_sha():
    return sha(Path(__file__).read_bytes())


def regular(path):
    path=Path(path)
    if path.is_symlink() or not path.is_file():
        raise RuntimeError('Missing/unsafe frozen private file')
    return path.read_bytes()


def ensure_original(state=LAB,source_state=lab.ORIGINAL,
                    old_lab=lab.LAB,profile=core.PROFILE,
                    recovered_state=lab.RECOVERY):
    """Never create/reset v012 state; freeze a separate v013 selection."""
    old_sel=Path(old_lab)/'selection.json'
    if old_sel.is_symlink() or not old_sel.is_file():
        raise RuntimeError('Original v012 comparison is missing')
    old_selection,english=lab.freeze(old_lab,source_state,profile)
    if len(old_selection['selected'])!=24:
        raise RuntimeError('Unexpected original v012 sample size')
    source_manifest=json.loads(regular(Path(source_state)/'manifest.json'))
    if source_manifest.get('model_id')!=core.MODEL_ID:
        raise RuntimeError('Pinned E4B model identity changed')

    baseline={}
    baseline_bytes={}
    for episode in lab.EPISODES:
        raw=regular(Path(recovered_state)/'episodes'/episode/'pilot-recovered.ja.srt')
        rows=service.parse_srt(raw)
        if len(rows)!=len(english[episode]) or any(
                a[:4]!=b[:4] for a,b in zip(rows,english[episode])):
            raise RuntimeError('Published recovery EN/JA baseline drifted')
        baseline_bytes[episode]=sha(raw)
        baseline[episode]={str(x[0]):x[4] for x in rows}

    selected=[]
    for item in old_selection['selected']:
        group=lab.group_for(item,english[item['episode']])
        if len(group)!=2:
            continue
        path=lab.result_path(old_lab,item,'lines')
        result=json.loads(regular(path))
        if any(result.get(k)!=v for k,v in (
              ('schema',lab.SCHEMA),('episode',item['episode']),
              ('unit_sha',item['unit_sha']),('ids',item['cue_ids']),
              ('mode','lines'),('stratum',item['stratum']))):
            raise RuntimeError('Prior raw response identity mismatch')
        if result.get('status')!='failed' or (
                result.get('failure_category')!='id_mapping_or_count'):
            continue
        raw=result.get('raw_private')
        # Specifically inspect real v012 responses that were ONE coherent
        # unnumbered Japanese sentence; never apply ad-hoc auto-splitting.
        if not isinstance(raw,str) or not raw.strip():
            continue
        raw=raw.strip()
        if (len(raw)>300 or len(raw.splitlines())!=1 or
            not JP.search(raw) or LEADING_ID.search(raw) or
            GROUP_SEPARATOR.search(raw)):
            continue
        selected.append({
            'episode':item['episode'],
            'stratum':item['stratum'],
            'unit_sha':item['unit_sha'],
            'cue_ids':item['cue_ids'],
            'whole_ja_sha':sha(raw.encode('utf8')),
            'whole_japanese':raw,
        })
    if len(selected)!=EXPECTED_GROUPS or sum(
            len(x['cue_ids']) for x in selected)!=MAX_CALLS:
        raise RuntimeError('Unexpected selection of coherent unnumbered v012 replies')
    info={
        'schema':SCHEMA,
        'code_sha':code_sha(),
        'model_id':core.MODEL_ID,
        'model_name':core.MODEL,
        'source_manifest_sha':sha(regular(Path(source_state)/'manifest.json')),
        'source_pipeline_sha':source_manifest['pipeline_sha'],
        'formatlab_selection_sha':sha(regular(old_sel)),
        'profile_sha':sha(Path(profile).read_bytes()),
        'baseline_shas':baseline_bytes,
        'selected':selected,
    }
    target=Path(state)/'selection.json'
    if target.exists() or target.is_symlink():
        if json.loads(regular(target))!=info:
            raise RuntimeError('Versioned focus lab selection/code identity changed')
    else:
        core.save(target,info)
    return info,english,baseline


def group_for(item,english):
    match={x[0]:x for x in english[item['episode']]}
    try:
        group=tuple(match[n] for n in item['cue_ids'])
    except KeyError as exc:
        raise RuntimeError('Missing source cue in focus selection') from exc
    if (len(group)!=2 or
        semantic.unit_sha(group)!=item['unit_sha'] or
        sha(item['whole_japanese'].encode('utf8'))!=item['whole_ja_sha']):
        raise RuntimeError('Focus group source/whole-translation identity changed')
    return group


def focus_messages(group,focus,whole_ja,profile):
    """One cue only, but show whole utterance as untrusted *meaning* context."""
    if len(group)!=2 or focus not in group:
        raise ValueError('Requires original focus cue in two-cue utterance')
    other=next(r for r in group if r[0]!=focus[0])
    prompt=(
        'You translate a SINGLE subtitle cue into natural spoken Japanese. '
        'This is adult comedy. PRESERVE the precise target cue meaning, intent, '
        'negation, slang, joke and character names. Do not sanitize. '
        'The source sentence was split across two time windows. The other '
        'English fragment and the existing whole-Japanese translation help '
        'interpret the sentence, but are CONTEXT ONLY, NOT text to translate. '
        'The existing whole Japanese may have mistakes. English is authoritative. '
        'Never place a fact, object, name or punchline first introduced in the '
        'OTHER cue in the TARGET cue. NEVER translate the whole sentence. '
        'Respond with ONLY the Japanese words corresponding to the TARGET_EN '
        'portion, with no numeric IDs, headings, JSON, quotes or explanation. '
        'Natural fragments are permitted when grammatically required. '
        'Make the target readable in its own allotted time.\n'
        '[ADVISORY_NAMES]\n'+core.compact_profile(profile)[:800]+
        '\n[/ADVISORY_NAMES]'
    )
    # Both English cues are shown, explicitly with their original IDs and roles.
    blocks='\n'.join(
       '%d [%s]: %s'%(r[0],
          'TARGET' if r[0]==focus[0] else 'CONTEXT_NOT_TARGET',
          re.sub(r'\s+',' ',r[4]).strip()) for r in group)
    user=(
        '[WHOLE_ENGLISH_UTTERANCE]\n'+blocks+
        '\n[/WHOLE_ENGLISH_UTTERANCE]\n'
        '[WHOLE_JAPANESE_CONTEXT_NOT_OUTPUT]\n'+whole_ja+
        '\n[/WHOLE_JAPANESE_CONTEXT_NOT_OUTPUT]\n'
        'TARGET_ID = '+str(focus[0])+'\n'
        'TARGET_EN = '+re.sub(r'\s+',' ',focus[4]).strip()+'\n'
        'CONTEXT_ONLY_EN = '+re.sub(r'\s+',' ',other[4]).strip()+'\n'
        'Translate TARGET_EN ONLY; no content introduced by CONTEXT_ONLY_EN.'
    )
    return [{'role':'system','content':prompt},
            {'role':'user','content':user}]


def path_for(state,item,row):
    return (Path(state)/'groups'/item['episode']/
            ('%05d-%05d-focus-%05d.json'%(
              item['cue_ids'][0],item['cue_ids'][-1],row[0])))


def error_kind(exc):
    s=str(exc).lower()
    if 'length cap' in s:return 'length_cap'
    if 'unwatchably dense' in s:return 'density'
    if 'speaker' in s or 'invalid singleton' in s:return 'invalid_ja_or_speaker'
    if 'timeout' in s:return 'timeout'
    return 'other_'+type(exc).__name__


def one(state,item,group,row,profile,ask=core.call):
    path=path_for(state,item,row)
    if path.exists() or path.is_symlink():
        doc=json.loads(regular(path))
        if any(doc.get(k)!=v for k,v in (
           ('schema',SCHEMA),('model_id',core.MODEL_ID),
           ('unit_sha',item['unit_sha']),('cue_id',row[0]),
           ('episode',item['episode']),('whole_ja_sha',item['whole_ja_sha']))):
            raise RuntimeError('Focus cue checkpoint identity differs')
        return doc
    raw=''
    japanese=None
    category=None
    try:
        raw=ask(focus_messages(group,row,item['whole_japanese'],profile),
                json_mode=False)
        japanese=old.validate_answer(raw,(row,))[str(row[0])]
    except Exception as exc:
        category=error_kind(exc)
    doc={
        'schema':SCHEMA,'model_id':core.MODEL_ID,
        'episode':item['episode'],'unit_sha':item['unit_sha'],
        'whole_ja_sha':item['whole_ja_sha'],'cue_id':row[0],
        'status':'valid' if japanese is not None else 'failed',
        'failure_category':category,'japanese':japanese,
        'raw_private':raw if isinstance(raw,str) else '',
    }
    core.save(path,doc)
    return doc


def tally(state,info):
    result={'schema':SCHEMA,'expected_calls':MAX_CALLS,
            'completed_calls':0,'valid_cues':0,'failed_cues':0,
            'complete_utterances':0,
            'failure_categories':{}}
    for item in info['selected']:
        docs=[]
        for cue in item['cue_ids']:
            path=(Path(state)/'groups'/item['episode']/
                  ('%05d-%05d-focus-%05d.json'%(
                     item['cue_ids'][0],item['cue_ids'][-1],cue)))
            if not path.is_file() or path.is_symlink():
                continue
            d=json.loads(regular(path))
            if (d.get('schema')!=SCHEMA or d.get('unit_sha')!=item['unit_sha']
                or d.get('cue_id')!=cue or d.get('whole_ja_sha')!=item['whole_ja_sha']):
                raise RuntimeError('Focus result tally identity mismatches')
            docs.append(d)
            result['completed_calls']+=1
            result['valid_cues']+=d.get('status')=='valid'
            result['failed_cues']+=d.get('status')=='failed'
            if d.get('status')=='failed':
                cat=d.get('failure_category') or 'unknown'
                result['failure_categories'][cat]=result['failure_categories'].get(cat,0)+1
        if len(docs)==len(item['cue_ids']) and all(d['status']=='valid' for d in docs):
            result['complete_utterances']+=1
    return result


def run(minutes=120,state=LAB,source_state=lab.ORIGINAL,old_lab=lab.LAB,
        profile=core.PROFILE,recovered_state=lab.RECOVERY,
        ask=core.call,base=core.BASE):
    info,english,_=ensure_original(state,source_state,old_lab,profile,recovered_state)
    profile_text=Path(profile).read_text(encoding='utf8')
    deadline=time.monotonic()+minutes*60
    with core.locks(base):
        if ask is core.call:
            core.preflight()
        for item in info['selected']:
            group=group_for(item,english)
            for row in group:
                if time.monotonic()>=deadline:
                    break
                record=one(state,item,group,row,profile_text,ask)
                print('FOCUSLAB_RESULT',item['episode'],
                      '%05d-%05d'%(group[0][0],group[-1][0]),
                      row[0],record['status'],record.get('failure_category') or 'ok',
                      flush=True)
            if time.monotonic()>=deadline:
                break
    counts=tally(state,info)
    print('FOCUSLAB_SUMMARY',json.dumps(counts,sort_keys=True),flush=True)
    return counts


def export(state=LAB,source_state=lab.ORIGINAL,old_lab=lab.LAB,
           profile=core.PROFILE,recovered_state=lab.RECOVERY,output=None):
    """Read-only private bilingual comparison archive after all focus calls."""
    info,english,baseline=ensure_original(state,source_state,old_lab,profile,recovered_state)
    stats=tally(state,info)
    if stats['completed_calls']!=stats['expected_calls']:
        raise RuntimeError('Focus lab incomplete; resume remaining calls')
    cases=[]
    for item in info['selected']:
        group=group_for(item,english)
        outputs={}
        for row in group:
            d=json.loads(regular(path_for(state,item,row)))
            if d.get('cue_id')!=row[0] or d.get('unit_sha')!=item['unit_sha']:
                raise RuntimeError('Focus export cue checkpoint identity differs')
            outputs[str(row[0])]={
                'status':d['status'],'japanese':d['japanese'],
                'failure_category':d['failure_category'],
                'raw_private':d['raw_private'],
            }
        flags={}
        if all(x['status']=='valid' for x in outputs.values()):
            trans={key:x['japanese'] for key,x in outputs.items()}
            checks=semantic.quality_flags(group,trans)
            flags={k:sorted(v) for k,v in checks.items()}
        cases.append({
            'episode':item['episode'],
            'stratum':item['stratum'],
            'original_unnumbered_whole_ja':item['whole_japanese'],
            'cues':[{'id':row[0],'timing':row[1],
                      'english':row[4],
                      'published_baseline_japanese':baseline[item['episode']][str(row[0])]}
                     for row in group],
            'focused_outputs':outputs,'mechanical_flags':flags,
        })
    data={
        'schema':'bruiser-focuslab-013-private-review-v1',
        'model_id':core.MODEL_ID,
        'source_description':'9 real original v012 one-line replies; 18 one-cue E4B calls',
        'summary':stats,'cases':cases,
    }
    body=(json.dumps(data,ensure_ascii=False,indent=2)+'\n').encode()
    dest=output if output is not None else sys.stdout.buffer
    with tarfile.open(fileobj=dest,mode='w|gz') as tar:
        info=tarfile.TarInfo('PRIVATE_focuslab_013_bilingual_comparison.json')
        info.size=len(body)
        info.mode=0o600
        tar.addfile(info,io.BytesIO(body))
    return stats


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('prepare','run','status','export'))
    parser.add_argument('--minutes',type=int,default=120)
    args=parser.parse_args(argv)
    if not 1<=args.minutes<=180:
        parser.error('Minutes 1..180')
    try:
        if args.action=='prepare':
            info,_,_=ensure_original()
            print('FOCUSLAB_FROZEN',len(info['selected']),'real 2-cue utterances')
        elif args.action=='run':
            run(args.minutes)
        elif args.action=='status':
            state=Path(LAB)/'selection.json'
            print(json.dumps(tally(LAB,json.loads(regular(state))),indent=2))
        else:
            export()
    except Exception as exc:
        # No raw English, Japanese, local paths or model response on terminal.
        print('FOCUSLAB_BLOCKED '+type(exc).__name__,file=sys.stderr)
        return 1
    return 0


if __name__=='__main__':
    raise SystemExit(main())
