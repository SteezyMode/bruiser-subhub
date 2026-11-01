# Benchmark 001 — measured results and caveats

**Real local-model run completed 2026-11-01, 23:36 JST.** Results are from the privately uploaded file `primate-model-matrix-v1-20261101T143341Z.json`. The private file and all movie dialogue stay out of GitHub. This is a *risk-enriched* 64-cue English→Japanese sample, not a random sample of the whole library.

## Frozen inputs and models

- Source job ID: `primate-2026-1080p-amzn-web--ad1c564197`
- English source SHA-256: `8967cfea3f6552c0a6b1645da13e0d79e62be2decb95c02c653e6a345c3b645a`
- Eight contiguous windows of 8 cues, centers: 35, 71, 143, 207, 265, 380, 428, 465
- Ordinary `gemma4:e4b-it-qat`, installed model ID `ee6656371218`
- Subtitle-tuned `hf.co/17slever17/translate-gemma-4-sub-e4b-GGUF:Q4_K_XL`, installed model ID `9ccfc3b07081`
- Service SHA-256 `24b8c20a4149c520a300eb7ce909f4a80928eb7da3f54e18898811fe3a8fa45c`
- Localization policy SHA-256 `4fe907bd447b241953d351fe3c94594647cd3e6eb43ab902bbec9aa3a4d09ceb`
- Legacy adapter SHA-256 `ef7c5eeedd0a6e488daa6f76d4f7d5cdc856686301c3594e49fed4ac424a8c62`

## Results verified from the run JSON

| Model | Prompt | Returned / accepted | Median Japanese chars/s | >14 chars/s | Eight call seconds | Recognizable formatting contamination |
|---|---|---:|---:|---:|---:|---:|
| Ordinary Gemma e4b | baseline | 64/64 | 6.25 | 4 | 45.26 s | **0** |
| Ordinary Gemma e4b | faithful_8 | 64/64 | 6.95 | 4 | 38.63 s | **2** |
| Subtitle-tuned Gemma 4 e4b | baseline | 64/64 | 6.60 | 6 | 58.15 s | **6** |
| Subtitle-tuned Gemma 4 e4b | faithful_8 | 64/64 | 6.85 | 5 | 51.37 s | **6** |

Total: **32/32 successful calls, 256/256 returned responses, 0 call errors**. Recognition checks cover obvious unmatched closing Japanese quotation marks, JSON/serialized punctuation and HTML entities; this is *not* a comprehensive detection of bad translations. The existing publisher validator accepted all 256, including 14 obvious format problems. A reusable read-only checker was added as `tools/analyze_model_benchmark.py`, with synthetic tests; its classifications are not a quality score.

### Initial non-native editorial observations (no fabricated numeric rating)

- Regular Gemma was usually cleaner in this test and sometimes preserved questions and scene relationships better.
- The subtitle-tuned version sometimes better captured a directed insult, a violent threat or a seat-switching idiom, but also produced unsupported details, confused speaker intent in certain passages, and leaked quote/serialization fragments.
- Both models could mishandle rhetorical questions and sexual slang; the `faithful_8` instructions did **not** make either model reliably unsanitized or consistently faithful.
- Overlong fast dialogue remains an issue in several scenes. Shorter Japanese must not be rewarded when it drops speaker turns or alters intent.
- **No credible native Japanese viewer score has been collected. No arm is certified 8/10.** These are preliminary unblinded assistant findings; models were not hidden during review.

## Critical caveat discovered after the run: this is NOT a fair model-native comparison

The subtitle-tuned model's [published model card](https://huggingface.co/17slever17/translate-gemma-4-sub-e4b-GGUF) explicitly trains for:

- A system task to translate source-language subtitles into Japanese.
- A **single** `[CURRENT_SOURCE]` segment as the item to translate.
- Optional `[PREVIOUS_SOURCE]` and `[PREVIOUS_TRANSLATION]` segments for *context only*.
- Explicit preservation of tone, slang, profanity, uncertainty, repetition and incomplete speech.

**Our benchmark instead forced BOTH models through the same legacy `bruiser_auto.build_prompt()` structured multi-cue JSON scheme.** That standardizes an interface but may disadvantage the tuned model and explain some artifact leakage. It does not demonstrate that the subtitle-tuned model is inherently worse, and we must **not** dismiss it on this evidence alone.

There is also a distinct official Google **TranslateGemma** family (Gemma 3 base; 4B, 12B, 27B). It is NOT the third-party Gemma 4 Sub fine-tune we tested, and official TranslateGemma has **not** been tested in this project.

## Decision and bounded next experiment

1. Keep ordinary Gemma baseline as the **provisional safest existing production option**; do not promote `faithful_8` or the tuned model on these results.
2. Run **one focused native-format test** of the *already installed* subtitle-tuned e4b against the same difficult cues, with real previous-dialogue context and a literal current-segment-only response. Use read-only source, isolated model calls, a private output file and the same meaning/tone/readability evaluation. No blanket model downloads, transcript rewriting or mass rollout.
3. Multi-pass (two models, draft + critic, or selective review) remains **optional**: test only if a single-pass system demonstrably misses problems that a second, independent model can correct. The second pass must prove net gains and avoid introducing errors; don't automatically translate all 2,026 ready-source candidates twice.
4. If the native prompt experiment remains mixed, do not iterate prompts endlessly. Evaluate the actual watchability of a brief Japanese-only sequence with the owner's Japanese-speaking partner and then choose a practical baseline or another truly different translator.
5. When a model/prompt wins, follow the already recorded roadmap toward source extraction and cautious, non-destructive library-scale queueing.

**Experiment status:** 001 completed/recorded, native-format follow-up **not run**. Never put source dialogue or full model outputs into public GitHub.
