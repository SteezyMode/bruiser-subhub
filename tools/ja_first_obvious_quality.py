#!/usr/bin/env python3
"""Very permissive mechanical sanity screening for acquired Japanese SRTs.

This does NOT grade Japanese idioms, meaning, fluent machine translation, or
human origin. Only catastrophic signs can hold publication. All returned
diagnostics are aggregate counts; no movie dialogue, spoilers, or text excerpts.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import re
import unicodedata

JA = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uff66-\uff9f\u31f0-\u31ff]")
TAGS = re.compile(r"<[^>\n]+>|\{\\[^}\n]*\}")
LATIN_WORDS = re.compile(r"[A-Za-z]{3,}")
ENGLISH_WORDS = re.compile(r"[A-Za-z]{2,}")
STAMP_LINE = re.compile(r"\S+\s*-->\s*\S+")
PLACEHOLDER = re.compile(
    r"(?i)\b(?:TODO|TBD|TRANSLATE\s+ME|TRANSLATION\s+MISSING|"
    r"NO\s+SUBTITLE|UNTRANSLATED)\b")
MOJIBAKE = re.compile(r"(?:ãƒ|ã‚|â€™|â€œ|â€\x9d|ï¿½|縺[ａ-ｚァ-ヶ]|繧[ａ-ｚァ-ヶ])")
MAX_BYTES = 2_000_000


def clean_text(raw: str) -> str:
    text = TAGS.sub("", raw)
    # Treat common SRT markup and speaker-dashes as non-linguistic, but
    # leave all actual words (including Latin names and loanwords) unchanged.
    return text.replace("\\N", " ").strip()


def texts_from_srt(raw: bytes):
    """Extract dialogue lines. Existing publication format gate stays authoritative."""
    if not 0 < len(raw) <= MAX_BYTES:
        raise RuntimeError("invalid_subtitle_size")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeError:
        raise RuntimeError("invalid_utf8") from None
    output = []
    for block in re.split(r"\r?\n[ \t]*\r?\n", text.strip()):
        lines = block.splitlines()
        index = int(bool(lines and lines[0].strip().isdigit()))
        if len(lines) < index + 2 or not STAMP_LINE.fullmatch(lines[index].strip()):
            raise RuntimeError("unparseable_srt_block")
        output.append(clean_text("\n".join(lines[index + 1:])))
    return output


def assess(raw: bytes) -> dict:
    lines = texts_from_srt(raw)
    n = len(lines)
    if not n:
        raise RuntimeError("subtitle_has_no_cues")
    counts = Counter()
    repeated = Counter()
    for text in lines:
        letters = [char for char in text if unicodedata.category(char).startswith("L")]
        ja = bool(JA.search(text))
        if letters:
            counts["letter_cues"] += 1
        else:
            counts["symbol_or_number_cues"] += 1
        if ja:
            counts["japanese_cues"] += 1
        elif len(ENGLISH_WORDS.findall(text)) >= 2 and LATIN_WORDS.search(text):
            counts["english_sentence_cues"] += 1
        if "\ufffd" in text:
            counts["replacement_character_cues"] += 1
        if "\x00" in text or any(
            unicodedata.category(char) == "Cc" and char not in "\t\n\r"
            for char in text
        ):
            counts["control_character_cues"] += 1
        if MOJIBAKE.search(text):
            counts["probable_mojibake_cues"] += 1
        if PLACEHOLDER.search(text):
            counts["placeholder_cues"] += 1
        if not text.strip():
            counts["empty_text_cues"] += 1
        normalized = " ".join(text.casefold().split())
        # Short natural exclamations (はい, ええ, etc.) can recur harmlessly.
        if len(normalized) >= 12 and JA.search(normalized):
            repeated[normalized] += 1
    counts["max_long_line_repetition"] = max(repeated.values(), default=0)
    denominator = max(1, counts["letter_cues"])
    japanese_fraction = counts["japanese_cues"] / denominator
    english_fraction = counts["english_sentence_cues"] / denominator
    holds = []
    if counts["control_character_cues"]:
        holds.append("broken_control_characters")
    if counts["replacement_character_cues"] >= max(4, int(n * 0.03)):
        holds.append("extensive_replacement_characters")
    if counts["probable_mojibake_cues"] >= max(10, int(n * 0.08)):
        holds.append("extensive_encoding_garbage")
    if counts["placeholder_cues"] >= max(15, int(n * 0.10)):
        holds.append("placeholder_instead_of_dialogue")
    if counts["english_sentence_cues"] >= 20 and english_fraction >= 0.30:
        holds.append("substantial_untranslated_english")
    if counts["max_long_line_repetition"] >= max(25, int(n * 0.22)):
        holds.append("extreme_repeated_japanese_text")
    if counts["empty_text_cues"] >= max(10, int(n * 0.10)):
        holds.append("substantial_empty_cues")
    if japanese_fraction < 0.65:
        holds.append("insufficient_japanese_text")
    warnings = []
    if (counts["english_sentence_cues"] >= 10
            and english_fraction >= 0.08 and "substantial_untranslated_english" not in holds):
        warnings.append("some_english_dialogue")
    if counts["probable_mojibake_cues"] and "extensive_encoding_garbage" not in holds:
        warnings.append("isolated_possible_encoding_artifacts")
    if counts["replacement_character_cues"] and "extensive_replacement_characters" not in holds:
        warnings.append("isolated_replacement_characters")
    return {
        "verdict": "hold" if holds else "pass",
        "holds": holds,
        "warnings": warnings,
        "cues": n,
        "japanese_fraction_of_letter_cues": round(japanese_fraction, 3),
        "english_sentence_fraction_of_letter_cues": round(english_fraction, 3),
        "signals": dict(sorted(counts.items())),
        "scope": "gross_corruption_only_not_translation_fidelity",
    }


def require_not_garbage(raw: bytes) -> dict:
    result = assess(raw)
    if result["holds"]:
        raise RuntimeError("obvious_source_quality_hold:" + ",".join(result["holds"]))
    return result


def audit_staged():
    root = Path.home() / "bruiser-pilot/ja-first-inventory/staged"
    if not root.is_dir() or root.is_symlink() or root.stat().st_mode & 0o077:
        raise RuntimeError("private_staging_directory_missing_or_insecure")
    outcomes = Counter()
    for file in sorted(root.glob("*.opensubtitles.*.ja.srt")):
        if file.is_symlink() or not file.is_file() or file.stat().st_mode & 0o077:
            raise RuntimeError("unsafe_staged_subtitle_file")
        try:
            result = assess(file.read_bytes())
            print("SOURCED_QA",file.name, json.dumps({
                "verdict":result["verdict"],"holds":result["holds"],
                "warnings":result["warnings"],"cues":result["cues"],
                "japanese_fraction":result["japanese_fraction_of_letter_cues"],
                "english_fraction":result["english_sentence_fraction_of_letter_cues"],
            },sort_keys=True),flush=True)
            outcomes[result["verdict"]] += 1
        except (OSError,RuntimeError,UnicodeError) as exc:
            print("SOURCED_QA",file.name,"ERROR",type(exc).__name__,str(exc)[:100],flush=True)
            outcomes["error"] += 1
    print("SOURCED_QA_SUMMARY",json.dumps(dict(outcomes),sort_keys=True),flush=True)
    print("READ ONLY: existing source/subtitle files unchanged; no translation, providers or video access.",flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit-staged",action="store_true",
                        help="read-only spoiler-free QA summary of existing host-staged Japanese SRTs")
    args=parser.parse_args()
    if not args.audit_staged:
        parser.error("--audit-staged required")
    audit_staged()


if __name__=="__main__":
    main()
