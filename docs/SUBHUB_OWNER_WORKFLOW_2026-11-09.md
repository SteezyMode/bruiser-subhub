# SubHub handoff — 2026-11-09

**Status:** owner-approved UI and pipeline plan. This document does not mean the changes are installed or working on the OptiPlex. Use this as the starting point in the next chat. Existing product issues: #86 (GUI/queue), #67 (native-source fallback/PLaMo), #64 (source recovery), #66 (background state).

## Purpose

Get usable subtitles in the **selected language** for any library movie or episode. **Japanese defaults** because most household use is English audio → Japanese subtitles. Do not hardcode Japanese as the only possible target. Only offer languages for which providers and/or the available translation model actually support the requested path.

This is hobby software. Preserve working pipelines, existing folders, media, downloaded subtitle bytes, checkpoints, credentials, thermal guards and create-only publishing. No enterprise ceremony, extra dashboards, new databases or show-specific workflows.

## Main interface

**Library | Work Queue | AI Activity**. Small **Settings** control.

Use established Sonarr/Bazarr episode coverage and Transmission queue conventions. Short labels. Remove motivational headings, copy such as **"Finish a season, not just a sourcing pass"**, and "X, not just Y" phrasing. No useless grey error walls, full progress bars on incomplete work, historical jobs in live status, or a second file search panel. Raw logs in optional Diagnostics only.

### Library (default)
- One type-to-search input for **movies and TV**, with simple media-type filter. The lookup merges **real files** (recently downloaded editions must appear immediately) and Jellyfin/subtitle metadata. Display exact movie editions without conflating the 119-minute and 144-minute cuts of *The Shining*. Avoid a blocking full-drive rescan on each keypress: cached catalog + bounded direct refresh.
- **Subtitles: Japanese ▼** is the default language dropdown. Persist the last selection.
- TV: click a show, select **Season** from one dropdown. **Multiple seasons** expandable. Expand season to view/select episodes; show per-episode coverage. No gimmicky "Select seasons 1–5" button, no giant unsearchable show dropdown.
- Headline counts **episodes**, e.g. `7 episodes need Japanese subtitles across 4 seasons`, not `4 season/movie tasks`. Show how many have usable target-language subtitles, are queued, and need attention. Mark seasons with full coverage.
- Episode row: prominent, readable `Available`, `Missing`, `Working`, or `Needs attention`. Under details: source (existing, provider, AI), actual processing steps, failed candidates, next action.
- Main action **Add missing to queue** or **Add selected to queue**. Don't force the user to choose the source engine, a failed-job retry mode, or supply native-language captions.

### Work Queue
- **Active | Queued | Needs attention | History**. Queued work persists independently of browser. Add more work while a job runs; remove/reorder pending; pause/resume/cancel at supported safe boundaries. No inert controls.
- Each item: movie/episode identity, requested language, phase, x/y covered, concrete result/next step, last *actual* activity. E.g. `15 episodes · 11 available · 4 missing`; a sourcing run finishing is not full coverage.
- Expand items for sources tried, sync status, limits, exact held reason and supported action. Don't show `English source needed` in the main view for a request for Japanese; it is a private fallback step.
- Failed old *Shining* task and finished American Dad checkpoints belong in **History**, not the top “Current activity.” If no actual worker, header says `Idle`.

### AI Activity
- Say `AI idle` when no live LLM process. Otherwise show running model, exact title/episode, translated cues N/total, actual progress, temperature, power, RAM, thermal pause when available. No inferred running status from ancient saved checkpoints. Link from main header.

### Settings
- Simple headline: **Downloads left today** and reset time **only if verified**. Provider details under Settings: actual allowance/used/remaining/reset, which account/provider reported it, searches versus chargeable download requests; unknown if unavailable.
- No "Japanese subtitle acquisition budget" or comparable jargon. Provider keys are internal and never exposed.

## Per-item automated pipeline

1. If usable subtitles already exist in the **selected target language**, mark Available.
2. Search target-language subtitles; reuse existing metadata and staged bytes first. Verify title, season/episode, exact edition, language and dialogue coverage; sync timing with proven repair; publish create-only on the **OptiPlex host**. The Sublarr movie-library bind mount is read-only. The owner-verified 144-minute *Shining* is a working example of OpenSubtitles → validate → ffsubsync → host publish.
3. If no usable target-language source after bounded attempts, determine **original spoken language**. Reuse embedded/sidecar native-language text or automatically source validated native-language subtitles. EN is the fallback *source* for most shows, not the user-requested outcome. No user intervention in normal case.
4. Translate native→selected language using the **supported** local model (EN→JA PLaMo now), checkpoint cues and protect Wolf/gaming/GPU/CPU thermal limits. Preserve original timing/dialogue and run QA; publish create-only. Translation unsupported for a pair → explain under Needs attention; don't pretend model supports all languages.
5. Actual blocker after these paths are tried → Needs attention with one meaningful action (saved-candidate recovery, another edition, edit held cue, resume, etc.). Do not charge again for saved candidate data or loop a blind Retry forever.

## Provider counts and quota behavior

Owner wants **one work queue** and practical use of all lawful, genuinely available provider capacity. Additional API keys are fine, but two keys on the **same account** must not be counted as separate allotments unless the provider explicitly gives independent quotas. Pool work, not fabricated limits.

