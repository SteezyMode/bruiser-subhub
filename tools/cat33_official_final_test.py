#!/usr/bin/env python3
"""Clean native CAT-Translate-3.3b (FINAL, not beta) EN->JA test.

Uses official Transformers tokenizer/chat_template.jinja, exact official user
instruction, native model weights, and model generation defaults with
max_new_tokens=512 as documented. The *only* deliberate adaptation is
bitsandbytes NF4 4-bit loading to fit an RTX 3050 6 GB.

No Ollama / GGUF / custom chat template, translation rewriting, retry,
secondary model, postprocessing, subtitle publication, or Jellyfin changes.
"""
import argparse
import json
import re
import sys
import time
from pathlib import Path

MODEL_ID = "cyberagent/CAT-Translate-3.3b"
INSTRUCTION = "Translate the following English text into Japanese.\n\n"


def parse_english_srt(path):
    data = path.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
    blocks = re.split(r"\n[ \t]*\n", data.strip())
    cues = []
    for block in blocks:
        match = re.fullmatch(
            r"(\d+)\n(\d\d:\d\d:\d\d,\d{3} --> [^\n]+)\n(.+)",
            block.strip(), flags=re.DOTALL
        )
        if match is None:
            raise ValueError(f"Bad English SRT block: {block[:70]!r}")
        cues.append({"index": int(match.group(1)), "english": match.group(3)})
    if len(cues) < 150:
        raise ValueError(f"Need at least 150 subtitles to compare identical passages; got {len(cues)}")
    return cues


def sample(cues, start, count=15):
    part = cues[start - 1:start - 1 + count]
    if len(part) != count:
        raise ValueError("Insufficient cues for comparison")
    return "\n\n".join(x["english"] for x in part)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", type=Path, required=True)
    p.add_argument("--workdir", type=Path, required=True)
    args = p.parse_args()
    if not args.source.is_file():
        p.error(f"English SRT not found: {args.source}")
    args.workdir.mkdir(parents=True, exist_ok=True)
    outfile = args.workdir / "cat33-final-results.json"
    if outfile.exists():
        p.error(f"Existing test output will not be overwritten: {outfile}")
    cues = parse_english_srt(args.source)
    passages = [
        ("opening_1_15", sample(cues, 1)),
        ("opening_16_30", sample(cues, 16)),
        ("second_121_135", sample(cues, 121)),
        ("second_136_150", sample(cues, 136)),
    ]
    # Keep importing heavy dependencies until AFTER validating our inputs.
    import torch
    from huggingface_hub import snapshot_download
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA not available; refusing to accidentally run CPU translation")
    gpu = torch.cuda.get_device_properties(0)
    print(f"GPU: {gpu.name}, {gpu.total_memory / 2**30:.2f} GiB", flush=True)
    print(f"DOWNLOADING OFFICIAL FINAL WEIGHTS: {MODEL_ID} (NOT beta)", flush=True)

    # Hugging Face's ordinary resumable download, no third-party GGUF conversion.
    local = Path(snapshot_download(repo_id=MODEL_ID))
    if "beta" in str(local).lower():
        raise RuntimeError("Unexpected beta model cache directory")
    print(f"Official model snapshot: {local}", flush=True)

    tokenizer = AutoTokenizer.from_pretrained(str(local), trust_remote_code=False)
    if not tokenizer.chat_template:
        raise RuntimeError("Official tokenizer has no chat template. Refusing to guess one.")

    check = tokenizer.apply_chat_template(
        [{"role": "user", "content": INSTRUCTION + "Hello."}],
        tokenize=False, add_generation_prompt=True
    )
    if not check.startswith("<|user|>") or not check.endswith("<|assistant|>"):
        raise RuntimeError(
            f"Unexpected official chat template. Refusing to test with a guessed template: {check!r}"
        )
    print("OFFICIAL CHAT TEMPLATE VERIFIED: user + EOS + assistant generation prefix", flush=True)
    print("Native prompt format:", repr(check), flush=True)

    # Standard memory-saving loading. Do not adjust model architecture or prompt.
    quant = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.float16
    )
    print("Loading the FINAL checkpoint with standard 4-bit NF4 quantization", flush=True)
    model = AutoModelForCausalLM.from_pretrained(
        str(local),
        device_map={"": 0},
        quantization_config=quant,
        dtype=torch.float16,
        trust_remote_code=False,
    )
    model.eval()
    print("MODEL LOADED", flush=True)

    records = []
    for i, (label, english) in enumerate(passages, start=1):
        user = INSTRUCTION + english
        ids = tokenizer.apply_chat_template(
            [{"role": "user", "content": user}],
            add_generation_prompt=True, return_tensors="pt"
        ).to("cuda:0")
        prompt_count = ids.shape[-1]
        if prompt_count > 4096:
            raise RuntimeError(f"Test passage unexpectedly long: {prompt_count} input tokens")
        print(f"\n=== TEST {i}/4: {label}, input tokens={prompt_count} ===", flush=True)
        started = time.monotonic()
        with torch.inference_mode():
            output = model.generate(ids, max_new_tokens=512)
        seconds = round(time.monotonic() - started, 1)
        tokens = output[0, prompt_count:]
        answer = tokenizer.decode(tokens, skip_special_tokens=True)
        capped = len(tokens) >= 512 and int(tokens[-1]) != tokenizer.eos_token_id
        record = {
            "passage": label,
            "english": english,
            "japanese": answer,
            "elapsed_seconds": seconds,
            "output_tokens": len(tokens),
            "hit_512_token_cap": capped,
        }
        records.append(record)
        print(answer, flush=True)
        print(f"TRANSLATED: {seconds}s, {len(tokens)} tokens; hit output cap: {capped}", flush=True)
        # Checkpoint the raw answers after EACH request, not only after the entire test.
        tmp = args.workdir / "cat33-final-results.partial.json"
        tmp.write_text(json.dumps({
            "official_model": MODEL_ID,
            "model_snapshot": str(local),
            "quantization": "bitsandbytes NF4, 4-bit; float16 compute",
            "chat_template": "from official tokenizer",
            "user_prompt": INSTRUCTION + "{English passage}",
            "max_new_tokens": 512,
            "results": records,
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.rename(outfile)
    print(f"\nALL FOUR TRANSLATIONS COMPLETE. RAW REPORT: {outfile}", flush=True)
    print("Original English and every Japanese response saved; no SRT or media was edited.", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"\nCAT33 TEST FAILED: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        raise
