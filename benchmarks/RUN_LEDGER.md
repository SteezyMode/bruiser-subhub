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

## Benchmark 002 — preregistered, local run pending

- Design: [EXPERIMENT_002.md](EXPERIMENT_002.md) — SAME 64 English cues as Benchmark 001, but the **already installed** tuned Gemma e4b receives the developer's native `[CURRENT_SOURCE]` with up to two prior source/translation pairs.
- One Ollama call per cue (64 calls), with no retry and no other model. Context from generated translations in the SAME eight-cue window only; no original Japanese fed into the model.
- Status: **NOT RUN on Ollama**. The synthetic test suite does not measure semantic fidelity.
- Future results must compare against Benchmark 001 on same IDs; judge meaning, idioms, profanity/sexual tone, omissions, and viewing speed before deciding whether an optional selective second pass is justified.

| Model/native method | Valid / 64 | Format flags | Median chars/s | Inference seconds | Human quality decision |
|---|---:|---:|---:|---:|---|
| Tuned Gemma e4b native previous/current prompt | Pending | Pending | Pending | Pending | Not reviewed |
