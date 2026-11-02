#!/usr/bin/env python3
"""Generic, conservative cross-cue utterance planning and validation.

Pure functions. No media, network, Ollama, DB or publication dependencies.
The source SRT's cue IDs/timestamps remain authoritative, even when the
English sentence crosses multiple subtitle cues.
"""
from __future__ import annotations

import hashlib
import json
import re

try:
    import subtitle_quality_010 as quality
except ModuleNotFoundError:
    from tools import subtitle_quality_010 as quality

SCHEMA = 'bruiser-utterance-units-v011'
MAX_CUES = 3
MAX_SPAN_MS = 10500
MAX_ENGLISH = 330
MAX_GAP_MS = 1000

# Avoid grouping dialogues crossing speakers or non-dialogue musical breaks.
SPEAKER_LINE = re.compile(r'^\s*[-–—]\s*(?:<[^>]+>)*\S', re.M)
HARD_END = re.compile(r'[.!?…。！？][”"’\x27)\]]*\s*$')
ANAPHOR = re.compile(
    r"^(?:nothing\s+will\b|nothing\s+does\b|neither\s+will\b|"
    r"neither\s+do\b|so\s+do\s+I\b|so\s+am\s+I\b|"
    r"I\s+do\b|I\s+did\b|I\s+won't\b|I\s+will\b)",
    re.I,
)


def clean_en(text):
    text = quality.display_text(text)
    return re.sub(r'\s+', ' ', text).strip()


def speaker_turn_count(text):
    return sum(bool(SPEAKER_LINE.match(line)) for line in str(text).splitlines())


def has_scene_break(text):
    return ('♪' in str(text) or
            bool(re.search(r'\[(?:music|applause|laughter|sighs|grunts)\]',
                           str(text), re.I)))


def should_join(previous, upcoming):
    """Conservative deterministic grouping, not a claim of semantic certainty."""
    gap = upcoming[2] - previous[3]
    if gap < -150 or gap > MAX_GAP_MS:
        return False
    a = clean_en(previous[4])
    b = clean_en(upcoming[4])
    if not a or not b or has_scene_break(previous[4]) or has_scene_break(upcoming[4]):
        return False
    if speaker_turn_count(previous[4]) or speaker_turn_count(upcoming[4]):
        return False
    # An elliptical response needs prior context to preserve the reference:
    # "Nothing will." after "That won't stop me."
    if gap <= 650 and ANAPHOR.match(b) and len(b.split()) <= 5:
        return True
    if HARD_END.search(a):
        return False
    if len(a) < 8 and not a.endswith((',', ':', ';', '—', '-', '…')):
        return False
    return True


def plan(rows):
    """Return ordered groups of original source tuples, exact partition."""
    if not rows:
        return []
    groups = []
    current = [rows[0]]
    for row in rows[1:]:
        old = current[-1]
        if (len(current) < MAX_CUES and
                row[0] == old[0] + 1 and
                row[3] - current[0][2] <= MAX_SPAN_MS and
                sum(len(clean_en(x[4])) for x in current) + len(clean_en(row[4])) <= MAX_ENGLISH and
                should_join(old, row)):
            current.append(row)
        else:
            groups.append(tuple(current))
            current = [row]
    groups.append(tuple(current))
    if [r[0] for g in groups for r in g] != [r[0] for r in rows]:
        raise RuntimeError('Utterance planner lost a source cue')
    return groups


def unit_sha(group):
    payload = [{'id':x[0], 'timing':x[1], 'english':x[4]} for x in group]
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False,
                                      sort_keys=True).encode('utf8')).hexdigest()


