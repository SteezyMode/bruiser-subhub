#!/usr/bin/env python3
"""READ ONLY: export existing v012 raw failed model replies for private diagnosis.

No model, inference, media, service or SQLite operations. Original v011 and
v012 frozen code/source/selection identities are validated. Output is a
PRIVATE compressed JSON archive on stdout, never public GitHub.
"""
from __future__ import annotations

from collections import Counter
import io
import json
from pathlib import Path
import re
import sys
import tarfile

CODE = Path.home()/'bruiser-pilot/utterance-formatlab-012-code'
if CODE.is_dir():
    sys.path.insert(0,str(CODE))
try:
    import utterance_formatlab_012 as lab
except ModuleNotFoundError:
    from tools import utterance_formatlab_012 as lab

SCHEMA = 'bruiser-utterance-formatlab-failures-private-v1'
NUMBERED = re.compile(r'^\s*([1-9]\d*)\s*\|\s*(\S.*)\s*$')


def classify_shape(raw, expected_ids, mode):
    """Mechanical observations only, not semantic translation quality."""
    raw=raw if isinstance(raw,str) else ''
    lines=[x for x in raw.splitlines() if x.strip()]
    id_lines=[]
    other_lines=0
    for line in lines:
        m=NUMBERED.fullmatch(line)
        if m:
            id_lines.append(m[1])
        else:
            other_lines+=1
    observations={
        'characters':len(raw),
        'nonempty_lines':len(lines),
        'numbered_lines':len(id_lines),
        'other_lines':other_lines,
        'numbered_ids':id_lines,
        'exact_requested_numbered_ids':id_lines==[str(x) for x in expected_ids]
    }
    if mode=='json':
        try:
            data=json.loads(raw)
            observations['json_valid_syntax']=True
            observations['json_is_object']=isinstance(data,dict)
            observations['json_keys_exact']=(
                isinstance(data,dict) and set(data)==set(map(str,expected_ids)))
        except (ValueError,TypeError):
            observations['json_valid_syntax']=False
            observations['json_is_object']=False
            observations['json_keys_exact']=False
    return observations


def collect(state=lab.LAB,original_state=lab.ORIGINAL,profile=lab.core.PROFILE):
    state=Path(state)
    # Existing private 012 selection MUST be present; never freeze a new one
    # from this forensic reader.
    selection=state/'selection.json'
    if selection.is_symlink() or not selection.is_file():
        raise RuntimeError('Existing frozen v012 selection missing')
    frozen,source_rows=lab.freeze(state,original_state,profile)
    if frozen.get('schema')!=lab.SCHEMA:
        raise RuntimeError('Unexpected frozen lab selection')
    all_episodes={}
    results=[]
    counts=Counter()
    for item in frozen['selected']:
        ep=item['episode']
        group=lab.group_for(item,source_rows[ep])
        for mode in lab.VARIANTS:
            path=lab.result_path(state,item,mode)
            if path.is_symlink() or not path.is_file():
                raise RuntimeError('Format lab comparison not yet complete')
            record=json.loads(lab.source_file(path))
            if any(record.get(k)!=v for k,v in (
                    ('schema',lab.SCHEMA),('episode',ep),
                    ('unit_sha',item['unit_sha']),
                    ('ids',item['cue_ids']),
                    ('mode',mode),('stratum',item['stratum']))):
                raise RuntimeError('Existing format output identity mismatch')
            if record.get('status')!='failed':
                continue
            raw=record.get('raw_private')
            if not isinstance(raw,str):
                raise RuntimeError('Missing private raw model response')
            category=record.get('failure_category')
            if not isinstance(category,str):
                raise RuntimeError('Missing original failure reason')
            shape=classify_shape(raw,item['cue_ids'],mode)
            counts[mode+'_'+category]+=1
            results.append({
               'episode':ep,
               'stratum':item['stratum'],
               'cue_ids':item['cue_ids'],
               'mode':mode,
               'original_failure_category':category,
               'output_tokens':record.get('response',{}).get('eval_count'),
               'done_reason':record.get('response',{}).get('done_reason'),
               'raw_model_output':raw,
               'shape_observations':shape,
               'source_cues':[
                  {'id':r[0],'english':r[4],'timing':r[1]} for r in group],
            })
    result={'schema':SCHEMA,'total_failure_responses':len(results),
            'failure_categories':dict(sorted(counts.items())),
            'records':results}
    return result


def export(state=lab.LAB,original_state=lab.ORIGINAL,
           profile=lab.core.PROFILE,output=None):
    result=collect(state,original_state,profile)
    raw=(json.dumps(result,ensure_ascii=False,indent=2)+'\n').encode('utf8')
    target=output if output is not None else sys.stdout.buffer
    with tarfile.open(fileobj=target,mode='w|gz') as tar:
        member=tarfile.TarInfo('PRIVATE_formatlab_012_failed_model_responses.json')
        member.mode=0o600
        member.size=len(raw)
        tar.addfile(member,io.BytesIO(raw))
    # STDERR only discloses aggregate counts, never dialogue or raw replies.
    print('PRIVATE_V012_FAILED_RESPONSES',len(result['records']),
          result['failure_categories'],file=sys.stderr)


def main():
    try:
        export()
    except Exception as exc:
        # Never print the private exception body: may contain source paths.
        print('FORENSICS_BLOCKED '+type(exc).__name__,file=sys.stderr)
        return 1
    return 0


if __name__=='__main__':
    raise SystemExit(main())
