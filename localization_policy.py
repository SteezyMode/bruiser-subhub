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


def enhance_system(system, rows):
    """Keep legacy structured-prompt instructions intact; append guidance."""
    if not isinstance(system, str):
        raise TypeError("Legacy system prompt must be a string")
    return system + "\n\n" + GUIDANCE + "\nDISPLAY-TIME HINTS (advisory only):\n" + cue_hints(rows)
