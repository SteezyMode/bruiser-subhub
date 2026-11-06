# The actual goal

> **MOST RECENT OWNER DECISION (November 6, 2026):** [Canonical Bruiser coverage/sourcing/repair/GPU-fallback contract](docs/BRUISER_SUBTITLE_POLICY_CANONICAL_2026-11-06.md) supersedes conflicting previous model-first/source-only proposals. Repair otherwise good **English or Japanese** timing before discarding it. Search real Japanese OpenSubtitles sources first, then verified EN recovery and significant eventual local GPU translation as **last resort, not an option to avoid**. PLaMo 8B has already been accepted for American Dad; E4B model statements below are legacy context, not permission to restart model comparisons. The full existing EN+JA library baseline is complete; do not rescan without a real reason.

> **2026-11-05 implementation update:** The household's highest-yield current route is **existing Japanese subtitle sourcing + ffsubsync + create-only publication**, which the user has now verified live. Automatic DIY translation is intentionally disabled in the source-only daily timer; test new PLaMo 3 Translate 0.8B/2B only as a separate prospective fallback for titles lacking satisfactory Japanese but having correctly timed English. See [hybrid policy](docs/HYBRID_JAPANESE_SOURCE_VS_DIY_POLICY_2026-11-05.md). Older model-first production goals and proposals below are historical; they do not authorize activating translation in the live source service.


This is **not a software product**. The user has nearly 6 TB of existing movies and television on an OptiPlex media server. The user is a native English speaker; his wife is a native Japanese speaker. They want to watch that media together, especially English-audio films, with **good, natural Japanese subtitles**.

Good existing Japanese subtitles are often difficult to find and have already been pursued. Dual-subtitle playback has **already been solved** and is not part of this project. The user's existing edited Japanese subtitles are valuable and must be preserved.

## Success condition

Choose an English-language movie already in the library, press Play in Jellyfin, and have accurate, readable Japanese subtitles available—without needing to manually request translations, fix one-cue hangs, or babysit the system. Repeat that across the library in unattended batches.

## Target quality: practical 8/10, not Netflix certification

**Aim clearly above generic SubtitleCat machine translations**, not perfection.
Keep the full emotional and conversational force: idioms, jokes, slang, profanity, sexual content, violence, threats, sarcasm, and insulting language. **Never sanitize, soften, or moralize away a character's words.** Avoid inventing extra crudity, too. Natural Japanese should communicate what the character *means*, not mechanically render the English words.
Improve subtitle readability by removing filler, awkward calques, and redundant phrasing, not by cutting a threat, joke, punchline, or important meaning. Soft reading-speed guidance is useful; Netflix-style fixed counts and hard publication gates are not requirements. A comprehensible, fluent, unsanitized ~8/10 viewing experience is a success.

## Non-negotiable priorities

1. **Translation quality first.** Fidelity, natural Japanese, character/scene context, brevity, correct negations/numbers/names; no fabricated dialogue.
2. **Free and local.** Prefer running on the existing RTX 3050 6 GB, preserving its other server/desktop workloads. No paid API dependency.
3. **Library-scale automation.** Preserve the existing ~6 TB file organization; find English embedded/sidecar tracks, acquire where needed, translate and publish only missing Japanese; checkpoint and recover.
4. **Preserve human work.** Existing Japanese/editorial tracks are authoritative; never overwrite, delete or silently supersede them.
5. **Minimize software maintenance.** Use off-the-shelf free tools wherever they work better. **SubHub/Bruiser code is disposable**; stop developing it if existing tools solve the goal with less work.
6. **No irrelevant scope.** Dual-sub playback, OptiPlex NOW commercialization, dashboards, product naming, feature parity, and speculative AI orchestration are not blockers. The current production translator is the pinned subtitle-tuned E4B, not generic Gemma or Hy-MT2 7B. Read docs/PRODUCTION_TRANSLATION_MODEL.md before changing it.

## Model-use contract — mandatory

1. **Use the chosen model exactly as its developer documents first.** Read the official model card before changing prompts, sampling parameters, input shape, context, or runtime. Link and record the published template and settings.
2. **Establish an uncontaminated baseline on real English subtitles.** Evaluate raw EN→JA output for naturalness and fidelity before writing any postprocessing, multi-model review, retry scheme, quality gates, or localization profile.
3. **One translation model by default.** Do not insert an independent AI critic, backtranslation, multiple-model voting, automatic rewrites, or custom scoring unless a demonstrated problem requires it and a controlled A/B proves an improvement to the household viewing experience.
4. **Keep the subtitle machinery boring.** Finding/extracting or generating accurate English, dividing an SRT into chunks when necessary, preserving cue numbers/timings, resuming interrupted work, and safely saving Japanese sidecars are permissible file handling—not license to change the translation prompt.
5. **Respect real viewing quality.** Subtitles must be judged in context, including readable on-screen duration; passing a timestamp check does not prove readability or Japanese accuracy. Target ~7.5–8.5/10 for home use, not a proprietary Netflix-grade metric.
6. **Protect existing files.** Never overwrite existing human-edited Japanese; full-episode trial output is a draft and should never automatically publish.
7. **Any deviation requires evidence.** State the exact departure from official model instructions, its reason, and a direct comparison against the untouched baseline. No speculative "enhancements."

## CURRENT production decision — 2026-11-04 (supersedes older experiments)

**Chosen production model: 17slever17 Translate Gemma 4 Sub E4B Q4_K_XL, exact Ollama tag hf.co/17slever17/translate-gemma-4-sub-e4b-GGUF:Q4_K_XL, model ID 9ccfc3b07081.** The authoritative model card, native CURRENT_SOURCE chat format, run settings, safeguards and matched E4B vs Hy7 evidence are in [docs/PRODUCTION_TRANSLATION_MODEL.md](docs/PRODUCTION_TRANSLATION_MODEL.md). The independent native-Japanese 8/10 grade is still unproven. E4B is nevertheless the current pinned production default, not a tentative model that workers may replace freely.

The legacy Hy-MT2 evidence below is historical. Generic gemma4:e4b-it-qat produced the inadequate Attachment (2022) track and is **not allowed** as the production fallback. Existing Japanese/editorial files must never be overwritten.

## Verified clean-test state — 2026-11-03

- Gemma E4B Sub, using its previous-segment subtitle template: 30/30 cues translated. It made conspicuous literal idiom mistakes. Other earlier SubHub/Sublarr model rankings remain confounded by custom processing.
- Hy-MT2 7B Q4_K_M, Tencent **Default Translation** prompt on 30 consecutive English cues: natural translation of several difficult lines and correct idioms; raw prose, not SRT.
- Hy-MT2 7B Q4_K_M, Tencent **Structured Data 1** prompt with format SRT, Japanese target, and published inference settings: 30/30 consecutive cues translated with all 30 cue numbers and timestamps **exactly preserved**, without any rewriting. Some cues were too long for their display durations; full-episode viewing quality is **not yet proven**.
- TranslateGemma 4B, its documented prompt: faster on this 30-cue example but made omissions and awkward translations.
- **Current experiment:** translate one full episode with the *same* documented Hy-MT2 structured-data prompt, divided into 30 consecutive cues per model call solely to respect finite context; verify numeric IDs and timestamps without altering text; save a non-published draft. See [clean model-use instructions](docs/TRANSLATION_MODEL_BASELINE.md).

**This file outranks older growth/product language, legacy README workflows, and past model rankings.** Development progress is measured by actual watchable Japanese subtitles, not commits, dashboards, technical sophistication, or productization.
