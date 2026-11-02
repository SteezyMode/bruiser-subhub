# Translation decision record — 2026-11-02

**Status: provisional design decision, not a production deployment.** This record exists to prevent rediscovering the same model, prompt, runtime or pipeline conclusions in future chats. After every real new model result, update this file and RUN_LEDGER, rather than proposing the same experiment again. Full numeric run evidence and limitations: [RESULTS_005_TUNED_HY_PAIRED.md](RESULTS_005_TUNED_HY_PAIRED.md), [RESULTS_005_PARTIAL.md](RESULTS_005_PARTIAL.md), [RESULTS_004.md](RESULTS_004.md), [EXPERIMENT_005.md](EXPERIMENT_005.md).

## Current conclusion — default SINGLE PASS, secondary model only on demonstrated benefit

**Provisional primary for NEW jobs:** 17slever17 subtitle-tuned Gemma4 E4B native current-cue + bounded previous dialogue prompt, pinned Ollama model ID `9ccfc3b07081`. This remains a benchmark decision and **has NOT been deployed into live SubHub**. On the same newly frozen 64 English subtitle cues, the tuned model was favored by a SINGLE assistant in **26**, HY-MT2 7B in **15**, **23 ties**; all 128 translations were structurally valid, 0 recognized format issues. Tuned produced median **6.60 JA chars/sec** vs HY's **7.45**, **0 vs 1 over 14**, and measured **61.98 vs 81.96 total per-cue wall seconds**. Different native prompts/generation settings mean it is not a pure controlled model architecture comparison.

**Hy-MT2 7B is a legitimate independent alternate, NOT proven to be a universally beneficial second pass.** It got some critical details right that tuned missed (social slang about attractiveness, telephoning somebody, names), but also made meaning/register errors. Critically, BOTH mistranslated the same physical-grip action. Running Hy on every cue therefore increases compute and creates a difficult **which output do we choose?** arbitration problem. A naive two-model vote, 'longer answer wins', unverified model self-grading, or blindly using the second answer must NOT be adopted.

**Current deployment direction:** one native tuned-model inference for ordinary new-job subtitles, existing source/checkpoint safety, and **NON-DESTRUCTIVE review flags** for verifiable mechanical problems (missing/empty Japanese, role labels, repeated template text, obvious truncation, extreme reading speed, known non-Japanese output). If reliable **semantic** uncertainty detection is demonstrated on an independent sample, a future opt-in **selective** HY check can process only those candidates. Automatic HY fallback is **not justified yet**, because the observed critical meaning errors do not necessarily trigger mechanical flags. No always-on full-library two-model pipeline.

## What the results DO and DO NOT establish

| Evidence | Established | Not established |
|---|---|---|
| Benchmarks 002–004 | Native formatted subtitle model corrects prior tuned Gemma batch-JSON corruption, improves several vulgar/idiomatic lines; Google official TranslateGemma **4B** is more formal and makes material semantic errors on fresh 16-cue pairs | Any native-Japanese viewer rating, broad-library generality |
| Benchmark 005 new frozen 64-cue paired tuned v HY7 | 64/64 per model, both structurally valid, fewer dense lines/shorter and modest assistant preference edge for tuned, HY fixes specific errors | Statistical or native-speaker superiority, improved results on a *second film*, controlled equal-context comparison |
| Benchmark 005 CAT7 GGUF | Its current Q4/Ollama interface produced 16/64 role-labelled/contaminated outputs and 2 generation cap failures; coarse validator missed much | That the FINAL CAT7 weights inherently translate poorly when run under the **developer's correct special 7B chat template** |
| Benchmark 005 Google TranslateGemma **12B** | Runs with substantial CPU offload and is much slower; generally formal Japanese | It is categorically bad for all films |
| Benchmark 005 CAT3.3 final | Python 3.12/CUDA source preflight works; final-model test previously blocked by RAM; NEW log confirms 5.7GiB free and **tokenizer imports missing** before any model translation | Real EN→JA quality or inference speed of final 3.3B |

Scores of 26/15/23 are **single-assistant cue-level preferences, not the original full 4+2+2+2 ten-point blinded rubric, not an independent native-Japanese review, and not a '26 wins proves significance' claim**. All existing data are from ONE Primate SRT with purposely difficult snippets; memorizing failed cue IDs and changing prompts specifically for them would overfit. New candidate testing must retain source hashes, cue IDs, models, prompt templates, per-model output and failure logs. Movie subtitle text, private review keys and transcripts stay OUT of public GitHub.

## Known recurring engineering failures — permanently diagnosed

