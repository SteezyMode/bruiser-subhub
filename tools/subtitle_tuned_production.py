#!/usr/bin/env python3
"""Production EN->JA subtitle inference profile. Subtitle-model ONLY.

Authoritative documented choice and deployment: docs/PRODUCTION_TRANSLATION_MODEL.md
No generic Gemma fallback. No batched JSON prompt. One CURRENT_SOURCE per call.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time
from urllib.request import Request, urlopen

MODEL = "hf.co/17slever17/translate-gemma-4-sub-e4b-GGUF:Q4_K_XL"
MODEL_ID_PREFIX = "9ccfc3b07081"
MODEL_CARD = "https://huggingface.co/17slever17/translate-gemma-4-sub-e4b-GGUF"
NUM_CTX = 1344
NUM_PREDICT = 256
TEMPERATURE = 0
PREVIOUS_PAIRS = 1
OLLAMA = "http://127.0.0.1:11434"
SYSTEM = (
    "TASK: Translate English subtitles into Japanese.\n"
    "STYLE: neutral.\n"
    "Translate only CURRENT_SOURCE. PREVIOUS_SOURCE and PREVIOUS_TRANSLATION "
    "are context only. Preserve meaning, tone, slang, profanity, uncertainty, "
    "repetitions and incomplete speech. Return only the final translation "
    "without labels or commentary."
)
PROFILE = {
    "schema": 1,
    "model": MODEL,
    "expected_model_id_prefix": MODEL_ID_PREFIX,
    "system_sha256": hashlib.sha256(SYSTEM.encode("utf-8")).hexdigest(),
    "num_ctx": NUM_CTX,
    "num_predict": NUM_PREDICT,
    "temperature": TEMPERATURE,
    "previous_pairs": PREVIOUS_PAIRS,
    "interface": "ollama_chat_current_source_one_cue",
}


def messages(current, previous=None):
    if not isinstance(current, str) or not current.strip():
        raise ValueError("Empty current source subtitle")
    segments = []
    if previous is not None:
        english, japanese = previous
        if not english.strip() or not japanese.strip():
            raise ValueError("Incomplete previous source/translation context")
        segments.extend((
            "[PREVIOUS_SOURCE]\n" + english,
            "[PREVIOUS_TRANSLATION]\n" + japanese,
        ))
    segments.append("[CURRENT_SOURCE]\n" + current)
    return [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": "\n\n".join(segments)},
    ]


def api(endpoint, body=None, timeout=15, opener=urlopen):
    if body is None:
        req = Request(OLLAMA + endpoint)
    else:
        req = Request(
            OLLAMA + endpoint,
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
    with opener(req, timeout=timeout) as res:
        obj = json.load(res)
    if not isinstance(obj, dict):
        raise RuntimeError("Unexpected Ollama response")
    return obj


def translation(english, previous=None, post=api):
    payload = {
        "model": MODEL,
        "messages": messages(english, previous),
        "stream": False,
        "think": False,
        "keep_alive": "5m",
        "options": {
            "temperature": TEMPERATURE,
            "num_ctx": NUM_CTX,
            "num_predict": NUM_PREDICT,
        },
    }
    result = post("/api/chat", payload, timeout=180)
    if result.get("done_reason") == "length":
        raise RuntimeError("Subtitle model output truncated")
    answered_model = result.get("model")
    if answered_model and answered_model != MODEL:
        raise RuntimeError("Ollama response model identity mismatch")
    answer = (result.get("message") or {}).get("content")
    if not isinstance(answer, str) or not answer.strip():
        raise RuntimeError("Subtitle model returned empty text")
    return answer.strip()


def model_preflight(post=api):
    """Check installed fingerprint, Ollama template, and complete GPU residency.

    One tiny non-media chat call warms the exact model. Abort before any cue
    checkpoints when the GPU cannot fit the model or another model is resident.
    """
    models = post("/api/tags").get("models") or []
    record = next((m for m in models if m.get("name") == MODEL), None)
    if record is None:
        raise RuntimeError("Required subtitle-tuned model is NOT installed: " + MODEL)
    digest = str(record.get("digest") or "")
    if not digest.startswith(MODEL_ID_PREFIX):
        raise RuntimeError("Wrong subtitle model digest; expected " + MODEL_ID_PREFIX)
    info = post("/api/show", {"model": MODEL}, timeout=25)
    detail = info.get("details") or {}
    if detail.get("family") != "gemma4":
        raise RuntimeError("Unexpected model family, expected gemma4")
    template = info.get("template")
    if not isinstance(template, str) or not template.strip():
        raise RuntimeError("Installed Ollama chat template missing; no fallback")
    active = post("/api/ps").get("models") or []
    competitors = [str(m.get("name")) for m in active if m.get("name") != MODEL]
    if competitors:
        raise RuntimeError("Other Ollama model resident: " + ", ".join(competitors[:3])
                           + ". Stop it only when idle before retrying.")
    if not any(m.get("name") == MODEL for m in active):
        # No job-specific source is transmitted or checkpointed by this warmup.
        sample = translation("Good morning.", post=post)
        if not any("\u3040" <= ch <= "\u30ff" or
                   "\u3400" <= ch <= "\u9fff" for ch in sample):
            raise RuntimeError("Subtitle-native model warmup did not produce Japanese")
    active = post("/api/ps").get("models") or []
    running = next((m for m in active if m.get("name") == MODEL), None)
    if running is None:
        raise RuntimeError("Subtitle model not resident after warmup")
    size = int(running.get("size") or 0)
    vram = int(running.get("size_vram") or 0)
    if size <= 0 or vram <= 0 or vram / size < 0.995:
        raise RuntimeError(
            "Subtitle model not fully GPU-resident: size_vram="
            + str(vram) + " size=" + str(size)
        )
    out = {
        "model": MODEL, "model_id": digest[:12],
        "family": detail.get("family"),
        "reported_quantization": detail.get("quantization_level"),
        "template_sha256": hashlib.sha256(template.encode()).hexdigest(),
        "gpu_resident_pct": round(100.0 * vram / size, 1),
        "context": NUM_CTX, "max_output_tokens": NUM_PREDICT,
    }
    print("SUBTITLE_MODEL_PREFLIGHT", json.dumps(out, sort_keys=True),
          flush=True)
    return out


def assert_job_profile(root, job, completed):
    """No silent resuming of earlier generic-model JA translations.

    The private profile file is create-only and tied to the source hash. All
    new translation jobs must be zero-progress before a profile is created.
    """
    root = Path(root)
    target_dir = root / "model-profiles"
    target = target_dir / (str(job["id"]) + ".json")
    if target_dir.is_symlink() or target.is_symlink():
        raise RuntimeError("Unsafe model profile symlink")
    expected = dict(PROFILE, job_id=str(job["id"]),
                    source_sha=str(job["source_sha"]))
    if target.exists():
        if not target.is_file():
            raise RuntimeError("Existing model profile is not a regular file")
        got = json.loads(target.read_text(encoding="utf-8"))
        if got != expected:
            raise RuntimeError("Mixed-model job checkpoint profile; refusing continuation")
        return target
    if completed:
        raise RuntimeError(
            "Existing Japanese cue checkpoints lack a pinned subtitle-model "
            "profile; refusing to mix general and subtitle-tuned translations"
        )
    if not target_dir.exists():
        target_dir.mkdir(mode=0o700)
    if target_dir.stat().st_mode & 0o077:
        raise RuntimeError("Model profile directory is not private")
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                 getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as out:
        json.dump(expected, out, indent=2, sort_keys=True)
        out.write("\n")
        out.flush()
        os.fsync(out.fileno())
    print("SUBTITLE_MODEL_PROFILE_PINNED", target.name, flush=True)
    return target


def translate_selected(selected, full_rows, post=api):
    """Return translations for exact requested cue IDs, never the context cues.

    A failed individual model call is left unfilled so native SubHub checkpoint
    retries can handle that cue. No invented or generic-model fallback.
    """
    import service
    by_id = {int(row["cue_id"]): row for row in full_rows}
    result = {}
    for row in selected:
        cue_id = int(row["cue_id"])
        previous = None
        prior = by_id.get(cue_id - 1)
        if prior is not None:
            prior_ja = result.get(str(cue_id - 1)) or prior["japanese"]
            if isinstance(prior_ja, str) and prior_ja.strip():
                previous = (prior["english"], prior_ja)
        try:
            ja = translation(row["english"], previous, post=post)
            if service.acceptable_ja(ja, row["english"]):
                result[str(cue_id)] = ja
            else:
                print("NATIVE_CUE_VALIDATION_HELD", cue_id, flush=True)
        except (RuntimeError, ValueError, OSError, TimeoutError) as exc:
            print("NATIVE_CUE_HELD", cue_id, type(exc).__name__, flush=True)
    return result


def make_translator(store, job):
    """Pass this callable to main.run(..., translator=...) under native locks."""
    def call(base, selected, memory):
        # No approved-memory prompt injected: obey the author's prompt contract.
        return translate_selected(selected, store.rows(job["id"]))
    return call


def self_test():
    x = messages("No.", ("What?", "何？"))
    assert x[0]["content"].startswith("TASK: Translate English subtitles into Japanese.")
    assert x[0]["content"].find("STYLE: neutral.") > 0
    assert "[PREVIOUS_SOURCE]\nWhat?" in x[1]["content"]
    assert "[PREVIOUS_TRANSLATION]\n何？" in x[1]["content"]
    assert x[1]["content"].endswith("[CURRENT_SOURCE]\nNo.")
    assert "PREVIOUS_SOURCE" not in messages("No.")[1]["content"]
    hits = []
    def fake_post(path, body, timeout=0):
        hits.append((path, body))
        return {"message": {"content": "いいえ。"}, "done_reason": "stop"}
    assert translation("No.", post=fake_post) == "いいえ。"
    path, body = hits[0]
    assert path == "/api/chat" and body["model"] == MODEL
    assert body["options"] == {"temperature": 0, "num_ctx": 1344,
                                "num_predict": 256}
    assert body["stream"] is False and body["think"] is False
    print("SELF-TEST PASSED: exact tuned model, native chat contract, "
          "one-cue translation, no live inference or state changes")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--preflight", action="store_true",
                        help="inspect installed model and warm it on GPU, no media access")
    args = parser.parse_args()
    if args.self_test:
        self_test()
    elif args.preflight:
        model_preflight()
    else:
        parser.print_help()
