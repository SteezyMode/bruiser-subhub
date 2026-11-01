#!/usr/bin/env python3
"""Reproducible read-only analysis of a PRIVATE local translation benchmark JSON.

Print only model-level statistics and cue IDs, NEVER copyrighted subtitle text.
This is structural QC, not a semantic or native Japanese review.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
import re

HTML_ENTITY = re.compile(r'&#(?:x[0-9a-f]+|\d+);|&(amp|quot|lt|gt);', re.I)
OBJECT_TAIL = re.compile(r'[」』]\s*[,，]\s*(?:\d+(?:\.\d+)?\s*:)?\s*$')


def structural_flags(text):
    if not isinstance(text, str) or not text.strip():
        return ['missing_japanese']
    flags = []
    if HTML_ENTITY.search(text):
        flags.append('escaped_html_entity')
    if text.count('」') > text.count('「') or text.count('』') > text.count('『'):
        flags.append('unmatched_japanese_quote')
    if OBJECT_TAIL.search(text):
        flags.append('serialized_object_fragment')
    if '<tool_call' in text or chr(96)*3+'json' in text or '"translations"' in text:
        flags.append('tool_or_json_fragment')
    return flags


def summarize(data):
    if data.get('schema') != 'bruiser-private-model-benchmark-v1':
        raise ValueError('Unsupported benchmark JSON schema')
    rows = data.get('entries')
    if not isinstance(rows, list):
        raise ValueError('Benchmark entries missing')
    groups = defaultdict(list)
    for row in rows:
        groups[(row['model'], row['style'])].append(row)
    reports = []
    for (model, style), group in sorted(groups.items()):
        marked = []
        for row in group:
            flags = structural_flags(row.get('candidate_japanese'))
            if flags:
                marked.append({'cue_id':row['cue_id'], 'flags':flags})
        reports.append({
            'model':model,'style':style,
            'outputs':len(group),
            'structurally_suspicious':len(marked),
            'flagged_cue_ids':[r['cue_id'] for r in marked],
            'details':marked,
        })
    return reports


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('private_json',type=Path)
    args=p.parse_args(argv)
    data=json.loads(args.private_json.read_text(encoding='utf-8'))
    reports=summarize(data)
    print('BENCHMARK',data.get('benchmark_id'), 'complete:',data.get('complete'),
          'candidate outputs:',len(data['entries']))
    for r in reports:
        print(f"{r['model']} [{r['style']}]: {r['structurally_suspicious']}/"
              f"{r['outputs']} suspicious; cue IDs {r['flagged_cue_ids']}")
    print('No subtitle text printed; no file, database or model changed.')
    print('This does not score idioms, speaker intent, tone or Japanese naturalness.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
