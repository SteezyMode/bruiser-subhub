# Translation model radar — November 2, 2026

**Research record only.** Nothing is downloaded, installed, tested or deployed by this PR. Source links verified November 2, 2026. Goal: natural, unsanitized English→Japanese movie dialogue above generic machine-subtitle quality, on RTX 3050 6GB / 32GB RAM, with no unnecessary model/prompt loops.

## Already tested: do not duplicate

- Benchmarks 001–004 tested regular Gemma 4 e4b, 17slever17's subtitle-tuned Gemma4 E4B using generic and native prompts, and official Google TranslateGemma 4B; read RESULTS_001 to RESULTS_004 and RUN_LEDGER before proposing another comparison. Native subtitle Gemma E4B is the **provisional** movie-translation winner, not deployed as production and not native-viewer graded.
- Earlier the user actually installed and ran `kaelri/hy-mt2:1.8b` (1.7GB), primarily for **Japanese→English backtranslation QA**, including full-episode runs. Also compared Index-Translate 2B for QA. It was NOT a controlled main English→Japanese translation test. HY backtranslation is advisory and can introduce its own errors. Avoid describing Hy-MT2 1.8B as totally untried.

## Best new EN→JA candidate #1 — CyberAgent CAT-Translate-3.3b

- Model: https://huggingface.co/cyberagent/CAT-Translate-3.3b (MIT license, Japanese↔English specialist, 3.3B). Native user instruction translates English text into Japanese; use model's actual chat template, not our Gemma4 JSON batching.
- Vendor's self-evaluation includes English→Japanese **business dialogue**. Their results: 3.3B EN→JA average BLEU **34.80**, 7B **34.31**; on BSD English→Japanese dialogue 3.3B **17.21**, 7B **16.29**. These differences are small and cannot establish superior horror/slang localization.
- A GGUF exists for **3.3B-BETA**, https://huggingface.co/mradermacher/CAT-Translate-3.3b-beta-GGUF, but that is NOT the final 3.3B release. Do NOT accidentally benchmark beta and claim it tests final. Verify final GGUF/chat template/source digest or use official original weights with reproducible inference. With appropriate quantization this is a sensible 6GB-GPU test.

## Candidate #2 — official Tencent Hy-MT2 7B (distinct from tested 1.8B QA)

- Model and official Q4_K_M GGUF: https://huggingface.co/tencent/Hy-MT2-7B-GGUF . Released May 21 2026, Apache 2.0; Japanese supported. Q4_K_M file **4.62GB**. Official Ollama invocation is `ollama run hf.co/tencent/Hy-MT2-7B-GGUF:Q4_K_M`.
- Model supports contextual translation and terminology preferences. It may just fit an idle RTX3050 6GB with short context, or need CPU-layer offloading, so check actual free VRAM and model residency. No claimed full-GPU compatibility until tested. This 7B model is untested here as an EN→JA translator; it is not the already-tested `kaelri/hy-mt2:1.8b`.

## Bigger models: possible but lower-priority

- https://ollama.com/library/translategemma:12b : Google TranslateGemma 12B Q4_K_M **8.1GB**, thus necessarily CPU/RAM offload on RTX 3050 6GB. Google's claimed translation MT benefit does not refute our observed poor official **4B** movie dialogue. Slow, later test at most if small specialists do not pass viewing review.
- Hy-MT2 30B-A3B Q4 ~18.2GB, 27B TranslateGemma Q4 ~17GB: neither viable as a reasonably fast GPU-first household service on this hardware; 30B's 3B *active* parameters does not shrink resident weights to 3B.
- PLaMo Translate **third generation** service was updated October 7 2026; https://translate.preferredai.jp/news/20261007-1-plamo3-major-update/ . Publisher says locally downloadable open weights in multiple sizes are **planned**, not verified released as of this research. Watch for verified offline weights; do not replace local-first pipeline with paid cloud.

## Research indicates context matters more than another decoding tweak

- WMT26 video-subtitle findings, https://aclanthology.org/2026.wmt-main.58/ : contextual prompting, terminology consistency, candidate generation/selection and deterministic checks correlated with stronger systems; these are **cross-system associations**, NOT causal ablations.
- WMT26 top system, https://aclanthology.org/2026.wmt-main.207/ : Hy-MT2 7B plus Gemma4 12B and full-video context. Its internal 122-cue test found contextual gains of 4.1–18 points on five target languages. **CRITICAL: WMT26 tested Simplified Chinese source subtitles, not English→Japanese**. This suggests a hypothesis, not a predicted gain for our films. Multi-model second pass is optional, not a mandate.
- Our actual 1.2-second English multi-speaker cues with 20–40 JA characters/second require attention to subtitle *timing/segmentation* as well as translation. Never remove insults, sexual meaning, profanity, jokes or speaker turns merely to meet a length cutoff.

## Recommended sequence to avoid circular work

1. Generate a **continuous private 10–15-minute subtitle sample** using already-tested Benchmark 002 native E4B format (not seven older published legacy samples). Intended Japanese viewer watches with only Japanese on, records comprehension, dialogue naturalness, unsanitized tone and missed timings. No production writes or overwrites.
2. If review indicates substantive language errors, run ONE reproducible **new-family** model-native comparison using final authentic CAT-Translate 3.3B (once correct GGUF/runtime confirmed), and possibly Hy-MT2 7B Q4 with short genuine context. Include fresh scene material and held-out cues, paired with existing E4B; retain texts privately and record summarized error types in GitHub.
3. If a genuine better model emerges, implement new-job-only translation with source/checkpoint protection, optional nonblocking density flags, and preserve approved Japanese; then resume the 2,026 English-source candidates out of 13,199 scanned videos. No forced two-model full-library workflow.
4. Monitor new local PLaMo Translate 3 weights only when formally published; no unverified model download.

Evidence limits: vendor self-benchmarks are not independent household watchability ratings, and no fresh candidate above was tested in this research PR.
