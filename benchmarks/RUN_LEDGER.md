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

## Benchmark 005 updated: tuned E4B control COMPLETE; CAT 3.3B blocked by available VRAM (2026-11-02)

Owner provided real 64-cue tuned run `model-sweep-005-tuned-20261102T022559Z.json`, `tuned-preflight.log`, `tuned-model-run.log`, and `cat33-run.log`. Frozen source SHA + all 64 English cues/timecodes match the previous HY7/CAT7/Google12 runs exactly. Tuned E4B exact model ID `9ccfc3b07081`, gemma4, correctly pinned reported Q4_K_M (tag still Q4_K_XL). **64/64 structurally accepted, 0 errors/format flags, median 6.6 Japanese chars/sec, 0 >14, 61.98 summed call seconds.** HY7 same cues: 64/64, 0 format flags, median 7.45, 1 >14, 81.96s. **Tuned calls were 24.4% faster** in this observed comparison. This is not a causal architecture-only speed experiment.

**Critical partial qualitative outcome:** a single assistant performed cue-by-cue masked-identity A/B preference screening (NOT native-speaker 10-point grading), revealing tuned preferred **26/64**, HY preferred **15/64**, and **23/64 ties**. Both translate a line about physically losing grip as inability to *endure* something, an important shared meaning error. HY understands an attractiveness idiom, a telephone call and a character's name more reliably; tuned more often preserves colloquial social register and concise urgency. **Do not assert either model meets 8/10 without independent Japanese-viewer trial.** Exact model IDs, other errors, limitations and recorded source identity: [RESULTS_005_TUNED_HY_PAIRED.md](RESULTS_005_TUNED_HY_PAIRED.md). Full paired text/identity-shuffled review are PRIVATE.

**CAT final 3.3B true blocker now visible:** source preflight and pinned isolated CUDA Python imports succeeded, then CAT preflight failed `Under 3GB free VRAM; stop competing inference before CAT 3.3B`; the model did not load/infer. Previous idle ~5.7GB free. Tuned model just ran with Ollama `keep_alive=5m`, so GPU residency is plausible but **specific VRAM consumer not proven**. Updated CAT runner prints read-only `ollama ps` + free GPU VRAM, NEVER automatically unloads other workloads. **Only remaining arm** is CAT3.3; mode `cat33` (or updated `missing`) now targets **ONLY it**, preventing successful model reruns. Reattempt when GPU is idle, otherwise stop and capture logs.

**State: 4/5 arms complete; CAT final pending.** No production SubHub source, SQLite checkpoints, queue, media, or approved Japanese sidecars changed. Next paired-scene Japanese-native viewing and a second film sample should follow before any library scale decision.

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

## Benchmark 005 CLOSED: actual final CAT3.3 succeeded (2026-11-02 UTC 03:17:57)

Owner uploaded FINAL CAT3.3 file `model-sweep-005-cat33-final-20261102T031344Z.json` and last run log; **64/64 output valid, zero formatting flags/call errors, median 6.8 JA chars/sec, one >14, 28.27 seconds summed 64 model generation calls**. Exact HF final revision `47e382331d005acd54a42cdf088a76aa88788e0c`, 4bit NF4 + fp16 Transformers CUDA, pinned sentencepiece/protobuf restored. First download 2 files ~3m04s, model load ~6s **not included in call time**. Transformers warned missing explicit attention_mask when pad/eos share token. Record as 006 reproducibility risk; don't relabel known literal slang errors as structural pass. Complete five-arm engineering comparison/limitations: [RESULTS_005_COMPLETE.md](RESULTS_005_COMPLETE.md). **Five arms ran; CAT7 GGUF remained only 59/64 accepted**, not five clean models.

**QUALITY GATE RETIRED:** assistant preference rankings on the known Primate lines are NOT credible final model-selection evidence. No native speaker scoring in 005. Move immediately to the [clean 006 independent holdout protocol](PROTOCOL_006_INDEPENDENT_HOLDOUT.md). First executable prerequisite: `tools/inventory_sources_006.sh HOST` reads existing SQLite in `mode=ro` and prints metadata only (Primate SHA excluded). No video paths or subtitle text. Need 3 fresh eligible unrelated titles plus unseen confirmation title; do not select/evaluate on this old film again.
## Experiment 006 RE-REGISTRATION — 2026-11-02 (PROTOCOL ONLY)

