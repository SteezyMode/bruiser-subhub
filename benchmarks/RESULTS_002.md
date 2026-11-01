# Benchmark 002 — measured native-format subtitle-model result

**Real local inference completed 2026-11-02 01:24 JST (2026-11-01 16:24 UTC), owner uploaded the PRIVATE JSON file.** This document contains aggregated results and paraphrased failure classes only. No copyrighted dialogue or generated Japanese is committed here. Protocol pre-registered in [EXPERIMENT_002.md](EXPERIMENT_002.md).

## Immutable run identity

- Benchmark: `primate-64cue-native-sub-e4b-v1`.
- Frozen English source SHA-256 `8967cfea3f6552c0a6b1645da13e0d79e62be2decb95c02c653e6a345c3b645a`; same 64 cue IDs, 8 groups of 8, as Benchmark 001.
- Model `hf.co/17slever17/translate-gemma-4-sub-e4b-GGUF:Q4_K_XL`, installed Ollama ID `9ccfc3b07081`.
- System prompt SHA-256 `8851928ba18d43df31cfb92872034325e097f94f7d55a08836f10382e14458e0`.
- Native benchmark SHA-256 `8a012b8695f979c1572caeae5399fffa8da798784ca7b65c8f7f2ed6899ff911`.
- Source service SHA-256 `24b8c20a4149c520a300eb7ce909f4a80928eb7da3f54e18898811fe3a8fa45c`.

## Measured outcome

| Metric | Native current-segment model (002) | Previous tuned batch-JSON baseline (001) |
|---|---:|---:|
| Completed / Japanese-validator accepted | 64 / 64 | 64 / 64 |
| Recognizable formatting/serialization artifacts | **0** | 6 |
| >14 Japanese chars/second | 6 | 6 |
| Median Japanese chars/second | 6.8 | 6.6 |
| Model calls | 64 | 8 |
| Reported cumulative model-call time | 56.37 sec | 58.15 sec |
| Failed calls | 0 | 0 |
| Native Japanese viewer grade | **NOT MEASURED** | **NOT MEASURED** |

Neither total wall time nor GPU energy is proven equivalent; model call counts are different. Structural validity does not imply idiomatic Japanese or 8/10 quality. Quantitative sample is risk-enriched, not representative of the full library.

## Qualitative, provisional English/Japanese review

- Stronger performance than tuned multi-cue JSON on several denials, speaker-directed profanity, euthanasia/violence, instruction semantics and rhetorical challenges; formatting contamination disappeared.
- Clear remaining weaknesses: fast 1.2-second cues with 22–27 visible Japanese characters/second, slang meaning inversion (colloquial compliment rendered as a hostile insult), literal sexual joke, an unnatural accusation, and an ambiguous physical-vs-figurative phrase.
- **Do not certify this model at 8/10.** These are unblinded ChatGPT observations from excerpted dialogue. Native Japanese viewer test has not been performed.

## Important settings audit against the actual model card

The author's [model card](https://huggingface.co/17slever17/translate-gemma-4-sub-e4b-GGUF) documents English→Japanese translation, `CURRENT_SOURCE`, optional previous source/translation, and a neutral/friendly/official style. This experiment follows those key structures, but is **not an exact manufacturer-example replay**:

- Added `STYLE: neutral, natural spoken Japanese appropriate for adult horror` rather than card's plain neutral.
- Chose **two** previous generated subtitle pairs rather than the card example's single previous pair. Prior translated text was from the experiment, not older human/editorial Japanese.
- Used `num_ctx=4096`, `num_predict=320`; card's llama.cpp example uses `n_ctx=1344`, `max_tokens=256`. Both use temperature 0.
- Used Ollama rather than the card's llama.cpp Python example. Ollama chat template and runtime version were not pinned in the result; this limits strict runtime reproducibility.
- Eight intra-window transitions have a **gap >8 seconds** between subtitles, including 23.54, 30.99, 44.22, 45.18 seconds, but previous translations were still provided. That stale scene context may confuse the model. Resets at artificial eight-cue block boundaries also limit scene continuity.

**Conclusion:** Native format is promising and the backend demonstrably runs. Do **not** treat this as an exact to-spec default or the maximum achievable quality. Benchmark 003 will make the prompt closely match the card, then vary only **stale-context gating** on exactly the same source to measure any marginal benefit. No forced multipass architecture, no new downloads, no library-scale deployment from this result alone.
