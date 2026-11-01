# Benchmark 004 — measured Google TranslateGemma 4B versus tuned subtitle Gemma E4B

**REAL MODEL RUN COMPLETE.** Owner supplied private file `primate-translategemma-004-20261101T165711Z.json`, generated `2026-11-01T16:59:40.417901+00:00` = **2026-11-02 01:59:40 JST**. This public result retains only grounded numerical metrics and *paraphrased* language failure descriptions; no copyrighted movie dialogue or generated Japanese outputs are committed. Protocol preregistered in [EXPERIMENT_004.md](EXPERIMENT_004.md).

## Models, source and parameters actually used

- Source job is *Primate*; frozen English source SHA-256: `8967cfea3f6552c0a6b1645da13e0d79e62be2decb95c02c653e6a345c3b645a`.
- Google official model: `translategemma:4b`, Ollama ID `c49d986b0764`, **Gemma 3 4.3B**, `Q4_K_M`. The official single-user English(en)→Japanese(ja) prompt was used, with **two blank lines** before the current English cue, **without history or a system/profile instruction**. Ollama `/api/generate`, `num_ctx=4096`, `num_predict=256`. No explicit temperature/top-k/top-p overrides. `/api/show` reported `top_k=64`, `top_p=0.95`, and a stop token.
- Existing subtitle-tuned model: `hf.co/17slever17/translate-gemma-4-sub-e4b-GGUF:Q4_K_XL`, Ollama ID `9ccfc3b07081`. Reused Benchmark 002's single-current-segment native instructions with up to two earlier successful within-window source/translation pairs. Both models use their **respective intended interfaces**; this compares workflows, not only architectures under identical settings.
- Google prompt SHA-256: `d8343d4381d837463d76c5f7c1da83eb5835b7106ed6ca3698627b65579160d8`.
- Google model template SHA-256: `e0a42594d802e5d31cdc786deb4823edb8adff66094d49de8fffe976d753e348`.
- Benchmark code SHA-256: `261ac58a8c6ca8c6f9af67cded708c0deab766860c716b6f8a9ce8cd66c7bf58`; source service SHA-256: `24b8c20a4149c520a300eb7ce909f4a80928eb7da3f54e18898811fe3a8fa45c`.

## Actual results

The preregistered design yielded **80 Google outputs** (64 previously examined anchors + 16 newly held-out English cues) and **16 new subtitle-tuned outputs** on the same held-out cues. **96/96 model calls succeeded, 96/96 Japanese strings accepted by the existing broad validator, zero detected serialization/formatting artifacts.** None of those automatic indicators measure correct meaning.

| Dataset / model | Returned | Valid | Formatting suspects | Median JA chars/sec | >14 JA chars/sec | Summed model-call time |
|---|---:|---:|---:|---:|---:|---:|
| Google official 4B (all 80) | 80 | 80 | 0 | 9.15 | 12 | 79.26s |
| Google official 4B (**16 held-out**) | 16 | 16 | 0 | **9.0** | 2 | **12.99s** |
| Subtitle-tuned Gemma4 E4B (**same 16 held-out**) | 16 | 16 | 0 | **6.6** | 2 | **17.07s** |

The held-out median reading density is **~36% higher for Google** than tuned Gemma (9.0/6.6), although both have two cues >14/s. **Do not infer Google is better at throughput from the 12.99 vs 17.07 seconds**: different model size, warmup, prompt length and previous-dialogue context. Google's 80-call total includes ~14.1s for the first call; tuned model's new 16-cue run includes ~5.4s first call. Exact wall-time, full-film cost, energy and VRAM peak were not measured.

## Meaning and spoken-Japanese review — primarily 16 fresh paired cues

This is an **unblinded editorial assessment**, NOT an independent native-Japanese viewer score.