def unit_messages(group, prior_en=(), prior_ja=(), series_bible='',
                  series_note='', title_note='', attempt=1):
    """Every raw English cue in the prompt is a target, never lookahead context."""
    ids = [str(row[0]) for row in group]
    if len(ids) < 2 or len(ids) > MAX_CUES:
        raise ValueError('Unit prompt requires a 2-3 cue group')
    system = (
        'You are localizing ONE English spoken utterance that was split across '
        'multiple SRT timestamps. First understand the COMPLETE source utterance, '
        'then provide ONE concise natural spoken Japanese subtitle PER source ID. '
        'Preserve the order and unique meaning of each clause. Never introduce '
        'words, information, a reveal or a punchline from a LATER source cue '
        'inside an EARLIER Japanese cue; do not repeat the same proposition in '
        'two output cues. Natural Japanese restructuring is permitted, but '
        'each cue must be understandable at its own time. Preserve negation, '
        'idioms, speaker intent, swear words, names, references and comedic tone. '
        'Do not invent events or speaker identities. Do not sanitize adult humor. '
        'Prefer short readable captions. Never append explanation or markdown. '
        'Respond with ONLY one JSON object, with EXACT string keys ' +
        json.dumps(ids) + ' and a Japanese subtitle string for EACH value. '
        'No additional keys, nesting, examples or missing IDs. '
        'A speaker-turn source cue must have two Japanese lines separating speakers.'
    )
    if attempt > 1:
        system += (' Prior output failed strict cue mapping or mechanical QA. '
                   'Do not add content from a later cue to an earlier cue; '
                   'keep each Japanese value nonempty, concise and idiomatic. '
                   'Keep one valid JSON object with exactly the requested keys.')
    system += (
        '\n[ADVISORY_SERIES_GUIDE]\n' + series_bible[:1250] +
        '\n[/ADVISORY_SERIES_GUIDE]\n[ADVISORY_SERIES_CONTEXT]\n' +
        series_note[:650] + '\n[/ADVISORY_SERIES_CONTEXT]\n'
        '[ADVISORY_TITLE_CONTEXT]\n' + title_note[:650] +
        '\n[/ADVISORY_TITLE_CONTEXT]'
    )
    targets = [{'id':str(r[0]),'english':str(r[4]),
                'duration_seconds':round((r[3]-r[2])/1000,2)} for r in group]
    user = ''
    if prior_en:
        user += '[ALREADY_SPOKEN_ENGLISH_CONTEXT]\n' + ' / '.join(
            str(x) for x in prior_en[-2:])[-260:] + '\n[/ALREADY_SPOKEN_ENGLISH_CONTEXT]\n'
    if prior_ja:
        user += '[ALREADY_ACCEPTED_JAPANESE]\n' + str(
            prior_ja[-1])[-140:] + '\n[/ALREADY_ACCEPTED_JAPANESE]\n'
    user += '[ALL_TARGET_CUES]\n' + json.dumps(
        targets, ensure_ascii=False) + '\n[/ALL_TARGET_CUES]\n'
    user += 'Translate precisely these IDs, keeping each idea at its original cue time.'
    return [{'role':'system','content':system}, {'role':'user','content':user}]


def valid_speakers(english, japanese):
    if speaker_turn_count(english) < 2:
        return True
    lines = [line.strip() for line in japanese.splitlines() if line.strip()]
    return len(lines) >= 2  # a visible linebreak distinguishes the two voices


def repeated_meaning_candidates(rows, translations):
    """Flag high long-character overlap missed by exact future-substring QA.

    This is NOT a semantic classifier; suppress source text that itself repeats.
    """
    out = set()
    for left, right in zip(rows, rows[1:]):
        en_l, en_r = clean_en(left[4]).casefold(), clean_en(right[4]).casefold()
        if not en_l or not en_r or en_l == en_r:
            continue
        a = quality.normalized_japanese(translations.get(str(left[0]), ''))
        b = quality.normalized_japanese(translations.get(str(right[0]), ''))
        if len(a) < 20 or len(b) < 20:
            continue
        grams_a = {a[i:i+4] for i in range(len(a)-3)}
        grams_b = {b[i:i+4] for i in range(len(b)-3)}
        if (grams_a and grams_b and
                len(grams_a & grams_b) / min(len(grams_a),len(grams_b)) >= .7):
            out.add(left[0])
    return out


def parse_unit_reply(reply, group, accept):
    """Fail closed on JSON shape, invalid Japanese, speaker erasure and density."""
    if isinstance(reply, str):
        value = json.loads(reply)
    else:
        value = reply
    expected = {str(r[0]) for r in group}
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError('Incomplete/extra keys in grouped translation')
    saved = {}
    for row in group:
        cue_id = str(row[0])
        answer = value[cue_id]
        if not isinstance(answer, str):
            raise ValueError('Non-text Japanese group value')
        japanese = accept(answer, row[4])
        if japanese is None or not valid_speakers(row[4], japanese):
            raise ValueError('Invalid Japanese or speaker-turn structure')
        if quality.length_risk(japanese, row[2], row[3])['severe_density']:
            raise ValueError('Unwatchably dense grouped output')
        saved[cue_id] = japanese
    if quality.overlap_ids(group, saved) or repeated_meaning_candidates(group, saved):
        raise ValueError('Repeated or prematurely copied adjacent translation')
    return saved


def quality_flags(rows, translations):
    density = quality.density_flags(rows, translations)
    overlap = quality.overlap_ids(rows, translations)
    repeated = repeated_meaning_candidates(rows, translations)
    speakers = {row[0] for row in rows if str(row[0]) in translations and
                not valid_speakers(row[4], translations[str(row[0])])}
    severe = {cid for cid,x in density.items() if x['severe_density']}
    return {'overlap':overlap, 'repeated':repeated,
            'speakers':speakers, 'severe':severe,
            'warnings':{cid for cid,x in density.items() if x['high_density']}}
