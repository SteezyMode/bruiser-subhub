# SubHub translation-quality experiment ledger

**Public summaries only. Private EN/JA samples and generated model outputs remain outside GitHub.** Update after a genuine measured comparison. Commit identifiers refer to GitHub source, NOT proof of live deployment.

## What was established before Benchmark 001

| Date | Experiment or observation | Verified outcome | What it did NOT establish |
|---|---|---|---|
| 2026-11-01 | Initial pilot translation (legacy batch path before fix) | Seven of ten pilot films published after targeted cue repair; read-only artifact scan found zero detectable tool/JSON contamination across 10 jobs | Reliable Japanese quality; direct comparable model baseline |
| 2026-11-01 | 80-cue risk-enriched Primate EN/JA editorial review | Several specific idiom errors, softened vulgarity, and excessive reading density; many ordinary lines understandable | Failure percentage for all 741 cues or all films |
| 2026-11-01 | Fresh Gemma e4b with `natural_8` prompt, five 8-cue windows | 40/40 results in 26.07 sec total reported model-call time (8.58/4.18/4.13/4.63/4.55 sec). Some idiom and brevity improvements | Adequate overall quality. It introduced serious errors: undirected exclamation instead of a directed insult; sex joke removed; rhetorical accusation turned into open question; speaker turn removed |
| 2026-11-01 | Read-only video/subtitle census | 13,199 video files, 4.14 TB video, 2,026 English-text+English-audio candidates, 442 detected JA, 268 OCR candidates, 4,670 missing English source, 5,764 audio unverified, 29 metadata failures | That all 2,026 can be translated immediately or that most of 5,764 are non-English |

## Benchmark 001: REAL 256-output comparison completed; see RESULTS_001.md

- Procedure and frozen design: [EXPERIMENT_001.md](EXPERIMENT_001.md).
- **Real 2-model x 2-prompt local inference finished.** Structural metrics and unblinded editorial fault analysis: [RESULTS_001.md](RESULTS_001.md). 256 outputs; no call errors; 14 recognized formatting-contaminated cues. The tuned model was given the generic batch-JSON prompt rather than its documented one-segment-with-previous-context format. **Do not conclude it is intrinsically worse.**
- No native-Japanese viewing assessment or justified numerical meaning/tone score yet. Model choice remains provisional. The official Google TranslateGemma is separate and was not evaluated.
- Optional multipass is a *testable hypothesis*, not a required design or authorized blanket expense.

### Benchmark 001 recorded result

| Model | Prompt | Accepted / 64 | Median chars/s | Model-call time | Formatting issues | Editorial score |
|---|---|---:|---:|---:|---:|---|
| Gemma 4 e4b | baseline | 64/64 | 6.25 | 45.26 s | 0 | Not independently rated |
| Gemma 4 e4b | faithful_8 | 64/64 | 6.95 | 38.63 s | 2 | Not independently rated |
| Subtitle-tuned Gemma 4 e4b | baseline | 64/64 | 6.60 | 58.15 s | 6 | Not independently rated |
| Subtitle-tuned Gemma 4 e4b | faithful_8 | 64/64 | 6.85 | 51.37 s | 6 | Not independently rated |

**Next action:** Benchmark 001 is complete, but trained tuned model did not receive its documented native prompt. Compare the installed tuned model in that format on the same difficult cues, then conduct human/native Japanese review and make a practical model/pipeline choice. Do not force multi-pass or automate a second model on all jobs without net-quality evidence. The 2,026 detected ready-source candidates are a separate queue-ingestion milestone after the quality decision.

## Benchmark 002 — COMPLETE (real local Ollama, 2026-11-02 JST); see RESULTS_002.md

**Result:** 64/64 accepted, zero recognizable format artifacts, 6 over 14 characters/sec, median 6.8 characters/sec, 56.37 model-call seconds, 64 successful calls. Unblinded qualitative review saw useful handling of threats, insults and instructions, but material slang/accusation errors and overly long fast dialogue. **Not independently rated 8/10.** Full measured report: [RESULTS_002.md](RESULTS_002.md). Its system style and context/runtime settings were chosen by us rather than a literal model-card replay. Eight within-group context gaps exceeded eight seconds.

## Historical preregistration record: Benchmark 002 (PR #16)

