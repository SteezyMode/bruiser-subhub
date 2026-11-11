# Bruiser SubHub

> **LATEST OWNER-VERIFIED HOST STATUS (Nov 11):** P0-D dashboard was installed and Sunny sourcing was tried: **78 missing, 3 held, 75 still queued, job paused** after three attempts. Independent S17E03 run **published one Japanese subtitle**. The three earlier errors cannot be recovered from the old generic logging; do not assume they were all provider failures.
>
> **FIXES NOW IN GITHUB, NOT YET DEPLOYED:** Accepted jobs visibly appear in Active Work before the first progress checkpoint, startup errors and each held episode's categorized reason show in the UI, whole-series progress persists across separate single-episode jobs, and independent media/QA holds no longer stop the next 75. Provider 429 and three actual upstream failures still pause safely. CI passing (Python 3.11/3.12): [run 42961708326](https://github.com/SteezyMode/bruiser-subhub/actions/runs/42961708326), commit `68872b6b27e9164496c998112bb175a9bb53d2e8`. **Next owner session:** one guarded install-only upgrade, then retry via dashboard; no more terminal work requested today. [Exact host audit/fixes](docs/SEARCH_RECOVERY_ROADMAP.md#2026-11-11-p0-d-host-follow-up--78-missing-sunny-3-held-75-queued-fixes-ci-tested-not-yet-deployed).

> **LATEST VERIFIED HOST RESULT — 2026-11-11:** Japanese subtitle **PUBLISHED** for IASIP S07E02, *The Gang Goes to the Jersey Shore*, via Jellyfin/subbuzz → existing private staging → FFSUBSYNC `mode=original` → create-only `.ja.srt`. **402 cues**, SHA256 `afaf762847bc25646704180536fa186805181822cd0959c381026669ffb5fcf2`. Original video/tracks unchanged. **Jellyfin playback and dialogue timing still need review.**
>
> **[START HERE: P0 search-recovery roadmap and full attempt log](docs/SEARCH_RECOVERY_ROADMAP.md)** · [Search issue #89](https://github.com/SteezyMode/bruiser-subhub/issues/89) · [Dashboard/queue issue #90](https://github.com/SteezyMode/bruiser-subhub/issues/90).
>
> **NEXT:** Generalize this proven Jellyfin-native path to **arbitrary movies/episodes** with provider-budget-aware batching and clear per-job dashboard progress. The separate Sublarr v4 `44 NONE / 1 DEFERRED` failure, movie-year loss, 50-result limit, and remaining staging gaps are **not solved**. No unrestricted library scan. Movie mixed-genre multi-select is high priority; complete category poster browsing and incremental new-media sourcing follow.

**The entire purpose:** give one household good, natural, correctly timed Japanese subtitles for the movies and TV it already watches in Jellyfin. This is not a startup, a software product, a showcase, or a competition to invent a subtitle manager. A subtitle that actually plays well is success. A commit, benchmark, downloaded candidate or attractive dashboard is not.

## Read these, in this order

1. [GOAL.md](GOAL.md) — what the owner actually needs.
2. **[docs/SEARCH_RECOVERY_ROADMAP.md](docs/SEARCH_RECOVERY_ROADMAP.md)** — **current priority, real Nov 11 audit, unresolved search failures, P1 dashboards/batches and P2 poster browser, next-chat handoff**.
3. [AGENTS.md](AGENTS.md) — mandatory AI/dev session behavior and deployed-vs-committed checks.
4. [docs/CURRENT_STATE.md](docs/CURRENT_STATE.md) — evolving status and older experiment evidence (read the newest priority banner first).
5. [docs/SUBHUB_CORRECTION_FIRST_POLICY_2026-11-10.md](docs/SUBHUB_CORRECTION_FIRST_POLICY_2026-11-10.md) — durable sourcing, review and non-destructive publication rules.

Other date-stamped documents, experiments, project handoffs, and GitHub issues are **historical evidence**, not competing current instructions. Do not infer live host state from this repository. Git history retains older versions of this README and instructions.

## Operating approach

- **Reuse existing software first.** We have Jellyfin, Sublarr, ffsubsync and working custom utilities. Inspect configuration and capabilities, then test on real files before duplicating them in code. **Bazarr is a first-class candidate**, not dismissed because it needs Sonarr/Radarr. Its maintained TV/movie catalog, Japanese-source provider search, ffsubsync synchronization and manual review may replace large portions of our custom infrastructure. Sonarr/Radarr can import existing libraries without configuring download automation; pilot against a scratch copy first. Evaluate setup and maintainability against the many dependencies already in custom code.
- **The custom dashboard is presently the owner's most useful interface, but still inadequate.** That is an observation, **not** a mandate to keep it or replace it. Determine which tool or small combination best handles the library. **Run a serious Bazarr + Sonarr (then Radarr) test in parallel with a properly configured Sublarr test.** Do not build or migrate by ideology.
- Search, retain, identify and repair **human-authored Japanese subtitles** before local AI translation. Never treat a search miss or failed automatic sync as proof that Japanese is unavailable.
- Inspect existing embedded/sidecar **native-language text** early; proactively obtain and cache a matching reference when useful. That can help release matching, timing and eventual translation. **Missing native/English subtitles never block Japanese search, reuse or repair.** Do not waste daily provider downloads sourcing references for the entire library before targeting Japanese.
- Prefer existing sync/repair engines; test **beginning, middle and end against dialogue**. Different-language cue starts are not a reliable automatic judge. Preserve original subtitle bytes and preview corrections before reversible promotion.
- Use existing PLaMo translation as a **last resort**, after meaningful sourcing/recovery and only with verified source dialogue. Do not run new model tournaments or add an AI critic by default.
- Preserve existing media folders, working subtitle sidecars, credentials, staging, checkpoints, thermal protections and live services. **No automatic overwrite.** Never conflate committed GitHub code with host deployment or Jellyfin playback acceptance.

## Current immediate work

1. **P0 — Fix real subtitle discovery.** Resolve Sublarr's simplified API losing movie year/TV series metadata, provider participation and budget deferral, 50-result truncation, cached evidence loss, and SubDL staging gap. Benchmark a small actual cohort and prove subtitles progress to ALASS, safe publication and Jellyfin playback. [Roadmap and evidence](docs/SEARCH_RECOVERY_ROADMAP.md); [issue #89](https://github.com/SteezyMode/bruiser-subhub/issues/89).
2. **P1 — Functional dashboard and operator batches.** ALL jobs (movie, selected TV, entire library, translation, stage and publication) need real, persistent per-job progress and outcomes. Arbitrary multiple movies selected across genres must queue together. An inactive button is not a progress indicator. [Issue #90](https://github.com/SteezyMode/bruiser-subhub/issues/90).
3. **P2 — Browse the actual Jellyfin movie library.** Selecting `Comedy` lists the **whole genre as a poster grid** without any title typed; title search works independently; selections survive paging/category changes. Later, add incremental Japanese sourcing for newly-added Jellyfin IDs after search reliably works.
4. **Separate timing QA backlog:** IASIP S01E04 ALASS cold-open correction and S01E05 control still require a final published/playback verification where appropriate. Keep the known successful preview and don't supplant it with speculative retiming. See [current state](docs/CURRENT_STATE.md).

Keep dashboard work tied to actual usable operation, not appearance. The yardstick remains **the next correctly matched, timed, playable Japanese subtitle in Jellyfin**, with visible job progress and minimal maintenance.