Owner explicitly rejects same-*Primate* line reuse and assistant-centered editorial scores as a scientific model quality test. **New governing protocol: [PROTOCOL_006_INDEPENDENT_HOLDOUT.md](PROTOCOL_006_INDEPENDENT_HOLDOUT.md)**. All numerical 001–005 timings/validator passes and observed compatibility defects stay valid. **Retire all 26/15/23 and 61/64 assistant preference counts as final-model selection evidence; these are exploratory and should not drive production.** Good subtitling is not literal translation: natural condensation/rewriting is allowed so long as plot/scene/voice remains comprehensible. Freeze 10-model finite roster, verified model-native configs and NEW unseen source scenes from ≥3 titles, reserve separate confirmation title, use blinded independent native-Japanese viewing as primary score, then pick a watchable model. Rerun **none of the previous 64-cue Primate benchmark for quality claims**. No new run/deploy or corpus selection by this documentation PR.
## 2026-11-02 — CAT3.3 last blocker identified and architecture decision frozen
Owner's latest `cat33-run(1).log` shows empty Ollama residency, 5803 MiB free VRAM, correct source SHA and successful CUDA/runtime preflight. `AutoTokenizer.from_pretrained` then failed **BEFORE any model inference** due to missing `sentencepiece` and `protobuf` in the CAT-specific isolated venv. This is a distinct new cause from earlier below-3GB VRAM blockage. Scripted fix: exact seven-package pins in `tools/cat33_requirements_005.txt` (including sentencepiece 0.2.2 and protobuf 6.33.6); staged by the CAT-only runner and verified by newly tested tokenizer preflight. Never install these into live service Python. Exact traceback privately preserved; no CAT final quality conclusion yet.
**DECISION RECORD:** [DECISION_RECORD_2026-11-02.md](DECISION_RECORD_2026-11-02.md) states which model tests are finished, verified engineering root causes, provisional single-pass tuned E4B preference, optional-but-UNPROVEN selective HY fallback, and stop conditions. No automatic 2-model workflow until net semantic quality benefit and a working trigger are measured. Need 10–15 min Japanese-only viewing and independent second-film check before automatic library scale. This ledger + decision record prevent rediscovery of the same diagnostic history.


## 2026-11-02 — Actual 006 English-source inventory COMPLETE; no new translations yet

Owner ran read-only source inventory on OptiPlex after PR #28: **10 registered English-SRT jobs, nine mechanically eligible after excluding previously benchmarked Primate SHA**; six already-published jobs, two queued and one publication-held. All are tagged `horror`; diversity outside horror needs a later dataset, but these provide sufficient inventory for at least 3 training/evaluation titles and a separate confirmation title **subject to unreviewed-history and playback verification**. No film dialogue, individual private source hashes or media paths committed. Existing published JA is **never supplied to candidate models or external reviewers**; approved sidecars remain untouched.

The finite 006 roster remains **ten core model-native workflows**, not indefinite new-model discovery: five completed 005 families **on NEW test material** plus smaller Hy-MT2 1.8B, tuned Gemma4 E2B, Index-Translate 2B, standard Gemma4 E4B and Google TranslateGemma 4B control. All 005 language rankings are exploratory, NOT quality measurements. Next stage is a deterministic source/scenes selection with a frozen private manifest and independent native Japanese viewing. No new inference, download, deployment or quality grade exists yet. See [PROTOCOL_006_INDEPENDENT_HOLDOUT.md](PROTOCOL_006_INDEPENDENT_HOLDOUT.md).


## 2026-11-02 — Benchmark 006 runnable experiment implementation (owner-triggered)

The user explicitly instructed execution rather than more plans or endless host troubleshooting. `tools/clean_sweep_006.py` now contains the complete 10-arm **host-side inference** harness and `tools/run_clean_sweep_006.sh` stages/starts it from the MacBook with one command. The selected 3 TITLE corpus + 4th holdout is sealed privately **BEFORE** inference; source SHA/English/timecodes verified on every arm using read-only SQLite. All 10 candidates use their documented native prompts, separate processes, exact pinned historical IDs where known and new resolved IDs/revisions before output. Blocked models are recorded, not given bad quality scores. Partial results checkpoint per cue on disk and a rerun resumes rather than resampling. All output/model identity/film text stays PRIVATE, blind viewer's .srt files and score template separate from identity key. No translation-model inference has yet been run under 006: this is an executable artifact tested with synthetic fixtures, not a completed model study. No production changes.

OWNER command after PR merge, from `~/Downloads/bruiser-subhub-repo` on MacBook:
```bash
git pull --ff-only
bash tools/run_clean_sweep_006.sh optiplex@100.121.156.34
```
Expect new Ollama model downloads; do not claim a result before `~/Downloads/benchmark006-private/COUNTS.json` is returned. Then obtain BLIND Japanese viewer scene playback scores, unblind ONLY after scores locked. Official 005 speed/format reports remain complete but are **NOT** a model-quality winner.
