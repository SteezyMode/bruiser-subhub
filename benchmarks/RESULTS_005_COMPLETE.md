# Benchmark 005 — finalized technical results (2026-11-02)

**STATUS: ALL FIVE REGISTERED MODEL ARMS HAVE REAL RUN RESULTS. Quality ranking remains UNDECIDED.** This report closes the *Primate* 64-cue engineering benchmark and explicitly **does not select a translation model**. Future language-quality testing is governed by [PROTOCOL_006_INDEPENDENT_HOLDOUT.md](PROTOCOL_006_INDEPENDENT_HOLDOUT.md), with new titles/scenes, pre-frozen model/prompt selection, and blinded native Japanese viewing. Earlier partial reports are preserved for provenance.

## Final run: official FINAL CyberAgent CAT-Translate 3.3B

Owner uploaded private `model-sweep-005-cat33-final-20261102T031344Z.json`, `cat33-run(2).log`, `STATUS(3).txt` on Nov 2 JST. Inference finished at `2026-11-02T03:17:57.374140+00:00`. Source job hash: `8967cfea3f6552c0a6b1645da13e0d79e62be2decb95c02c653e6a345c3b645a`; 64 cue IDs match the preregistered 8x8 set (87–94, 123–130, 171–178, 231–238, 299–306, 339–346, 539–546, 687–694) used by previous Benchmark 005 arms. No private EN/JA dialogue was uploaded to public GitHub.

- Exact model: `cyberagent/CAT-Translate-3.3b`, Hugging Face revision **`47e382331d005acd54a42cdf088a76aa88788e0c`**; this is FINAL official HF weights, **not the older beta GGUF**.
- Engine: CUDA `torch 2.9.0+cu128`, `transformers 4.57.3`, `accelerate 1.12.0`, `bitsandbytes 0.48.2`, `huggingface_hub 0.36.0`, `sentencepiece 0.2.2`, `protobuf 6.33.6`, 4bit bitsandbytes **NF4** (`float16` compute). Generator `do_sample=false`, `max_new_tokens=512`, official CAT model chat-template translation request. Pin this exact manifest and checkpoint if comparing future runtime changes.
- Observed free GPU memory **5803 MiB** in shell preflight, CUDA self-report `5,997,068,288` bytes free and `6,088,359,936` total. `ollama ps` reported no resident models. The model downloaded two files (progress display ~184 seconds) and loaded two checkpoint shards (~6.36 seconds); **model-download/load cost excluded** from cue wall time.
- **64/64 attempted, 64/64 structurally accepted, 0 failed model calls, 0 detected format warnings, 1 cue above 14 Japanese chars/sec, median 6.8 chars/sec, sum of 64 per-cue call times 28.27 seconds**, maximum individual cue call time 0.96s. All 64 private output strings are present; no obvious assistant-role leakage by a simple scan.
- Important honest warning: Transformers emitted **`attention_mask is not set ... pad token is same as eos token`** at first inference. The script did not explicitly supply attention masks. This is **NOT a proven wrong translation**, but is a **recorded protocol defect** that must be corrected and frozen before clean Experiment 006 (without retroactively changing Benchmark 005 outputs). Do not claim fully production-hardened runtime from 64 successful responses.
- Exploratory English/JA spot-check on already-familiar *Primate* lines still shows literal interpretations of *hot* (attractiveness), *shit-faced* (drunkenness), and *call* (telephone contact). These demonstrate that broad `acceptable_ja` can pass substantive meaning/register errors. **They are NOT blind, independent native-speaker ratings.** No 10-point quality score or final CAT-vs-other ranking assigned.

## All five 005 model workflows, operational results ONLY

| Arm | Returned/structurally valid | Format/runtime notes | Median JA chars/sec | >14 chars/sec | Sum cue call time |
|---|---|---|---:|---:|---:|
| FINAL CAT-Translate 3.3B, NF4 HF Transformers | **64/64** | 0 failed calls, 0 format flags; tokenizer deps fixed; attention-mask warning logged | **6.8** | **1** | **28.27 sec** |
| 17slever17 tuned Gemma4 E4B GGUF | **64/64** | Exact model pinned; Q4_K_XL tag but Ollama Q4_K_M reported | **6.6** | **0** | **61.98 sec** |
| Tencent Hy-MT2 7B official GGUF Q4 | **64/64** | 0 errors/format flags | **7.45** | **1** | **81.96 sec** |
| CyberAgent CAT-Translate 7B third-party GGUF Q4 | **59/64** | 2 generation length errors, role-template leakage in 16 outputs; must verify author's special 7B chat template | **10.05** | **21** | **81.83 sec** |
| Google TranslateGemma 12B official GGUF Q4 | **64/64** | Runs with CPU/RAM offload on 6GB GPU | **8.95** | **6** | **256.92 sec** |

**Do not treat speed as a clean quality comparison.** The CAT3.3 run uses HF/bitsandbytes rather than Ollama; cold model downloads, model-loading, total GPU/CPU power, warmed caches, batching and sampling differ. These are recorded as system usability evidence. CAT3.3's 28.27s does not include its first-time ~3-minute model download. Speed can be compared operationally only after equal warm-start/background conditions.

## Decision and no-repeat contract

1. **Benchmark 005 is CLOSED FOR MODEL INFERENCE.** Five registered arms have been attempted/completed as stated; all models' existing private results remain untouched. No more attempts to prove a quality winner with the same 64 *Primate* cues.
2. **Revoke previous 'tuned beats HY 26–15' as final-model selection evidence.** That was one assistant's editorial preference on familiar lines, not independent native Japanese viewer grading. Retain only as exploratory internal observations. Likewise no new CAT quality ranking from the same text.
3. Candidate list for *clean* Benchmark 006 can include these five plus smaller tuned Gemma4 E2B, official Hy-MT2 1.8B, Index-Translate 2B, original untuned Gemma4 E4B and previously used Google TranslateGemma 4B. Require exact model-native prompt, digest, independent NEW titles and balanced blind playback for valid language ranking.
4. **Next operation is a read-only eligible-source inventory/selection**, not another model diagnostic. Pick at least three fresh unrelated titles plus an unseen confirmation title; lock deterministic continuous scenes and source hashes before any model outputs are viewed. Do not select from familiar *Primate* examples or old prompts.
5. Evaluate natural localization with native Japanese viewing: comprehension/pace/character voice, **allow sensible condensation/rewording**, and penalize plot-breaking rather than deviations from literal wording. If two models are essentially equivalent, choose simpler/faster single-pass default. Consider optional selective multi-model only if a separately validated semantic trigger has demonstrated actual net improvement.
6. No production translator, human subtitle SRT, existing checkpoints, media or queue was modified by 005. The goal remains reliable Japanese subtitle tracks in Jellyfin, not benchmark scores.

**Final 005 state: ALL five model arms measured, translated subtitle watchability not independently adjudicated.**