- Design: [EXPERIMENT_002.md](EXPERIMENT_002.md) — SAME 64 English cues as Benchmark 001, but the **already installed** tuned Gemma e4b receives the developer's native `[CURRENT_SOURCE]` with up to two prior source/translation pairs.
- One Ollama call per cue (64 calls), with no retry and no other model. Context from generated translations in the SAME eight-cue window only; no original Japanese fed into the model.
- Status: **NOT RUN on Ollama**. The synthetic test suite does not measure semantic fidelity.
- Future results must compare against Benchmark 001 on same IDs; judge meaning, idioms, profanity/sexual tone, omissions, and viewing speed before deciding whether an optional selective second pass is justified.

| Model/native method | Valid / 64 | Format flags | Median chars/s | Inference seconds | Human quality decision |
|---|---:|---:|---:|---:|---|
| Tuned Gemma e4b native previous/current prompt | Pending | Pending | Pending | Pending | Not reviewed |

## Benchmark 003 — COMPLETED, real Ollama comparison and decision

- Pre-registered design: [EXPERIMENT_003.md](EXPERIMENT_003.md); actual numeric results, interpretation and decision: **[RESULTS_003.md](RESULTS_003.md)**. User supplied private 128-result JSON (2026-11-02 JST); all dialogue/output remains private.
- 64/64 accepted in each arm, zero recognized formatting artifacts, seven >14 JA chars/sec in each, median 6.85 JA chars/sec each. Always previous: 56 contexts and 55.81 model-call seconds. Gap>8 seconds: 48 contexts and 52.57 model-call seconds.
- Eight cue contexts were suppressed by gap cutoff. **Six out of 64 candidate Japanese texts changed** (4 direct, 2 propagated); no consistent net quality gain. Both arms still mishandled colloquial slang and high-density exchanges; strict card wording degraded a past-tense denial previously handled correctly by Benchmark 002.
- **Decision: do not deploy arbitrary gap gating or keep tweaking microparameters.** Benchmark 002 remains the more promising *provisional* native single-pass version, but no real native-speaker 8/10 rating exists. No movie/subtitle/checkpoint/production service was changed by any comparison.
- **Read [COMMUNITY_RESEARCH_2026-11-02.md](COMMUNITY_RESEARCH_2026-11-02.md)** for actual model author recommendations (Q4_K_XL, compact verified speaker/glossary context, Japanese Tier 1), constraints of 6GB VRAM, and cautious anecdotal community advice.

| Arm | Valid / 64 | Format suspicions | Median JA chars/sec | Model-call time | Native viewer grade | Decision |
|---|---:|---:|---:|---:|---|---|
| Tuned E4B, strict card, immediate previous pair | 64 | 0 | 6.85 | 55.81s | Not measured | No improvement |
| Same, drop previous after >8s silence | 64 | 0 | 6.85 | 52.57s | Not measured | Do not deploy rule |

**Highest-value next task:** have the Japanese-speaking household viewer watch 10–15 minutes with only the existing machine Japanese track, record intelligibility/awkwardness/timecodes. After that, make one model/pipeline decision before resuming guarded library source extraction and queueing the 2,026 ready-source candidates. Multi-pass remains optional and must show net benefit on actual errors.

## Benchmark 004 — COMPLETE, real native-model comparison and decision (2026-11-02 JST)

- Frozen design: [EXPERIMENT_004.md](EXPERIMENT_004.md). **Real observed results: [RESULTS_004.md](RESULTS_004.md)**. Private uploaded JSON `primate-translategemma-004-20261101T165711Z.json`, generated 2026-11-02 01:59 JST, was examined; full copyrighted movie EN/JA text remains private.
- Models: official Google `translategemma:4b`, Gemma3 4.3B Q4_K_M, Ollama ID `c49d986b0764`; existing tuned Gemma4 E4B Q4_K_XL ID `9ccfc3b07081`. Both native prompts; Google official single-translation user prompt, tuned subtitle model prior-context current-cue prompt.
- 96/96 calls returned, all broad validator passes, no detected format artifacts. **Google 80**: median 9.15 JA chars/sec, 12 >14, 79.26 total model-call seconds. **New held-out 16** Google: median **9.0**, two >14, 12.99 model-call seconds; tuned native **same 16**: median **6.6**, two >14, 17.07 model-call seconds. Two models use different context and code paths; inference time is not a pure per-model speed ranking.
- **Qualitative result:** Google's output repeatedly imposed formal Japanese in casual film dialogue and made substantive errors on meaning, slang, profanity, past-tense denial and temporary absence, plus invented actions and overlong timed lines. Tuned E4B more conversational and semantically sound on most of the new held-out cues, but was NOT flawless (catchphrase, command/subject drift). No native Japanese viewer score or certified 8/10 threshold.
- **Decision:** DO NOT replace the movie translator with Google 4B or automatically use it as a critic. The already-tested **17slever17 tuned E4B under Benchmark 002's native prompt** remains the provisional choice; **this is not a production deployment**. Stop parameter-prompt microbenchmarks and get 10–15 minutes of actual Japanese-only viewing before promoting anything at scale. Multi-pass only if the viewer discovers a problem and a separate, controlled test shows net gain.
- Next engineering milestone after practical viewing: safe new-job native translation path and guarded batch intake from the previously identified 2,026 English-source candidates, preserving existing human subtitles.

