"""Non-destructive structural repair for staged Japanese SRTs.

Only alter mechanical defects: eliminate forbidden C0/C1 control bytes in
dialogue (never letters/punctuation), discard truly EMPTY timed cues, and
rebuild correct SRT separation/indexes. Any other malformed input is held.

The saved provider file is NEVER modified. Callers retain its bytes/SHA in
the publication provenance and validate the derived output independently.
"""
from __future__ import annotations

import re
import unicodedata

MAX_BYTES=2_000_000
STAMP=re.compile(
    r"\A((?:\d{1,3}:)?\d{2}:\d{2}[,.]\d{2,3})\s*-->\s*"
    r"((?:\d{1,3}:)?\d{2}:\d{2}[,.]\d{2,3})\Z"
)
ARROWS=re.compile(
    r"(?m)^[ \t]*(?:\d{1,3}:)?\d{2}:\d{2}[,.]\d{2,3}"
    r"[ \t]*-->[ \t]*(?:\d{1,3}:)?\d{2}:\d{2}[,.]\d{2,3}"
)


def _milliseconds(token):
    fields=token.replace(",",".").split(":")
    if len(fields)==3:
        hours,minute,rest=fields
    else:
        hours,minute,rest="0",*fields
    sec,millis=rest.split(".")
    if not 0<=int(minute)<60 or not 0<=int(sec)<60:
        raise RuntimeError("invalid_staged_srt_clock")
    return ((int(hours)*3600+int(minute)*60+int(sec))*1000+
            int(millis.ljust(3,"0")))


def _remove_controls(dialogue):
    keep=[]
    removed=0
    for ch in dialogue:
        # Newlines/tabs are structural text; all other Unicode Cc controls
        # are invalid in this SRT context (e.g. SUB U+001A).
        if unicodedata.category(ch)=="Cc" and ch not in "\t\n\r":
            removed+=1
        else:
            keep.append(ch)
    return "".join(keep),removed


def normalize(raw,*,expected_timestamps=None):
    """Return (working SRT bytes, change report) without modifying raw.

    No dialogue is dropped except empty cue slots and non-text control chars.
    Fail closed if an unparseable block contains actual text, if timestamps
    are lost, or if cue order/timing is invalid. Do not infer edition fit.
    """
    if not isinstance(raw,bytes) or not 0<len(raw)<=MAX_BYTES:
        raise RuntimeError("invalid_staged_srt_bytes")
    try:
        original=raw.decode("utf-8-sig")
    except UnicodeError:
        raise RuntimeError("staged_srt_not_utf8") from None
    if "\ufffd" in original or "\x00" in original:
        raise RuntimeError("staged_srt_invalid_characters")
    stamp_total=len(ARROWS.findall(original))
    if (expected_timestamps is not None and
            stamp_total!=int(expected_timestamps)):
        raise RuntimeError("staged_srt_timestamps_mismatch_saved_record")
    if stamp_total<1:
        raise RuntimeError("staged_srt_no_timestamps")
    blocks=re.split(r"\r?\n[ \t]*\r?\n",original.strip(" \t\r\n"))
    parsed=[]
    empty=0
    invalid_controls=0
    for k,block in enumerate(blocks,1):
        lines=block.strip(" \t\r\n").splitlines()
        ix=int(bool(lines and lines[0].strip().isdigit()))
        if len(lines)<ix+1:
            raise RuntimeError("staged_srt_block_malformed:"+str(k))
        timing=lines[ix].strip()
        m=STAMP.fullmatch(timing)
        if not m:
            raise RuntimeError("staged_srt_block_malformed:"+str(k))
        start,end=map(_milliseconds,m.groups())
        if start>=end:
            raise RuntimeError("staged_srt_interval_invalid:"+str(k))
        dialogue="\n".join(lines[ix+1:])
        clean,removed=_remove_controls(dialogue)
        invalid_controls+=removed
        if not clean.strip():
            empty+=1
            continue
        parsed.append((start,end,timing,clean))
    if len(blocks)!=stamp_total:
        # Never normalize a block which silently combines multiple cues,
        # even if the parser happened to accept its first timestamp.
        raise RuntimeError("staged_srt_multiple_timestamps_per_block")
    if not parsed:
        raise RuntimeError("staged_srt_no_dialogue")
    if any(parsed[i][0]<parsed[i-1][0] for i in range(1,len(parsed))):
        raise RuntimeError("staged_srt_cue_order_invalid")
    changed=bool(empty or invalid_controls or raw.startswith(b"\xef\xbb\xbf"))
    changed=changed or "\r" in original or any(
        not block.strip(" \t\r\n").startswith(str(i))
        for i,block in enumerate(blocks,1) if block.strip(" \t\r\n").splitlines()[0].strip().isdigit()
    )
    report={
        "source_timestamp_cues":stamp_total,
        "retained_dialogue_cues":len(parsed),
        "empty_cues_removed":empty,
        "control_characters_removed":invalid_controls,
        "structural_repair":changed
    }
    if not changed:
        return raw,report
    result="\n\n".join(
        f"{i}\n{stamp}\n{text}" for i,(_,__,stamp,text) in enumerate(parsed,1)
    )+"\n"
    output=result.encode("utf-8")
    if len(output)>MAX_BYTES:
        raise RuntimeError("normalized_staged_srt_too_large")
    if len(ARROWS.findall(result))!=len(parsed):
        raise RuntimeError("staged_srt_normalization_lost_timestamps")
    # Recheck every original nonempty dialogue string was preserved, minus
    # only invalid control chars and empty slots.
    return output,report