| Failure | Root evidence | Correct recurrence prevention |
|---|---|---|
| Native tuned E4B incorrectly 'missing/wrong quantization' | Model's TAG says `Q4_K_XL`; Ollama `/api/show` on exact ID `9ccfc3b07081` reports quant `Q4_K_M`, family `gemma4`. The benchmark rejected its tag/metadata difference | Pin exact model ID, **actual** quant metadata and family, not suffix-derived guess. Synthetic regression tests. Do NOT redownload a correct model. |
| CAT3.3 first attempt under 3 GB free VRAM | First rerun ran tuned Gemma immediately before CAT; Ollama uses keep_alive and the GPU was occupied. Specific process not recorded at failure | Run only `cat33` with read-only `ollama ps`/`nvidia-smi` before loading; never stop household workloads automatically. Model source SHA and CUDA env tested. |
| CAT3.3 second attempt tokenizer import failed, 2026-11-02 | Owner's `cat33-run(1).log`: 5803 MiB NVIDIA VRAM FREE, CUDA/source preflight pass, then `ValueError: Cannot instantiate this tokenizer from a slow version` and final `ImportError: requires protobuf` / `sentencepiece` not installed. Failed **before loading model or generating any subtitle** | `tools/cat33_requirements_005.txt` now pins **both** `sentencepiece==0.2.2` and `protobuf==6.33.6` alongside the five earlier Torch/Transformers/HF deps; CAT venv installer reads this single list. Source/env preflight NOW checks both libraries, with synthetic fail-fast tests. If NEXT failure differs, capture actual stderr and document THAT cause; don't guess. |
| CAT7 GGUF returns assistant role text/explanations | Current GGUF/Ollama adapter yielded contaminated replies; developer says 7B needs distinct chat template | Do not 'clean' gross role leakage into approved Japanese; verify template compatibility under model author's instructions if CAT7 merits retry. No blind mass rerun of known bad wrapper. |
| Generic multi-subtitle JSON prompt harmed tuned subtitle model | Early 001 benchmark showed JSON/role contamination, compared with 002 native one-cue format | Use each model's documented native interface. Do not revive batch JSON for convenience without new accuracy evidence. |
| Translation validator accepts grammatical nonsense or wrong meaning | 005 CAT role leakage passed broad acceptable-JA test; both main models failed same physical-action semantics | Structural validity is NOT semantic fidelity. Keep separate structural flags and human/Japanese-viewer quality gate. Never silently publish because contains Japanese characters. |

## Experimental stopping rules and next actions

1. **Finish ONE pending CAT3.3 final run** after pinned tokenizer dependency repair in isolated venv. Use **the same frozen 64 cues**, never switch to beta weights or an easier sample. If a new runtime failure arises, preserve exact failure/log and categorize as compatibility BLOCKED; no indefinite speculative changes. Other 4 models are already complete: do not rerun them merely to generate more files.
2. Score actual CAT3.3 outputs against existing private same-cue results if it runs. **Do not choose a primary from mechanical metrics alone.** Keep a true paired fair comparison, note critical semantic errors, and record the review method (independent native viewer vs assistant).
3. Produce a **fresh, continuous 10–15-minute Japanese-only viewing sample** with chosen native single-pass candidate using original timings, separate from seven old batch-produced movies, and get native Japanese-speaking household feedback on comprehension, idiom, emotional intensity, missing speaker meaning, readable density, and watchability. Record representative failure categories and timecodes (private).
4. Test on a **second independent film/episode** before whole-library rollout. Unless significant new errors are discovered, **STOP model and prompt carousel** and integrate the chosen profile into guarded new-job-only translation, preserving all approved existing subtitles.
5. If genuine persistent meaning errors remain, design **ONE controlled selective HY fallback trial** with explicit trigger definition, identical fresh cues, semantic error counts before/after, introduction of new errors, runtime/VRAM impact and acceptance threshold agreed before inference. If improvement is not consistent, RETAIN single pass. Full mandatory multi-model/multi-tier strategy is not selected.

## Change-control contract for future work

- Never present research/PR/CI as real server inference, or an assistant model preference as a measured native-Japanese viewer score.
- Every model trial needs a frozen source SHA, fixed IDs, model weights/digest, exact native prompt, environment, timing and **private** raw results.
- Every failure needs observed stderr and a **specific permanent prevention** (preflight, packaging, contract test), not another undocumented terminal workaround.
- Every revised decision needs an explicit `DECISION_RECORD` update and RUN_LEDGER line. Do not propose previously completed trial as if untried.
- No automatic destructive changes to production subtitles, movie files, queue, SQLite checkpoint, active workers or other OptiPlex household services.

**Current system is not yet at the scale milestone.** The real finish line remains selecting a movie in Jellyfin and finding an accurate, enjoyable JA subtitle without babysitting. Commits and diagnostics are means, not the deliverable.