| Arm | Cues | Japanese accepted | Format flags | Median JA chars/sec | >14 JA chars/sec | Human/native viewer rating |
|---|---:|---:|---:|---:|---:|---|
| Google official TranslateGemma 4B (all) | 80 | 80 | 0 | 9.15 | 12 | Not measured |
| Google 4B (held-out only) | 16 | 16 | 0 | 9.0 | 2 | Not measured |
| Tuned subtitle Gemma4 E4B (same held-out) | 16 | 16 | 0 | 6.6 | 2 | Not measured |

## November 2, 2026 — new model and subtitle-method research (NOT a benchmark)

- Read [MODEL_RADAR_2026-11-02.md](MODEL_RADAR_2026-11-02.md) before suggesting further model downloads. Two genuinely new English→Japanese families: **CyberAgent CAT-Translate 3.3B/7B** (Japanese–English specialist; final-model GGUF must be verified) and **Tencent Hy-MT2 7B Q4_K_M** (4.62 GB, context/glossary capable). Both untested as primary translation models on this host.
- IMPORTANT historical correction: `kaelri/hy-mt2:1.8b` was already genuinely used in prior Japanese→English *backtranslation QA*, compared with Index-Translate 2B; do **not** treat those as never tested or confuse QA quality with English→Japanese primary quality.
- TranslateGemma 12B (8.1 GB) needs CPU offload on 6GB GPU; do not assume 12B solves failures of tested official 4B. Third-generation PLaMo Translate service updated Oct 7; local third-gen weights were **announced as future**, not verified available.
- WMT26 Oct 2026 video-subtitle research supports investigating real scene context and verified terminology, but its quantitative studies used **Chinese-source** languages, NOT EN→JA. Do not transpose scores. Multi-model candidate selection is optional only with proven net gain.
- **Next recommendation remains continuous Japanese-only 10–15-minute viewing on a NEW native-E4B generated sample**, not another 64 random cues and not old pre-fix published outputs. After actual viewer comments, consider a SINGLE controlled CAT 3.3B or Hy-MT2 7B native-model comparison on fresh scenes if needed.

## Benchmark 005 PARTIAL RESULTS — 2026-11-02 JST (real files, incomplete control)

Actual owner-uploaded `STATUS.txt`, `model-sweep-005-{cat7,hy7,google12}-20261102T013757Z.json` examined. **Three completed 64-cue arms; tuned E4B control and FINAL CAT 3.3B BLOCKED, not tested.** Full public numeric and provisional assistant-only editorial analysis: [RESULTS_005_PARTIAL.md](RESULTS_005_PARTIAL.md). No private EN/JA dialogue has been committed.

| Model | 64 cues returned/accepted | Role contamination | Median JA chars/sec | >14 chars/sec | Sum call time | Outcome |
|---|---|---:|---:|---:|---:|---|
| Hy-MT2 7B Q4_K_M | 64/64 | 0 | 7.45 | 1 | 81.96s | Strong provisional assistant-only reviewer preference |
| Google TranslateGemma 12B Q4_K_M | 64/64 | 0 | 8.95 | 6 | 256.92s | Correct structure; more formal, slower; not proven better |
| CAT-Translate 7B GGUF Q4_K_M | 64 attempted/59 valid | **16** | 10.05 | **21** | 81.83s | Real output has role/explanatory leakage; MUST audit distinct 7B chat template |
| Existing tuned Gemma4 E4B | BLOCKED preflight | — | — | — | — | Essential same-cue control missing |
| FINAL CAT 3.3B Transformers | BLOCKED/incomplete | — | — | — | — | Exact CUDA/venv failure not in uploaded status |

