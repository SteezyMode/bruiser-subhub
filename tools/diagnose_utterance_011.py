#!/usr/bin/env python3
"""Read-only diagnostic for the frozen, incomplete SubHub v011 viewing pilot.

Prints ONLY aggregate counters, failure categories and numeric cue IDs.
Does not expose English/Japanese dialogue, media paths, model responses, or
private prompt context. No Ollama calls, staging, checkpoint writes or resets.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sys

STATE = Path.home()/'bruiser-pilot/american-dad-utterance-011'
STAGED_CODE = Path.home()/'bruiser-pilot/utterance-011-code'
SCHEMA = 'bruiser-utterance-pilot-v011'
EPISODE_RE = re.compile(r'S\d{2}E\d{2,3}\Z')
ATTEMPT_RE = re.compile(r'(\d{5})-(\d{5})-(\d+)\.json\Z')


def load_regular(path: Path):
    """Refuse symlinks and unusual paths, rather than following them."""
    if path.is_symlink() or not path.is_file():
        raise RuntimeError('Missing or unsafe private pilot file')
    return json.loads(path.read_text(encoding='utf8'))


def failure_category(error):
    """Categorize error messages without printing raw model/source data."""
    s = error if isinstance(error,str) else ''
    patterns = (
      ('Incomplete/extra keys in grouped translation','group_keys_incorrect'),
      ('JSONDecodeError','invalid_group_json'),
      ('Invalid Japanese or speaker-turn structure','invalid_ja_or_speakers'),
      ('Invalid singleton Japanese/speaker turns','invalid_ja_or_speakers'),
      ('Unwatchably dense','density_rejected'),
      ('Repeated or prematurely copied','adjacent_copy_rejected'),
      ('Output length cap','model_length_cap'),
      ('TimeoutError','model_timeout'),
      ('timed out','model_timeout'),
      ('HTTPError','ollama_http_error'),
      ('URLError','ollama_connection_error'),
      ('ConnectionRefusedError','ollama_connection_error'),
      ('RateLimitError','model_rate_limited'),
      ('Non-text Japanese group value','nontext_group_value'),
      ('Not enough memory','model_memory'),
      ('out of memory','model_memory'),
      ('Expecting value','invalid_group_json'),
    )
    for pattern,category in patterns:
        if pattern in s:
            return category
    tag = s.split(':',1)[0].strip()
    if re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]{0,35}',tag):
        return 'other_'+tag
    return 'other'


def code_fingerprint(code_dir: Path):
    paths=[code_dir/x for x in (
        'american_dad_utterance_011.py','semantic_groups_011.py',
        'subtitle_quality_010.py')]
    if any(x.is_symlink() or not x.is_file() for x in paths):
        return None
    return hashlib.sha256(b''.join(x.read_bytes() for x in paths)).hexdigest()


def diagnose(state=STATE,code_dir=STAGED_CODE,parser=None,planner=None,unit_hash=None):
    state=Path(state)
    code_dir=Path(code_dir)
    if parser is None or planner is None or unit_hash is None:
        sys.path.insert(0,str(code_dir))
        import service
        import semantic_groups_011 as semantic
        parser = parser or service.parse_srt
        planner = planner or semantic.plan
        unit_hash = unit_hash or semantic.unit_sha

    manifest=load_regular(state/'manifest.json')
    if manifest.get('schema') != SCHEMA:
        raise RuntimeError('Not the expected frozen v011 pilot')
    entries=manifest.get('episodes',[])
    if not isinstance(entries,list) or not 1<=len(entries)<=8:
        raise RuntimeError('Unexpected episode list')
    fingerprint=code_fingerprint(code_dir)
    if fingerprint is not None and fingerprint!=manifest.get('pipeline_sha'):
        raise RuntimeError('Frozen v011 runner fingerprint changed; do not resume')

    output={'schema':'bruiser-v011-readonly-diagnostic-v1',
            'frozen_runner_fingerprint_ok':fingerprint==manifest.get('pipeline_sha'),
            'episodes':[]}
    seen=set()
    for entry in entries:
        episode=entry.get('episode')
        if not isinstance(episode,str) or not EPISODE_RE.fullmatch(episode) or episode in seen:
            raise RuntimeError('Invalid or duplicate episode ID')
        seen.add(episode)
        folder=state/'episodes'/episode
        source=folder/'source.en.srt'
        if Path(entry.get('source_path',''))!=source:
            raise RuntimeError('Frozen source location mismatches pilot')
        if source.is_symlink() or not source.is_file():
            raise RuntimeError('Frozen source is unavailable or symlinked')
        data=source.read_bytes()
        if hashlib.sha256(data).hexdigest()!=entry.get('source_sha'):
            raise RuntimeError('Frozen English source has changed')
        rows=parser(data)
        if len(rows)!=entry.get('count'):
            raise RuntimeError('Frozen source cue count has changed')
        groups=planner(rows)
        if [r[0] for g in groups for r in g]!=[r[0] for r in rows]:
            raise RuntimeError('Group planner changed source cue ordering')

        categories=Counter()
        final_categories=Counter()
        examples=[]
        accepted_cues=accepted_units=failed_units=exhausted=untouched=0
        all_group_keys=set()
        for group in groups:
            first,last=group[0][0],group[-1][0]
            key=f'{first:05d}-{last:05d}'
            all_group_keys.add(key)
            checkpoint=folder/'units'/(key+'.json')
            attempts=[]
            for attempt in range(1,4):
                path=folder/'attempts'/(key+f'-{attempt}.json')
                if path.is_symlink():
                    raise RuntimeError('Unsafe failed-attempt symlink')
                if path.exists():
                    saved=load_regular(path)
                    if saved.get('ids')!=[r[0] for r in group]:
                        raise RuntimeError('Failed-attempt cue IDs differ')
                    attempts.append((attempt,failure_category(saved.get('error'))))
                    categories[attempts[-1][1]]+=1
            if checkpoint.is_symlink():
                raise RuntimeError('Unsafe saved unit symlink')
            if checkpoint.exists():
                saved=load_regular(checkpoint)
                if any(saved.get(k)!=v for k,v in (
                    ('schema',SCHEMA),('source_sha',entry.get('source_sha')),
                    ('unit_sha',unit_hash(group)),('ids',[r[0] for r in group]),
                    ('pipeline_sha',manifest.get('pipeline_sha')),
                    ('model_id',manifest.get('model_id')))):
                    raise RuntimeError('Incompatible existing unit checkpoint')
                ja=saved.get('translations')
                if not isinstance(ja,dict) or set(ja)!={str(r[0]) for r in group}:
                    raise RuntimeError('Incomplete saved unit checkpoint')
                accepted_units+=1
                accepted_cues+=len(group)
            elif attempts:
                failed_units+=1
                exhausted+=len(attempts)>=3
                final_categories[attempts[-1][1]]+=1
                if len(examples)<12:
                    examples.append({'first_cue':first,'last_cue':last,
                                     'saved_attempts':len(attempts),
                                     'last_error_category':attempts[-1][1]})
            else:
                untouched+=1

        # Inspect orphaned attempt files without opening copyright-bearing data.
        folder_attempts=folder/'attempts'
        if folder_attempts.is_dir():
            for p in folder_attempts.iterdir():
                if p.is_symlink():
                    raise RuntimeError('Unsafe attempt file symlink')
                match=ATTEMPT_RE.fullmatch(p.name)
                if not match or f'{match[1]}-{match[2]}' not in all_group_keys:
                    raise RuntimeError('Unexpected saved attempt filename/identity')

        output['episodes'].append({
          'episode':episode,'source_cues':len(rows),
          'total_units':len(groups),
          'accepted_cues':accepted_cues,'accepted_units':accepted_units,
          'unaccepted_cues':len(rows)-accepted_cues,
          'failed_units_with_records':failed_units,
          'exhausted_units':exhausted,
          'never_attempted_units':untouched,
          'attempt_errors_by_category':dict(sorted(categories.items())),
          'last_error_by_failed_unit':dict(sorted(final_categories.items())),
          'first_failed_units':examples,
          'published_flag':(folder/'pilot-v3.ja.srt').is_file(),
        })
    return output


def main():
    try:
        print(json.dumps(diagnose(),ensure_ascii=False,indent=2,sort_keys=True))
    except Exception as exc:
        # Never include unsanitized exception text, which may contain paths.
        print('DIAGNOSTIC_BLOCKED '+type(exc).__name__,file=sys.stderr)
        return 1
    return 0


if __name__=='__main__':
    raise SystemExit(main())
