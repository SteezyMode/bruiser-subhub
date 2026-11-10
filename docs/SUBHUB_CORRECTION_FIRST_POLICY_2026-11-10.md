# Bruiser SubHub: owner-canonical correction-first policy (2026-11-10)

**This decision supersedes any older project document or comments suggesting "strict intake", arbitrary rejection thresholds, throughput optimization, or mandatory custom software.** The objective is to watch movies/television with Japanese subtitles on the existing Jellyfin library. Household utility beats feature breadth, code volume, or startup-style metrics.

## Operating rules

1. **Permissive sourcing and preservation:** Query configured sources, retain plausible *and* ambiguous Japanese results, downloaded candidates, original subtitle bytes, and source evidence. A zero-result response, missing metadata, or unsuccessful automated match is not proof that subtitles are unavailable. Investigate alternate provider titles, seasons, episode orders, release variants, and retained downloaded candidates before concluding sourcing is exhausted.
2. **Spend time fixing, not rejecting:** Attempt justified offset, variable-drift, release-timebase and scene-cut corrections; compare multiple subtitle candidates; review manually when needed. Extra per-episode compute/review time is acceptable. Correct errors in old published subtitles as well as newly found ones.
3. **Distinguish availability from readiness:** A candidate may be **FOUND / NEEDS IDENTITY REVIEW / NEEDS TIMING REPAIR / NEEDS TEXT REVIEW / VERIFIED / PUBLISHED / WITHDRAWN AFTER REVIEW**. Do not collapse all non-published candidates into "missing subtitles". Never erase candidate history after a later empty search.
4. **Evidence-based, reversible publication:** Identify the correct movie or episode, check Japanese content, inspect beginning/middle/end timing, and verify corrections with independent evidence wherever possible. Maintain a recoverable original and rollback path. **Previously accepted/published subtitles can be rejected and ejected from active Jellyfin playback if a thorough identity, dialogue, timing and repairability investigation demonstrates that they are unusable.** Exhaust reasonable repair or replacement first; never delete the only copy. After an evidence-backed rejection, quarantine/withdraw the published sidecar with an explicit, logged, reversible operation; do not leave a known-bad subtitle active merely because it passed an earlier gate. When evidence is insufficient, mark for review rather than assuming good or bad.
5. **Reuse existing tools:** Sublarr and Jellyfin are the primary substrate. Avoid building a second orchestration stack or show-specific controls unless a demonstrated gap cannot be solved with installed tools.
6. **AI is a last-resort source**, not the next step after one failed provider request. Inspect/repair Japanese subtitles first. Compare PLaMo's already-finished output with human-authored Japanese for concision, tone, names, idioms and timing.

## Active validation

- **Known timing concern:** *It's Always Sunny in Philadelphia* S01E04, "Charlie Has Cancer"—Japanese dialogue is several seconds late in parts of the cold open but closer mid-episode. A constant shift is **not** assumed to fix it.
- **Control case:** S01E05, "Gun Fever"—spot checks closer to English timing, but neither this nor runtime similarity guarantees full sync.
- **Provenance hold:** Five staged S02/S03 Japanese subtitle files exist, but their current search-history entries lack original candidate IDs. Preserve files; independently verify episode identity and recover evidence before final publication.
- **Translation review backlog:** Four completed PLaMo IASIP Japanese subtitle outputs; review against known-good sourced Japanese after timing work.

## Implementation / acceptance order

1. Run a **read-only** timing comparison for already-published S01E04 and S01E05 with per-section evidence. Report missing/uncertain reference honestly. Never alter existing files during this phase.
2. Validate the audit's positive and negative behavior on host examples. A misaligned cold open should be distinguishable from a plausible control; otherwise improve the method before drawing conclusions.
3. Add candidate **repair previews**, preferably reusing installed synchronization tools. Require before/after evidence for corrections; never blindly reshift all published subtitles.
4. Extend audits to other episodes and movies, including existing published sidecars. Make work selectable and resumable, with outcomes good/corrected/review-needed; only then consider a library-wide repair pass.
5. Resolve stranded provenance candidates and review AI translations without changing the source-first priority.

**States must report reality:** code committed to GitHub != installed, a diagnostic candidate != verified, and runtime closeness != synchronization confirmation.
