# Benchmark 004 — Google TranslateGemma 4B using the officially documented prompt

**Status: PRE-REGISTERED, NOT RUN against the user's Ollama.** This experiment tests a substantively different model, rather than changing Gemma 4 prompts yet again. Previous results: [001](RESULTS_001.md), [002](RESULTS_002.md), [003](RESULTS_003.md).

## Question

Can the official **Google TranslateGemma 4B** (Gemma 3, Q4_K_M) deliver more accurate and naturally phrased English→Japanese subtitles than the 17slever17 subtitle-tuned Gemma 4 E4B while keeping sex/profanity, slang, threats, speaker meaning and readable timings? There is **no evidence yet** that the new model is better; this is the controlled test.

## Official model and prompt (frozen before running)

- Official Ollama tag: \`translategemma:4b\`; expected Ollama model ID prefix \`c49d986b0764\` from official registry on 2026-11-02. \`/api/show\` must report **\`gemma3\`** and **\`Q4_K_M\`**. Expected download approximately **3.3 GB**, separate from Gemma 4 E4B. Source: [Ollama TranslateGemma 4B](https://ollama.com/library/translategemma:4b).
- TranslateGemma official format is a **single USER prompt with English (en) and Japanese (ja)** and **exactly two blank lines before the source text**. NO system message, legacy batch JSON schema, previous translation, extra horror instructions, glossary, or post-hoc cleaning is added. See model page's [Prompt Guide](https://ollama.com/library/translategemma).
- Ollama endpoint \`/api/generate\`, **native model chat template preserved** (no raw or template override). No overrides of the model's temperature, \`top_k\`, \`top_p\`, stop tokens or other sampling defaults; record actual \`/api/show\` parameter metadata.
- Operational safety caps \`num_ctx=4096\`, \`num_predict=256\`; no evidence these are *quality-optimal*, and 4,096 context tokens are ample for one source subtitle on a 6GB card. Do not apply a hard JA character limit, remove profanity, or impose an artificial 8s context rule.
- This is **not** identical to a full document translation; it tests isolated single subtitle cues, which may disadvantage a model without dialogue context. This is intentional to match Ollama's official prompt; don't claim all real-film problems solved by this alone.
- Model download is an **explicit host operation** after source verification, not silently performed by the Python benchmark. Never replace or delete currently installed models. The download consumes ~3.3GB of disk and data.

## Fixed comparison sets

- **64 anchor cues already used in Benchmarks 001–003:** same Primate English source SHA-256 \`8967cfea3f6552c0a6b1645da13e0d79e62be2decb95c02c653e6a345c3b645a\`. Frozen eight consecutive eight-cue windows centered at IDs \`35, 71, 143, 207, 265, 380, 428, 465\`. Useful for direct retrospective comparison to 002's tuned native results and other historical arms. These are **not blind holdouts** and reflect a problem-enriched selection.
- **16 preregistered NEW held-out cues**: eight consecutive cues around ID **515** and eight around **625**, using the same source SHA. These were not part of 001–003 and are fixed **before** observing either model's new output. If original cue IDs/source cannot be verified, abort; do not substitute easier segments.
- **Google arm**: translate all 80 source cues using exact official user prompt, one call per cue.
- **Existing subtitle-tuned arm**: translate ONLY the 16 held-out cues with the previously measured Benchmark 002 native format (up to 2 prior successful generated source/JA pairs within each held-out scene, temperature=0, context=4096, max output=320). Model pinned to ID \`9ccfc3b07081\`. This is a **model-native workflow comparison**, not an isolated test of weight differences or matched decoding temperature.
- Totals expected: **80 Google + 16 tuned = 96 outputs**, 96 model calls. Holdout results are the main new unbiased sample; anchor outcomes contextualize against previous 64 tuned native outputs.
- Preserve **all raw model text privately**, including mistranslations, hallucinations, incomplete speaker turns, formatting debris. Existing published JA is present in the private file for context only; never fed to the models or used as a primary fair control.

## Metrics and decision

- Structural diagnostics: exact cue coverage, model ID/architecture/quantization, valid JA, artifact flags, duration, chars/sec, timestamps, per-call errors and total reported call time.
- **Manual adjudication required**: English semantic accuracy and who-did-what, character/tone/profanity/sex/threat fidelity, contemporary slang and idioms, Japanese fluency, and readability given screen time. Mark serious hallucinations/sanitization, not simply how long a string is.
- Compare **fresh 16-cue head-to-head** first, then contextualize with 64 prior benchmarks. A credible winner must demonstrate a meaningful net quality benefit in substance, not just validator pass rate.
- Do not label either model 8/10 until intended Japanese-speaking household viewer has watched at least 10–15 uninterrupted minutes with Japanese subtitles.
- If Google 4B is worse than the subtitle-tuned model, stop and keep existing tuned model provisional. If it wins on semantic accuracy but loses slang/tone, consider an **optional** selective review second pass only with evidence of a real net benefit. Do not force two models or auto-process thousands of files based on this pilot.
- No more prompt micro-tweaks before receiving actual model outputs and language-quality judgement.

## Run (Mac mini checkout; after code merged)

\`\`\`bash
cd ~/Downloads/bruiser-subhub-repo
git pull --ff-only
bash tools/run_translategemma_004.sh optiplex@100.121.156.34
\`\`\`

The runner:
1. Runs all local synthetic regression tests.
2. Stages only source/scripts under the separate server \`~/bruiser-pilot/subhub-benchmark\` scratch directory.
3. Checks the **frozen English source hash and cue windows BEFORE any download**.
4. If needed, explicitly runs \`ollama pull translategemma:4b\` (about 3.3 GB; may need some free server disk).
5. Checks official model ID/family/quantization and the existing subtitle tuned model ID before inference.
6. Acquires existing worker locks, runs 96 isolated Ollama calls, writes one **private create-only JSON** to the server review directory and copies it to Mac mini Downloads.
7. Does **not** replace production service, alter SQLite cues, published Japanese SRT, media/video, model settings, or restart running queue jobs.

Private EN/JA data must never be committed to this public GitHub repository. Public ledger should record model IDs/hashes, numeric results, paraphrased errors and decision only.

## Real results

**PENDING. Synthetic tests cannot establish Ollama availability or Japanese linguistic quality.**
