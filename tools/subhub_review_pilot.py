#!/usr/bin/env python3
"""Conservative standalone Japanese SRT review pilot. Never touches the first-pass translator."""
import argparse
import csv
import fcntl
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

MODEL_DEFAULT = "hf.co/tencent/Hy-MT2-7B-GGUF:Q4_K_M"
PROMPT_REVISION = "subhub-review-pilot-v1"
STAMP = re.compile(r"\d{2}:\d{2}:\d{2},\d{3} --> \d{2}:\d{2}:\d{2},\d{3}(?:[^\n]*)")
NON_JAPANESE_SCRIPTS = re.compile(r"[\uac00-\ud7af\u0400-\u04ff]")
HAS_JAPANESE = re.compile(r"[\u3040-\u30ff\u3400-\u9fff]")
CATEGORIES = {
    "wrong_action", "reversed_meaning", "wrong_object", "wrong_person",
    "literal_idiom", "material_omission", "material_addition", "wrong_language",
    "nonsense",
}


def read_srt(path):
    text = path.read_text(encoding="utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
    entries = []
    for pos, block in enumerate(re.split(r"\n\s*\n", text.strip()), 1):
        m = re.fullmatch(r"(\d+)\n([^\n]+)\n([\s\S]+)", block)
        if not m or not STAMP.fullmatch(m[2]) or not m[3].strip():
            raise ValueError(f"Malformed SRT block {pos}: {path}")
        entries.append((int(m[1]), m[2], m[3]))
    if not entries:
        raise ValueError(f"Empty SRT: {path}")
    if len(set(n for n, _, _ in entries)) != len(entries):
        raise ValueError(f"Repeated cue number: {path}")
    return entries


def render_srt(entries):
    return "\n\n".join(f"{n}\n{when}\n{txt}" for n, when, txt in entries) + "\n"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_write(path, data):
    tmp = path.with_name(path.name + ".writing")
    tmp.write_text(data, encoding="utf-8")
    os.replace(tmp, path)


def as_one_line(value):
    return re.sub(r"\s+", " ", value).strip()


def prompt(english, japanese, lo, hi, context=2):
    begin = max(0, lo - context)
    end = min(len(english), hi + context)
    lines = []
    for idx in range(begin, end):
        n, _, en = english[idx]
        _, _, ja = japanese[idx]
        label = "TARGET" if lo <= idx < hi else "CONTEXT-ONLY"
        lines.append(
            f"[{label} {n}] EN: {as_one_line(en)}\n"
            f"[{label} {n}] JA: {as_one_line(ja)}"
        )
    return (
        "You are checking Japanese movie subtitles against their original English. "
        "This is an ERROR CHECK, NOT a rewrite or new translation. "
        "Most Japanese lines are already good. Keep them unchanged.\n\n"
        "Find ONLY HIGH-CONFIDENCE meaning failures: the wrong action/object/person, "
        "reversed meaning, literal idiom that changes meaning, major omission or "
        "addition, Korean or another wrong language, or unmistakably nonsensical "
        "Japanese. Do not suggest stylistic polish, more literal translations, "
        "alternative wording, speaker-label changes, or subtitle sound-effect "
        "changes. A natural paraphrase is GOOD and must not be changed. "
        "For instance, translating 'take point' as 'take command' is acceptable. "
        "When uncertain, leave the existing Japanese alone.\n\n"
        "Examine the target cues, considering surrounding context. "
        "Never edit CONTEXT-ONLY cues. Return at most 4 edits. "
        "Every new_ja must be short, natural Japanese dialogue appropriate to the "
        "original speaker and context; do not invent facts.\n\n"
        "Respond with only this JSON object (empty edits is normal):\n"
        '{"edits":[{"cue":123,"type":"wrong_action",'
        '"new_ja":"正しい日本語","why":"brief reason referencing English"}]}\n'
        "Allowed type: " + ", ".join(sorted(CATEGORIES)) + ".\n\n"
        "SUBTITLE PAIRS:\n" + "\n".join(lines) + "\n"
    )


def call_ollama(endpoint, model, request_text):
    payload = {
        "model": model,
        "stream": False,
        "format": "json",
        "messages": [{"role": "user", "content": request_text}],
        "options": {
            "num_gpu": 99, "num_ctx": 4096, "num_predict": 1024,
            "temperature": 0.1, "top_p": 0.6,
        },
    }
    req = urllib.request.Request(
        endpoint.rstrip("/") + "/api/chat",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=1200) as response:
        data = json.load(response)
    return (data.get("message") or {}).get("content", ""), data.get("done_reason")


def parse_proposals(raw, english, japanese, lo, hi):
    """Keep valid in-range corrections; log invalid model suggestions separately.

    Invalid suggestions must never modify Japanese, but they also must not
    discard other valid suggestions from the same reviewer response.
    """
    data = json.loads(raw)
    if not isinstance(data, dict) or not isinstance(data.get("edits"), list):
        raise ValueError("Reviewer did not return an object with an edits list")
    if len(data["edits"]) > 4:
        raise ValueError("Reviewer proposed more than 4 changes in one batch")
    mapping = {english[i][0]: i for i in range(lo, hi)}
    seen = set()
    edits, ignored = [], []
    required = {"cue", "type", "new_ja", "why"}
    for position, entry in enumerate(data["edits"], 1):
        reason = None
        number = entry.get("cue") if isinstance(entry, dict) else None
        if not isinstance(entry, dict):
            reason = "Non-object edit"
        elif not required.issubset(entry):
            reason = "Missing required fields"
        elif type(number) is not int or number not in mapping:
            reason = "Outside target range (context-only or invented cue)"
        elif number in seen:
            reason = "Duplicate cue"
        else:
            kind = entry["type"]
            new = entry["new_ja"]
            why = entry["why"]
            if kind not in CATEGORIES or not isinstance(new, str) or not isinstance(why, str):
                reason = "Invalid edit type or text fields"
            elif not why.strip() or len(why) > 600:
                reason = "Missing or overlong explanation"
            elif (not new.strip() or len(new) > 200 or "\n\n" in new
                  or STAMP.search(new) or NON_JAPANESE_SCRIPTS.search(new)
                  or not HAS_JAPANESE.search(new)):
                reason = "Unsafe or non-Japanese replacement"
            else:
                idx = mapping[number]
                old = japanese[idx][2]
                if as_one_line(new) == as_one_line(old):
                    continue
                en_text = as_one_line(english[idx][2])
                if re.fullmatch(r"(?:[\[(][^\])]+[\])][\s]*)+", en_text):
                    reason = "Sound-only caption excluded"
                else:
                    seen.add(number)
                    edits.append({
                        "cue": number, "type": kind, "why": why.strip(),
                        "old_ja": old, "new_ja": new.strip(),
                        "en": english[idx][2], "timestamp": english[idx][1],
                    })
        if reason:
            ignored.append({
                "position": position,
                "cue": number,
                "reason": reason,
                "original_proposal": entry,
            })
    return edits, ignored


def salvage_saved_failed(workdir, name, original_record, english, japanese, lo, hi):
    """Re-evaluate saved reviewer replies without invoking Ollama.

    Original failed record and all raw model responses are retained.
    """
    candidates = []
    for attempt in (1, 2):
        raw_path = workdir / f"{name}.attempt-{attempt}.txt"
        if not raw_path.exists():
            continue
        try:
            edits, ignored = parse_proposals(
                raw_path.read_text(encoding="utf-8"), english, japanese, lo, hi
            )
        except (json.JSONDecodeError, ValueError, TypeError) as exc:
            print(f"  Saved attempt {attempt} remains invalid: {exc}", flush=True)
            continue
        candidates.append((edits, ignored, attempt))
    if not candidates:
        return original_record
    # Conservative choice: prefer fewer invalid suggestions, then fewer
    # automatic edits. Every rejected proposal remains in the audit log.
    edits, ignored, chosen = min(
        candidates, key=lambda item: (len(item[1]), len(item[0]), item[2])
    )
    backed_up = workdir / f"{name}.pre-salvage.json"
    if not backed_up.exists():
        atomic_write(
            backed_up,
            json.dumps(original_record, ensure_ascii=False, indent=2) + "\n",
        )
    result = dict(original_record)
    result.pop("error", None)
    result["status"] = "warning" if ignored else "ok"
    result["edits"] = edits
    result["ignored_proposals"] = ignored
    result["salvaged_from_attempt"] = chosen
    atomic_write(
        workdir / f"{name}.json",
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
    )
    print(
        f"  Salvaged saved attempt {chosen}: {len(edits)} valid edits, "
        f"{len(ignored)} rejected proposals (logged)", flush=True
    )
    return result


def save_outputs(workdir, english, japanese, results, complete):
    changes = {}
    for result in results:
        for proposal in result.get("edits", []):
            if proposal["cue"] in changes:
                raise ValueError(f"Duplicate proposed cue {proposal['cue']}")
            changes[proposal["cue"]] = proposal
    updated = [
        (n, timing, changes[n]["new_ja"] if n in changes else ja)
        for n, timing, ja in japanese
    ]
    if len(updated) != len(japanese) or any(
        (n, timing) != (en_n, en_timing)
        for (n, timing, _), (en_n, en_timing, _) in zip(updated, english)
    ):
        raise ValueError("Internal SRT structure drift")
    if any(new_ja != old_ja for (n, _, new_ja), (_, _, old_ja) in zip(updated, japanese)
           if n not in changes):
        raise ValueError("Unedited cue text changed")
    candidate = workdir / ("reviewed-candidate.ja.srt" if complete else "partial-review-candidate.ja.srt")
    atomic_write(candidate, render_srt(updated))
    summary = {
        "complete": complete,
        "total_cues": len(japanese),
        "batches": len(results),
        "successful_batches": sum(r.get("status") in ("ok", "warning") for r in results),
        "warning_batches": [r["batch"] for r in results if r.get("status") == "warning"],
        "failed_batches": [r["batch"] for r in results if r.get("status") == "failed"],
        "ignored_model_proposals": sum(len(r.get("ignored_proposals", [])) for r in results),
        "edited_cues": len(changes),
        "unchanged_cues": len(japanese) - len(changes),
        "candidate_path": str(candidate),
        "notice": "Experimental proposals only; warning batches had rejected suggestions. No semantic guarantee, not published to Jellyfin",
    }
    atomic_write(workdir / "report.json", json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    with (workdir / "edits.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "cue", "timestamp", "type", "en", "old_ja", "new_ja", "why"
        ])
        writer.writeheader()
        for n in sorted(changes):
            writer.writerow({k: changes[n][k] for k in writer.fieldnames})
    rejected = []
    for result in results:
        for entry in result.get("ignored_proposals", []):
            rejected.append({"batch": result["batch"], **entry})
    atomic_write(
        workdir / "ignored-proposals.json",
        json.dumps(rejected, ensure_ascii=False, indent=2) + "\n",
    )
    return summary


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--english", required=True, type=Path)
    p.add_argument("--japanese", required=True, type=Path)
    p.add_argument("--workdir", required=True, type=Path)
    p.add_argument("--ollama", default="http://127.0.0.1:11434")
    p.add_argument("--model", default=MODEL_DEFAULT)
    p.add_argument("--batch-size", type=int, default=25)
    p.add_argument("--validate-only", action="store_true")
    args = p.parse_args()
    if not 5 <= args.batch_size <= 30:
        p.error("batch-size must be between 5 and 30")
    english, japanese = read_srt(args.english), read_srt(args.japanese)
    if len(english) != len(japanese) or any(
        (en_n, en_time) != (ja_n, ja_time)
        for (en_n, en_time, _), (ja_n, ja_time, _) in zip(english, japanese)
    ):
        raise SystemExit("English/Japanese cue numbers or timestamps differ; refusing review")
    print(f"Verified matching original files: {len(english)} cues", flush=True)
    if args.validate_only:
        print("Validation-only passed. No model called.", flush=True)
        return 0
    workdir = args.workdir
    workdir.mkdir(parents=True, exist_ok=True)
    with (workdir / ".run.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit("Another reviewer is already running in this workdir")
        manifest = {
            "english_sha256": digest(args.english),
            "japanese_sha256": digest(args.japanese),
            "model": args.model, "batch_size": args.batch_size,
            "prompt_revision": PROMPT_REVISION,
        }
        mf = workdir / "manifest.json"
        if mf.exists():
            if json.loads(mf.read_text(encoding="utf-8")) != manifest:
                raise SystemExit("Existing review workdir belongs to different inputs/configuration")
        else:
            atomic_write(mf, json.dumps(manifest, indent=2) + "\n")
        count = (len(english) + args.batch_size - 1) // args.batch_size
        print(f"Reviewing {count} batches with {args.model}; unchanged translator", flush=True)
        results = []
        for index in range(count):
            lo = index * args.batch_size
            hi = min(len(english), lo + args.batch_size)
            name = f"batch-{index+1:03d}"
            record_file = workdir / f"{name}.json"
            if record_file.exists():
                record = json.loads(record_file.read_text(encoding="utf-8"))
                if record.get("batch") != index+1:
                    raise SystemExit(f"Mismatched saved batch: {record_file}")
                if record.get("status") == "failed":
                    print(f"[{index+1}/{count}] Recovering saved failed review of {lo+1}–{hi}", flush=True)
                    record = salvage_saved_failed(
                        workdir, name, record, english, japanese, lo, hi
                    )
                else:
                    print(f"[{index+1}/{count}] Reusing saved review of {lo+1}–{hi}", flush=True)
            else:
                print(f"[{index+1}/{count}] Reviewing cues {english[lo][0]}–{english[hi-1][0]}", flush=True)
                q = prompt(english, japanese, lo, hi)
                started = time.monotonic()
                record = {"batch": index+1, "first_cue": english[lo][0],
                          "last_cue": english[hi-1][0], "status": "failed", "edits": []}
                for attempt in range(1, 3):
                    raw_path = workdir / f"{name}.attempt-{attempt}.txt"
                    if raw_path.exists():
                        raw = raw_path.read_text(encoding="utf-8")
                        finish_reason = "stop"
                    else:
                        try:
                            raw, finish_reason = call_ollama(args.ollama, args.model, q)
                        except (urllib.error.URLError, TimeoutError, OSError) as exc:
                            raise SystemExit(f"Ollama unavailable at batch {index+1}: {exc}") from exc
                        atomic_write(raw_path, raw)
                    try:
                        if finish_reason != "stop":
                            raise ValueError(f"Model returned {finish_reason!r}, not stop")
                        edits, ignored = parse_proposals(raw, english, japanese, lo, hi)
                    except (json.JSONDecodeError, ValueError, TypeError) as exc:
                        record["error"] = str(exc)
                        print(f"  Attempt {attempt} rejected: {exc}", flush=True)
                        continue
                    record["status"] = "warning" if ignored else "ok"
                    record["edits"] = edits
                    record["ignored_proposals"] = ignored
                    record.pop("error", None)
                    break
                record["elapsed_seconds"] = round(time.monotonic()-started, 1)
                atomic_write(record_file, json.dumps(record, ensure_ascii=False, indent=2)+"\n")
                print(f"  {record['status']}: {len(record['edits'])} proposed edits; {record['elapsed_seconds']}s", flush=True)
            results.append(record)
        complete = all(r["status"] in ("ok", "warning") for r in results)
        summary = save_outputs(workdir, english, japanese, results, complete)
        print("\n=== REVIEW SUMMARY ===", flush=True)
        print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
        if not complete:
            print("Some batches failed format validation; outputs labelled PARTIAL, not ready.", flush=True)
            return 2
        print("Independent pilot complete. Candidate is NOT published.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
