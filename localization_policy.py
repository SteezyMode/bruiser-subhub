"""Optional subtitle-localization profile: meaning and voice before compression.

Pure helper: no Ollama calls or file/database writes. The legacy translator
keeps its original prompt unless this profile is explicitly selected.
"""
from __future__ import annotations

import math


PROFILE = "natural_8"

GUIDANCE = """JAPANESE SUBTITLE LOCALIZATION PRIORITIES (ADULT FILMS):
1. Faithfully preserve intent, subtext, emotional intensity, who says what, and
   especially negation, tense, numbers, names, and relationships.
2. Translate idioms, sarcasm, teasing, jokes and slang by MEANING into idiomatic
   conversational Japanese, not awkward literal English calques.
3. DO NOT CENSOR OR SANITIZE: preserve sex, profanity, violence, insults and
   threats with natural Japanese of comparable bluntness. Do not soften "fuck"
   into a mild "oh dear" or intensify an ordinary joke into an extreme slur.
4. Match each character's voice and social register in context: closeness,
   age, gender expression, anger, panic, humor, formality. Avoid generic polite
   language when characters are being crude.
5. Subtitle for viewing: cut redundant filler or unimportant repeated words;
   prefer concise, easy-to-read Japanese. Keep essential information, jokes,
   curses, threats and punchlines intact. Avoid long explanatory paraphrases.
6. Display durations below are SOFT guidance, not limits. Aiming for roughly
   8–10 Japanese visible characters/second on short dialogue can improve
   comfort, but do NOT sacrifice meaning, voice or punchlines to hit a count.
   Prefer 1–2 sensible lines; don't force original English line breaks.
7. Keep the exact cue IDs and output schema/format required by the original
   instructions. Output TRANSLATIONS ONLY. Never add commentary, JSON examples,
   tool calls, markup, or translation explanations.
These instructions supplement (not replace) the existing translation schema.
"""


def duration_seconds(row):
    """Read actual milliseconds from SQLite rows or row-like mappings."""
    return max(0.001, (int(row["end_ms"]) - int(row["start_ms"])) / 1000.0)


def cue_hints(rows):
    """A short nonbinding budget; no dialogue or copyrighted text repeated."""
    hints = []
    for index, row in enumerate(rows, 1):
        seconds = duration_seconds(row)
        # Deliberately soft: small cues can need a short swear, name, or punchline.
        guide = max(8, min(75, math.ceil(seconds * 9)))
        hints.append(f"local cue {index}: {seconds:.1f}s, soft ~{guide} Japanese chars")
    return "\n".join(hints)




FAITHFUL_GUIDANCE = """MEANING-FIRST ADULT JAPANESE SUBTITLES (faithful_8 experiment):
Your first job is complete, accurate, spoken Japanese, not shorter output.
PRIORITY ORDER: 1) meaning and speaker intent; 2) adult tone/character voice;
3) natural idiomatic Japanese; 4) concision within the time available.
Do NOT censor or sanitize sex, profanity, violence, insults, threats, jokes,
and slang. An insult directed AT someone must remain an insult AT that person,
not a generic frustrated exclamation. Sexual teasing must remain explicitly
sexual, neither a euphemistic ordinary request nor an exaggerated slur.
Keep each speaker turn: don't drop a second speaker, shouted interruption,
direct address, question, or urgent request merely to shorten a subtitle.
Preserve who acts on whom, negation, past/present/future, and the conversational
speech act (rhetorical question, accusation, refusal, threat, teasing, apology).
Do not change a rhetorical accusation into a neutral information question.
Do not fabricate relationship details such as cheating from an ambiguous label.
Replace English idioms with their natural Japanese MEANING, not a word-for-word
calque. Avoid stiff subtitles, generic politeness, or invented gendered voice.
Readability matters: drop safe fillers, repetitions or padding while preserving
meaning, punchlines and intensity. Do not omit essential words to meet a
character-count target. Never deliberately overlengthen a line either.
Use proper newline-separated speaker turns when necessary; don't prepend
a dash to every single-speaker line or insert arbitrary slash separators.
Keep the EXACT original cue ID and JSON/response schema; return translations
only, with no notes or tool-output fragments.
"""


def duration_hints(rows):
    """Advisory duration only; no per-cue character budget in faithful_8."""
    return '\n'.join(
        f"local cue {i}: {duration_seconds(row):.1f}s on screen"
        for i, row in enumerate(rows, 1)
    )

def enhance_system(system, rows, profile='natural_8'):
    """Keep legacy structured-prompt instructions intact; append guidance."""
    if not isinstance(system, str):
        raise TypeError("Legacy system prompt must be a string")
    if profile == 'natural_8':
        return system + "\n\n" + GUIDANCE + "\nDISPLAY-TIME HINTS (advisory only):\n" + cue_hints(rows)
    if profile == 'faithful_8':
        return (system + "\n\n" + FAITHFUL_GUIDANCE +
                "\nDISPLAY DURATION (advisory, not a character limit):\n" +
                duration_hints(rows))
    raise ValueError('Unknown localization profile: '+str(profile))
