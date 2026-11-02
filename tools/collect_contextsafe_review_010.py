#!/usr/bin/env python3
"""Stream a PRIVATE EN/JA review archive for completed ContextSafe 010 episodes.

Read-only. Source is the frozen private v010 state; published media are checked
for byte identity, never edited. STDOUT is gzip data, STDERR is diagnostics.
No media paths or English/Japanese dialogue are written to public metadata.
"""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import re
import sys
import tarfile


STATE = Path.home() / 'bruiser-pilot/american-dad-contextsafe-010'
EPISODE = re.compile(r'^S\d{2}E\d{2,3}$')
SCHEMA = 'bruiser-context-safe-v010'


def check_archive(state: Path):
    """Build all members in memory so validation errors cannot emit a partial archive."""
    # Prefer the already-staged version of the parser used by the actual pilot.
    code = Path.home() / 'bruiser-pilot/contextsafe-010-code'
    sys.path.insert(0, str(code))
    import service

    state = Path(state)
    manifest_path = state / 'manifest.json'
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise RuntimeError('Frozen ContextSafe manifest is missing or symlinked')
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    if manifest.get('schema') != SCHEMA:
        raise RuntimeError('Not a ContextSafe v010 manifest')
    entries = manifest.get('episodes')
    if not isinstance(entries, list) or not entries or len(entries) > 8:
        raise RuntimeError('Expected 1..8 frozen preview episodes')

    members = {}
    index = {'schema': 'bruiser-contextsafe-v010-private-review-v1',
             'source_schema': SCHEMA, 'episodes': []}
    seen = set()
    for entry in entries:
        eid = entry.get('episode')
        if not isinstance(eid, str) or not EPISODE.fullmatch(eid) or eid in seen:
            raise RuntimeError('Invalid or duplicate episode identifier')
        seen.add(eid)
        folder = state / 'episodes' / eid
        source_path = folder / 'source.en.srt'
        draft_path = folder / 'pilot-v2.ja.srt'
        if any(x.is_symlink() or not x.is_file() for x in (source_path, draft_path)):
            raise RuntimeError(f'{eid}: missing/unsafe completed source or Japanese draft')
        if Path(entry.get('source_path', '')) != source_path:
            raise RuntimeError(f'{eid}: frozen source path does not match expected scratch layout')
        en = source_path.read_bytes()
        ja = draft_path.read_bytes()
        if hashlib.sha256(en).hexdigest() != entry.get('source_sha'):
            raise RuntimeError(f'{eid}: frozen English source SHA mismatch')
        source = service.parse_srt(en)
        translated = service.parse_srt(ja)
        if len(source) != entry.get('count') or len(source) != len(translated):
            raise RuntimeError(f'{eid}: incomplete or mismatched SRT cue count')
        for a, b in zip(source, translated):
            if a[:4] != b[:4]:
                raise RuntimeError(f'{eid}: cue ID or timing drift')
        # Verify that the draft is byte-identical to the published track.
        video = Path(entry.get('video', ''))
        target = video.with_name(video.stem + '.Bruiser ContextSafe v2 Japanese.ja.srt')
        if target.is_symlink() or not target.is_file() or target.read_bytes() != ja:
            raise RuntimeError(f'{eid}: published JA track not identical to private draft')
        members[eid + '/source.en.srt'] = en
        members[eid + '/contextsafe.ja.srt'] = ja
        index['episodes'].append({'episode': eid, 'cues': len(source),
                                  'source_sha256': entry['source_sha'],
                                  'japanese_sha256': hashlib.sha256(ja).hexdigest(),
                                  'published_verified_identical': True})
        for qpath in sorted(folder.glob('quality-v2-*.json')):
            if qpath.is_symlink() or not qpath.is_file():
                raise RuntimeError(f'{eid}: unsafe QA report path')
            # Reports contain aggregate numerical QA only, but do not trust
            # unexpected extra keys, paths, or full copyrighted dialogue.
            report = json.loads(qpath.read_text(encoding='utf-8'))
            allowed = {'episode','source_cues','first_pass_leak_flags',
                       'first_pass_severe_density','repaired_cues','unresolved_ids',
                       'remaining_leak_flags','remaining_severe_density',
                       'warning_over_18_cps'}
            if set(report) != allowed or report['episode'] != eid:
                raise RuntimeError(f'{eid}: QA report schema mismatch')
            members[eid + '/' + qpath.name] = (
                json.dumps(report, sort_keys=True, indent=2) + '\n').encode('utf-8')
    members['INDEX.json'] = (json.dumps(index, sort_keys=True, indent=2) + '\n').encode('utf-8')
    return members, index


def stream(state=STATE, output=None):
    members, index = check_archive(Path(state))
    if output is None:
        output = sys.stdout.buffer
    with tarfile.open(fileobj=output, mode='w|gz') as tar:
        for name, data in sorted(members.items()):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o600
            tar.addfile(info, io.BytesIO(data))
    print('PRIVATE REVIEW EXPORT: ' + ', '.join(
        f"{x['episode']}={x['cues']}" for x in index['episodes']), file=sys.stderr)


if __name__ == '__main__':
    try:
        stream()
    except Exception as exc:
        print(f'REVIEW EXPORT BLOCKED: {type(exc).__name__}: {exc}', file=sys.stderr)
        sys.exit(1)