- Reconstruct historic counts (past 24h/48h/7d) from **saved search history, stage DB timestamps, provider account records and service journals**, then say which numbers are verified and which are incomplete. 600 searches ≠ 600 downloads; staged ≠ charged; published ≠ downloaded today.
- Going forward, record provider/account identity (nonsecret), timestamp, candidate, successful/failed download calls, stage and publish separately. Use provider-reported allowance and reset when available, and observe actual rejections/cooldowns.
- Use the allowance deliberately up to a small user-set reserve after accounts/limits are verified; stop gracefully before known quota exhaustion and resume after reset. No quota probing that makes useless repeated downloads or evades per-account limits. Work may be acquired from multiple providers, but the GUI headline can be unified only if a defensible combined remaining count is available.
- OpenSubtitles API consumer `BruiserSubHub` was registered as **Under dev**; do not assume 100/day until actual authenticated `allowed_downloads`, `downloads_count`, `remaining_downloads` and reset are read. SubDL download/search limits are distinct.

## Implementation order and acceptance

**Slice 1 — Honest, usable Library:** unify discovery, searchable series, language selector, per-episode coverage counts, strong status rows; hide clutter/history. Verify added movie appears immediately even if Jellyfin cache stale. No second search panel.

**Slice 2 — Real queue and job states:** adapt *existing* persistent coverage/staging/checkpoints and worker ownership. Add enqueue/reorder/stop/retry, real active/idle, durable per-item outcomes. Avoid creating a competing scheduler or relying on transient systemd unit states alone.

**Slice 3 — Full automatic fallback:** target subtitle → sync/publish → native subtitle sourcing → PLaMo → QA/publish. Safely restartable; no repeated provider charges for saved bytes. Pilot the still-missing *It's Always Sunny in Philadelphia* S1–S5 episodes (recheck current coverage; prior screenshot example said seven episodes across four seasons, not a live inventory statement).

**Slice 4 — Usage/AI reporting:** source-attributed download counts, provider reset data and quota-friendly scheduling; genuine PLaMo live process/temperature/cue progress. History and optional Diagnostics.

**Tests/verification:** a season with 11/15 published shows 4 missing; held Japanese source does not become `No English subs`; downloaded cut A does not match movie cut B; native EN automatically sourced when needed; a newly downloaded movie is searchable without waiting for Jellyfin; active PLaMo displaces old failed batch in header; browser closure/reboot preserves work; publish cannot overwrite an existing subtitle; no false quota numbers.

## Current known state at handoff

- Host-verified *The Shining* 143.78-minute BONE movie in the existing 2TB Horror folder now has Japanese sidecar that owner confirmed plays **perfectly**. Original shorter file deletion command was provided, but successful execution **not independently confirmed**.
- GitHub has new generic movie-host publishing source and a standalone movie job plus a basic GUI path, but owner's installed GUI is a *different newer local completion workbench*. Merge into that version; **do not overwrite installed UI with older GitHub HTML**.
- An owner-facing overlay package `SubHub-Nov9-Movie-Workflow.zip` was prepared but installation was not verified from user output. Later unified-library and UX mockups were local iterations, not verified deployments. Inspect actual installed version and back it up before modifying.
- The English-source→PLaMo fallback is still incomplete and genuine queued-work management is not verified end to end. No claim of a finished SubHub.
- Primary reference issue: https://github.com/SteezyMode/bruiser-subhub/issues/86.


## Library Phase 1 implementation — November 9 (local tested release, host acceptance pending)

Produced the guarded install package `SubHub-Library-Phase1-20261109.zip` in the current chat (contains the exact source and rollback installer). Source files: `subhub_dashboard.html` (new three-tab Library/Work Queue/AI Activity plus Settings), `subhub_dashboard_server.py` (one Library API, direct movie files, indexed+live TV directory discovery, exact-episode job API), `subhub_completion_queue.py` (per-episode coverage and exact episode scope), and `subhub_season_sources.py` (restrict search/stage/publish to owner-chosen episodes), plus tests. The new source **has not yet been merged into the public repo `tools/` directory**: source of truth for this version is the ZIP until a verified GitHub source upload. Do not replace installed host code with the older GitHub dashboard. Installer is SHA-guarded for the known Nov 9 owner-completion and movie dashboard version; backs up previous files and refuses unknown installed versions or active subtitle workers.

Verification: Python syntax, node `--check`, six offline tests and a headless Chromium test with mock API passed for exact BONE movie and exact S03E03 request, with no JS exceptions. **No OptiPlex deployment or full provider/AI run verified**.

Functional scope: one typed search with Movies/TV switch, Japanese subtitle selector (only supported language enabled), exact movie version/year, per-season/episode coverage rows and exact-episode selection. The temporary Work Queue view reflects current worker plus stored completion result but still cannot append jobs while running. Native-language subtitle acquisition, multi-target translation, real provider quota numbers, actual AI temperature telemetry and cross-browser restartable queue are NOT finished. On new chat: first inspect installer output/host acceptance; then implement the durable appendable queue and native-subtitle→PLaMo fallback, rather than another UI redesign. No slogan copy or clutter should be reintroduced.
