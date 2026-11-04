#!/usr/bin/env python3
"""Attachment E4B 24-cue A/B: unchanged raw HTML vs presentation-tag-free English.

The only experimental variable is the input SRT's HTML presentation tags.
Model, author-native system/user format, context count, temperature, n_ctx
and max tokens stay the same. No media or subtitle writes. Results PRIVATE.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
from urllib.parse import quote

HOME = Path.home()
HOST = HOME / "bruiser-pilot/subhub1"
CONTROL = HOME / "bruiser-pilot/subhub-control"
STATE = HOME / "bruiser-pilot/attachment-e4b-rerun"
JOB = "daily-attachment-e4b-review-e953178a24b7"
OUTPUT = STATE / "markup-ab"
CUES = (25,65,87,95,126,140,180,280,367,420,502,530,
        620,733,738,750,780,930,1027,1074,1082,1138,1265,1275)
# ONLY presentation tags, never arbitrary angle-bracketed spoken dialogue.
PRESENTATION = re.compile(r"</?(?:font|i|b|u)(?:\s+[^<>]*)?>", re.IGNORECASE)
OTHER_TAG = re.compile(r"</?[A-Za-z][^<>]*>")
EXPECTED_MODEL = "hf.co/17slever17/translate-gemma-4-sub-e4b-GGUF:Q4_K_XL"
EXPECTED_ID = "9ccfc3b07081"

if HOST.is_dir():
    sys.path.insert(0, str(HOST))
if CONTROL.is_dir():
    sys.path.insert(0, str(CONTROL))

try:
    import service
    import main
    import subtitle_tuned_production as tuned
except ModuleNotFoundError:
    import service
    import main
    from tools import subtitle_tuned_production as tuned


def clean_presentation(text):
    """Remove HTML styling, preserve exact dialogue, speaker lines and wording."""
    if not isinstance(text, str):
        raise TypeError("Expected subtitle text")
    cleaned = PRESENTATION.sub("", text)
    if OTHER_TAG.search(cleaned):
        raise ValueError("Unexpected HTML-like tag: refusing unchecked stripping")
    return cleaned


def input_pair(current, previous, clean):
    """Same one previous model-produced JA pair in both experimental arms."""
    en = clean_presentation(current) if clean else current
    context = None
    if previous is not None:
        prev_en, prev_ja = previous
        context = (clean_presentation(prev_en) if clean else prev_en, prev_ja)
    return en, context


def config():
    if service.GEMMA != EXPECTED_MODEL or tuned.MODEL != EXPECTED_MODEL:
        raise RuntimeError("Wrong live or benchmark model")
    if tuned.MODEL_ID_PREFIX != EXPECTED_ID:
        raise RuntimeError("Wrong installed tuned-model digest")
    if tuned.NUM_CTX != 1344 or tuned.NUM_PREDICT != 256:
        raise RuntimeError("Unexpected model-card context/output settings")
    if tuned.TEMPERATURE != 0 or tuned.PREVIOUS_PAIRS != 1:
        raise RuntimeError("Unexpected model-card temperature/history settings")


def original_cues(root=STATE):
    """Read only the complete source+Japanese of the verified E4B Attachment job."""
    db = root / "jobs.sqlite3"
    if not db.is_file() or db.is_symlink():
        raise RuntimeError("Attachment tuned-model checkpoint DB missing")
    uri = "file:" + quote(str(db.resolve()),safe="/") + "?mode=ro"
    with sqlite3.connect(uri, uri=True, timeout=15) as con:
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA query_only=ON")
        jobs = con.execute(
            "SELECT id,status,source_sha,source_cues,video FROM jobs").fetchall()
        if len(jobs) != 1 or jobs[0]["id"] != JOB:
            raise RuntimeError("Wrong or mixed isolated Attachment state")
        job = jobs[0]
        if job["status"] != "published" or job["source_cues"] != 1276:
            raise RuntimeError("Attachment E4B baseline is not finished")
        rows = con.execute(
            "SELECT cue_id,timing,english,japanese FROM cues "
            "WHERE job_id=? ORDER BY cue_id",(JOB,)).fetchall()
    if len(rows) != 1276 or any(
            r["japanese"] is None or not r["japanese"].strip() for r in rows):
        raise RuntimeError("Incomplete original E4B baseline")
    profile = root / "model-profiles" / (JOB + ".json")
    if not profile.is_file() or profile.is_symlink():
        raise RuntimeError("Missing original model provenance")
    pinned = json.loads(profile.read_text("utf-8"))
    if pinned.get("source_sha") != job["source_sha"] or any(
            pinned.get(k) != v for k,v in tuned.PROFILE.items()):
        raise RuntimeError("Original E4B model/prompt provenance mismatched")
    return dict(job), {int(row["cue_id"]):dict(row) for row in rows}


def ensure_private(path):
    if path.is_symlink() or (path.exists() and not path.is_dir()):
        raise RuntimeError("Unsafe scratch output path")
    path.mkdir(parents=True,mode=0o700,exist_ok=True)
    if path.stat().st_uid != os.getuid() or path.stat().st_mode & 0o077:
        raise RuntimeError("Scratch output folder not private")


def create_record(path, body):
    """Write-once, crash-resumable and refusing conflicting existing records."""
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise RuntimeError("Unsafe scratch record path")
    data = (json.dumps(body,ensure_ascii=False,sort_keys=True,indent=2)+"\n").encode()
    if path.exists():
        if path.read_bytes() != data:
            raise RuntimeError("Conflicting scratch record: "+str(path))
        return
    fd = os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY|
                 getattr(os,"O_NOFOLLOW",0),0o600)
    with os.fdopen(fd,"wb") as out:
        out.write(data)
        out.flush()
        os.fsync(out.fileno())


def trial(root=STATE, out=OUTPUT):
    config()
    job, cues = original_cues(root)
    ensure_private(out)
    ensure_private(out / "cases")
    manifest = {
        "schema": "attachment-e4b-html-presentation-ab-1",
        "job_id": JOB, "source_sha": job["source_sha"],
        "model": tuned.MODEL, "model_digest_prefix": tuned.MODEL_ID_PREFIX,
        "prompt_sha256": tuned.PROFILE["system_sha256"],
        "options": {"temperature":tuned.TEMPERATURE,
                    "num_ctx":tuned.NUM_CTX,"num_predict":tuned.NUM_PREDICT},
        "history_pairs":1, "cue_ids": list(CUES),
        "one_variable":"remove recognized HTML styling from CURRENT_SOURCE "
                       "and PREVIOUS_SOURCE only, never Japanese or other data",
    }
    create_record(out / "manifest.json",manifest)
    # Prevent concurrent active SubHub/Ollama users from changing inference
    # and protect model identity/preflight; does not touch real cue checkpoints.
    with main.lockfiles(root):
        print("HTML_AB_EXPERIMENT",len(CUES),"cues; 2 arms, fixed model/settings",
              flush=True)
        tuned.model_preflight()
        for idx, cue_id in enumerate(CUES,1):
            current = cues.get(cue_id)
            if current is None:
                raise RuntimeError("Missing selected cue")
            prev = cues.get(cue_id-1)
            context = ((prev["english"],prev["japanese"])
                       if prev is not None and prev["japanese"] else None)
            candidate = {
                "cue_id":cue_id, "timing":current["timing"],
                "english_source_markup":current["english"],
                "english_source_clean":clean_presentation(current["english"]),
                "baseline_e4b_japanese":current["japanese"],
                "previous_source":prev["english"] if context else None,
                "previous_japanese":prev["japanese"] if context else None,
            }
            if candidate["english_source_clean"] == current["english"]:
                raise RuntimeError("Selected source unexpectedly lacks formatting tags")
            for arm in ("raw","clean"):
                filename = out / "cases" / (f"{cue_id:04d}-{arm}.json")
                if filename.exists():
                    record = json.loads(filename.read_text("utf-8"))
                    if record.get("case") != candidate or record.get("arm") != arm:
                        raise RuntimeError("Existing case cannot be trusted")
                    print("AB_REUSED",f"{idx}/{len(CUES)}",cue_id,arm,flush=True)
                    continue
                main.thermal_guard(gpu_limit=82,cpu_limit=85)
                text, prev_pair = input_pair(current["english"],context,
                                              clean=arm=="clean")
                # Same author-documented Ollama /api/chat translator in BOTH
                # arms; no second model, new prompt or inference parameters.
                try:
                    answer = tuned.translation(text,previous=prev_pair)
                    record = {"case":candidate,"arm":arm,"japanese":answer,
                              "accepted":bool(service.acceptable_ja(
                                  answer,current["english"]))}
                except Exception as exc:
                    record = {"case":candidate,"arm":arm,"japanese":None,
                              "accepted":False,"error":type(exc).__name__+
                              ": "+str(exc)[:180]}
                create_record(filename,record)
                print("AB_RESULT",f"{idx}/{len(CUES)}",cue_id,arm,
                      "accepted",record["accepted"],flush=True)
    # No publisher. Only a private pairing report for human/assistant review.
    bundle = dict(manifest,results=[])
    for cue_id in CUES:
        pair={}
        for arm in ("raw","clean"):
            p=out/"cases"/(f"{cue_id:04d}-{arm}.json")
            pair[arm]=json.loads(p.read_text("utf-8"))
        bundle["results"].append(pair)
    create_record(out/"report.json",bundle)
    print("EXPERIMENT_COMPLETE",len(CUES)*2,"calls max",
          "private_report",out/"report.json",flush=True)
    return bundle


def self_test():
    config()
    sample='<font face="Tahoma" color="#eeeeee">That <i>sounds</i> good.</font>'
    assert clean_presentation(sample)=="That sounds good."
    assert clean_presentation("A < B")=="A < B"
    assert clean_presentation("One\\nTwo")=="One\\nTwo"
    assert input_pair(sample,("foo", "フー"),True) == (
        "That sounds good.",("foo","フー"))
    assert input_pair(sample,("foo", "フー"),False) == (
        sample,("foo","フー"))
    assert len(CUES)==24 and len(set(CUES))==len(CUES)
    assert "CURRENT_SOURCE" in tuned.messages("Hello.")[1]["content"]
    print("SELF_TEST_PASSED: exact pinned E4B; remove formatting ONLY; "
          "no media DB, model or filesystem writes",flush=True)


def main_cli():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=("run","self-test"),nargs="?",
                   default="self-test")
    a=p.parse_args()
    if a.action=="self-test":
        self_test()
    else:
        trial()


if __name__=="__main__":
    try:
        main_cli()
    except Exception as exc:
        print("HTML_AB_HELD",type(exc).__name__,str(exc)[:200],
              file=sys.stderr,flush=True)
        raise SystemExit(1) from None