A cue-shuffled, identity-masked **single-assistant** editorial pass on the 3 completed files found Hy tied or best on 61/64; uniquely best on 35, Google12 on 1, CAT7 on 2, and 26 ties. **This is NOT a native-Japanese watchability grade**, and translation-scenario preferences are subjective. The broad Japanese validator misses many of CAT7's actual role labels and translator notes. Original CAT7 model card explicitly requires a **special 7B chat template**, so do not attribute wrapper corruption to intrinsic final CAT weight quality without checking template packaging.

**Next action (not rerun all arms):** owner runs `bash tools/diagnose_model_sweep_005.sh optiplex@100.121.156.34` from updated MacBook checkout, shares output. Diagnose exact tuned model ID/quantization and CAT3.3 CUDA venv; rerun only two blocked arms after targeted fixes, using the EXACT same 64 source cues. Preserve successful JSON files and score true paired tuned vs HY after that. No live SubHub changes.

## Follow-up diagnostic finding — Benchmark 005 blocked arms (2026-11-02)

Owner ran **read-only** `tools/diagnose_model_sweep_005.sh` on OptiPlex (Ollama 0.32.1). **Tuned control root cause:** expected tag suffix `Q4_K_XL` versus actual `/api/show` `quantization_level=Q4_K_M`. Model itself is correct, same pinned `9ccfc3b07081` ID, `gemma4` family, 7.52B metadata. The benchmark test, not the installed model, rejected it. Source fix pins exact ID + real reported Q4_K_M + family; no model repull or productive system changes.

**Final CAT3.3 diagnostics:** exact frozen English source validated; isolated Torch 2.9.0+cu128, Transformers 4.57.3, Accelerate 1.12.0, bitsandbytes 0.48.2, huggingface_hub 0.36.0 all import; CUDA available, GPU free ~5719 MiB and 201 GB free disk. Its source+environment preflight succeeds. **Actual after-preflight model load/inference error still unknown** because the previous run's stderr was not uploaded. Must capture real error rather than guess.

**One selective rerun after fix:** `bash tools/run_model_sweep_005.sh optiplex@100.121.156.34 missing`, which runs ONLY tuned and CAT3.3. The earlier 3 complete private JSON files remain valid. Local result folder includes `cat33-run.log`, `tuned-preflight.log` and `tuned-model-run.log`; only successful arms can be blindly combined with earlier result files. No public movie dialogue or production switch.

## Benchmark 005 — PR #22 merged (`463231bc`), 107 offline tests passed; real model runs NOT YET PERFORMED

- Methodology: [EXPERIMENT_005.md](EXPERIMENT_005.md); eight NEW contiguous eight-cue English windows centered at 91/127/175/235/303/343/543/691, under the prior immutable Primate English SRT SHA. A fresh **64-cue** sample per arm, disjoint from 001–004, five arms = at most 320 translated candidates.
- Arms: existing tuned native Gemma4 E4B (control), **FINAL** CAT-Translate-3.3B via isolated HuggingFace Transformers 4bit NF4 (not the beta GGUF), FINAL CAT-Translate-7B via sourced GGUF Q4_K_M, official Hy-MT2 7B Q4_K_M (STQ kernel compatibility uncertain), Google TranslateGemma 12B Q4_K_M (must CPU offload on 6GB GPU). Native prompts, no generic JSON wrapper. Model/backend/quantization may differ; compare workflows, not purely model size.
- All downloads are **owner-side opt-in via a command** and may consume >25GB disk/cache in total. The code is staged in server scratch, not live service. Model metadata and source hash checked before inference. No existing SRT, sidecar, checkpoints, media, queues or production translator changed.
- Blinded cue-level reviewer scores meaning 0–4, unsanitized character voice 0–2, fluency 0–2 and timed readability 0–2; separate identity key. Critical errors (negation, idiom, profanity, missing speaker, fictional details) independently counted. Blind scoring alone is not a native-Japanese viewing trial. Holdout sample is still from ONE movie.
- **Actual results: PENDING.** Do not confuse synthetic CI with model downloads, successful compatibility or translation quality. Runtime incompatibility, GPU-memory error or missing weights should be logged honestly as BLOCKED, never treated as poor translation.
