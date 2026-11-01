#!/usr/bin/env python3
"""Read-only, local editorial sampling of SubHub EN/JA subtitle checkpoints.

Produces a review packet, not a translation score or an automatic QA gate.
No inference, publishing, source-file reads, DB writes, or network calls.
"""
from __future__ import annotations
import argparse
from collections import Counter
import datetime as dt
import json
from pathlib import Path
import re
import sqlite3

JP = re.compile(r'[\u3040-\u30ff\u3400-\u9fff]')
NEG = re.compile(r"\b(?:no|not|never|can't|cannot|couldn't|wouldn't|don't|doesn't|didn't|won't|isn't|aren't|without|nothing)\b", re.I)
NUM = re.compile(r'(?<![\w])\d+(?:[.,]\d+)?(?![\w])')
MARK = re.compile(r'</?(?:i|b|u|font)(?:\s+[^>]*)?>|\{\\an\d+\}', re.I)
STRIP = re.compile(r'<[^>]*>|\{\\[^}]*\}')


def plain(text):
    return STRIP.sub('', text or '').strip()


def flag_cue(row, repeats):
    """Mechanical review prompts only. Flags do not establish mistranslation."""
    en, ja = row['english'] or '', row['japanese'] or ''
    if not ja.strip():
        return ['missing_japanese']
    flags = []
    if not JP.search(ja):
        flags.append('no_japanese_script')
    source_marks = sorted(MARK.findall(en))
    target_marks = sorted(MARK.findall(ja))
    if source_marks != target_marks:
        flags.append('formatting_review')
    numbers = NUM.findall(en)
    if numbers and not all(number in ja for number in numbers):
        flags.append('number_review')  # Japanese may legitimately spell numbers in kanji
    if NEG.search(en):
        flags.append('negation_review')  # English negation need not map word for word
    if len(plain(ja)) > 65:
        flags.append('long_japanese')
    duration = max(.25, (row['end_ms'] - row['start_ms']) / 1000)
    if len(plain(ja).replace('\n', '')) / duration > 14:
        flags.append('reading_speed_review')
    if repeats.get(ja.strip(), 0) >= 3 and len(plain(ja)) >= 6:
        flags.append('repeated_japanese_review')
    return flags


def pick_indices(cues, flags, count):
    """Mix spread-through-film coverage with risk-weighted cues."""
    n = len(cues)
    if count >= n:
        return list(range(n))
    if count < 1:
        raise ValueError('count must be positive')
    chosen = set()
    coverage = min(count, max(2, (count + 2) // 3))
    for i in range(coverage):
        chosen.add(round((n - 1) * i / max(1, coverage - 1)))
    weights = {'missing_japanese': 10, 'no_japanese_script': 8,
               'formatting_review': 6, 'number_review': 4,
               'long_japanese': 3, 'reading_speed_review': 3,
               'repeated_japanese_review': 3, 'negation_review': 2}
    ranked = sorted(range(n), key=lambda i: (-sum(weights[f] for f in flags[i]), i))
    for i in ranked:
        if len(chosen) >= count:
            break
        chosen.add(i)
    return sorted(chosen)


def make_packet(db, job_id, count=60, all_cues=False):
    """Open the existing SQLite DB read-only, preserving live WAL/checkpoints."""
    db = Path(db).resolve(strict=True)
    cn = sqlite3.connect(db.as_uri() + '?mode=ro', uri=True, timeout=5)
    cn.row_factory = sqlite3.Row
    try:
        cn.execute('PRAGMA query_only=ON')
        job = cn.execute('SELECT id, source_sha, status, source_cues FROM jobs WHERE id=?', (job_id,)).fetchone()
        if job is None:
            raise ValueError('Unknown job: ' + job_id)
        cues = [dict(row) for row in cn.execute(
            'SELECT cue_id, timing, start_ms, end_ms, english, japanese, hy_back '
            'FROM cues WHERE job_id=? ORDER BY cue_id', (job_id,))]
        if len(cues) != job['source_cues']:
            raise ValueError('Stored cue count differs from job metadata')
    finally:
        cn.close()
    repeats = Counter((row['japanese'] or '').strip() for row in cues if row['japanese'])
    flags = [flag_cue(row, repeats) for row in cues]
    selected = pick_indices(cues, flags, len(cues) if all_cues else count)
    entries = []
    for i in selected:
        row = cues[i]
        context = [{'cue_id': cues[k]['cue_id'], 'english': cues[k]['english']}
                   for k in range(max(0, i-2), min(len(cues), i+3)) if k != i]
        entries.append({'cue_id': row['cue_id'], 'timing': row['timing'],
                        'english': row['english'], 'japanese': row['japanese'],
                        'hy_back': row['hy_back'], 'flags': flags[i],
                        'english_context': context})
    counts = Counter(f for row_flags in flags for f in row_flags)
    return {'schema': 'bruiser-editorial-sample-v1', 'job_id': job_id,
            'source_sha256': job['source_sha'], 'job_status': job['status'],
            'generated_utc': dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds'),
            'total_cues': len(cues), 'translated_cues': sum(bool(r['japanese']) for r in cues),
            'selected_cues': len(entries), 'flag_counts': dict(sorted(counts.items())),
            'caution': ('Flags are mechanical review prompts, NOT proof of incorrect Japanese. '
                        'HY backtranslation is advisory only. Nothing is approved or published.'),
            'entries': entries}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--root', type=Path, required=True, help='Existing SubHub state directory')
    ap.add_argument('--job', required=True, help='Existing SubHub job ID')
    ap.add_argument('--count', type=int, default=60, help='Review cues to sample (default: 60)')
    ap.add_argument('--all', action='store_true', help='Include all cues, not a sample')
    ap.add_argument('--out', type=Path, help='Explicit local JSON export path; omitted means summary only')
    args = ap.parse_args(argv)
    if not 1 <= args.count <= 12000:
        ap.error('--count must be between 1 and 12000')
    try:
        packet = make_packet(args.root / 'jobs.sqlite3', args.job, args.count, args.all)
    except (OSError, sqlite3.Error, ValueError) as exc:
        ap.error(str(exc))
    print(f"{packet['job_id']}: {packet['translated_cues']}/{packet['total_cues']} translated; "
          f"{packet['selected_cues']} selected for editorial review")
    print('Advisory flags:', json.dumps(packet['flag_counts'], sort_keys=True))
    if args.out:
        # Export only by explicit opt-in. Never write into the DB or media library.
        if args.out.exists():
            ap.error('Output exists; refusing to overwrite: ' + str(args.out))
        args.out.parent.mkdir(parents=True, exist_ok=True)
        fd = args.out.open('x', encoding='utf-8')
        with fd:
            json.dump(packet, fd, ensure_ascii=False, indent=2)
            fd.write('\n')
        print('Editorial packet:', args.out)
    else:
        print('Summary only. Add --out PATH to export local EN/JA dialogue and context.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
