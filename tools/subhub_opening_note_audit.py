#!/usr/bin/env python3
"""Read-only census of opening release notes in SubHub's SAVED staged tracks.

Reports how many existing downloaded Japanese SRTs contain recognizable
technical opening annotations or potential translator credits. This is a
development audit, NOT permission to remove translator names or release
notes. Originals remain unchanged; no provider usage, jobs or model calls.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from urllib.parse import quote

try:
    from . import ja_first_srt_normalize as structure
except ImportError:
    import ja_first_srt_normalize as structure

ROOT=Path.home()/"bruiser-pilot/ja-first-inventory"
CREDIT=re.compile(
    r"(?:字幕(?:制作|翻訳|作成|担当)?|翻訳)\s*[:：]|"
    r"(?:subtitles?(?:\s+(?:by|from))?|translated\s+by|"
    r"translation\s+by)\s*[:：]?\s+\S",re.IGNORECASE)


def _clock(text):
    match=structure.STAMP.fullmatch(text.strip())
    if not match:
        return None
    return structure._milliseconds(match.group(1))


def opening_candidates(raw):
    """Classify only the opening *two* cues; never infer scene truth."""
    try:
        text=raw.decode("utf-8-sig")
    except UnicodeError:
        return []
    blocks=[x.strip() for x in re.split(
        r"\r?\n[ \t]*\r?\n",text.strip(" \t\r\n")) if x.strip()][:2]
    result=[]
    for i,block in enumerate(blocks):
        lines=block.splitlines()
        j=int(bool(lines and lines[0].strip().isdigit()))
        if len(lines)<j+2:
            continue
        start=_clock(lines[j])
        if start is None or start>120000:
            continue
        words="\n".join(lines[j+1:]).strip()
        if not words:
            continue
        if i==0 and structure._release_note(words,start):
            category="recognized_first_cue_timing_note"
        elif CREDIT.search(words):
            category="possible_credit_needs_review"
        elif ("動画" in words and
              any(x in words for x in ("ズレ","ずれ","秒","合わせ"))):
            category="possible_timing_note_needs_review"
        else:
            continue
        result.append({"kind":category,"cue":i+1,"at_seconds":round(start/1000,2),
                       "text":words[:100]})
    return result


def main():
    if not ROOT.is_dir() or ROOT.is_symlink():
        raise RuntimeError("source_inventory_missing")
    stage=ROOT/"japanese-stage.sqlite3"
    if not stage.is_file() or stage.is_symlink():
        raise RuntimeError("staging_database_missing")
    manifests=sorted(ROOT.glob("ja-intake-*.json"))
    if not manifests or manifests[-1].is_symlink():
        raise RuntimeError("saved_inventory_missing")
    doc=json.loads(manifests[-1].read_text("utf-8"))
    names={str(item.get("jellyfin_id")):str(item.get("title") or "")
           for item in doc.get("items",[]) if isinstance(item,dict)}
    with sqlite3.connect("file:"+quote(str(stage.resolve()),safe="/")+
                         "?mode=ro",uri=True,timeout=20) as db:
        stages=db.execute(
            "SELECT jellyfin_id,subtitle_id,host_path,sha256 FROM staged "
            "WHERE status IN ('staged','held_duration_mismatch')").fetchall()
    stats=Counter()
    found=[]
    content_digests=set()
    for jid,sid,path,digest in stages:
        stats["stage_records"]+=1
        p=Path(path)
        if p.is_symlink() or not p.is_file():
            stats["missing_or_untrusted"]+=1
            continue
        try:
            if (not p.resolve().is_relative_to((ROOT/"staged").resolve())
                    or not 0<p.stat().st_size<=2_000_000):
                stats["missing_or_untrusted"]+=1
                continue
            raw=p.read_bytes()
        except OSError:
            stats["unreadable"]+=1
            continue
        if hashlib.sha256(raw).hexdigest()!=digest:
            stats["sha_mismatch"]+=1
            continue
        if digest in content_digests:
            stats["duplicate_stage_bytes"]+=1
            continue
        content_digests.add(digest)
        stats["distinct_valid_sources"]+=1
        matches=opening_candidates(raw)
        if not matches:
            continue
        for match in matches:
            stats[match["kind"]]+=1
            found.append((match["kind"],names.get(jid,jid),jid,sid,match))
    print("=== READ-ONLY OPENING METADATA AUDIT ===")
    for key in ("stage_records","distinct_valid_sources",
                "duplicate_stage_bytes","recognized_first_cue_timing_note",
                "possible_credit_needs_review",
                "possible_timing_note_needs_review","sha_mismatch",
                "missing_or_untrusted","unreadable"):
        print(f"{key}: {stats[key]}")
    for category,title,jid,sid,info in sorted(found)[:80]:
        print(f"[{category}] {title} [{str(jid)[:8]}] "
              f"release={sid} cue={info['cue']} at={info['at_seconds']}s "
              f"text={info['text']!r}")
    if len(found)>80:
        print(f"... {len(found)-80} further annotations not shown")
    print("A potential credit is NOT automatically removed. "
          "Counts cover only staged saved SRTs, not the whole library.")
    print("No subtitle or database modifications performed.")


if __name__=="__main__":
    main()
