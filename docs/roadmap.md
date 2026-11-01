# Engineering priorities

**Actual mission is [GOAL.md](../GOAL.md).** Deliver free, natural Japanese subs across the household's existing media; the custom code is expendable. Dual-subtitle playback is already handled.

## First: understand the production translation outcomes

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
