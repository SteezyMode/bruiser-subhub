# Bruiser SubHub

> **CURRENT WORK — 2026-11-11 | SEARCH RELIABILITY P0, JOB PROGRESS & BATCHES P1**
>
> **[START HERE: Search Recovery Roadmap & Next-Chat Handoff](docs/SEARCH_RECOVERY_ROADMAP.md)**
>
> The owner has lost substantial time across filled AI chats repeating "fixes" without usable Japanese subtitle yield. This roadmap is **the prominent live technical handoff**, including host-tested evidence, what's committed vs installed, known broken paths, precise priorities, tests, safety rules, and how to continue. **Read before editing code or requesting new provider searches.** Check [P0 search issue #89](https://github.com/SteezyMode/bruiser-subhub/issues/89) and [P1/P2 job progress, batches and movie browse issue #90](https://github.com/SteezyMode/bruiser-subhub/issues/90).
>
> **Latest verified host result:** source **v4 installed**, 44/600 searches returned no usable new matches; attempt #45 deferred because SubDL hit `stretch` budget pacing **while OpenSubtitles remained available**. 19 separately saved/staged subtitles published; this does **not** show new search yield. **Do not run another full-library scan until search recall and staging are proven on a bounded real-media cohort.**
>
> **Owner requirements, easy to miss:** all jobs need actual persistent progress bars and current-item/remaining/outcome state **inside the dashboard**, never a disabled button as the only indicator; manually select any mix of movies in one batch; a `Comedy` category must actually display the full Jellyfin Comedy library as a **poster grid** even with an empty search field. These are recorded and prioritized, not implemented.

> **2026-11-11 P0 continuation (NOT deployed):** A tested patch now continues searching with OpenSubtitles when SubDL's provider budget is exhausted and labels incomplete zeroes `partial` instead of `none`. A new 1–3-item Jellyfin remote-subtitle comparison is ready for controlled live measurement (`tools/benchmark_subtitle_search_paths.py`). This **does not fix Sublarr's lost movie-year metadata, 50-result cap or SubDL staging**, and has not yet improved verified subtitle yield. Read [attempt log and next test](docs/SEARCH_RECOVERY_ROADMAP.md#2026-11-11-continuation--p0-a-attempt-record-code--comparison-no-host-acceptance-yet) before searching again.
>
> **LATEST LIVE P0-B EVIDENCE:** Owner completed that Jellyfin comparison: *Late Night with the Devil* = 6 JA remote candidates (3 Open Subtitles + 3 subbuzz), IASIP S07E02 = 2 JA candidates (1 each), *Bride of Chucky* = 0. IASIP's saved miss was v2, not v4; no claims of improved publication yet. Upstream Jellyfin supports read-only remote subtitle **GET**, unlike direct-to-media **POST**. A single-item, one-provider, one-candidate in-memory byte-fetch pilot was committed and CI passed; **not yet executed on the host**. [Exact test and verified distinction](docs/SEARCH_RECOVERY_ROADMAP.md#p0-b-single-japanese-subtitle-byte-retrieval-without-touching-jellyfin-media).

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
