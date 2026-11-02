# Experiment 006 — independent blind EN→JA subtitle evaluation (PRE-REGISTRATION)

> **Implementation update (2026-11-02):** All five 005 technical arms have completed; see [RESULTS_005_COMPLETE.md](RESULTS_005_COMPLETE.md). The first 006 prerequisite is a metadata-only inventory, now implemented and synthetically tested at `tools/inventory_sources_006.py`. Run from MacBook checkout: `bash tools/inventory_sources_006.sh optiplex@100.121.156.34`. This does not select scenes or generate Japanese; new sources still must be frozen and explicitly excluded from prior human/assistant evaluation. Ensure final CAT3.3 Transformers uses an explicit attention mask (warned when EOS=PAD in its 005 run) in the frozen 006 inference implementation. Do not compare results on the old *Primate* cues.
**Status: PROTOCOL ONLY. No dataset selected, no model called, no quality grade awarded.** Effective 2026-11-02. User requested a scientific reset because repeated *Primate* lines and assistant-only evaluation had contaminated the interpretation. This document **supersedes prior subtitle-quality rankings**, not the real measured technical/runtime facts in Benchmarks 001–005.

## The question, and what success means

Which realistically deployable, free/local English→Japanese translator produces **natural, comprehensible, enjoyable Japanese subtitles in real timecoded movie scenes** on the household OptiPlex?

**Subtitles are localization, not word-for-word translation.** Intelligent shortening, culturally natural rephrasing, omission of unimportant verbal filler and rearrangement are ALLOWED and can improve quality. Do NOT subtract quality points for departures from literal English **unless** they damage important intent, relationships, plot causality, emotion, jokes or character voice. Preserve sexual/vulgar/violent content and real character attitudes (not necessarily exact word choices). The working goal is pleasant **~8/10 viewing**, not Netflix-perfect literal correspondence.

## Why earlier results cannot establish a language-quality winner

1. **Benchmark 001–005 reuse *Primate* source.** Several lines were inspected and discussed repeatedly; subsequent experiment choices were informed by earlier error patterns. Fresh cue blocks within that film are not an entirely independent test corpus.
2. A single assistant suggested and authored much of the evaluation and judged the Japanese. Even shuffled identities do not make this an independent expert/native-Japanese rating. The 26 tuned / 15 HY / 23 tied count is an **exploratory assistant preference**, never a viewer-quality grade, statistically demonstrated superiority, or final model promotion.
3. Per-cue comparison without watching moving scenes can miss speaker changes, sarcasm, visual gags, character relationships and legitimate subtitle compression.
4. Mechanical metrics (64/64 Japanese accepted, JA chars/sec, latency, formatting) are **valid operational observations** but not measures of meaning quality. The CAT7 adapter's role-label leakage demonstrates their limits.
5. We lacked a precommitted **external** quality decision-maker and strong enough stop rule. Do not keep optimizing a few famous mistranslated lines.

**Retain 001–005 as development/runtime investigations with source hashes/model IDs and known defects. Do NOT delete, rerun or rewrite the historical records. Mark language ordering exploratory and NEVER use those source snippets for final 006 judging.**

## Frozen CANDIDATE ROSTER to qualify before reading new output

Candidate families, with exact weight digests and runner versions to be pinned in the PRIVATE manifest before generation. No substitutions without adding an explicit new roster version **before evaluation**:

| Candidate | Reason | Expected category |
|---|---|---|
| 17slever17 subtitle-tuned Gemma4 E4B (native prompt) | Existing leading baseline | Core |
| 17slever17 subtitle-tuned Gemma4 E2B | Smaller subtitle-specialist | Core |
| Tencent Hy-MT2 7B | Strong newer translation model | Core |
| Tencent Hy-MT2 1.8B | Smaller sibling; earlier used for JA→EN QA but **not established for EN→JA** | Core |
| Index-Translate 2B | Alternative translation-specific family; prior QA experience not a direct EN→JA evaluation | Core if correct local runtime available |
| CyberAgent CAT-Translate FINAL 3.3B | Japanese–English specialist (final HF weights, **not** older beta GGUF) | Core if environment loads |
| CyberAgent CAT-Translate FINAL 7B | Japanese–English specialist; requires author's **distinct 7B chat template** | Core only under verified template |
| Google TranslateGemma 4B | Translation specialist; previous small-arm failure is historical | Core negative/low-cost control |
| Google TranslateGemma 12B | Larger translation specialist | Core slower/CPU-offload comparison |
| Original standard Gemma4 E4B | Establish subtitle-tuning's incremental value | Core baseline |

