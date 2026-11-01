# SubHub translation-quality experiment ledger

**Public summaries only. Private EN/JA samples and generated model outputs remain outside GitHub.** Update after a genuine measured comparison. Commit identifiers refer to GitHub source, NOT proof of live deployment.

## What was established before Benchmark 001

| Date | Experiment or observation | Verified outcome | What it did NOT establish |
|---|---|---|---|
| 2026-11-01 | Initial pilot translation (legacy batch path before fix) | Seven of ten pilot films published after targeted cue repair; read-only artifact scan found zero detectable tool/JSON contamination across 10 jobs | Reliable Japanese quality; direct comparable model baseline |
| 2026-11-01 | 80-cue risk-enriched Primate EN/JA editorial review | Several specific idiom errors, softened vulgarity, and excessive reading density; many ordinary lines understandable | Failure percentage for all 741 cues or all films |
| 2026-11-01 | Fresh Gemma e4b with `natural_8` prompt, five 8-cue windows | 40/40 results in 26.07 sec total reported model-call time (8.58/4.18/4.13/4.63/4.55 sec). Some idiom and brevity improvements | Adequate overall quality. It introduced serious errors: undirected exclamation instead of a directed insult; sex joke removed; rhetorical accusation turned into open question; speaker turn removed |
| 2026-11-01 | Read-only video/subtitle census | 13,199 video files, 4.14 TB video, 2,026 English-text+English-audio candidates, 442 detected JA, 268 OCR candidates, 4,670 missing English source, 5,764 audio unverified, 29 metadata failures | That all 2,026 can be translated immediately or that most of 5,764 are non-English |

## Benchmark 001: PRE-REGISTERED, waiting for host model run

- Procedure: [EXPERIMENT_001.md](EXPERIMENT_001.md); frozen 8x8 cue selection and 2-model x 2-profile matched arms.
- Aim: test **genuinely different local models** and new `faithful_8` (no sanitized slang or meaning loss), rather than indefinite prompt-only tweaks.
- Score with human EN/JA semantic/tone/readability rubric; speed and structurally valid output are secondary metrics, not quality scores.
- Source output will be a private create-only JSON on the Mac mini; GitHub will only receive reproducible setup, arm digests, numerical summary, reviewer scores, paraphrased failure patterns, final decision.

### Benchmark 001 recorded result (do NOT fill until real run)

| Model/digest | Prompt | Valid/64 | Median characters/sec | Model seconds | Human score/10 | Critical errors | Decision |
|---|---|---:|---:|---:|---:|---:|---|
| Pending | baseline | — | — | — | — | — | Not run |
| Pending | faithful_8 | — | — | — | — | — | Not run |
| Pending | baseline | — | — | — | — | — | Not run |
| Pending | faithful_8 | — | — | — | — | — | Not run |

**Next action:** Run one fixed local model comparison, attach the private JSON in chat, score it against the existing English source, record results here, then make ONE model/prompt choice or acknowledge the quality ceiling. The 2,026 detected ready-source candidates are a separate queue-ingestion milestone after the quality decision.
