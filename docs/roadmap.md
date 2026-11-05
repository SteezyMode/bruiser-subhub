# Engineering priorities

> **Priority update, November 5:** Production strategy is sourced-Japanese-first, with ffsubsync and create-only sidecar publishing. The live OptiPlex controller has completed real source-to-sidecar operations. The historical first section below describes *earlier* translation-centric priorities and does not supersede [the current architecture](WHAT_IS_SUBHUB_AND_HOW_TO_USE_IT_2026-11-05.md), [hybrid source/DIY policy](HYBRID_JAPANESE_SOURCE_VS_DIY_POLICY_2026-11-05.md), or [isolated PLaMo 0.8B / 2B evaluation](PLAMO_3_TRANSLATE_EVALUATION_2026-11-05.md). No model should be automatically deployed or inserted into the currently working source-only scheduler.


**Actual mission is [GOAL.md](../GOAL.md).** Deliver free, natural Japanese subs across the household's existing media; the custom code is expendable. Dual-subtitle playback is already handled.

## Current phase: scale the household library without another one-film debugging cycle

1. Obtain/review the existing **private Primate English/Japanese 80-cue sample**. Rate meaning, naturalness, speaker consistency, and readability; structural checks are not proof of good subtitles. Test any better free local translator on the *same* material before replacing the engine.
2. Run `tools/library_census.sh` read-only across both video roots. Categorize pre-existing Japanese, extractable English text, OCR-only sources, and titles missing English tracks. **Do not auto-queue from filename guesses.**
3. Reuse existing discovery/extraction components (Sublarr, ffprobe, Subtitle Edit) where practical; make only the minimal reliable bridge from proven English SRT into the resumable translator. Preserve all edited Japanese and limit GPU use to idle periods.
4. Resume the two queued pilot jobs when scheduling and translation quality are acceptable; do not block library progress on further Heretic-specific fixes.

## Historical / subsequent: understand production translation outcomes

1. Inspect current queue, cue completion, isolated errors and published sidecars; do not infer success from HTTP 200 or a loaded model.
2. Export a representative translated film's EN/JA alignment for a *human* linguistic review. Cover dialogue, named entities, negation, register, timing and compression. Never treat HY backtranslation as ground truth.
3. Benchmark actual Gemma throughput, correction rate, and per-title completion, plus CPU/GPU pressure while the desktop is used.

## Make daily use dependable

4. Vendor or replace the legacy Gemma adapter so a fresh checkout works without `bruiser_auto.py`. Keep the known-good prompt behavior in golden tests, then compare output on the same source cues.
5. Make source selection independent of the old Sublarr container; separate discovery/extraction from translation. Handle tracks with no usable English SRT as explicit queued/held cases, not fake translations.
6. Add documented, reversible systemd services and a guided configuration for user-specified media roots, models, and quiet hours. Preserve the existing SQLite state via versioned schema migrations and backup before deployment.
7. Harden local API/auth before any integration with Bruiser/OptiPlex NOW. SubHub stays an independent service; NOW can provide an optional client integration later.

## Non-goals for the initial daily-use release

- Mandatory HY approval or auto-replacing Japanese with HY guesses.
- Promising dual-subtitle playback; that is a separate player/Jellyfin capability.
- Shipping movie files, subtitles, translation memory or local paths to GitHub.
- Breaking or stopping the currently running pilot to deploy development changes.