**Heavy feasibility lane, separately labeled**: Hy-MT2 30B-A3B or other >6GB GPU models only if a local, valid runtime with 32GB system RAM has been proven feasible and the expected latency/compute is acceptable. **Do not treat unfittable weights or cloud-only services as failed translations.** PLaMo Translate 3 is not eligible until offline/downloadable weights can actually be verified. The 10 core entries are a *finite* roster, not a rolling stream of new downloads. A model blocked by a missing tokenizer, quantization or chat-template issue is reported as **RUNTIME BLOCKED** with exact reason; it receives NO translation-quality ranking. No need to rerun successful *Primate* results.

## Independent corpus: new titles, not cherry-picked lines

1. Before generating **any** candidate outputs, choose **at least 3 unrelated video titles** from the owner's library (prefer distinct register, e.g. horror/thriller, everyday dialogue or comedy, action). **Exclude *Primate* and any clips previously used for 001–005 QA/prompt selection.** Exclude source cues whose prior generated Japanese was used for training/context/examples/hand-crafted prompt tuning. Never take existing approved Japanese as model input.
2. From eligible English SRTs, **algorithmically select 4–6 continuous scenes of 5–8 minutes each** from those titles, using a predeclared deterministic selection rule (e.g. SHA256 of private fixed seed plus title/source SHA and eligible time-block ID). Aim for **at least 200 cues total**. Do not cherry-pick idioms, curses, convenient sections or known model failures. If scenes do not meet eligibility (insufficient EN/timings, credits, music-only), advance deterministically to next eligible candidate without looking at JA outputs.
3. Commit **only the selection algorithm, number of scenes/cues, source hashes, dataset identifier, and sealed manifest digest** to public GitHub BEFORE scoring; keep source text, video paths, private selection seed and actual manifest out of the repo. Record exact title source SHA and cue identities in the PRIVATE manifest. **Freeze the dataset.**
4. Include complete dialog sequences, speaker changes and silence where appropriate. All candidate models receive **the same frozen English source, same original timings and same scene boundaries**; their own native prompts/context specifications are pinned *before* translation. Never give historical Japanese subtitles, human review comments or previous models' output as context unless the experimental arm was independently preregistered as explicitly multipass.
5. Reserve **one further entirely unseen title** as a final confirmation set *not used for model selection, troubleshooting or prompt adjustment*. A model change after viewing this confirmation title invalidates its holdout status; allocate a new confirmation title instead.

## One controlled inference per qualified candidate

- Freeze the **exact** weight/model digest or HF commit, quantization, package versions, chat template/prompt hash, language directions, sampling options, context policy and runtime backend. Verify models actually translate EN→JA and the correct template is applied (especially CAT7) before *scoring*. Fix only packaging compatibility using SYNTHETIC or prior development snippets; never repeatedly tweak a candidate on the sealed test-set outputs.
- Use **one ordinary model-native translation run per candidate** for the entire frozen set; if stochastic settings cannot be made deterministic, record seed, variability and runtime limitations. No 'best of five' or cherry-picked reruns. A machine failure is an unavailable output, not 'worst Japanese'.
- Preserve raw private SRT/JSON, timestamps, per-cue errors, energy/VRAM if available, output throughput and source hash for every arm. Use private create-only paths; never publish dialogue or rewrite approved subtitles/movie files or live SQLite cue state.
- All model outputs get the **same light, purely mechanical formatting safety check**. Never use an LLM critic's rewrite to create a hidden extra advantage for one model.

## Independent native-Japanese quality evaluation (primary endpoint)

