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

## Benchmark 004 — PR #19 merged (`632ab253`), 95 synthetic tests passed (3.11/3.12); REAL model run pending

- Protocol: [EXPERIMENT_004.md](EXPERIMENT_004.md), frozen before model installation. A truly different model, not a Gemma4 prompt tweak. Official `translategemma:4b` is **Gemma 3, 4.3B, Q4_K_M, ~3.3 GB**, with recommended **single user** translation prompt and two blank lines before the input text.
- Google receives 64 prior frozen English anchor cues plus 16 **new held-out** cues (8 near 515; 8 near 625); existing pinned subtitle-tuned Gemma4 receives only the 16 new held-out cues through its own validated Benchmark 002 native format. **96 private outputs**, real EN/JA assessment needed.
- Model installation/download (~3.3 GB) is explicit in the Mac mini runner *after* frozen source verification. Do not confuse GitHub merge, offline unit test success, and actual owner-side run.
- No production translator, checkpoint, media, or subtitle changes. Even if this model is superior, wait for Japanese-only viewing before whole-library rollout.
- **Current result: PENDING.**

| Arm | New source cues | Prior anchor cues | JA valid | Formatting flags | Human language/tone verdict |
|---|---:|---:|---|---|---|
| Google TranslateGemma 4B official prompt | 16 | 64 | — | — | Not tested |
| Existing tuned Gemma4 E4B native protocol | 16 | 0 | — | — | Not tested |
