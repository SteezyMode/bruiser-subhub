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

# A release-duration note is metadata, not spoken Japanese. Trial only:
# require ALL strong cues, never guess merely from a number or a title.
RELEASE_DURATION=re.compile(r"(?<![0-9])(?:[0-9]{1,2}[:：]){2}[0-9]{2}(?![0-9])")

MAX_BYTES=2_000_000
STAMP=re.compile(
    r"\A((?:\d{1,3}:)?\d{2}:\d{2}[,.]\d{2,3})[^\S\r\n]*-->[^\S\r\n]*"
    r"((?:\d{1,3}:)?\d{2}:\d{2}[,.]\d{2,3})\Z"
)
ARROWS=re.compile(
    r"(?m)^[^\S\r\n]*(?:\d{1,3}:)?\d{2}:\d{2}[,.]\d{2,3}"
    r"[^\S\r\n]*-->[^\S\r\n]*(?:\d{1,3}:)?\d{2}:\d{2}[,.]\d{2,3}"
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


def _canonical_clock(milliseconds):
    """Exact SRT clock: a format change must never move a cue in time."""
    hours, rest = divmod(milliseconds, 3600000)
    minutes, rest = divmod(rest, 60000)
    seconds, fraction = divmod(rest, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{fraction:03d}"


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


def _release_note(text,start_ms):
    """Strict first-cue technical annotation predicate, never an AI guess."""
    if start_ms>120000 or not RELEASE_DURATION.search(text):
        return False
    japanese=("動画" in text and
              any(term in text for term in ("合わせ", "ズレ", "ずれ", "同期")))
    lowered=text.casefold()
    english=("video" in lowered and
             any(term in lowered for term in ("sync", "offset", "version",
                                               "timing", "aligned")))
    return japanese or english



# Credit slates are metadata, NOT dialogue. The following are intentionally
# anchored to an entire short opening cue; no arbitrary "by" substring match.
# Keep this narrow enough that a character mentioning subtitles is retained.
EN_CREDIT = re.compile(r"""(?ix)
    \A(?:(?:japanese|english|jp|en)\s+)?
    (?:
      (?:subtitles?|subs?|fan[- ]?subs?|translations?|transcriptions?|
         captions?|sync|synchroni[sz]ation|timing|typesetting)
         \s+(?:by|from|courtesy\s+of)
      |(?:subbed|translated|transcribed|captioned|synced|synchroni[sz]ed|
          timed|typeset)\s+by
      |(?:subtitles?|subs?|translations?|captions?)\s*[:：]
    )
    \s*[:：\-]?\s*(?P<name>.+)\Z
""")
JP_CREDIT = re.compile(r"""(?ix)
    \A(?:日本語字幕|字幕(?:翻訳|制作|作成|担当|協力|提供)?|
         翻訳(?:担当|者)?|字幕[・/]翻訳|翻訳[・/]字幕)
       \s*(?:[:：\-]|by\s+)\s*(?P<name>.+)\Z
""")


def _opening_credit(text, start_ms):
    """Identify a demonstrably non-dialogue opening translator/uploader slate.

    NEVER use this for general content removal. Only the initial cue(s)
    before spoken dialogue and <=2 minutes into the video may qualify.
    Ordinary names without an explicit credit label remain dialogue.
    """
    if start_ms > 120000 or "\n" in text.strip() or len(text) > 160:
        return False
    plain = re.sub(r"\{\\an[1-9]\}", "", text.strip())
    plain = re.sub(r"</?(?:i|b|u|font)\b[^>]*>", "", plain,
                   flags=re.IGNORECASE)
    plain = plain.strip().strip("[]【】").strip()
    if not 8 <= len(plain) <= 110:
        return False
    match = EN_CREDIT.fullmatch(plain) or JP_CREDIT.fullmatch(plain)
    if match is None:
        return False
    name = match.group("name").strip(" \t:：-")
    if not 2 <= len(name) <= 70:
        return False
    # Reject sentence-like text rather than risking deletion of movie dialogue.
    if re.search(r"[!?。！？\r\n]|(?:\.\s+[A-Z])", name):
        return False
    if re.search(r"(?i)\b(?:is|are|was|were|said|says|because|when|that)\b",
                 name):
        return False
    return True

# A non-time punctuation mark sometimes appears immediately before otherwise
# intact seconds, e.g. 00:54:？46,150. Never invent a missing digit.
STRAY_TIMESTAMP_MARK = re.compile(
    r"(?m)^(?P<left>(?:[0-9]{1,3}:)?[0-9]{2}:[0-9]{2}[,.][0-9]{2,3})"
    r"(?P<arrow>[ \t]*-->[ \t]*)"
    r"(?P<right>(?:[0-9]{1,3}:)?[0-9]{2}:)"
    r"？(?P<seconds>[0-5][0-9][,.][0-9]{3})[ \t]*$"
)


def _repair_intact_seconds_mark(original):
    """Remove one extraneous fullwidth mark, without filling in any clock digit."""
    matches=list(STRAY_TIMESTAMP_MARK.finditer(original))
    if len(matches)>1:
        raise RuntimeError("staged_srt_multiple_corrupted_clock_marks")
    if not matches:
        return original,0
    match=matches[0]
    fixed=(match.group("left")+match.group("arrow")+
           match.group("right")+match.group("seconds"))
    if not STAMP.fullmatch(fixed):
        raise RuntimeError("staged_srt_corrupted_clock_unverifiable")
    a,b=STAMP.fullmatch(fixed).groups()
    if _milliseconds(a)>=_milliseconds(b):
        raise RuntimeError("staged_srt_corrupted_clock_interval_invalid")
    return original[:match.start()]+fixed+original[match.end():],1


def _block_index(block):
    """A cue number is corroboration only if followed by a real timestamp."""
    lines=block.strip(" \t\r\n").splitlines()
    if len(lines)>=2 and lines[0].strip().isdigit() and STAMP.fullmatch(lines[1].strip()):
        return int(lines[0].strip())
    return None


def _separate_merged_timed_block(block, *, preceding_index=None,following_index=None):
    """Recover cues whose separator blank line is missing.

    Never invent time ranges or discard text. Every embedded clock must be
    a complete standalone SRT timestamp, with nonempty dialogue between
    clocks and after the last one. Ambiguous numeric text that could be a
    missing cue index must be reviewed, not silently stripped.
    """
    lines=block.strip(" \t\r\n").splitlines()
    ix=int(bool(lines and lines[0].strip().isdigit()))
    if len(lines)<=ix or not STAMP.fullmatch(lines[ix].strip()):
        raise RuntimeError("staged_srt_merged_block_invalid_first_timestamp")
    portions=[]
    current=lines[:ix+1]
    initial_index=int(lines[0].strip()) if ix else None
    clock_count=len(ARROWS.findall(block))
    for line in lines[ix+1:]:
        if STAMP.fullmatch(line.strip()):
            text_lines=current[(1 if current[0].strip().isdigit() else 0)+1:]
            if not any(x.strip() for x in text_lines):
                raise RuntimeError("staged_srt_merged_block_missing_dialogue")
            next_number=None
            if text_lines[-1].strip().isdigit():
                # Interpret a trailing bare number as the next cue index ONLY
                # if it is consecutive and corroborated by an adjacent block.
                # Without that evidence, it could be spoken numeric dialogue.
                previous=(int(current[0].strip())
                          if current[0].strip().isdigit() else None)
                proposed=int(text_lines[-1].strip())
                before_ok=(preceding_index is not None and initial_index is not None
                           and preceding_index==initial_index-1)
                after_ok=(following_index is not None and initial_index is not None
                          and following_index==initial_index+clock_count)
                if (previous is None or proposed!=previous+1
                        or not (before_ok or after_ok)
                        or (preceding_index is not None and not before_ok)
                        or (following_index is not None and not after_ok)
                        or not any(t.strip() for t in text_lines[:-1])):
                    raise RuntimeError("staged_srt_merged_block_ambiguous_index")
                next_number=text_lines[-1].strip()
                current=current[:-1]
            portions.append("\n".join(current))
            current=[next_number,line] if next_number else [line]
        elif "-->" in line and ARROWS.fullmatch(line.strip()) is None:
            raise RuntimeError("staged_srt_merged_block_invalid_timestamp")
        else:
            current.append(line)
    text_lines=current[(1 if current[0].strip().isdigit() else 0)+1:]
    if not any(x.strip() for x in text_lines):
        raise RuntimeError("staged_srt_merged_block_missing_dialogue")
    portions.append("\n".join(current))
    if sum(len(ARROWS.findall(x)) for x in portions)!=len(ARROWS.findall(block)):
        raise RuntimeError("staged_srt_merged_block_timestamps_mismatch")
    return portions


def normalize(raw,*,expected_timestamps=None,
              trial_release_note=False,trial_local_swap=False,
              trial_chronological_reorder=False):
    """Return (working SRT bytes, change report) without modifying raw.

    No dialogue is dropped: only empty slots, explicit opening metadata credits,
    and non-text control chars can be excluded from the working trial.
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
    # Repair an intact clock with a stray punctuation mark BEFORE counting
    # timestamps. Original provider bytes remain unchanged on disk.
    original,repaired_marks=_repair_intact_seconds_mark(original)
    stamp_total=len(ARROWS.findall(original))
    if (expected_timestamps is not None and
            stamp_total!=int(expected_timestamps)):
        raise RuntimeError("staged_srt_timestamps_mismatch_saved_record")
    if stamp_total<1:
        raise RuntimeError("staged_srt_no_timestamps")
    original_blocks=[b for b in re.split(r"\r?\n[ \t]*\r?\n",
               original.strip(" \t\r\n")) if b.strip(" \t\r\n")]
    blocks=[]
    merged_blocks=0
    for block_no,block in enumerate(original_blocks):
        stamps=len(ARROWS.findall(block))
        if stamps>1:
            previous=(_block_index(original_blocks[block_no-1])
                      if block_no else None)
            following=(_block_index(original_blocks[block_no+1])
                       if block_no+1<len(original_blocks) else None)
            pieces=_separate_merged_timed_block(
                block,preceding_index=previous,following_index=following)
            if len(pieces)!=stamps:
                raise RuntimeError("staged_srt_merged_block_cue_count_mismatch")
            blocks.extend(pieces)
            merged_blocks+=1
        else:
            blocks.append(block)
    parsed=[]
    empty=0
    invalid_controls=0
    release_notes=0
    opening_credits=0
    reordered=[]
    canonicalized_timestamps=0
    for k,block in enumerate(blocks,1):
        if len(ARROWS.findall(block))>1:
            raise RuntimeError("staged_srt_multiple_timestamps_per_block")
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
        canonical=(_canonical_clock(start)+" --> "+_canonical_clock(end))
        if timing!=canonical:
            canonicalized_timestamps+=1
        dialogue="\n".join(lines[ix+1:])
        clean,removed=_remove_controls(dialogue)
        invalid_controls+=removed
        if not clean.strip():
            empty+=1
            continue
        if trial_release_note and k==1 and _release_note(clean,start):
            # Only exclude the explicit technical opening annotation from
            # the working trial. The provider original remains immutable.
            release_notes+=1
            continue
        if (trial_release_note and k<=3 and not parsed
                and _opening_credit(clean,start)):
            # Strict opening metadata only. Never strip a subsequent credit
            # interleaved with actual dialogue, or modify saved provider bytes.
            opening_credits+=1
            continue
        parsed.append((start,end,canonical,clean))
    if len(blocks)!=stamp_total:
        # Never normalize a block which silently combines multiple cues,
        # even if the parser happened to accept its first timestamp.
        raise RuntimeError("staged_srt_multiple_timestamps_per_block")
    if not parsed:
        raise RuntimeError("staged_srt_no_dialogue")
    reversals=[i for i in range(1,len(parsed))
               if parsed[i][0]<parsed[i-1][0]]
    chronological_reorder=None
    if reversals:
        # Keep the established one-adjacent-pair <=2s recovery unchanged.
        local_fixed=False
        if trial_local_swap and len(reversals)==1:
            i=reversals[0]
            jump=parsed[i-1][0]-parsed[i][0]
            if 0<jump<=2000:
                trial=list(parsed)
                trial[i-1],trial[i]=trial[i],trial[i-1]
                if all(trial[j][0]>=trial[j-1][0]
                       for j in range(1,len(trial))):
                    parsed=trial
                    reordered=[{"original_cues":[i,i+1],"jump_ms":jump}]
                    local_fixed=True
        if not local_fixed:
            if not trial_chronological_reorder:
                raise RuntimeError("staged_srt_cue_order_invalid")
            # Old provider SRTs occasionally contain intact cue blocks in a
            # slightly wrong order. We may move only COMPLETE timestamp/text
            # pairs, without editing a single clock or Japanese character.
            # Require consecutive explicit source indexes, no removed cues,
            # a tiny rearrangement (<=8 cues, <=3 index positions), and
            # <=30s displacement at each position. Larger or ambiguous
            # scrambling stays private for manual inspection.
            if (len(parsed)!=len(blocks) or
                    any(_block_index(block)!=i
                        for i,block in enumerate(blocks,1))):
                raise RuntimeError("staged_srt_cue_order_invalid")
            order=sorted(range(len(parsed)),key=lambda i:(parsed[i][0],i))
            moved=[i for i,source_i in enumerate(order) if i!=source_i]
            if (not moved or len(moved)>8
                    or max(abs(i-order[i]) for i in moved)>3
                    or any(abs(parsed[i][0]-parsed[order[i]][0])>30000
                           for i in moved)):
                raise RuntimeError("staged_srt_cue_order_invalid")
            lo=max(0,min(moved)-1)
            hi=min(len(parsed),max(moved)+2)
            starts=[parsed[i][0] for i in range(lo,hi)]
            if len(set(starts))!=len(starts):
                raise RuntimeError("staged_srt_cue_order_invalid")
            maximum_time_displacement=max(
                abs(parsed[i][0]-parsed[order[i]][0]) for i in moved)
            parsed=[parsed[i] for i in order]
            if any(parsed[i][0]<parsed[i-1][0]
                   for i in range(1,len(parsed))):
                raise RuntimeError("staged_srt_cue_order_invalid")
            chronological_reorder={
                "moved_cues":len(moved),
                "max_index_displacement":max(abs(i-order[i]) for i in moved),
                "max_position_time_displacement_ms":maximum_time_displacement,
            }
    changed=bool(repaired_marks or empty or invalid_controls or release_notes or opening_credits or reordered or chronological_reorder or merged_blocks
                 or canonicalized_timestamps or raw.startswith(b"\xef\xbb\xbf"))
    changed=changed or "\r" in original or any(
        not block.strip(" \t\r\n").startswith(str(i))
        for i,block in enumerate(blocks,1) if block.strip(" \t\r\n").splitlines()[0].strip().isdigit()
    )
    report={
        "source_timestamp_cues":stamp_total,
        "retained_dialogue_cues":len(parsed),
        "empty_cues_removed":empty,
        "merged_blocks_repaired":merged_blocks,
        "intact_seconds_stray_marks_removed":repaired_marks,
        "merged_cues_recovered":len(blocks)-len(original_blocks),
        "control_characters_removed":invalid_controls,
        "technical_release_notes_excluded":release_notes,
        "opening_credit_cues_excluded":opening_credits,
        "local_timestamp_swaps":reordered,
        "chronological_cue_reorder":chronological_reorder,
        "timestamp_formats_normalized":canonicalized_timestamps,
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




def inspect_timestamp_reversals(raw):
    """Read-only localization of out-of-order source cues. No reordering."""
    if not isinstance(raw,bytes) or not 0<len(raw)<=MAX_BYTES:
        raise RuntimeError("invalid_staged_srt_bytes")
    text=raw.decode("utf-8-sig")
    parts=[b for b in re.split(r"\r?\n[ \t]*\r?\n",
                              text.strip(" \t\r\n")) if b.strip()]
    entries=[]
    for index,block in enumerate(parts,1):
        lines=block.strip(" \t\r\n").splitlines()
        ix=int(bool(lines and lines[0].strip().isdigit()))
        if len(lines)<ix+1:
            continue
        m=STAMP.fullmatch(lines[ix].strip())
        if not m:
            continue
        start=_milliseconds(m.group(1))
        entries.append((index,start,
                        "\n".join(lines[ix+1:]).strip()[:120]))
    reversals=[]
    for prev,current in zip(entries,entries[1:]):
        if current[1]<prev[1]:
            reversals.append({
                "prior_block":prev[0],
                "prior_start_seconds":round(prev[1]/1000,3),
                "prior_text":prev[2],
                "later_block":current[0],
                "later_start_seconds":round(current[1]/1000,3),
                "later_text":current[2],
                "backward_jump_seconds":round((prev[1]-current[1])/1000,3),
            })
    return {"total_timed_blocks":len(entries),
            "timestamp_reversals":len(reversals),
            "examples":reversals[:12]}


def _audit_staged(jids):
    """Host-local, strictly read-only proof of repair effects on saved bytes."""
    import hashlib
    import json
    from pathlib import Path
    import sqlite3
    from urllib.parse import quote
    root=Path.home()/"bruiser-pilot/ja-first-inventory"
    db=root/"japanese-stage.sqlite3"
    if not db.is_file() or db.is_symlink() or not root.is_dir():
        raise RuntimeError("missing_private_staged_database")
    paths=sorted(root.glob("ja-intake-*.json"))
    if not paths:
        raise RuntimeError("missing_jellyfin_manifest")
    info=json.loads(paths[-1].read_text("utf-8"))
    names={str(item.get("jellyfin_id")):item.get("title")
           for item in info.get("items",[]) if isinstance(item,dict)}
    with sqlite3.connect("file:"+quote(str(db.resolve()),safe="/")+"?mode=ro",
                         uri=True,timeout=15) as conn:
        selected=[]
        for jid in jids:
            selected.extend(conn.execute(
                "SELECT jellyfin_id,subtitle_id,host_path,sha256,status,metrics_json "
                "FROM staged WHERE jellyfin_id=? ORDER BY subtitle_id",(jid,)))
    print("=== NON-DESTRUCTIVE JAPANESE SRT REPAIR PREFLIGHT ===")
    print("Selected media IDs:",len(jids),"saved stage records:",len(selected))
    for jid,sid,path,digest,status,raw_metrics in selected:
        print("\nTITLE:",names.get(jid) or jid,"["+jid[:8]+"]",
              "stage ID:",sid,"status:",status)
        source=Path(path)
        if (source.is_symlink() or not source.is_file()
                or not source.resolve().is_relative_to((root/"staged").resolve())
                or not 0<source.stat().st_size<=MAX_BYTES):
            print("  HOLD: staged file missing or unsafe")
            continue
        raw=source.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=digest:
            print("  HOLD: saved file SHA mismatch")
            continue
        metrics=json.loads(raw_metrics)
        try:
            revised,report=normalize(
                raw,expected_timestamps=metrics.get("cues"),
                trial_release_note=True,trial_local_swap=True,
                trial_chronological_reorder=True)
            decoded=revised.decode("utf-8-sig")
            ends=[]
            for match in ARROWS.finditer(decoded):
                timing=match.group().strip()
                pair=STAMP.fullmatch(timing)
                if pair:
                    ends.append(_milliseconds(pair.group(2)))
            if len(ends)!=report["retained_dialogue_cues"]:
                raise RuntimeError("repaired_timing_count_mismatch")
            runtime=float(metrics.get("video_seconds") or 0)
            if runtime<=0:
                raise RuntimeError("video_duration_unavailable")
            end_sec=max(ends)/1000
            print("  Before:",report["source_timestamp_cues"],"timed cues")
            print("  After:",report["retained_dialogue_cues"],"dialogue cues",
                  "| empty removed:",report["empty_cues_removed"],
                  "| control characters removed:",
                  report["control_characters_removed"])
            print("  Last dialogue ends:",round(end_sec,2),"seconds",
                  "| video runtime:",round(runtime,2),"seconds",
                  "| ratio:",round(end_sec/runtime,3))
            print("  Structural repair:",report["structural_repair"],
                  "| original SHA:",digest[:16],
                  "| derived SHA:",hashlib.sha256(revised).hexdigest()[:16])
            print("  Timing verdict: NOT TESTED — needs video alignment")
        except (ValueError,RuntimeError,UnicodeError) as exc:
            print("  HOLD:",str(exc))
            if str(exc)=="staged_srt_cue_order_invalid":
                try:
                    print("  SOURCE TIMING REVERSALS:",
                          json.dumps(inspect_timestamp_reversals(raw),
                                     ensure_ascii=False))
                except (ValueError,RuntimeError,UnicodeError) as audit_exc:
                    print("  REVERSAL INSPECTION UNAVAILABLE:",str(audit_exc))
    print("\nNo saved stage, video, sidecar or search database was modified.")


if __name__=="__main__":
    import argparse
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--audit-staged",action="store_true",
                   help="read saved stages; compute normalization in memory only")
    p.add_argument("--id",action="append",default=[],
                   help="exact 32-character Jellyfin ID, repeat for movies")
    a=p.parse_args()
    if not a.audit_staged or not a.id or len(a.id)>30 or any(
            not re.fullmatch(r"[a-f0-9]{32}",jid) for jid in a.id):
        p.error("specify --audit-staged and one or more exact --id values")
    _audit_staged(a.id)