**Do not ask the assistant that chose/runs the models to choose the winner.** A native Japanese viewer (ideally the intended household viewer) should see anonymized **complete scenes during playback** with the original English audio, without seeing model identity, vendor names, output lengths or speed rankings beforehand. Shuffle **model IDs and viewing order at the scene level** under a saved random seed. Make review workload manageable: stage 1 may use a balanced subset of scenes to screen all eligible models; stage 2 uses longer clips for finalists. Never present one model with only difficult scenes and another with only easy scenes; every model must be graded on matched source scenes, with candidate order counterbalanced. If only one viewer is available, treat that as a useful household acceptability test, **not an independent multi-reviewer statistical study**.

For each blinded viewing segment record:
- **Enjoyment/watchability, 1–5:** Would the viewer willingly watch the whole movie with these subtitles?
- **Natural Japanese, 1–5:** Does it sound like plausible spoken character dialogue rather than written translationese?
- **Plot/scene comprehension, 1–5:** Can the viewer follow what is happening and why?
- **Reading comfort, 1–5:** Text readable at displayed timings without constant distraction.
- **Serious comprehension breaks:** timecode + short description when a line conveys the wrong action, person, timeline, emotional intent, joke, or event. IMPORTANT: **Do not flag acceptable compression or idiomatic reframing as an error.**
- Optionally: character-voice fidelity, profanity/sex/joke tone, key proper names, subtitle vs film alignment.

Allow a reviewer to say **"not sure"** rather than force a grade. Do not fill blank scores with an assistant's guess. The viewer should give judgments **before opening the model identity key**. Maintain locked review scores and randomized viewing-order manifest privately; reveal identities only after locked ratings.

A separate **bilingual spot-check** can target viewer-reported comprehension breaks, but it is SECONDARY. Review the English source with scene context, not literal cue-for-cue word matching. Other automated critics may propose issues for a human to verify, but cannot certify model ranking.

## Decision rules / stopping conditions

- **First choose models that actually deliver watchable tracks** to the intended viewer at reasonable compute cost, not the highest assistant BLEU/CHRF or longest sentences. No 1:1 English-word overlap benchmark.
- Candidate provisional pass: viewer's **watchability and comprehension each ≥4/5**, without recurrent plot-breaking errors, on multiple continuous scenes. This is a pragmatic household acceptance criterion, not a universal language standard or scientific hypothesis-test threshold.
- Compare paired scene-level results, report uncertainties, medians, variability, reviewer count, operational failures and GPU/CPU cost. If multiple candidates pass and ratings are effectively similar, **choose the simplest/faster single-pass model**. Do not continue testing for an imagined marginal gain.
- Only explore a **selective second-model pass** if direct viewer evidence shows **recurring important errors**, a clear measurable *trigger* identifies them, and a separate fresh trial reduces serious errors **without introducing as many new ones** and with acceptable CPU/GPU/maintenance cost. If no reliable trigger, retain single pass and optionally flag quality issues for human review. Never auto-combine two outputs just because they disagree.
- The 006 confirmation title must substantiate the winning model's usability. If confirmation fails, log why and re-open selection with NEW scenes—do not tune prompts against and then reuse that same confirmation title.
- Stop engineering model tests once one practical model passes the viewer gate plus confirmation. Return attention to new-job-only non-destructive library intake and Jellyfin playback.

## Outputs / governance

- **Public:** protocol, candidate roster version, hashes, model metadata, numeric operational results, **anonymized aggregate viewer scores only after reveal**, uncertainty/limitations, final decision, documented compatibility failures and follow-up action. Keep journal in RUN_LEDGER and main handoff.
- **Private:** film paths, source/candidate subtitles, actual scene/clip IDs, model identity key until scores locked, viewer raw notes (if desired), individual translations, playback exports and arbitrary human commentary.
- **Freeze once, run once, adjudicate separately.** Any new prompting experiment goes to a separate development dataset; 006 holdout is never a debugging loop.
- CAT3.3 currently running on owner's OptiPlex remains **unaffected** by drafting this protocol. No new model calls, deployments, downloads or production writes are authorized by creating this document.

**Implementation readiness:** This document is a pre-registered methodology, **not a claim that new unseen titles or scores are already selected**. Model runtime verification, private scene selector, playback exports and blind review scoring tools must be implemented/tested as separate reproducible components BEFORE actual 006 inference; no unvetted "one command runs all" promise.