- **Tuned E4B substantially more usable for informal household dialogue on these 16 cues**. It correctly uses informal affirmations and short commands, preserves that *people* should have arrived at a location, translates a request to *repeat words along with the speaker*, and often avoids corporate-service politeness. Google produced implausibly formal Japanese equivalents of casual apologies, yes/no replies, staying nearby and asking whether someone wants an object. It misread *people already there* as *objects located there* and expanded a simple request to repeat speech into a request to express one's feelings. Several Google lines are also unnecessarily verbose or unviewable at their original timings.
- **Neither model is free of serious mistakes.** In the held-out children's-TV catchphrase, Google's name/transliteration varies and the tuned model replaces stealing/swiping with physical *touching* and sometimes adds an unsupported claim about dialogue playing on television. For the fetch command, Google invents a request for help, while tuned incorrectly turns the second command into the speaker saying they themselves will go. The sample has no unambiguous 16/16 winner.
- The tuned model is **not guaranteed 8/10**; it still sometimes misrepresents speaker intention, names, and multi-speaker or time-constrained dialogue. Do not equate more concise Japanese with higher meaning accuracy.

## Familiar 64 anchor cues confirm Google's failure pattern

On the previously tested anchors, Google's official native prompt produced additional meaning and register problems:

- A flirty/social reference to a **player** became a sports athlete; meaning and slang lost, with extremely dense timed output (cue 207, ~40.2 JA chars/sec).
- A conversation about taking the undesirable **middle seat** acquired an unsupported **eating** action (cue 74).
- A directed vulgar rejection became a statement about **mocking someone**, erasing the actual insult (cue 378).
- A simple past-tense denial became a denial of **being present**, and a nearby character's name was modified (cue 265).
- A sentence saying the speaker **would not return until Tuesday** was translated as an affirmative intention to return **by Tuesday** (cue 267): material temporal/negation drift.
- An emotional expression of **loneliness** became a comment about the location being **quiet** (cue 145).
- Many other lines became administrative/corporate-sounding speech in casual or frightened conversations; some characters addressing family/friends sounded inappropriately deferential.
- English “Whore Mansion” was turned into a largely **phonetic proper noun**, losing the sexual/crude content (cue 263).
- Most of these invalid or awkward Japanese strings **passed the current publisher structural validator**, showing why output-shape checks cannot certify translation quality.

These are clear failures of *this actual model-native 4B output*. They do **not** establish every future official TranslateGemma generation or higher-capacity 12B variant would behave identically.

## Decision: model-native test concluded

1. **Do not promote Google `translategemma:4b` as the movie/TV translator**, and do not automatically use it as a critic or second pass. Its current one-cue official format introduces substantive tone, semantic and length problems relative to the tuned E4B model. On this sample it is not the hoped-for solution to SubtitleCat-quality Japanese.
2. **Keep 17slever17 subtitle-tuned E4B Q4_K_XL with Benchmark 002 native profile as our *provisional preferred local translator*.** That configuration got 64/64 structurally clean outputs and better preserved a number of important threats, vulgar insults, denials and idioms in prior reviews. This is a research recommendation only; **the production worker was NOT updated** and existing published Japanese remains unchanged.
3. **Stop prompt/decoding/quantization carousel.** No compelling evidence for a new model download, higher precision or forced two-model architecture. If source/context quality still disappoints, the next high-value information is **10–15 minutes of Japanese-only viewing by the intended Japanese-speaking household viewer**, with comments on comprehension, slang/profanity/tone, dialogue flow and missed timings.
4. If that actual viewing check finds the model usable, integrate the existing native prompt into a cautious **new-job** worker path with non-destructive artifacts, source integrity checks and density review flags, then work toward the 2,026 English-text candidates out of the 13,199 scanned videos. Do not bulk replace previously published tracks.
5. If a real viewer finds persistent meaning errors, test **one material change** on representative, new scenes (known speakers / scene glossary, truly different model, or selectively triggered second-model correction) with controlled comparisons and explicit risk of new hallucinations. Multipass remains **optional** and must prove net benefit. No more loops over one *Primate* edge case.

**Benchmark 004 status: COMPLETE and reviewed.** Private model-generated movie dialogue stays outside GitHub; actual editor viewing scores have **not** been measured.
