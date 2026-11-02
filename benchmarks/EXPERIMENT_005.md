# Experiment 005: new-model EN→JA subtitle sweep

**PRE-REGISTERED; NOT RUN ON THE OPTIPLEX.** Owner explicitly approved systematically testing all viable new 2026 model candidates. This is a screening study, NOT a demonstration of 8/10 quality and NOT a reason to alter the live translation worker.

## Fixed, unseen source

Primate source job `primate-2026-1080p-amzn-web--ad1c564197`, SHA-256 `8967cfea3f6552c0a6b1645da13e0d79e62be2decb95c02c653e6a345c3b645a`. Eight *consecutive 8-cue blocks* centered at **91, 127, 175, 235, 303, 343, 543, 691** (64 total). The code rejects altered source, missing/overlapping windows and every cue used in Benchmarks 001–004. All model arms receive identical English/timecodes. This sample is from a single film, so it does not establish library generality; final viewing and a second film should follow.

## Arms and native inference

| Arm | Model | Native prompting and format | Hardware/runtime note |
|---|---|---|---|
| `tuned` | Already installed `hf.co/17slever17/translate-gemma-4-sub-e4b-GGUF:Q4_K_XL`, ID `9ccfc3b07081` | Benchmark 002's native CURRENT_SOURCE/previous successful cue pairs, temperature 0 | Control; known 6 GB operation |
| `cat33_final` | **Final** `cyberagent/CAT-Translate-3.3b`, exact HuggingFace SHA pinned at run | Official single user English→Japanese instruction + Sarashina 2.2 chat template; greedy, 512 output tokens | No final GGUF verified. Isolated Transformers, torch and bitsandbytes **NF4 4-bit**, fp16 compute; NOT equivalent to GGUF Q4 |
| `cat7` | Final-source `hf.co/mradermacher/CAT-Translate-7b-GGUF:Q4_K_M` | Official CAT user English→Japanese instruction and model chat template; sampling defaults retained | Q4 GGUF ~4.6 GB, tight on 6 GB GPU |
| `hy7` | Official `hf.co/tencent/Hy-MT2-7B-GGUF:Q4_K_M` | Official English request to translate into Japanese, temp .7/top_p .6/top_k 20/repeat_penalty 1.05 | ~4.62 GB Q4, author documents **STQ-kernel GGUF dependency**; if unsupported by installed Ollama, mark BLOCKED, do not mislabel results |
| `google12` | Official `translategemma:12b`, Gemma3 Q4_K_M | Google's original English(en)→Japanese(ja) single-user prompt with TWO blank lines before source; no decoding overrides | ~8.1 GB, **RAM/CPU offload required** on 6 GB VRAM; may be slow |

Model cards: [CAT final 3.3B](https://huggingface.co/cyberagent/CAT-Translate-3.3b), [CAT final 7B](https://huggingface.co/cyberagent/CAT-Translate-7b), [CAT7 Q4](https://huggingface.co/mradermacher/CAT-Translate-7b-GGUF), [Hy7 official GGUF](https://huggingface.co/tencent/Hy-MT2-7B-GGUF), [Google 12B](https://ollama.com/library/translategemma:12b), [tuned E4B](https://huggingface.co/17slever17/translate-gemma-4-sub-e4b-GGUF).

**Historical distinction:** previously tested `kaelri/hy-mt2:1.8b` was Japanese→English backtranslation QA, not the new HY 7B EN→JA arm. Previously failed official Google TranslateGemma **4B**, not 12B. Do not substitute the publicly available **CAT 3.3B-beta GGUF** for the actual final CAT 3.3B weights.

## Metrics, quality scoring, and scientific caveats

Each arm translates 64 identical English cues, giving **up to 320 new outputs**. Per-arm private create-only JSON records source hash, HF revision/Ollama ID, architecture/quant, model parameters/template hash, source and code hashes, cue coverage, Japanese validator results, obvious formatting artifacts, per-cue wall time, Ollama token/evaluation timing where available, median Japanese characters/sec and >14 chars/sec warnings. **Valid Japanese is not necessarily accurate Japanese.** Backend, prompt length, quantization, load cost and default sampling differ; this compares viable **model-native workflows**, not parameter count in isolation. HY uses the manufacturer's stochastic settings so a single run is a screening result, not a confidence interval.

**Blind human scoring** via `tools/blind_model_sweep_005.py`: per cue randomly permuted A–E candidates, a separate private identity key and 10-point rubric: (1) semantic fidelity 0–4 (meaning, negation, actors, tense, idioms), (2) tone and unsanitized adult speech 0–2 (profanity, sex, violence, threats, sarcasm), (3) natural Japanese 0–2, (4) subtitle readability at original timing 0–2. Record **critical errors independently** (reversal, missing speaker, invented facts, sanitized jokes/threats, dropped negation, unreadable density). Reviewers should not see the identity key until initial grading. Have a Japanese-speaking household viewer watch a continuous 10–15-minute selection of the finalist before claiming actual 8/10 watchability.

## Owner-side run, after merge

```bash
cd ~/Downloads/bruiser-subhub-repo
git pull --ff-only
bash tools/run_model_sweep_005.sh optiplex@100.121.156.34 all
```

The `all` command includes the large 12B CPU-offload arm and **new isolated final CAT3.3B CUDA venv**, and may consume **well over 25 GB of download/cache disk** in total. `small` omits 12B; individual `cat33`, `tuned`, `cat7`, `hy7`, `google12` arms are supported. Confirm GPU is not needed for gaming/other AI. It verifies the frozen source **before downloads**; pulls specific weights only when needed, never replaces installed models, does not upgrade the SubHub interpreter, and holds existing worker locks during GPU inference. Results are per-arm private JSON files in an owner-only Downloads directory. If a model fails, it is labeled BLOCKED or INCOMPLETE; other arms continue. No queue, SQLite checkpoint, SRT, movie, existing Japanese subtitle or live service is modified.

After complete results exist, create a blind review pack (the runner can do this automatically):

```bash
python3 tools/blind_model_sweep_005.py /path/to/private/model-sweep-005-*.json --out /path/to/private/blind.json --key /path/to/private/blind-key.json
```

Keep full text private and commit **only summarized metrics, blinded scores, paraphrased errors and decision** to RUN_LEDGER. One-film risk-enriched benchmarking is not a substitute for movie-length viewing.

## Results

**PENDING.** Synthetic CI can only prove orchestration, never actual compatibility or Japanese quality.
