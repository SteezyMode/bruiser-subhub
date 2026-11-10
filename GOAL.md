# GOAL — Japanese subtitles for household Jellyfin viewing

The owner wants to watch existing movies and television with his Japanese wife. The practical target is **correctly matched, comprehensible, natural, reasonably concise Japanese subtitles, timed to the actual release**, roughly 7.5–8.5/10 for normal home viewing. Preserve character intent, jokes, slang, sarcasm, profanity, proper names and important dialogue; do not sanitize or mechanically translate idioms.

This is **not a commercial or novel software project**. The dashboard is a byproduct, not the mission. Existing software should win whenever it delivers the same or better real result with less setup and maintenance.

**Definition of done for a media item:** the Japanese subtitle is present and selectable in Jellyfin, belongs to the correct movie cut/episode, covers the meaningful dialogue, is readable and synchronized during the cold open, middle and ending, and remains available after restart. A job finishing or a subtitle being staged is not this result.

## Method

1. Identify the actual video and preserve good existing Japanese tracks.
2. Reuse retained Japanese candidates; search configured providers for genuine Japanese; keep plausible unmatched results for review.
3. Proactively inspect embedded/sidecar subtitles in the original spoken language, obtain an edition-matched text reference if useful and available, and cache it. This is **supporting evidence**, not a prerequisite for Japanese acquisition or repair.
4. Use existing tools (Sublarr, ffsubsync and other proven subtitle tools) to preview and repair offsets, drift, cuts, missing sections or edition mismatch; then verify actual dialogue. A failed automatic match is a reason to investigate, not discard.
5. Publish non-destructively, with original bytes and rollback. Previously published mistakes can be replaced or withdrawn only after evidence and repair attempts, reversibly.
6. Only after genuine Japanese sourcing and recovery are reasonably exhausted, use verified source-language dialogue and the existing resumable PLaMo worker as a last resort. Missing English matters for English-to-Japanese translation, **not** for Japanese sourcing.
7. Prefer the simplest tested end-to-end tooling. Preserve server, files, GPU/game streaming, quota limits and working jobs. Do not build a second orchestration system to avoid configuring the first.

Track progress only as **verified watchable outcomes and specific remaining failures**. Read [CURRENT_STATE.md](docs/CURRENT_STATE.md) and [the correction-first policy](docs/SUBHUB_CORRECTION_FIRST_POLICY_2026-11-10.md).

Older model-selection, dashboard, business/product and experimental plans remain in Git history and dated documents for reference; they do not override this goal.
