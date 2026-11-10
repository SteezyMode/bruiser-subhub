# SubHub — short execution plan (2026-11-10)

**Only objective:** a Jellyfin movie/episode plays with good, properly synchronized Japanese subtitles for the household. See [GOAL](../GOAL.md) and [CURRENT STATE](CURRENT_STATE.md). The former long roadmap remains in Git history; its priorities are superseded.

**P0 — one actually corrected title.** Repair the existing IASIP S01E04 Japanese cold open in a non-destructive preview, with opening/middle/end playback verification and rollback. S01E05 is comparison. Use installed ffsubsync/Sublarr features before writing new algorithms. Stop producing inconclusive timestamp charts.

**P1 — use what we've already downloaded.** Recover five held Japanese candidates with missing provenance, preserving originals and episode identity. Review four existing PLaMo tracks rather than starting fresh model work.

**P2 — independently validate our tooling choices.** Audit actual Sublarr configuration/version against its documented standalone Wanted, provider search, Sync Compare, and editor. In a backed-up isolated trial, see whether it beats the current custom experience. Bazarr requires an assessment of its Sonarr/Radarr dependency. Retire custom pieces only after proven working replacement; don't build more duplicate pieces.

**P3 — make the best workflow routine.** Per selected title: inspect existing native-language/English references, acquire one proactively when helpful, reuse/seek Japanese separately, recover/sync/verify and publish reversibly. English absence is not a Japanese-source failure; translate only when genuine sourcing and repair are reasonably exhausted and the dialogue source is verified.

**P4 — improve UI only when function demands it.** The current dashboard is better for the owner today but not satisfactory. Keep functional parts, correct misleading states and add only working controls backed by actual jobs. No second scheduler, show-specific UI or design-only rework.

No phase is complete because GitHub code or tests pass; verify actual host execution and Jellyfin playback before moving it to done.
