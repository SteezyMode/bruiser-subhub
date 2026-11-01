# Benchmark 001 — controlled local EN→JA subtitle quality test

**Original protocol was PRE-REGISTERED before the run. Actual local inference is now COMPLETE; see [RESULTS_001.md](RESULTS_001.md).** This plan is fixed before examining candidate model outputs. Source: existing private Primate SRT checkpoint. No copyrighted dialogue, media or subtitles belong in this public repository.

## Decision we are testing

Can a free model already installed on the OptiPlex RTX 3050 6 GB deliver **roughly 8/10 enjoyable Japanese subtitles**, consistently better than generic SubtitleCat translations, while preserving idioms, slang, profanity, sexual jokes, violent threats, and speaker intent? Perfect Netflix specifications and hard character limits are **not** required.

## Frozen test set

- Source job: `primate-2026-1080p-amzn-web--ad1c564197`.
- Source SHA-256: `8967cfea3f6552c0a6b1645da13e0d79e62be2decb95c02c653e6a345c3b645a`.
- 8 non-overlapping blocks of 8 **consecutive** cues, centered at cue IDs **35, 71, 143, 207, 265, 380, 428, 465** = 64 unique cues per experimental arm.
- Sections deliberately include fast dialogue, idioms, tense/negation, argumentative speech, tone, violence, and sexual slang. **Risk-enriched test, not a statistically representative sample of the library.**
- The model sees the source context of all 8 English cues per block. Preserve cue identity and each speaker's meaning. No access to future translated Japanese except the existing approved translation memory shared between arms.

## Four matched experimental arms

| Arm | Model | Prompt |
|---|---|---|
| A | Installed production `gemma4:e4b-it-qat` | Fresh **baseline** legacy prompt |
| B | Same production model | Experimental `faithful_8` prompt |
| C | One installed `translate-gemma-4-sub` **e4b** model, resolved from actual `ollama list` | Fresh **baseline** legacy prompt |
| D | Same installed subtitle-tuned model | Experimental `faithful_8` prompt |

The tuned model **must already be installed**. Auto-detect only if a single unambiguous `translate-gemma-4-sub` e4b ID exists; otherwise fail closed and run again with `--challenger-model` after inspecting `ollama list`. Do not auto-download gigabytes or silently substitute a different model. SHA/digest identifiers are captured from the Ollama CLI. If no subtitle-tuned model exists, note this and choose a separately installed alternative explicitly, updating this plan before running.

Each arm translates the SAME English cue groups using the SAME production `bruiser_auto.build_prompt()` and `call_ollama()` adapter. Styles are interleaved within each model's window; models are grouped to reduce repeated VRAM loads. Style effects and model effects are separately visible. The legacy wrapper may have its own model/runtime defaults; their true effect is not measured here and must be reported as a possible confound.

**Do not use the old published Japanese as a controlled baseline.** Most older subtitles were generated before the malformed-SRT batch bug was fixed and could have used singleton fallback. Existing Japanese is kept in private output only for historical comparison.

## Measurements and blind language adjudication

**Automatic, nonsemantic diagnostics:** structured response success; missing/malformed Japanese; exact source/cue coverage; median Japanese non-whitespace characters/second; number exceeding 14 chars/s; per-window model-call durations; model digest, source hash, and benchmark source checksums. These DO NOT grade meaning, tone, or native-language naturalness.

**Manual reviewer, ideally blind to the model/profile:** score each candidate (64 per arm) against its English and scene context on a 10-point scale:

| Dimension | Points | Definition |
|---|---:|---|
| Semantic fidelity | 0–4 | Correct who/what/when, speaker, negation, rhetorical intent, facts, and implied meaning |
| Tone & adult voice | 0–2 | Equally strong profanity, sexual/violent implications, insult direction, humor, sarcasm; no sanitizing or made-up obscenity |
| Natural Japanese | 0–2 | Conversational, idiomatic, consistent character register, no wooden English calques |
| Viewing readability | 0–2 | Readable within displayed duration, reasonable line breaks, avoids unnecessary filler |

Mark **CRITICAL** independently when a cue reverses meaning, drops a speaker/urgent clause, sanitizes a sexual joke/threat/directed insult, or invents consequential content. Do not reward short lines if they are incomplete. Report counts of critical failures and cue-level reasons along with median score, NOT merely a single '8/10' number. ChatGPT assessment is useful but **not a substitute for a native Japanese viewer**; have the user's Japanese partner watch a short segment with the chosen output before any library-scale rollout.

**Promotion rule:** choose a candidate only if evidence shows a clear semantic/tone advantage over baseline with comparable operational reliability and acceptable reading comfort, with no worrying pattern of critical changes. If results remain mixed, stop prompt churn and trial an honestly different model or workflow; don't claim success from shorter text or faster model calls alone.

## Reproducible execution

From the Mac mini checkout (after fetching this PR when merged):

    cd ~/Downloads/bruiser-subhub-repo
    git pull --ff-only
    bash tools/run_model_benchmark.sh optiplex@100.121.156.34

The script runs offline regression tests, stages files in a SEPARATE benchmark folder on the OptiPlex, preflights the **real installed models** and frozen source hash, acquires existing worker locks, uses local Ollama/GPU on 32 eight-cue requests, and copies the **private** JSON to Mac mini Downloads. No production code/queue, SQLite cue, source subtitle, published Japanese file or video is changed. Do not run it while gaming/AI workloads must have the GPU.

Upload the private JSON to the conversation for a blinded/manual review. **Never commit movie dialogue, private model responses, media filenames, or checkpoint databases to public GitHub.** Public GitHub may record only the model IDs/digests, code/source hashes, numeric metrics, adjudicated scores, paraphrased failure classes, decisions and next action.

## Results ledger

**Completed real host run.** See `benchmarks/RESULTS_001.md` and `benchmarks/RUN_LEDGER.md` for measured outcomes and the important model-native-prompt limitation. No human/native-speaker quality rating is yet established.
