#!/usr/bin/env python3
"""Read-only private EN/JA review archive for published v011 recovery tracks.

Outputs gzip tar on stdout; uses the frozen ORIGINAL English SRT and the
independent recovery JA draft, validating its identity with published media.
Does not read other subtitles, retranslate, write to host, or expose paths.
"""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import re
import sys
import tarfile

OLD=Path.home()/'bruiser-pilot/american-dad-utterance-011'
RECOVERY=Path.home()/'bruiser-pilot/american-dad-utterance-011-recovery'
EP_RE=re.compile(r'S\d{2}E\d{2,3}\Z')
SCHEMA='bruiser-utterance-recovery-v011r1'


def regular(path):
    if Path(path).is_symlink() or not Path(path).is_file():
        raise RuntimeError('Missing/unsafe private review file')
    return Path(path).read_bytes()


def collect(old=OLD,recovery=RECOVERY,parser=None):
    old,recovery=Path(old),Path(recovery)
    if parser is None:
        original_code=Path.home()/'bruiser-pilot/utterance-011-code'
        sys.path.insert(0,str(original_code))
        import service
        parser=service.parse_srt
    original=regular(old/'manifest.json')
    source_manifest=json.loads(original.decode('utf8'))
    rescue_manifest=json.loads(regular(recovery/'manifest.json').decode('utf8'))
    if (source_manifest.get('schema')!='bruiser-utterance-pilot-v011' or
        rescue_manifest.get('schema')!=SCHEMA or
        rescue_manifest.get('original_manifest_sha')!=hashlib.sha256(original).hexdigest()):
        raise RuntimeError('Incorrect original/recovery manifest identity')
    members={}
    index={'schema':'bruiser-utterance-recovery-private-review-v1','episodes':[]}
    seen=set()
    for item in source_manifest.get('episodes',[]):
        eid=item.get('episode')
        if not isinstance(eid,str) or not EP_RE.fullmatch(eid) or eid in seen:
            raise RuntimeError('Invalid/duplicate episode identifier')
        seen.add(eid)
        folder=old/'episodes'/eid
        if Path(item.get('source_path',''))!=folder/'source.en.srt':
            raise RuntimeError('Unexpected private English source location')
        source=regular(folder/'source.en.srt')
        if hashlib.sha256(source).hexdigest()!=item.get('source_sha'):
            raise RuntimeError('Original English source fingerprint changed')
        draft=recovery/'episodes'/eid/'pilot-recovered.ja.srt'
        if not draft.exists():
            continue  # An incomplete episode is never exported as finished.
        ja=regular(draft)
        erows=parser(source)
        jrows=parser(ja)
        if len(erows)!=item.get('count') or len(jrows)!=len(erows):
            raise RuntimeError(eid+': incomplete EN/JA cue counts')
        if any(x[:4]!=y[:4] for x,y in zip(erows,jrows)):
            raise RuntimeError(eid+': EN/JA cue ID or timing drift')
        video=Path(item.get('video',''))
        target=video.with_name(video.stem+
            '.Bruiser Utterance Recovery v3 Japanese.ja.srt')
        if regular(target)!=ja:
            raise RuntimeError(eid+': published JA does not match private draft')
        reports=sorted((recovery/'episodes'/eid).glob('quality-recovery-*.json'))
        if not reports:
            raise RuntimeError(eid+': no private QA record')
        members[eid+'/source.en.srt']=source
        members[eid+'/recovered.ja.srt']=ja
        for path in reports:
            record=json.loads(regular(path).decode('utf8'))
            allowed={'schema','episode','source_cues','units','qa_repairs',
                     'pre_qa','post_qa','unresolved_ids'}
            if set(record)!=allowed or record['schema']!=SCHEMA or record['episode']!=eid:
                raise RuntimeError(eid+': unexpected QA schema')
            members[eid+'/'+path.name]=(json.dumps(
                record,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode()
        index['episodes'].append({'episode':eid,'cues':len(erows),
                'published_identical':True,
                'source_sha256':item['source_sha'],
                'japanese_sha256':hashlib.sha256(ja).hexdigest()})
    if not index['episodes']:
        raise RuntimeError('No fully published recovery subtitles available')
    members['INDEX.json']=(json.dumps(index,sort_keys=True,indent=2)+'\n').encode()
    return members,index


def stream(old=OLD,recovery=RECOVERY,output=None,parser=None):
    members,index=collect(old,recovery,parser)
    output=output if output is not None else sys.stdout.buffer
    with tarfile.open(fileobj=output,mode='w|gz') as tar:
        for name,body in sorted(members.items()):
            info=tarfile.TarInfo(name)
            info.size=len(body)
            info.mode=0o600
            tar.addfile(info,io.BytesIO(body))
    print('PRIVATE_RECOVERY_EN_JA',[(x['episode'],x['cues'])
           for x in index['episodes']],file=sys.stderr)


if __name__=='__main__':
    try:
        stream()
    except Exception as exc:
        print('PRIVATE_REVIEW_BLOCKED '+type(exc).__name__,file=sys.stderr)
        sys.exit(1)
