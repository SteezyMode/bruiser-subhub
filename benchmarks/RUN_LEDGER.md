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
