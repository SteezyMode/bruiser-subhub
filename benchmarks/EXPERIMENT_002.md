# Benchmark 002 — native-format subtitle-tuned Gemma

**Status: PRE-REGISTERED, REAL OLLAMA RUN NOT YET PERFORMED.** Proposed after discovering that Benchmark 001 used the legacy batch-JSON prompt for both models. Prior public results: [RESULTS_001.md](RESULTS_001.md).

## Narrow question

Does the **already installed** 17slever17 subtitle-tuned Gemma 4 e4b produce more natural, accurate, non-sanitized Japanese when prompted in the native single-segment format it was trained on, rather than generic multi-cue JSON?

Test **without** changing the normal translator, queue, database, or published SRT. This is not a mandate for multiple models or multiple passes.

## Source and hardware controls

- Same **64 English cues** as Benchmark 001: eight disjoint contiguous groups of eight, centered at IDs `35, 71, 143, 207, 265, 380, 428, 465`, from the same Primate source SHA `8967cfea3f6552c0a6b1645da13e0d79e62be2decb95c02c653e6a345c3b645a`.
- Installed tuned model **exact tag and Ollama ID**: `hf.co/17slever17/translate-gemma-4-sub-e4b-GGUF:Q4_K_XL`, `9ccfc3b07081`. **Abort rather than pull or silently change version** if ID differs.
- Developer's published prompt card: https://huggingface.co/17slever17/translate-gemma-4-sub-e4b-GGUF .
- System task: translate **English subtitles to Japanese**, neutral spoken adult-horror style. Preserve meaning, tone, slang, profanity, uncertainty, repetitions, incomplete speech. **Translate only CURRENT_SOURCE**.
- User prompt: `[PREVIOUS_SOURCE]`, `[PREVIOUS_TRANSLATION]` when available; `[CURRENT_SOURCE]` always. At most the previous two **successfully generated native model outputs from within this run and this window** are context. Never use old published JA or future subtitles for context.
- Source cue durations and IDs are unchanged. Raw model output is retained privately including malformed text, not silently cleaned. No backtranslation, retries, model changes, or automatic revision.
- Runtime: Ollama `/api/chat`, one call per current cue, temperature 0, `num_ctx=4096`, `num_predict=320`, `think=false`, five-minute model retention. Holds both existing SubHub worker locks; scratch code only. It is okay if this consumes more GPU/call overhead than Benchmark 001; **do not compare call speed without accounting for 64 calls versus eight**.

## Decision criteria

Primary: manual, context-sensitive assessment of **who said what, intent, idioms, directed profanity, sexual/violent meanings, grammatical speaker turns**, and fluent Japanese that can be read within the existing timecodes. Evaluate against the two previous tuned-model arms and the ordinary Gemma baseline in Benchmark 001 on **identical cue IDs**, not unrelated films. Mark crucial omissions, mistranslation, sanitized jokes and hallucinations explicitly.

Secondary structural outcomes: 64 calls attempted; success/missing output; cue validity; recognizable serialized JSON/stray quotation punctuation/escaped HTML; chars/sec; total model time; source hash and model ID. These do not establish the film is '8/10'.

**Promotion:** only adopt native tuned model if it actually preserves meaning and tone better enough to offset more requests and potential errors, and after a Japanese-speaking viewer checks a short sequence. Otherwise retain the ordinary Gemma baseline. Multipass/multi-model review remains OPTIONAL: consider an independent reviewer only if benchmark findings demonstrate a net accuracy gain, preferably on flagged difficult cues rather than every subtitle.

## Run instructions, once merged

From the Mac mini:

    cd ~/Downloads/bruiser-subhub-repo
    git pull --ff-only
    bash tools/run_native_subtitle_benchmark.sh optiplex@100.121.156.34

The script runs all synthetic tests, stages the benchmark into the **separate** `~/bruiser-pilot/subhub-benchmark` directory, verifies frozen source SHA and Ollama model ID, acquires existing worker locks, performs local inference, and returns a **private, create-only** JSON to Mac mini Downloads. No media, subtitles or checkpoints are edited. Do not run while the GPU is needed for another workload.

**Privacy:** never commit film dialogue, Japanese model outputs, media or private result JSON to public GitHub. Only numeric metrics, paraphrased problem classes, model IDs/digests, source/code hashes and honest review conclusions belong in `benchmarks/RUN_LEDGER.md`.

## Result

**NOT RUN.** See `benchmarks/RUN_LEDGER.md` for pending slot. `python3 -m unittest` checks the harness, not live Ollama Japanese quality.
