#!/usr/bin/env python3
"""Read-only private archive of completed Context/Utterance v011 JA pilot pairs.

STDOUT: gzip tar archive. STDERR: summary. Refuses anything missing, modified,
out-of-order or not byte-identical to the create-only published JA sidecar.
"""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import re
import sys
import tarfile


STATE = Path.home() / 'bruiser-pilot/american-dad-utterance-011'
EPISODE = re.compile(r'^S\d{2}E\d{2,3}$')
SCHEMA = 'bruiser-utterance-pilot-v011'


def collect(state=STATE):
    code=Path.home()/'bruiser-pilot/utterance-011-code'
    sys.path.insert(0,str(code))
    import service
    state=Path(state)
    manifest=state/'manifest.json'
    if manifest.is_symlink() or not manifest.is_file():
        raise RuntimeError('Missing/unsafe v011 manifest')
    obj=json.loads(manifest.read_text(encoding='utf8'))
    if obj.get('schema')!=SCHEMA or not 1<=len(obj.get('episodes',[]))<=8:
        raise RuntimeError('Invalid v011 pilot manifest')
    result={}
    index={'schema':'bruiser-utterance-private-review-v1','episodes':[]}
    seen=set()
    for entry in obj['episodes']:
        eid=entry.get('episode')
        if not isinstance(eid,str) or not EPISODE.fullmatch(eid) or eid in seen:
            raise RuntimeError('Invalid/duplicate episode ID')
        seen.add(eid)
        folder=state/'episodes'/eid
        source=folder/'source.en.srt'
        japanese=folder/'pilot-v3.ja.srt'
        if any(p.is_symlink() or not p.is_file() for p in (source,japanese)):
            raise RuntimeError(eid+': missing/unsafe completed EN/JA files')
        if Path(entry.get('source_path',''))!=source:
            raise RuntimeError(eid+': unexpected private source location')
        en=source.read_bytes()
        ja=japanese.read_bytes()
        if hashlib.sha256(en).hexdigest()!=entry.get('source_sha'):
            raise RuntimeError(eid+': frozen source hash mismatch')
        erows=service.parse_srt(en)
        jrows=service.parse_srt(ja)
        if len(erows)!=entry.get('count') or len(jrows)!=len(erows):
            raise RuntimeError(eid+': wrong cue counts')
        if any(e[:4]!=j[:4] for e,j in zip(erows,jrows)):
            raise RuntimeError(eid+': cue ID/timestamps drifted')
        video=Path(entry.get('video',''))
        published=video.with_name(video.stem+'.Bruiser Utterance v3 Japanese.ja.srt')
        if published.is_symlink() or not published.is_file() or published.read_bytes()!=ja:
            raise RuntimeError(eid+': published SRT is not identical to final draft')
        reports=list(sorted(folder.glob('quality-v3-*.json')))
        if not reports:
            raise RuntimeError(eid+': no QA report for completed episode')
        result[eid+'/source.en.srt']=en
        result[eid+'/utterance.ja.srt']=ja
        for report in reports:
            if report.is_symlink() or not report.is_file():
                raise RuntimeError(eid+': unsafe QA report')
            data=json.loads(report.read_text(encoding='utf8'))
            if data.get('schema')!=SCHEMA or data.get('episode')!=eid:
                raise RuntimeError(eid+': inconsistent QA schema')
            # Aggregate QA-only keys; explicitly never export unexpected
            # text fields or paths in an allegedly safe public summary.
            safe={'schema','episode','source_cues','unit_count','multi_cue_units',
                  'grouped_cues','first_pass_flags','repaired_cues',
                  'remaining_flags','unresolved_ids'}
            if set(data)!=safe:
                raise RuntimeError(eid+': unexpected QA report keys')
            result[eid+'/'+report.name]=(json.dumps(
                data,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode('utf8')
        index['episodes'].append({
            'episode':eid,'cues':len(erows),'published_verified_identical':True,
            'source_sha256':entry['source_sha'],
            'japanese_sha256':hashlib.sha256(ja).hexdigest()})
    result['INDEX.json']=(json.dumps(index,sort_keys=True,indent=2)+'\n').encode()
    return result,index


def stream(state=STATE,out=None):
    members,index=collect(state)
    if out is None:
        out=sys.stdout.buffer
    with tarfile.open(fileobj=out,mode='w|gz') as tar:
        for filename,body in sorted(members.items()):
            item=tarfile.TarInfo(filename)
            item.size=len(body)
            item.mode=0o600
            tar.addfile(item,io.BytesIO(body))
    print('PRIVATE_UTTERANCE_ARCHIVE',[(x['episode'],x['cues'])
            for x in index['episodes']],file=sys.stderr)


if __name__=='__main__':
    try:
        stream()
    except Exception as exc:
        print('READ_ONLY_EXPORT_BLOCKED',type(exc).__name__,str(exc),file=sys.stderr)
        sys.exit(1)
