# Search recovery & operating roadmap — 2026-11-11 JST

> **START HERE FOR ANY SEARCH/PUBLISH WORK. Priority P0.**
> Maintained handoff for future ChatGPT sessions, owners, and AI coding agents.
> The user has repeatedly lost progress when chats filled up. **Do not restart investigation from scratch, invent a show-specific fix, or claim unit tests prove on-host search yield.**
> Read [GOAL](../GOAL.md), [AGENTS](../AGENTS.md), [CURRENT_STATE](CURRENT_STATE.md), [issue #89](https://github.com/SteezyMode/bruiser-subhub/issues/89), and [issue #90](https://github.com/SteezyMode/bruiser-subhub/issues/90).
>
> **Owner's current explicit order:** (1) fix reliable Japanese subtitle search and publication end-to-end; (2) all jobs need real dashboard progress, and manual batches must be possible; (3) Jellyfin-style movie poster grid with genre browsing/multi-selection; (4) eventually incremental source-on-add. No enterprise/startup framing. Do not build attractive controls that fail to deliver Japanese subtitles.

## Nov 11 dashboard denominator fix — "32" versus "23" missing Sunny episodes

Owner reports "32 missing" in one view but "23" upon expanding **Review missing Japanese**, alongside disabled **Last resort: PLaMo (0)**. **Verified dashboard behavior:** the Review button ONLY toggles episode detail visibility; it does NOT rescan or recalculate. `tools/subhub_dashboard.html::counts()` sums `coverage` map for **currently selected and successfully fetched seasons**, sourced from `subhub_translation_batch.season_report()` backed by the saved coverage queue plus file-sidecar checks. Earlier 32 came from a DIFFERENT source snapshot/selection; never assert equivalence or a canonical total without a same-time inventory reconciliation. The translation button shows zero when no episodes are checked, **even if many are missing**; its eligibility is separately restricted by source-first queue state and actual English availability.

**GitHub UI fix** at commit `a3d3b9ec85cecefd104d350aba19a62e5ca904a0`:
- Label numerator and denominator **selected seasons only**, explicitly show loaded/selected season count and caution stale queue; show breakdown by review, sourcing and English-needed, and total PLaMo eligible episodes.
- Label translation action `Translate checked with PLaMo (N selected / M eligible)`, preventing "0" from being mistaken for zero missing episodes.
- Add **Recheck selected episode coverage**; refreshes selected season reports and exact-video JA sidecar flags without provider calls and without falsely pretending a Jellyfin library rescan.
- Do not deploy GitHub changes while 600-search source job is active. Verify true cross-source count (fresh Jellyfin catalog + all seasons saved matrix) and only then prioritize remaining translations.

## Next feature proposal — optional timed PLaMo translation window (user request Nov 11)

**Not enabled or scheduled yet.** Simple SubHub Settings control: **Auto-translate (Off by default)**, **Start time** (local JST, e.g. 05:00), **Duration** (e.g. 120 minutes). This is a user-configurable daily start+duration, not approval to start translating the whole library or to require the user to review each routine hold.

- Keep the source-first pipeline autonomous for routine work: saved JA candidates → release variants / provider search → ALASS / ffsubsync / timing QA → publish only verified and create-only. A failed sync is an **active recovery task**, not a human review request; retain per-media attempt history and evidence, avoid infinite retries of the same candidate, and show reason classes.
- Translation-eligible queue is **separate** from JA timing/source holds. Require correctly identified media, trusted matching EN subtitle, sufficiently exhausted reasonable JA alternatives, and no existing JA. No automatic EN extraction/search unless that workflow is separately approved. Model is the actual local **PLaMo** backend, not the older Gemma fallback.
- Optional window drains queue **sequentially**, checks existing worker lock and temperature pauses, uses persistent per-cue checkpoints, stops claiming work after allotted wall-clock duration and safely pauses at a checkpoint. Resume unfinished episode during a future enabled window. Don't overpromise exact stop at a cue boundary. Manual selections/batches at any time, with source/translation priorities and exclusions; one active worker, no competing jobs.
- Pass routine quality and timing gates → create-only Japanese subtitle for Jellyfin without asking owner to manually approve every ordinary result. Genuinely ambiguous or unreliable translations → explicit **needs human review** reason. Clear UI shows upcoming window, running/paused, completed, held/blocked counts **per distinct episode**, next prioritized items.
- Avoid new private service infrastructure: reuse existing SubHub worker, job DB, and simple user timer only after the owner explicitly enables it. While the current 600-search source-only pass is running, **do not deploy/restart related jobs**. No schedule created in this roadmap update.

## Nov 11 native Sublarr v1.20.1 provider inspection — owner evidence, no new downloads

Owner opened **Sublarr v1.20.1** Providers page: **28/28 enabled, 17/28 healthy**, Sublarr dashboard reports **0 native downloads**, **active API budget**, automation partially paused. These native download stats do **NOT** count every saved/staged/published Japanese sidecar from the SubHub raw download pipeline. Provider counters are all-language aggregate and do not prove Japanese search participation. Examples from owner screen: OpenSubtitles healthy, 48% hit rate, day budget 65/1000; SubDL healthy, 2%, 65/500; Subf2m healthy, 6%, 64/500; Gestdown healthy 0%; Podnapisi and Addic7ed "Delivers nothing"; SubSource "Healthy" with 0 previous searches; Jimaku and Customapi "No credentials"; TVsubtitles recovering with 10 consecutive failures; SubsDump delivers nothing and needs its own imported local archive database.

**Correction of earlier imprecise description:** `ja_first_search_pilot.py` calls Sublarr's `/api/v1/providers/search`, which dispatches to **all enabled/search-eligible providers**, not just OpenSubtitles/SubDL. BUT `recover_via_sublarr` only stages **OpenSubtitles and SubDL** results, ignoring native provider candidates from the other 26; hence a positive from a third source could be lost downstream. A provider's overall healthy status alone does not prove it attempted an individual Japanese episode; API response contains hits, not per-provider no-hit receipts. A zero hit is not proof all 28 were queried or no Japanese track exists anywhere.

**Use native Sublarr v1.20.1 UI before more custom coding:** `Wanted` → filter for an unresolved episode (first S18E01, then S09E09) → row's **Interactive Search** magnifying-glass icon → tick **All providers** (defaults off and overrides profile-level provider selection) → set language filter `ja` or `jpn` if results exist → inspect provider, episode identity and release. Do not click download yet if synchrony/source identity is uncertain. Native **Decision Log** available from Wanted rows with decisions, to distinguish actual skips from true no-hits. Do not infer "all providers" will include broken/missing-credential endpoints; read decision reasons. This is source discovery, not guaranteed publication. If a worthwhile third-provider Japanese result exists, **prioritize using Sublarr's own tested download/sync path** over building a new provider adapter, and verify output in Jellyfin. Do not bulk enable/disable credentials or duplicate old search again until this test reveals where the gap is.

## Nov 11 inventory classification fix — keep covered episode identities

Generic bug in `tools/ja_first_catalog_manifest.py::classify()`: when a video already has Japanese sidecar/embedded subtitle or Japanese audio, classifier previously returned **before setting the series title and season/episode identifiers**. This made it impossible to count fully subtitled episodes per series from a new manifest, hiding 55 existing sidecars in the stale source audit. Now populate descriptive series title, season and episode metadata **before the coverage short-circuit**, without modifying the existing search-eligibility logic. Regression test added in `test_ja_first_native_series_identity.py`. **GitHub only until next guarded install**; full CI environment has unrelated ffprobe-dependent test failures. Next run `install_global_ja_sourcing.py --commit pinned_sha --install-only` when workers idle, then `ja_first_catalog_manifest.py --save` and count exact 179 episodes from the refreshed intake manifest.

## Nov 11 owner executed no-duplicate sourcing preflight — 11 source gaps have a reason

**Owner's actual OptiPlex output** of pinned `ja_first_recover_unstaged.py --series ... --start`: `MISSING_WITH_SAVED_JA_STAGE=12`, `ALREADY_PUBLISHED_BUT_STALE_MANIFEST=55`, `MISSING_WITH_NO_JA_STAGE=11`, `INVENTORY_REQUIRES_REVIEW=0`, `INCOMPLETE_LOOKUPS_OR_SAVED_RESULTS_TO_RETRY=0`, `COMPLETED_LOOKUPS_NEED_NEW_SOURCE=11`. **Nothing was launched** because no justified repeat against current OS/SubDL. The pre-existing latest manifest is stale: do **not** infer definitive coverage from 141/179 or 149/179; obtain fresh Jellyfin catalog via existing `ja_first_catalog_manifest.py --save` (create-only) and cross-check sidecars.

**11 un-staged misses**: S05E13, S06E09, S08E02, S09E09, S14E03, S18E01/E02/E04/E05/E07/E08. All have stored `outcome=none`, `provider_total=0`, no rejected candidates and no incomplete providers for the **two downloader sources**.

**Important clustering verified using published external series metadata**:
- **Four of five removed-from-streaming episodes**: S06E09 *Dee Reynolds: Shaping America's Youth*, S08E02 *The Gang Recycles Their Trash*, S09E09 *The Gang Makes Lethal Weapon 6*, S14E03 *Dee Day*. These are unlikely to have Disney+ matched Japanese streaming subtitles; prioritize correctly-matched English source and *manually chosen* PLaMo, not repeated OS/SubDL empty searches. S04E03 is the fifth generally removed episode but is NOT in these un-staged gaps.
- S05E13 is likely *A Very Sunny Christmas* — a 2009 hour-long Christmas special, historically a DVD release, season-number ambiguity; inspect actual file and English captions, search **special's title** not only numeric S05E13. Never rename/swaps based on Jellyfin label alone.
- S18 E01/E02/E04/E05/E07/E08 are **brand-new 2026 releases** (US season premiered Aug 17 and concluded Oct 12, 2026); Japanese subtitle upload lag plausible. Test enabled native Sublarr alternatives rather than assume permanence. Four remaining S18 episodes already have Japanese available, so 6/10 missing is specific, not total absence.

**Sublarr upstream** documents built-in provider adapters broader than the two hardwired SubHub stage downloaders. Relevant no-key provider candidate **SubsDump**; **Subf2m** also no key; assess actual installed version, enabled providers, language coverage, and per-provider health with local `/api/v1/providers/health` before enabling/installing anything. Jimaku/Kitsunekko are anime-focused, likely low-value for this American live-action sitcom. SubsDump and any other native provider results should flow through Sublarr's own staging/sync mechanisms where feasible; don't DIY adapters without a genuine need. Do not blindly upgrade installed Sublarr or bulk search entire library.

**Distinct next steps:** (1) refresh local Jellyfin inventory and get exact uncovered tally; (2) inspect local provider health and 11 episodes' available English subtitle source; (3) targeted S18 provider discovery with a non-OS/SubDL source if configured; (4) 4 removed + special to English→PLaMo only after source inspection and owner approval; (5) retain 12 staged timing holds separately, matching release rather than trusting enormous ALASS shifts. No media changes during diagnostic.

## Nov 11 NEXT SOURCE PASS — all remaining episodes, avoiding duplicate downloads

From prior host verified **8 additional staged-JA publications**, projected IASIP Japanese coverage is **149/179; 30 missing pending refreshed Jellyfin catalog**. Rough partition: **12 have Japanese stages but remain alignment/QA held**; approx **18 have no successfully staged Japanese**. Counts must be reconciled against physical sidecars and the latest Jellyfin inventory before claiming exact missing count.

**Critical source gap discovered by code review:** `subhub_jellyfin_batch.py::recover_via_sublarr()` only calls `ja_first_stage_saved_batch.py` for OpenSubtitles and `ja_first_stage_subdl.py` for SubDL, even if Sublarr's wider providers are configured and returned hits. **Thus a 'no verified Japanese from available providers' job receipt is not proof that every Sublarr provider was exhausted.** Never classify all remaining as translation-required. Official Sublarr docs list many other adapters (including Jimaku, SubsDump, SubSource and Addic7ed) and a built-in search/repair pipeline, but suitability for non-anime Japanese series varies; verify host version/provider availability and evaluate letting Sublarr manage other sources rather than writing dozens of custom adapters. Host currently used 1.18 API paths; latest upstream release observed via official GitHub 1.20.1 (Nov 7), **do not blindly upgrade running container**.

**Generic next-pass tool in repository** `tools/ja_first_recover_unstaged.py`: read-only by default, reports exact missing/unstaged eligible items (with last provider outcome, saved/rejected results); `--start` hands **only previously unsearched, partial, deferred, old-strategy or saved-positive-but-not-staged episodes** to the **existing dashboard's** `start_jellyfin_source()`. Crucially, **complete empty v5 provider searches are NOT repeated**; these go to new-provider-source investigation or manually chosen translation, not a wasteful same-API repeat. Normal Active Work, locks, pacing and 20-search selected-items cap apply. One generic implementation for any series; script is not installed by the standard installer and is runnable directly from its pinned GitHub version on OptiPlex as Python stdin; no dashboard rewrite, no PLaMo auto-start. GitHub Actions full suite has environment failures in unrelated freeze/transcription tests requiring ffprobe on its runner; do NOT claim green entire CI or hosted execution yet. Once run completes, reclassify successes and remaining source gaps.

**Follow-up:** For the 12 timing-held candidates, match the subtitle release (many Disney+ WEB-DL) with the user's existing video releases (several HDTV), or use alignment methods informed by matched-English tracks. Do not force-publish impossible timing; inspect the long-shift S09E06 real playback. English→PLaMo is selected manually for truly source-less episodes (e.g. S09E09), not automatically after a provider miss.

## Nov 11 HOST VERIFIED — staged JA recovery succeeded (8 new publications), 12 holds remain

**Owner installed pinned build** `9b3d37083c79f193878ff6cbadb48875d34e8939` using `install_global_ja_sourcing.py --install-only`. Preflight, dashboard status and private receipt write probe all passed. Generic `ja_first_publish_queue.py --series "It's Always Sunny in Philadelphia" --max-titles 300 --limit 100 --apply` then ran against **20 eligible staged titles, 28 candidates**, without any provider searches/downloads/translation. **8 newly published, 12 held** (actual host log). This is verified real media writes, not CI-only.

**Published titles**: S02E01, S03E04, S08E05, S09E06, S13E05, S14E05, S14E10, S16E01. All `PUBLISHED:` and `BRUISER_PUBLISH_ITEM result=published` recorded create-only sidecars. Given preceding Jellyfin inventory **141/179**, expectation is now **149/179 JA coverage, 30 missing**, *conditional on fresh Jellyfin rescan/reclassification.* No video files or prior subtitles were overwritten.

**Season 9**: S09E08 + S09E10 were already published in earlier run; S09E06 newly recovered from staged OpenSubtitles, proving library-wide legacy `provider` metadata compatibility fix works. S09E01/E02/E03/E04/E05/E07 remain timing-held. S09E09 returned no sourced Japanese candidate (content removed from some streamers; owner expects English→PLaMo last resort). Other held stages: S03E03, S03E07, S03E08, S08E04, S08E06, S14E09.

**Failure categories in exact output**: 
- ALASS `alass_out_of_video` for essentially every remaining staged title (often for both available candidates). This is **aligned last cue beyond video duration**, NOT a missing provider candidate. FFSUBSYNC often `ffsubsync_shift_or_variation_excessive`, `ffsubsync_invalid_video_coverage` or `sync_cue_count_changed`; direct fallback `unverified_no_reference`. These files are mainly release mismatch / reference availability investigations; do not relax identity/cue-count/timing gates indiscriminately.
- S09E04 previous `KeyError: 'provider'` is now gone; current failure solely ALASS `alass_out_of_video`, ffsubsync shift variation. S09E06 passed and published. Global fix is effective for older stage DB metadata.
- New keep-source-dialogue formatting code permits ALASS corrections but only when non-whitespace dialogue characters and original cue order match; the original source dialogue remains unchanged.

**High-risk timing quality note:** S09E06 ALASS used `video_audio` and applied shift range **-47.928..+67.674 seconds** (opening median +63.096, middle -7.364, ending -29.63), *not* a trivial uniform correction. S14E10 (same-video English reference) also shows **-24.201..+60.880 seconds** spread; S03E04 **-38.042..+16.908**. These passed mechanical validation (dialogue unchanged, plausible episode bounds), which does **NOT** prove spoken dialogue synchrony. Request a sample playback spot-check at cold open, middle and end for S09E06 and other large-spread examples before claiming excellent sync. Avoid redefining broad QA thresholds merely to raise coverage numbers.

**Next productive work:** Refresh Jellyfin coverage and reconcile actual new total, then inspect video runtime versus original and ALASS-derived subtitle cue bounds for **all 12 holds at once** (read-only): distinguish late credits/added cues from incompatible HDTV/WEB-DL edits. If video/JP releases differ substantially, **matching-release media** is likely preferable to forced timing manipulation, provided the owner explicitly chooses replacement. No destructive operations. Do not start PLaMo automatically.

## Deferred media-library correctness: American Dad Season 20 playback mismatch (owner report, Nov 11)

**Known wrong episode playback; investigate after current Japanese-subtitle recovery.** In Jellyfin the owner selects **American Dad S20E05, displayed as "Stretched Thin"**, but playback shows **"Cow I Met Your Moo-ther", expected by owner as S20E07**. Do NOT assume the Jellyfin display title is correct or that the media filename matches the actual contents. American Dad has long-running DVD/broadcast/streaming episode numbering and season-order disagreements, so confirm the exact episode order source before making any correction. This is a **media identity correctness issue**, not a subtitle timing issue, and may affect much more than S20E05.

**Later action (read-only audit first):** enumerate every S20 Jellyfin ID, display title, season/episode indexes, physical path and basename, embedded metadata, and actual content/title identities (compare known episode plots or first scenes where practical); determine whether the video files are misplaced, simply misnamed, cataloged in a different order, or wrongly mapped by Jellyfin. Cross-check adjacent S20E05/S20E07 and the whole season rather than swapping two files blindly. Inventory downstream subtitle names and PLaMo work before any renumbering; preserve existing files, subtitles, stored translations, and Jellyfin watch state. Apply one coherent correction to actual series ordering only after mapping is verified. **Not yet investigated or fixed.** No media or metadata changes authorized at this stage.

## Nov 11 Season 09 and scattered misses — generic staged-publication bug discovered

**After 141/179 coverage (38 missing), owner reports entire Season 09 still missing JA, with scattered holes elsewhere.** Historical S09E04 and S09E06 have saved Japanese candidate/staging evidence (Nov 10 notes in CURRENT_STATE); Season 09 did not appear in earlier IASIP source-video replacement list (S01–08 and S10–11 were replaced). Do not assume a season-wide media filename mismatch without inspecting the actual host manifest/filename+search+stage DB in ONE read-only grouped audit.

**Code defect confirmed from source:** `ja_first_stage_saved_batch.choices()` excludes an already-staged candidate via `read_staged()`; before the fix, `subhub_jellyfin_batch.recover_via_sublarr()` only invoked the unified ALASS/ffsubsync publisher *after a fresh STAGED receipt*. Thus previously downloaded and staged Japanese subtitles could be stranded across subsequent source attempts, notably potentially S09E04/S09E06 and scattered exceptions. Fixed in generic worker at commit `472acfee615eba5fe4d3f2c5980f73f2b9cf7aae`: before any fresh provider requests, attempt existing `ja_first_publish_queue.py --jellyfin-id ... --apply` and credit a verified published receipt. CI green after updating obsolete external-match expectation in commit `9140c984fa6b4bbdbeb217617c32f2c3c10691e9`. **GitHub only, not installed on host.** Do not interrupt a live worker or claim this proves all 10 S09 episodes are fixable. Inspect real host result summary to distinguish filename numbering conflicts, provider misses, false matching rejections, already-staged QA holds, and bad release-specific timing. Fix underlying general-purpose issue, not hardcoded Season 09.

## 2026-11-11 LIVE MULTI-PROVIDER PASS + DASHBOARD UX NOTES — owner screenshots

**This is live host evidence and supersedes stale 'install pending' notices in older sections.** Owner installed commit `12c1691708830d3009345e197fe698ca7c29e238` on OptiPlex with successful dashboard status check; owner API accepted full-series pass with **65 eligible episodes**. Existing Jellyfin coverage showed **112/179 Japanese-covered, therefore 67 truly missing Japanese** at start. The 65 is *job attempts*, not coverage; 2 more missing lie outside eligible job scope and eventually need queue/inventory reconciliation. No reason to claim new publications merely from download counts.

**Subsequent screenshots:** Running pass advanced **8/65 → 11/65**. Observed daily ledger rose **6 downloaded/52 attempted → 11 downloaded/61 attempted**; these totals are **daily cumulative instrumented provider downloads/attempts**, NOT this pass's completed episodes, not 11 newly sourced episodes, and not 11 published subtitles. The contemporaneous exception list showed at least 9 held/no-match items; it can contain earlier holds and does not establish source-availability failure. Correct interpretation: the multi-provider workflow is making real download progress, but **newly published/usable subtitle yield is unverified**. Never tell the owner the pipeline failed just because the exception list is long, nor declare success based on download counter alone.

**Dashboard usability, after source/publish correctness is established (NOT a reason to interrupt current job):**

1. **One dominant number: episodes that still lack Japanese subtitles** across the selected series/library, from refreshed Jellyfin coverage. In this snapshot **67 missing**. This is the user's only headline success metric. After publications, refresh coverage so this number actually falls.
2. Under it, **one pass progress meter: X/Y episodes attempted in this pass**, regardless of outcome. Label exactly `11/65 attempted this pass`. Keep attempts separate from actual coverage.
3. **Three subordinate, explicitly scoped outcomes for *this pass***: `published (new JA sidecars)`, `downloaded (files obtained, not necessarily published)`, `held/no match (need recovery)`. Use accurate counts from actual job receipts; never merge lifetime, daily, historical or current-pass totals. Current UI shows daily 11 downloads but no clear batch new-publications number; fix that.
4. Keep provider budgets/usage accessible but subordinate under a collapsible **Provider activity** section, labeled **'today, instrumented only'** with per-provider used/remaining/reset if actually known; do not imply 61 attempts = 61 billable downloads, or fabricate quota allowance.
5. Place only **short exceptions summary** under progress (`N set aside`, expandable by episode/reason); no scrolling wall of mixed old/new exceptions taking over Active Work. Preserve a review/action path for all exceptions, and identify historical vs current pass.
6. Show current episode and **real phase** (`searching → downloading → synchronizing → publishing`) and outcomes; remove misleading vague `Starting`/generic `Idle` when service has checkpoint state. Always show whether work is active and don't leave competing start buttons apparently usable.
7. Auto-refresh coverage **after actual publication**, not merely job completion, and reconcile the two out-of-scope items. Ensure per-show view and eventual new-media automation share the same UI semantics. No show-specific hacks.
8. Avoid dashboard redesign work until the current batch finishes and actual Japanese publication yield is recorded. These are roadmap notes only; current background job should continue undisturbed.

**Current engineering status:** Code supporting broader Jellyfin + Sublarr (OpenSubtitles/SubDL) search is deployed at the pinned host commit above. Additional code commits after host deployment are **not** automatically live on OptiPlex. Do not claim a GitHub-only tweak has changed the running process. Keep the user's immediate goal as usable Japanese subtitles, not growing test/probe metrics.

## 2026-11-11 P0-D CRITICAL DASHBOARD EROFS FIX — tested code, host installation pending

**Owner's latest live screenshot:** *It's Always Sunny in Philadelphia* 18/18 seasons, **104 of 179** episodes have JA subtitles, **75 missing**. Clicking `Retry missing Japanese · entire series` displayed:
```text
Not started: [Errno 30] Read-only file system:
'/home/optiplex/bruiser-pilot/ja-first-inventory/.jellyfin-source-launch-...'
```
**Precisely diagnosed in repo:** `tools/install_subhub_dashboard.sh` created a `bruiser-subhub-dashboard.service` with **`ProtectSystem=strict` and `ProtectHome=read-only`**, yet newer `start_jellyfin_source()` in `tools/subhub_dashboard_server.py` tried to atomically create a private launch receipt in `~/bruiser-pilot/ja-first-inventory`. Earlier dashboard server also invoked `systemd-run` **before** writing that receipt, so it could show “Not started” **even after actually starting a background sourcing job**. **Do not assume the job is idle just because the UI said not started; check service status before any new install or retry.** The numbers 75 missing are from Jellyfin coverage, not necessarily the last saved source-job queue.

**Permanent repairs committed and CI-passing Python 3.11/3.12** (code pin `9f9231d141985cd21179eeabdff528df9a14c0bd`, [run 42963876873](https://github.com/SteezyMode/bruiser-subhub/actions/runs/42963876873)):

- The **existing reversible, busy-worker-guarded code-only installer** `tools/install_global_ja_sourcing.py --install-only` now backs up and installs one systemd drop-in under the **existing** dashboard user unit with precisely `ReadWritePaths=%h/bruiser-pilot/ja-first-inventory`, calls `systemctl --user daemon-reload`, restarts the dashboard only, and verifies a real temporary-file write **inside the service's own mount namespace** via the local `/healthz` endpoint (`job_receipts_writable:true`). On failure it rolls back code/drop-in; no media writes or broad source worker actions. `ProtectSystem=strict` and `ProtectHome=read-only` remain in place; other home/media paths remain read-only.
- The standalone `tools/install_subhub_dashboard.sh` unit template includes the same narrow exception to prevent reintroducing this bug on fresh installations.
- `start_jellyfin_source()` now **first** writes the owner-private launch receipt and **only then** invokes `systemd-run`. A read-only folder now prevents the worker from being launched and produces a truthful “Not started”. A failed systemd start produces a visible `launch_failed` receipt instead of silently masking old progress.
- `/healthz` checks **actual filesystem writability**, not just `os.access` mode bits (which do not detect a read-only sandbox mount).
- Regression tests verify EROFS prevents launch entirely, systemd start failures remain visible, the sandbox write restriction is limited to the one existing private directory, and the actual health probe works.

**Host remains on the old unit configuration pending install**; the user has not reported running the new install command. When the current source worker is idle, use exactly **one** code-only installer upgrade to pinned commit `9f9231d141985cd21179eeabdff528df9a14c0bd` and require output `DASHBOARD SANDBOX: live private-job write probe PASS`; then refresh dashboard and retry missing Sunny. Do not start a broad library scan or invent new per-show commands. Remaining original 3 generic failures are still unclassified.

## 2026-11-11 P0-D host follow-up — 78 missing Sunny, 3 held, 75 queued; fixes CI-tested, not yet deployed

**Owner provided actual OptiPlex read-only service status/journal.** This **supersedes the earlier "P0-D not installed" notice below**: owner DID install the original dashboard release and launched three bounded source jobs:

1. First *It's Always Sunny in Philadelphia* full-series job: `selected=78`, `3 held`, `75 queued`, `3 searches`, `0 new published`, `state=paused` after three consecutive errors. Source service returned inactive after pause.
2. Separate owner-selected **S17E03** one-episode job: `selected=1`, `published=1`, `state=completed`. This is a **real new publication** distinct from S07E02, not a whole-series result.
3. Retried full-series job: exactly `3 held/75 queued`, `3 searches`, `0 new published`, paused again. No provider rate limit reported in those receipts. **Why the three failed is still unknown**; original worker persisted only generic `preflight_or_provider_download_failed`, discarding specific stderr. Do not guess which episode error or provider caused it or claim the whole series has been sourced.

**Owner complained "progress visible under Active Work" was false**. Audit showed the dashboard conditioned the entire source panel on `p.known||p.active`: when the accepted service had no progress file yet or failed before first write, the panel simply vanished. Additionally, a **one-episode job overwrote the sole all-series JSON receipt**, losing the earlier all-series history and causing retries to start from the first failed episodes.

### GitHub repairs committed after this real host audit (not installed, CI-tested)

- **Persistent launch receipt in dashboard**: `tools/subhub_dashboard_server.py` records a private owner-only job ID and scope when systemd accepts the start; `tools/subhub_jellyfin_batch.py` writes the same job ID with progress. Dashboard shows an accepted job **before the first checkpoint**; shows a clear early failure if process exits without progress, and will not mislabel old job results as the current run. The actual progress panel lists **the held episode labels and safe categorized reasons** rather than hiding the job. This cannot retrospectively recover the old discarded errors.
- **Exact-scope resume:** New per-selector 0600 private receipts mean a one-episode success no longer destroys the whole-series 78-item resume state. The dashboard's latest-job file remains separate. On first new whole-series resume, the prior latest 78-item receipt is migrated for that scope when available; existing `held=3` items remain held and the **75 remaining queued** are the next work, subject to actual video/sidecar rechecks. A separately successful S17E03 will be rechecked for existing Japanese sidecar and skipped with no provider request, not overwritten.
- **Stop policy corrected:** Three independent *media preflight or quality assurance holds* no longer stop a 78-episode series. Still pause on three genuine consecutive **upstream provider search/download failures**, any provider 429, or configured request cap. No flood of retries.
- **Actual failure categories** (e.g. `media_duration_unavailable`, `subtitle_validation_failed`, `provider_download_failed`, `provider_http_403`) are sanitized in new item receipts without publishing the raw exception, token, URL, or subtitle contents. The original three generic failures **cannot be diagnosed without new evidence**.
- **Offline regressions:** 3 independent media failures do not halt the series; 3 upstream failures DO; per-selector history isolation survives intervening one-episode jobs; accepted job is visible before progress; stale progress cannot masquerade as a new job; existing scoped publisher/QA behavior remains. Full CI passed Python 3.11/3.12 in [run 42961708326](https://github.com/SteezyMode/bruiser-subhub/actions/runs/42961708326) at commit `68872b6b27e9164496c998112bb175a9bb53d2e8`; later documentation-only revisions do not change code.

**CURRENT HOST STATE:** the most recent host command reported source service **inactive**, all-series latest receipt `paused`, **3 held / 75 queued**, and independent S17E03 publication success. None of these repairs have yet been deployed to OptiPlex, and no all-series rerun after them has been made. **Next action when owner returns:** a single safeguarded `install_global_ja_sourcing.py --install-only` with a pinned passing code revision, then use the existing dashboard's **Continue remaining / Retry entire series**, rather than one-off per-episode terminal commands. Observe real results before any broader library-wide scheduling. The owner has spent ~4 hours at the computer today; **do not request more terminal work today**. P1 mixed-movie batching, all-other-job progress and P2 poster/genre browser remain open.

## 2026-11-11 P0-D — dashboard-controlled, resumable Jellyfin-native library sourcing (CODE READY; HOST NOT YET DEPLOYED)

**Owner's current explicit correction:** The goal is the entire Japanese subtitle library, NOT a bespoke IASIP terminal flow. Implement everything reusable through the SubHub dashboard, and maintain real job progress. *It's Always Sunny in Philadelphia* is only the owner-selected acceptance workload. Do not instruct future chats to enter a fresh CLI command per episode, season, or movie.

### Implementation (same existing private Jellyfin catalog and stage/publisher)

- **New generic background source worker:** `tools/subhub_jellyfin_batch.py`. Select an arbitrary Jellyfin series, season(s), individually selected episodes, or an arbitrary set of exact Jellyfin movie IDs. Uses `ja_first_stage_jellyfin.py --jellyfin-id <item>` for each item, then the **existing** exact-item ALASS/FFSUBSYNC guarded publisher. No direct Jellyfin POST, no invented media directory, no overwrite, no translation/model call. Each item is independently inspected for an existing JA sidecar; remaining stream/format/identity validation stays in the source-stage and publisher.
- **One-click whole-series action on the real dashboard:** after searching/opening a TV series, click `Retry missing Japanese · entire series`. This starts one genuine background systemd job, **up to 200 remote-search requests** in that selected show, with a 3-second per-request gate. Automatic pause on HTTP 429/provider refusal, three consecutive failed downloads/QA, or selected absolute cap; provider-dependent actual remote calls may differ. This is the user's explicitly selected series, **not a library-wide 10k scan**. Scoping by checked seasons/episodes remains available, limited to 20 searches per pass. All these routes use Jellyfin-native sourcing, **not the old failed combined Sublarr endpoint**.
- **Progress in dashboard's Active Work:** a real completion bar (`processed / selected eligible`), queued/remaining, actual current episode/phase, published, already-covered, not-found, held, deferred and search allowance consumed; real Stop and Continue actions. The worker runs independently via an existing systemd-user workflow; closing the browser does not interrupt it. Progress is an **atomic private owner-only JSON receipt** under the existing `ja-first-inventory` directory, not inferred from inactive/greyed action buttons. Reopening the page reconstructs the display from the receipt and systemd state.
- **Resume without redoing previous work:** Same selector reuses saved `published`, `covered`, `held` and `no_match` statuses. A `no_match` or provider-deferred item is only retried after a **20-hour safety cooldown**, preventing repeated quota-burning when the job is restarted. New selectors start new scoped work, with previous job summary retained. This is a rate-limit backoff, **not** a claim to know official provider quota reset times. On exceeding a per-job cap before all items are processed, remaining stay queued and Continue is shown.
- **No hidden write to library:** `ja_first_stage_jellyfin.py` now accepts an exact authoritative Jellyfin media ID for movie/episode to prevent ambiguity between titles/remakes. Native search attempts log a sanitized request-start receipt for accurate search accounting. Source uses existing private stage DB, QA gates, ALASS fallback, content hashes and create-only publisher. Original IASIP S07E02 remains published and will be skipped by the on-disk sidecar gate even if the manifest is stale.
- **Dashboard API:** `subhub_dashboard_server.py` adds authenticated same-origin `/api/jellyfin-source/start` / `stop`, actual status in `/api/status`, systemd conflict checks with old source/movie/translation workers, and a read-only bounded preflight against real catalog IDs before accepting the job. `subhub_dashboard.html` includes series retry, selected-season retry, actual progress meter, remaining and per-stage results, Stop and Continue.
- **Deployment:** Existing rollback installer `tools/install_global_ja_sourcing.py --install-only --commit <pinned SHA>` now includes the worker, its exact-item stage and dashboard UI/API, refuses active workers, backs up old source files, restarts existing dashboard only, never starts a scan or edits provider settings. The host is **still on the previously confirmed P0-C installation** until the owner installs the new SHA. **No real whole-series run has occurred yet.**
- **Regression history:** Initial tests caught existing source-service conflict priority ordering, a fake time base in cooldown tests, and an invalid fake media path in the skip-covered test. Corrected tests to match the actual safety requirements, **not** by weakening the original gates. Added Node.js syntax check for the dashboard's inline JavaScript where available. Offline suites must pass on Python 3.11/3.12 before host installation. Per-source actual throughput/yield on Sunny remains **unverified**.
- **Important distinction:** This resolves UI control/batch generalization and reuses a proven provider path, but is **not proof of all-library coverage**. The original 44/44 Sublarr misses, dropped year field, 50-result cap, missing cache evidence and SubDL-only stage gap remain documented; do not claim they vanished. The earlier P0-C single-sidecar success remains host-proven and playback owner-confirmed.

### Next owner action after CI

**One guarded code-only deployment**, then use the **dashboard**: search for `It's Always Sunny in Philadelphia`, open the series, and click `Retry missing Japanese · entire series`. The job should show in Active Work with genuine counts and can be stopped without closing Jellyfin. Start only when existing background source/translation workers are idle. After the first handful of items, inspect dashboard source yield, held reasons and published sidecars; if most are `no_match`, stop and investigate provider participation rather than burning more search allowance. **Do not turn this into one-off manual terminal scripts.**

## 2026-11-11 P0-C PUBLISHED — one complete real-world source-to-sidecar success

**Owner-run OptiPlex apply verified. This supersedes prior “not published” and “ready only” entries below.**

- Episode: *It's Always Sunny in Philadelphia* S07E02, *The Gang Goes to the Jersey Shore*; Jellyfin ID `76f7bdc090eb5db4f0287610859f386d`; source Jellyfin remote GET → subbuzz/OpenSubtitles.com. 402 Japanese SRT cues, 25,989 bytes.
- Existing private-stage ID: `9494097471374`. User executed `ja_first_publish_queue.py --jellyfin-id 76f7bdc090eb5db4f0287610859f386d --max-titles 1 --limit 1 --apply` using installed commit `360638244a3cd3b15e114ac6f8c53daa12317757`.
- `ALASS HELD: alass_dialogue_changed` (safety gate retained). FFSUBSYNC `mode=original`, `shift_range_seconds=[0.12,0.12]`, 402 cues, no overlap repairs. Gross QA pass, no warnings (**not a translation-quality grade**).
- **PUBLISHED, create-only:** `/mnt/2TB/Plex Expansion/Television/Episodic/It's Always Sunny in Philadelphia/Season 07/It's Always Sunny in Philadelphia - S07E02 - The Gang Goes to the Jersey Shore.ja.srt`. SHA256 `afaf762847bc25646704180536fa186805181822cd0959c381026669ffb5fcf2`. Publisher returned `BRUISER_PUBLISH_ITEM: {"jellyfin_id":"76f7bdc090eb5db4f0287610859f386d","proof":"ready_ffsubsync","result":"published"}`, `QUEUE SUMMARY: {"ready_ffsubsync":1,"published_new":1}`. Existing video and tracks unchanged. **No new provider queries/downloads in publication.**
- **Still unverified:** Whether Jellyfin displays/selects this sidecar in playback, and opening/middle/end dialogue timing/quality. Do not assert playback-verified yet; owner can test in Jellyfin browser.
- **Generalization remains P0:** This proves ONE item from library metadata → discovery → source download → private stage → integrity checks → FFSUBSYNC fallback → no-clobber sidecar. It does **not** repair the 44/44 v4 Sublarr source misses or make bulk Jellyfin searches automatic. Next implement budget-aware **general-purpose queue** calling the proven Jellyfin adapter for selected/all eligible catalog items with accurate per-title states and dashboard progress. Preserve provider quotas and avoid existing Japanese sidecars; test a small heterogeneous set before all-library automation. Prioritize actual usable Japanese results, NOT one-show improvements.

## 2026-11-11 P0-C HOST VERIFIED: private stage succeeds, publisher dry-run fallback ready

**Owner executed the pinned reversible installer, private stage and ONE exact-item publisher dry-run. Actual host evidence (supersedes the older "CODE ONLY" status below):**

- Installed pinned commit **`360638244a3cd3b15e114ac6f8c53daa12317757`** on OptiPlex with `install_global_ja_sourcing.py --install-only`. Backed up originals in the host's existing private source directory (`.ja-library-source-backup-_a5fq4eb`). Dashboard restarted; **no catalog refresh, queue reconciliation, scheduled search, or PLaMo job was launched.** Existing ALASS binary available.
- **Jellyfin/private staging succeeded:** `It's Always Sunny in Philadelphia` S07E02, Jellyfin ID `76f7bdc090eb5db4f0287610859f386d`, subbuzz/OpenSubtitles SRT **25,989 bytes, 402 cues, 3,502 Japanese characters**. Verified video length **1291.29 sec**. One private stage row saved with numeric stage ID **`9494097471374`**, `status=staged_not_published`. No media modifications. Exact-content SHA prefix **`afaf762847bc2564`**.
- **Exact-item publisher DRY RUN succeeded:** `--jellyfin-id 76f7bdc090eb5db4f0287610859f386d --max-titles 1 --limit 1` selected **one and only one** existing stage. `ALASS HELD: RuntimeError alass_dialogue_changed` (its proposed output did not preserve cue-by-cue dialogue). The **existing FFSUBSYNC fallback** passed content/coverage/QA: `mode=original`, `shift_range_seconds=[0.12,0.12]`, `cues=402`, Japanese fraction 1.0, 0 overlaps repaired; resulted `ready_ffsubsync` in dry run. **No publication**. The ALASS rejection is a safety gate operating correctly, NOT evidence that the downloaded Japanese SRT is bad. Do NOT relax dialogue equality or run another broad search to "fix" this.
- **Current decision:** for THIS exact item, FFSUBSYNC already approved the **original byte-identical Japanese subtitle** for create-only publication. After owner invokes an explicit `--apply` on this same single-ID publisher command, re-running the same hard gates, check Jellyfin playback at beginning, middle and ending. Publisher may still hold if library/host state changed. Do not misstate `ready_ffsubsync` as a published track.
- **Next command (explicit one-item publication only, no provider requests):**
```bash
ssh optiplex@100.121.156.34 \
'python3 -B "$HOME/bruiser-pilot/subhub-control/ja_first_publish_queue.py" \
  --jellyfin-id 76f7bdc090eb5db4f0287610859f386d \
  --max-titles 1 --limit 1 --apply'
```
**Only inspect ALASS after first playback or other evidence of real drift.** Future controlled ALASS diagnostics should count changed cues, classify whitespace-only versus semantic differences and keep source dialogue unmodified. Prefer the tested FFSUBSYNC original result now rather than postponing the first end-to-end Japanese track indefinitely.
- **Still open P0:** initial v4 search hit rate, metadata loss/50-result truncation, per-provider participation/quotas, SubDL staging, full-library throughput, and dashboard job progress/multi-selection. One successful pilot cannot prove full coverage.

## 2026-11-11 P0-C — Jellyfin subtitle into existing private SubHub stage (CODE ONLY)

**P0-C is now implemented in GitHub but NOT installed on OptiPlex. No staged Jellyfin candidate, ALASS result, publication or playback is yet verified.** This preserves P0 status honestly.

### Change, deliberately using existing machinery

- New `tools/ja_first_stage_jellyfin.py`: **one explicitly selected actual Jellyfin movie or episode** (no show-specific code), using the existing authoritative inventory and authentication. Preview is zero provider calls and zero writes. Explicit `--apply` performs **one** Jellyfin provider search and at most **one** remote subtitle GET. It reuses `probe_jellyfin_remote_subtitle.py`, not Jellyfin's direct-save POST; confirms correct media title/episode and Japanese SRT, checks host video duration, existing Japanese tracks, strict cue/text density, and writes **only** an exclusive-create private file and a row in the **existing** `japanese-stage.sqlite3`. It does not start ALASS or publish; there are no additional credentials, services or media directories.
- Source identity: staged names `<jellyfin_id>.jellyfin.<stable_numeric_hash_of_remote_id>.ja.srt` (not a fabricated OpenSubtitles ID). Private metrics record `provider=jellyfin`, the real underlying Jellyfin provider label (e.g. `subbuzz`), remote-ID SHA-256, item-scoped media identity, subtitle-content SHA-256, cue count and video runtime. No raw provider remote ID or credentials printed/saved. The existing DB has a `(jellyfin_id,subtitle_id)` key; collision against an existing provider must be refused rather than overwritten.
- Shared `ja_first_stage_timing_audit.py`, `ja_first_publish_staged.py`, `ja_first_alass.py`, `ja_first_ffsubsync.py`, `ja_first_publish_shifted.py`, `ja_first_publish_queue.py` now distinguish original OpenSubtitles vs new Jellyfin provenance. Their original publisher gating (timing comparison, ALASS/ffsubsync, Japanese density, exact item identity, video stream checks, create-only sidecars) is retained. Jellyfin stage provenance uses the existing private DB instead of falsifying Sublarr's historical search record. Original staged OpenSubtitles paths remain unchanged.
- `ja_first_publish_queue.py --jellyfin-id <32hex>` added so the pilot can examine/publish **only** its selected item, never accidentally another old staged title. Default remains dry-run. An actual `--apply` must be explicit and requires normal publisher approval.
- Updated the **existing reversible** `install_global_ja_sourcing.py`, not a new installer: includes required modules, preserves old files in a private rollback backup, refuses active source workers, and has an explicit `--install-only` flag that skips catalog refresh, coverage queue reconciliation, source timer changes and broad search. The old post-install check erroneously required a v3 marker `title_only_fallback`; it now checks the installed v4 strategy.

### Regressions encountered and resolved (avoid repeating)

- Initial shared-publisher integration introduced missing-provider-tag rejection for legacy OpenSubtitles stages. **Resolved:** old `.opensubtitles.` files may have no provider tag, but new `.jellyfin.` files require explicit valid source provenance. Existing publication-retirement tests pass.
- Existing ffsubsync tests create in-memory prepared records before a stage DB exists. Initial provider-aware derived naming tried to open that nonexistent DB. **Resolved:** legacy filename fallback only if stage DB is missing (publication still cannot proceed without DB); real staged records read/validate actual provider.
- New test imported bare `tools` modules while leaving `sys.path` globally altered, triggering unrelated older benchmark fixture errors in the **same test runner**. **Resolved:** restore import path immediately after loading test module; do not change frozen model fixtures. The provider-specific stage tests pass, and the full original suite was green after this correction.
- Tests added: `test_ja_first_stage_jellyfin.py` verifies exact episode identity, wrong-title/year rejection, encrypted/opaque remote-ID hashing, copy-once private staging + stored SHA, idempotence, no overwrite/collision, source-aware publisher file checks. `test_ja_first_publish_item_filter.py` verifies dry-run exact-ID filtering and invalid-ID denial.
- **Latest full CI:** [GitHub Actions P0-C suite](https://github.com/SteezyMode/bruiser-subhub/actions) passes on 3.11/3.12; **commit result from the latest test run must be rechecked** before host deployment. Unit success is not host success.

### P0-C next safe acceptance

1. Use only the **pinned** existing installer with `--install-only` (no source batch, no queue transition), after verifying source services idle. It backs up changes; the owner should see the exact installed revision in its output.
2. Run new adapter **without** `--apply` against IASIP S07E02: verifies real Jellyfin media file, runtime, existing Japanese sidecar/stream status without provider credits.
3. If eligible, single `--apply`: one remote search, at most one byte retrieval, private stage only. Report stage-ID, SHA and Japanese cue counts, not downloaded text. **No new media sidecar yet.**
4. Run `ja_first_publish_queue.py --jellyfin-id <ID> --max-titles 1 --limit 1` in **dry-run** to test ALASS/timing publication gates; only after affirmative owner review should `--apply` create the first sidecar. Check actual in-Jellyfin playback/timing before a broader batch.
5. If the exact episode already has Japanese subtitles or owner changes their media, hold. Do NOT bypass the no-clobber gate or choose another title without owner input.

**Remaining P0 problems:** confirmed 44/44 v4 no new matches, simplified Sublarr API losing metadata/year, first-50 truncation and cached `matches`, incomplete SubDL staging, and per-provider budget fixes still only tested in GitHub. The provider-backed adapter gives a practical alternate source path but is NOT a proven whole-library fix. P1 progress bars/mixed-movie batches and P2 poster grid remain clearly prioritized in issue #90.

## 2026-11-11 P0-B download **VERIFIED on OptiPlex** — authentication fixed

**Owner's successful rerun** (pinned probe SHA `9512c3cbba8ea90cafc624329f7783112f5a81b6`, single IASIP S07E02):
```text
JELLYFIN_REMOTE_RESULTS: 2
  Open Subtitles: Its.Always.Sunny.in.Philadelphia.S07E02.WEB-DL.DSNP (ja)
  subbuzz: Its.Always.Sunny.in.Philadelphia.S07E02.WEB-DL.DSNP.ja (jpn)
REMOTE_BYTES_PROBE: {"bytes":25989,"content_type":"application/x-subrip",
  "sha256_prefix":"afaf762847bc2564","text_decoded":true,
  "timed_cues":402,"japanese_characters":3502,
  "looks_like_timed_japanese":true}
IN-MEMORY ONLY: no files or DB altered.
```
**Proven now:** after owner configured existing OpenSubtitles credentials in subbuzz, its OpenSubtitles.com backend can actually download Japanese SRT bytes through Jellyfin's GET without touching media. **No staged file, ALASS sync, quality approval, publication, or Jellyfin playback has occurred yet.** The password is not stored in this repo. Do not repeat the old login-debugging attempt.
**Next:** correctly attribute Jellyfin/subbuzz source identity in existing SubHub private staging and ALASS publisher, with create-only publication and regression tests. Existing publisher/staging filenames were originally locked to `opensubtitles.<numeric-id>`; do not rename a subbuzz result to OpenSubtitles or bypass existing trust gates. Start with one owner-chosen media, then generalize. P0 broader v4 search quality remains unsolved.

## 2026-11-11 owner-confirmed OpenSubtitles identity and provider toggles

- **Owner-confirmed OpenSubtitles username: `ajstarrett`** (the earlier `optiplex` login guess was incorrect). Use the EXISTING account, not a new registration. The account password was provided privately in chat, but **must not be committed to this public repository**; no password/email/reset link/token/API key has been added here. ChatGPT/this repository must not be treated as a reliable secret vault.
- **Owner's screenshot of subbuzz Settings → Providers:** `OpenSubtitles.com` checked, `YIFY Subtitles` checked, `Subdl.com` and all remaining sources unchecked. This is a **list of enabled nested subbuzz providers**, not evidence that the checked ones can authenticate or download.
- **Exact existing source behavior:** `subbuzz`'s `Providers/OpenSubtitlesCom.cs` requires its own username+password at download time; Jellyfin's other OpenSubtitles plugin and Sublarr account are independent. `subbuzz`'s `Providers/SubDl.cs` requires both the provider checkbox **and** a `SubdlApiKey`; checking it without an API key does nothing. Sublarr already has SubDL enabled/working in its separate configuration, so only consider reusing that existing key locally; avoid another account. YIFY respects the requested subtitle language, so it can stay enabled but its actual Japanese yield is unproven.
- **Operational next action:** save correct existing OpenSubtitles credentials in Jellyfin Dashboard → Plugins → subbuzz → OpenSubtitles.com Account. Keep OpenSubtitles and YIFY on; optionally enable SubDL once its existing valid key is locally configured, respecting combined provider quota. Then rerun ONE in-memory subtitle GET before adding any new source/publisher code. Never enable every provider indiscriminately.
- **Priority still P0 search quality:** this fixes an authentication/download blocker only; it does NOT resolve the 44/44 new-search miss rate, Sublarr metadata transport/50-result truncation, or full-workflow validation.

## 2026-11-11 P0-B root cause confirmed — subbuzz OpenSubtitles authentication not configured

**Host log inspected by owner after in-memory GET failure**:

```text
Jellyfin GET /Providers/Subtitles/Subtitles/<redacted provider-specific ID>
System.Security.Authentication.AuthenticationException:
  Account username and/or password are not set up
at subbuzz.Providers.OpenSubtitlesCom.Login(...)
at subbuzz.Providers.OpenSubtitlesCom.GetDownloadLink(...)
at subbuzz.Providers.SubBuzz.GetSubtitles(...)
at Jellyfin.Api.Controllers.SubtitleController.GetRemoteSubtitles(...)
```

- **Confirmed:** The selected subbuzz result's actual underlying provider was **OpenSubtitles.com**. The OpenSubtitles.com username/password fields in the subbuzz plugin were **not configured**; it can show search results but cannot download until authenticated. This is a **configuration blocker**, not evidence of a missing Japanese subtitle, a bad title match, or a failed ALASS correction.
- Verified upstream `josdion/subbuzz` code: `Providers/OpenSubtitlesCom.cs` `Login()` throws this exact exception if `OpenSubUserName` or `OpenSubPassword` is missing. Its Jellyfin configuration page has **OpenSubtitles.com Account** username/email and password inputs, plus the separate OpenSubtitles provider toggle. The existing independent Jellyfin OpenSubtitles plugin and separate Sublarr account settings do **not** populate the subbuzz fields automatically.
- **Prior existing-account recovered privately:** An existing OpenSubtitles registration was confirmed through connected personal mail and past interactions; **do not place account email, username, passwords, API keys, reset links or tokens in this PUBLIC GitHub repository**. No new account needed merely to resolve this issue. The owner can use that already-owned login and recover/reset its password through OpenSubtitles if needed. **Do not suggest creating another OpenSubtitles account by default.**
- **Next allowed repair:** owner opens Jellyfin Dashboard → Plugins → subbuzz configuration → OpenSubtitles.com Account, configures the **existing** account locally, saves, and only then performs a one-candidate in-memory GET again (budget-aware). Do not send credentials in chat, shell history, GitHub or logs. If plugin configuration already has a valid login for the native OpenSubtitles plugin, that is *separate plugin configuration*; consolidate identities, not code duplication.
- **Still unverified:** successful remote subtitle bytes retrieval via this backend; private staging to ALASS and no-clobber publication; whether subbuzz's other underlying providers add new candidates. Do not mark P0 solved. Separate unrelated FFprobe errors for *American Horror Story* during Jellyfin scan are not part of this failure.
- **Diagnostic patch:** `tools/probe_jellyfin_remote_subtitle.py` now reports `HTTP_XXX` (without response body, URL, or credentials); unit tests passed. The actual journal supplied the decisive error without another provider request.

## 2026-11-11 P0-B LIVE retrieval attempt — search succeeded; bytes NOT retrieved

**Actual owner-run host output (one episode, subbuzz):**

```text
ITEM: It's Always Sunny in Philadelphia S07E02
SAVED SUBHUB: version 2, none, provider hits 0
JELLYFIN_REMOTE_RESULTS: 2
  Open Subtitles, Its.Always.Sunny.in.Philadelphia.S07E02.WEB-DL.DSNP,
     language ja, exact_item_name=true, selected_provider=false, srt
  subbuzz, Its.Always.Sunny.in.Philadelphia.S07E02.WEB-DL.DSNP.ja,
     language jpn, exact_item_name=true, selected_provider=true, srt
REMOTE_BYTES_HELD: HTTPError
```

**What we know:** `GET /Items/{id}/RemoteSearch/Subtitles/ja` succeeded; exact episode/title match selected; **subbuzz GET of bytes failed**. No remote subtitle bytes obtained, staged, synced, published or played in Jellyfin. No media files changed. The pilot caught `urllib.error.HTTPError` but **printed only its type**, hiding the actual HTTP code. We **cannot yet classify** as 401/403 authorization, 404 route/ID issue, 429 provider cap, or 500 plugin error. **Do not repeatedly call providers to guess.** Start with Jellyfin's *existing* journal from that time. A narrow `safe_failure()` patch in `tools/probe_jellyfin_remote_subtitle.py` now prints the HTTP numeric code only, without error body, provider URL or auth, if a later bounded rerun is justified; regression test added.

**New upstream subbuzz source finding:** [josdion/subbuzz](https://github.com/josdion/subbuzz) is **one Jellyfin plugin aggregating multiple underlying catalogs** including OpenSubtitles and SubDL. Its visible `ProviderName="subbuzz"` is not proof of an independent subtitle source. SubBuzz uses nested provider-prefixed `Id` values and dispatches `GetSubtitles` to the relevant underlying provider. The two IASIP results could point to the same subtitle. **Do not count them as independent coverage or assume subbuzz adds free search/download allowance.** Check the actual installed plugin and the journal before making further integration promises.

**Read-only OptiPlex journal command, no provider queries:**

```bash
ssh optiplex@100.121.156.34 \
  'journalctl -u jellyfin --since "3 hours ago" --no-pager -o cat |
   grep -Ei -C 4 "subbuzz|GetRemoteSubtitles|SubtitleController|subtitle.*(error|fail)|Exception|rate.limit" |
   tail -110'
```

Review/redact any accidentally printed provider credentials before posting the output. If logs have rotated or omit the error, the next controlled attempt should use the patched probe and print only `HTTP_XXX`, not a new full-library search. With the precise status and/or stack trace, repair only the actual cause, then validate a **single** in-memory retrieval before touching private staging.

## 2026-11-11 LIVE benchmark outcome — Jellyfin existing provider path

**Owner executed** `tools/benchmark_subtitle_search_paths.py --execute` against three actual Jellyfin items on OptiPlex; **no subtitles downloaded/published and no library files altered**. This is the first real alternate-path measurement; don't revert to the earlier `not run` statement further below.

| Same Jellyfin item | SubHub stored search | Jellyfin native remote-search |
|---|---|---|
| *Bride of Chucky* (1998) | v4 `none`, provider reported 12 results, 62 retained rejects, 0 usable | **0** Japanese candidates |
| *Late Night with the Devil* (2024) | v3 `review`, 3 saved exact-title JA candidates (original year 2023) | **6** JA results: **3 Open Subtitles** and **3 subbuzz** (potential duplicate releases; NOT 6 distinct translations) |
| *It's Always Sunny in Philadelphia* S07E02 (2011) | **v2** `none`, provider total 0, zero saved candidates | **2** JA results: **1 Open Subtitles** and **1 subbuzz**, same `WEB-DL.DSNP` release candidate (possibly duplicate) |

**What this actually proves:** Jellyfin's configured remote subtitle providers can discover real, correctly titled Japanese candidates for two known-positive items, including the **subbuzz** provider absent from SubHub's effective OpenSubtitles staging flow. The old v2 episode miss is **not evidence v4 would miss that episode**. The *Late Night* v3 results had already been recovered into REVIEW (unverified 2023/2024 release), so do not claim Jellyfin alone found that film. For *Bride*, **both paths returned no usable JA**; do not accept mismatched 'Bride' filenames. Remote search results are NOT downloaded subtitle bytes or verified timing.

**Newly verified API possibility:** Jellyfin supports `GET /Providers/Subtitles/Subtitles/{subtitleId}` returning remote subtitle bytes **without attaching/writing them to the video**. Inspect upstream `Jellyfin.Api/Controllers/SubtitleController.cs` `GetRemoteSubtitles` versus **do NOT use** `POST /Items/{itemId}/RemoteSearch/Subtitles/{subtitleId}`—the latter calls `DownloadSubtitles()` then `TrySaveSubtitle()`, writing directly in media directories and bypassing SubHub's ALASS/non-overwrite QA. A bounded, single-result **in-memory GET probe** is the appropriate next test. GET of remote bytes may consume a provider download allowance. No media-file side effects claimed for the GET endpoint; test on the installed host before integrating into the private stage pipeline.

### P0-B: Single Japanese subtitle byte retrieval without touching Jellyfin media

- **Confirmed upstream API semantics from Jellyfin's own source:** [`SubtitleController.GetRemoteSubtitles`](https://github.com/jellyfin/jellyfin/blob/master/Jellyfin.Api/Controllers/SubtitleController.cs) handles authenticated `GET /Providers/Subtitles/Subtitles/{subtitleId}` by returning the provider's remote subtitle stream as a file; the corresponding `POST /Items/{itemId}/RemoteSearch/Subtitles/{subtitleId}` calls `SubtitleManager.DownloadSubtitles` → `TrySaveSubtitle` and may write into the media directory. **NEVER use the POST in a SubHub pilot**: it bypasses pre-stage ALASS, identity QA and existing no-clobber protection.
- **Added/committed:** `tools/probe_jellyfin_remote_subtitle.py`, `test_probe_jellyfin_remote_subtitle.py`. Explicit one-media / one-provider `--execute --fetch-one` uses Jellyfin's existing auth and catalog identity, one remote search, conservatively validates exact series/title + episode or exact movie title/year, then at most **one** authenticated GET of remote subtitle bytes into **bounded memory** (2 MB). It prints only candidate metadata, format, timestamp-cue count, Japanese character count and a short hash. It **never saves subtitle bytes, reveals their text or remote IDs, changes DB/files, creates media folders, stages or publishes**. Authentication redirects blocked. User must deliberately opt in: an underlying plugin search and download allowance may be consumed. Defaults to a zero-network preview.
- **Test evidence:** [GitHub Actions run 42950322756](https://github.com/SteezyMode/bruiser-subhub/actions/runs/42950322756) passed Python 3.11/3.12 with tests for exact IASIP identity despite apostrophe style, wrong episode/title/language rejection, GET-only with credential on loopback, cap/redirect fail-closed and subtitle cue/Japanese evidence.
- **Host status:** **NO live remote subtitle byte GET performed yet**. Code only. A positive fetch proves the third-party subtitle plugin's remote bytes are retrievable without media writes; it **does NOT** prove release timing, translation quality, safe auto-publication or fully working batch sourcing.
- **Next integration decision:** once a real in-memory fetch succeeds, implement the **smallest** private staging adapter into the **existing** SubHub stage database and ALASS publisher (not Jellyfin's direct-download POST), retaining Jellyfin provider ID/provenance, real media identity and no-clobber. Keep the unproven metadata/SubDL defect separately open. Avoid repeated provider calls and alternate provider account setup until proven necessary.

**Reproducible one-item host command; optional, total of one remote search + at most one GET:**

```bash
ssh optiplex@100.121.156.34 'bash -s' <<'REMOTE'
set -euo pipefail
PIN="0e3f2875715eba0fcdf802e7f352bef4704bf8aa"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
for file in benchmark_subtitle_search_paths.py probe_jellyfin_remote_subtitle.py; do
  curl -fsSL "https://raw.githubusercontent.com/SteezyMode/bruiser-subhub/$PIN/tools/$file" -o "$WORK/$file"
done
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$WORK:$HOME/bruiser-pilot/subhub-control" \
  python3 -B "$WORK/probe_jellyfin_remote_subtitle.py" \
  --episode "It's Always Sunny in Philadelphia S07E02" \
  --provider subbuzz --execute --fetch-one
REMOTE
```

This deliberately tests **subbuzz**, the added Jellyfin provider path, on the previously recognized exact S07E02 release. The command creates only temporary copies of the two scripts under `mktemp` (cleaned at exit), makes **no media modifications** and only prints aggregate/candidate names—not any copyrighted subtitle text. Results may be `REMOTE_BYTES_HELD` if the plugin has no remaining download allowance; record this honestly.

**P0 direction after benchmark:** don't rebuild a provider catalog or assume v4 success. Verify Jellyfin remote retrieval on one exact episode candidate (prefer subbuzz for incremental provider coverage), then consider an adapter that stages bytes **privately**, retaining provider/ID/episode provenance and existing ALASS/QA. Correct Sublarr metadata/query/participation remains unresolved separately; an alternate maintained Jellyfin provider route may reduce the need for bespoke source work if proved successful. Keep OpenSubtitles/SubDL quotas separate across systems.

## 2026-11-11 continuation — P0-A attempt record (code + comparison, NO host acceptance yet)

**This section is the most recent work.** Keep it visible. The earlier host audit below remains the authoritative measurement of the installed OptiPlex.

### Attempt P0-A1: Stop losing OpenSubtitles when SubDL reaches its pacing gate

- **Trigger/repro:** Owner's November 11 audit: full-library source v4 performed 44 `NONE` and ended at #45 `DEFERRED` on *Jug Face*. `provider_gates={opensubtitles:ok, subdl:budget_exhausted}`. Earlier `require_sources()` required **every** provider to be open.
- **Patch:** `tools/ja_first_search_pilot.py` now sends a search to the existing long-lived Sublarr server when **any** enabled core Japanese provider is healthy. Sublarr's own coordinator still applies the other provider's budget and skips blocked providers. Health is checked before and after, and if any enabled provider is unavailable, results are marked **partial/incomplete**, never an exhaustive `none`. If all are unavailable, the worker emits `deferred` and does not POST. If a provider closes between first IMDb lookup and optional fallback, the first response is retained.
- **Persistence:** Empty incomplete queries get `outcome=partial`; `incomplete_providers` and gates are stored alongside existing candidate/rejected evidence. Partial search is retry-eligible after 20 hours, not continuously re-requested in the same budget window. The coverage queue continues `search_ja` for partial/deferred; selected-TV workflow uses the same contract. Staging code can recognize `partial` history. Journal/parser/dashboard now count **Partial** separately from **No match**. Existing plausible candidates are retained without being automatically published.
- **Offline evidence:** `test_ja_first_partial_providers.py` covers SubDL blocked/OpenSubtitles active, all blocked/zero provider POSTs, a gate closure between movie queries, private history+retry and real partial progress reporting. A fully completed `PARTIAL` batch now displays **"Finished selected searches; provider coverage incomplete"**, not all providers searched. The read-only audit parser also recognizes `PARTIAL`; additional tracker and audit regressions pass. The latest full-suite run (GitHub Actions [42949454242](https://github.com/SteezyMode/bruiser-subhub/actions/runs/42949454242)) passed on Python 3.11 and 3.12.
- **Deployment & limitations:** **NOT confirmed installed on OptiPlex. NOT a proven increase in Japanese subtitle matches.** The combined endpoint can still return caches, skip particular providers, strip metadata and cap results. Pre/post health alone cannot prove which provider was searched. There is no per-provider-specific search API here, so rechecking partial records later can repeat queries for already-open providers. That is tracked, not concealed.

### Attempt P0-A2: Compare an *existing* metadata-aware library search route before rewriting Sublarr

- **Reason:** Sublarr v1.18.0 POST `/providers/search` drops `VideoQuery.year`; SubDL's actual `year` parameter is generated only from that field. Appending a year to plain title in SubHub v4 does not restore it. The same endpoint truncates to 50; cached match evidence may be absent. We verified those behaviors also persist in the simplified endpoint at Sublarr v1.20.1; upgrading untested would be an ungrounded promise.
- **Added:** `tools/benchmark_subtitle_search_paths.py` with `test_benchmark_subtitle_search_paths.py`. It selects **one to three explicitly named items** from the existing Jellyfin-authoritative private manifest, prints previous SubHub outcome/partial-rejected counts, and *optionally* calls Jellyfin's authenticated, built-in `GET /Items/{itemId}/RemoteSearch/Subtitles/ja` for the **same library item**. Defaults to **preview/no remote requests**; `--execute` is explicit; no downloads, DB writes, publisher or folder mutations. The actual underlying Jellyfin plugin request counts may differ from the 1–3 API requests and may consume quotas.
- **Use to determine:** Is a known correct-title Japanese subtitle discoverable via Jellyfin with its exact item metadata when SubHub v4 says `none`? What provider responded? Does the title/episode name match? This is **discovery only**, not subtitle validation or publication.
- **Test history:** The first standalone benchmark-test CI failed because the unittest accessed `urllib.request.Request.method` (not the documented `.get_method()`); corrected in [commit `35d8679`](https://github.com/SteezyMode/bruiser-subhub/commit/35d867965c68efb4bb470a94c1a8b3caa35a7d62). Running as a pinned temporary file originally also required the installed source directory on `PYTHONPATH`; direct-script import fallback was added in `1b7026b`. The complete latest offline tests passed on both Python versions ([run 42949454242](https://github.com/SteezyMode/bruiser-subhub/actions/runs/42949454242)). **No live Jellyfin provider call has yet been made by this benchmark.**
- **Deployment & outcome:** **Owner ran the three-item benchmark on OptiPlex Nov 11.** It returned 0 candidates for *Bride of Chucky*, 6 for *Late Night with the Devil* (3 Open Subtitles + 3 subbuzz; may duplicate), and 2 for IASIP S07E02 (1 each, same release). This verifies Jellyfin's existing providers can find JA for known-positive items, **not** that v4 would miss them or that returned candidates are stageable or publishable. Full original output is transcribed in the P0-B live benchmark section above.

### Reproducible Jellyfin comparison command, only after checking installed source is idle

Download the pinned comparison tool (does not install or modify anything) and show the plan with **zero provider calls**:

```bash
ssh optiplex@100.121.156.34 'bash -s' <<'REMOTE'
set -euo pipefail
PIN="1b7026b9cea9dfbd018c325537085b0ea19db0f4"
TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT
curl -fsSL "https://raw.githubusercontent.com/SteezyMode/bruiser-subhub/$PIN/tools/benchmark_subtitle_search_paths.py" -o "$TMP"
python3 -B "$TMP" --movie "Bride of Chucky" \
    --movie "Late Night with the Devil" \
    --episode "It's Always Sunny in Philadelphia S07E02"
# To perform THREE Jellyfin remote-subtitle searches (which MAY spend upstream
# quotas), repeat the same python command with --execute appended.
REMOTE
```

The script reads the existing private catalog/Jellyfin auth, prints only titles, metadata, prior SubHub counts and up to ten subtitle result names per item; no credentials, subtitle bytes, sidecar writes or new directories. If a title is missing/ambiguous, **the probe fails instead of guessing**. These examples are a **bounded comparison cohort only**, not hardcoded search logic. To test other titles, replace the three CLI arguments.

### One bounded next real test (do not start a full scan)

1. Verify source worker idle and retain backups; if choosing to install P0-A1, use an installer pinned to a verified commit. **Do not silently enable the daily timer** or launch a batch.
2. Probe the *read-only preview* against actual Jellyfin manifest identities. Compare up to three known titles with `--execute` **only after checking provider quotas**, e.g. *Bride of Chucky*, *Late Night with the Devil*, and IASIP S07E02. No files will be downloaded; even zero Jellyfin results may reflect a missing plugin.
3. Compare outputs against the saved SubHub evidence. If Jellyfin finds real correct-title Japanese and SubHub doesn't, locate the minimal maintained metadata-aware route. If both miss, inspect provider raw search/skip logs. A single successful sample never authorizes a library-wide scan.
4. Document actual provider calls, confirmed matches, staging verdict and installed SHA in this roadmap and [issue #89](https://github.com/SteezyMode/bruiser-subhub/issues/89). **P0 remains open** until subtitles reach Jellyfin verified; P1 job progress/movie batches remain explicitly prioritized.

## 0. Truth-in-status register — update after EACH real test

| Layer | What is currently established | What is NOT established |
|---|---|---|
| GitHub | Search v4, quota deferral safeguard, saved-year review recovery, progress-stop parser/UI and a read-only audit are committed; tests have passed for individual changes. | That changing the repo improves a real source-to-Jellyfin job. |
| OptiPlex | **Owner ran audit Nov 11:** installed source worker strategy **4**. Last run had **44 `NONE` and 1 `DEFERRED`**, stopped at search 45/600 because **SubDL budget exhausted while OpenSubtitles gate was OK**. `AUTOFILL_CYCLE_COMPLETE` means downstream steps finished, NOT full search complete. | Latest dashboard parser/UI patch installed; search metadata truly reaching providers; all provider participants/usage for each title. |
| Actual provider performance | 44 v4 movie searches in that run produced **zero saved acceptable candidates**. Direct Japanese OpenSubtitles test for IASIP S07E02 (and earlier S08E01) found an exact-episode candidate. A sample of movies returned many **irrelevant** Japanese results with overlapping title words. | 44 actual titles have no JP subtitles; v4 improves usable yield; SubDL title lookup improves film recall. |
| Staging & playback | 19 previously saved/staged Japanese sidecars were published in the source-only pass (not from the 44 new hits). Owner separately confirmed **ALASS binary available** and **publisher invokes `alass.prepare()`** on OptiPlex. | Those 19 were playback-reviewed; all staged results pass opening/middle/end dialogue checks; all provider candidates can be staged. |
| UI | TV-season/episode multi-select exists and works at an elementary level. User can search/select one movie; full-library pass has partial progress. | Movie category/poster browsing, multi-movie batch, or **reliable progress bars for every job** have shipped. |

**Definitions:** `provider_total` = Sublarr combined endpoint results, not necessarily correct-media hits. `none` = no candidate surviving local grading; does NOT prove no Japanese is published online. `deferred` = incomplete provider attempt; must not advance to PLaMo. `staged` = bytes acquired, not a playable subtitle. `published` != correct sync/readability in Jellyfin.

## 1. Reproducible server evidence, not hypotheses

**Nov 10 sample (last 25 movies):** 809 summed provider-reported hits; 24 `none`, 1 `deferred`, 0 usable, **854 saved rejections** (includes previously retained evidence, thus not equal to 809 distinct responses). Examples:
- `Bride of Chucky` returned Japanese for `Bride Of Re-Animator`, `Cult of Chucky` and an unrelated Japanese “Bride” movie; do not accept those.
- `Mad God` -> `The Mad Women's Ball`; `Grave Encounters` -> `Grave of the Fireflies`. Strict wrong-title rejection is correct.
- `Late Night with the Devil` returned three matching-title JA files labeled **2023** while library year could be **2024**. We committed narrow **review-only** one-year discrepancy recovery, not automatic publication. Actual saved-history recovery found only **7 review candidates across 4 of 586 movies** (~0.7% of records). Not the primary blocker.
- `It's Always Sunny in Philadelphia S07E02` direct combined/provider test found `Its.Always.Sunny.in.Philadelphia.S07E02.WEB-DL.DSNP.ja` plausible. A previous full-show run had ~54 zeroes while separate direct per-provider searches found S07E02/S08E01: search coverage and participation differ.

**Nov 11 owner-run read-only audit** (`tools/audit_subhub_sourcing.py`, commit `d41ca4ae51cf9742569552c6e15b63aefa9d304d`):
```text
installed_source_strategy = "4"
last_source_cycle.plan = "Search requests planned: 600 | budget: 600"
last_source_cycle.search_outcomes = {"NONE": 44, "DEFERRED": 1}
last_source_cycle.last_search_index = 45
last_source_cycle.pipeline_completed = true
defer at Jug Face: opensubtitles: ok, subdl: budget_exhausted
latest_100_saved_searches = 96 none, 1 deferred, 1 in_progress, 2 review
strategy_versions = 45 v4, 3 v3, 52 v2
budget_pacing = stretch; safety_margin_pct = 20
provider health = OpenSubtitles enabled/initialized/ok, SubDL enabled/initialized/ok
current quota usage = 0 for both following UTC counter reset
```
**Exact conclusion:** v4 did run; the **whole batch stopped because ONE provider (SubDL) hit pacing while OpenSubtitles could still search**; stale `in_progress` and high rejected counts also need accurate accounting. Do **not** blame the browser or old v3, and do **not** claim 44 films have no JA.

## 2. Cause map — confirmed code defects versus open questions

### A. Subtitle search / response path
1. **Metadata stripped in Sublarr 1.18.0:** POST `/api/v1/providers/search` constructs `VideoQuery` from basic fields, **not** supplied `year`, `episode_title`, extended IDs, profile or allowed-provider settings. OpenSubtitles searches can therefore be too broad; **SubDL's `year` parameter is only sent if `VideoQuery.year` is set.**
2. **Result truncation:** route responds `results[:50]` even when combined provider manager found more. Irrelevant partial-title results can crowd correct ones before SubHub's grader sees them.
3. **Episode series-ID mismatch (v1.18.0):** query's series IMDb is treated as OpenSubtitles episode `imdb_id` rather than `parent_imdb_id`. Upstream 1.20.1 fixes parent-ID behavior, but upgrading alone has not been tested and may not fix endpoint metadata loss.
4. **Cache evidence loss:** Sublarr combined cache deserializer reconstructs result without `matches` evidence; SubHub stage identity insists on series/season/episode match markers, so a cached answer can be rejected even if the same fresh provider response was acceptable. Confirm exact on-host behavior before patching.
5. **v4 is incomplete by design:** appending `1998` to a text title is **not** the true year constraint; a too-broad results set still returns irrelevant Japanese subtitles. v4 retains only first 100 selected results locally, before full identity audit. No proven source-yield improvement on the host.
6. **Per-provider participation unknown:** health `gate: ok` after an attempt does not prove provider was queried for that title. Log evidence showed AnimeTosho responses without OpenSubtitles/SubDL during some zero-result searches. Need per-attempt cache/search/skip/error information.
7. **One-provider gate abort:** v4 `require_sources()` blocks if **either** OpenSubtitles or SubDL is unavailable. On Nov 11 the run aborted though OpenSubtitles was still open. Must treat per-provider deferred states independently and continue available safe sources without claiming exhaustiveness.
8. **Pacing/quota:** Sublarr `stretch` uses hour-of-day UTC quota fractions plus 20% safety margin. A 600 search plan is a **ceiling**, not an ETA or actual eligible denominator, and title retries can require multiple provider calls. Do not disable budgets or bypass shared manager quotas just to increase counts.

### B. Candidate / stage / publish path
9. **OpenSubtitles-only staging:** `tools/ja_first_stage_saved_batch.py::identity_ok` hard-requires `provider == opensubtitles` and numeric subtitle ID; `stage` downloads only OpenSubtitles. SubDL candidates never progress through the same automatic staging/ALASS pipeline.
10. **Overstrict identity and missing evidence:** exact title+year checks can reject different release/film-festival years; stage requires series-title tokens and full match markers even if identity could be independently confirmed. **Never blindly relax these.** Route ambiguous candidates to review with proven independent provider media ID / correct season and episode. Avoid wrong-file publication.
11. **Unfinished observability:** old tracker didn't recognize `DEFERRED`, and UI showed `44/600 (7%)` even after stage/publication completed. Parser/UI fix was committed (CI success), but host deployment not confirmed. Manual movie / season / translation job progress still needs consistent bars.

## 3. What was actually done — chronological change log

| Work | Code or evidence | Verification / limitation |
|---|---|---|
| Alternate series-name search | Initial IMDb-free fallback + owner selected-show checks | Used, but 54 returned zero and provider participation was unverified |
| Gate inspection | Sublarr `GET /api/v1/providers/health` + budgets | Live health: OpenSubtitles/SubDL enabled; hourly `stretch` can still block |
| Deferred, not absence | `tools/ja_first_search_pilot.py`, `tools/subhub_season_sources.py` (Nov 10) | Safeguard committed; Nov 11 host shows a real defer at title 45; one-provider stop flaw remains |
| Full-library browser counters | Dashboard markup/parser, Nov 10-11 | UI progress added; misleading partial completion later corrected in GitHub, **not known installed** |
| Narrow film year review | Same shared candidate grader + offline saved-review restoration | **7 candidates, 4 movies / 586 checked**; zero automatically published from this recovery |
| v4 movie/TV worker | [Commit 16eebc8](https://github.com/SteezyMode/bruiser-subhub/commit/16eebc824515256fce779a31e58bce233f347c54) | **Installed v4** verified by owner audit; **44/44 new searches yielded 0 stageable**, so do not mark fixed |
| ALASS path | Installed `ja_first_alass.py`; publisher uses it | Owner confirmed binary available and publisher integration; do not change timing engine while diagnosing source yield |
| Read-only consolidated audit | `tools/audit_subhub_sourcing.py` + test, [commit d41ca4a](https://github.com/SteezyMode/bruiser-subhub/commit/d41ca4ae51cf9742569552c6e15b63aefa9d304d) | Owner ran successfully; no provider credits, no downloads |
| Early-stop dashboard correction | `tools/ja_first_source_tracker.py`, `tools/subhub_dashboard_server.py`, `tools/subhub_dashboard.html` | GitHub CI passed after `10d57a8`; **not confirmed host-installed** |
| Consolidated active work | [Issue #89](https://github.com/SteezyMode/bruiser-subhub/issues/89) (P0 search) and [Issue #90](https://github.com/SteezyMode/bruiser-subhub/issues/90) (P1/P2 UI, automation) | Open; these are work records, not completion proof |

**No owner authorization** to launch another 600-title run or silently enable scheduled search/translation. Do not overwrite sidecars/media. Do not repeat 2023/2024 title-review micro-fixes as the supposed search solution.

## 4. Recovery plan — high-priority and testable

### P0 — Diagnose and repair *search recall through an end-to-end working provider path*
- [x] Establish host version v4 and exact reason for 44/600 stop; preserve zero-credit audit.
- [ ] **Read-only baseline:** review saved Japanese search records for a named 10-item cohort including known positives/negatives and missing-media metadata. Distinguish provider raw hits, filtered hits, exact-media hits, stageable, and sync/publish status. No search credits required for existing history.
- [ ] **Compare available maintained solutions before more custom code.** In a controlled scratch setup, evaluate correctly configured Sublarr and Bazarr+Sonarr/Radarr (already an open project principle). Preserve installed working host stack. Choose simplest effective approach; do not construct a parallel subtitle manager.
- [ ] **Correct precise provider query metadata in the existing long-lived Sublarr service** (or through a maintained API/upgrade that exposes it): movie IMDb/TMDb + **true year**, TV **parent series identity** + season/episode, native title aliases/release evidence as appropriate. Preserve session, budget counting, provider errors and cache keys. Avoid instantiating an ephemeral provider manager in `docker exec` that could reset in-memory quotas.
- [ ] **Fix result transport**: no premature 50-result cap before safe identity evaluation; preserve `matches`, exact provider feature IDs, release data and format in fresh **and cached** responses; journal/debug a single attempt's provider participation (attempted, skipped and why, cached, failed).
- [ ] **Fix provider budget semantics**: when SubDL is paced but OpenSubtitles available, search OS; persist incomplete SubDL coverage separately and retry its portion next allowance. A partial `NONE` is **not** final exhaustion. Do not exceed provider safety ceilings.
- [ ] **Fix staging breadth**: add safe authenticated SubDL download for candidates with proven identity, private byte validation, checksum/provenance, normal ALASS/ffsubsync QA and no-clobber publication. No arbitrary broad acceptance.
- [ ] **Benchmark cohort, not another library run:** include `Bride of Chucky`, `Mad God`, `Late Night with the Devil`, IASIP S07E02 and S08E01, plus representative no-hit examples. Use explicitly bounded provider requests. Compare true correct-title JA candidates, stageable artifacts, and at least one verified playing in Jellyfin. Wrong-title hits must remain rejected.
- [ ] **Only after this passes**, resume bounded library work, persist per-title outcomes and provider-deferred resumes; never label `provider_total>0` as useful coverage by itself.

**P0 acceptance:** at least the known-positive IASIP case can be found, correctly staged, synchronized/validated and selectable in Jellyfin; no unrelated `Bride`/`Grave` files accepted; source queries transmit required metadata to provider; no silent skip; no surprise 600-title queries; benchmark shows independently measured correct-title results, not merely more noise.

### P1 — Every job must have a REAL progress bar in the dashboard (core usability, not polish)
- [ ] Persistent dashboard Active / Queued / Recent jobs across full-library, single movie, multi-movie, selected TV, PLaMo, staging, ALASS/ffsubsync QA, publish.
- [ ] **Every job**: running/queued/paused/blocked/failed/done state, real numerator/denominator, current film/episode, phase, remaining count and outcome counters. On error or budget defer show reason and, when known, next retry. Reopen browser without losing progress. A greyed-out button **is never a status indicator**.
- [ ] Use actual job scope; if numerator/denominator unknown show indeterminate + completed count, not a fabricated `44/600 7%` claim. If provider budget stops early show partial search while completed publications remain visible.
- [ ] Include clear Stop/Resume where supported (honest state); no unused decorative buttons.

### P1 — Owner-initiated multi-movie batches at will
- [ ] Accept arbitrary selected existing Jellyfin movie IDs across genres and search results, build **one bounded serial/resumable queue**, show per-film steps/outcomes. The existing single-film source path and TV batch prove owner need; DO NOT wait for 100% library coverage to make this available.
- [ ] Respect existing shared source/ALASS/QA and provider budgets; no second catalog/provider client/hidden translation.

### P2 — Jellyfin-style movie poster browser (not just a search filter)
- [ ] **Selecting Comedy loads the entire Comedy library as a poster grid when search input is empty.** Same for Horror, Action, All Movies. Genre drop-down is **navigation**, not a meaningless extra restriction on typed title search.
- [ ] Paginated/infinite-scroll poster grid with title/year, real artwork or placeholder and missing/existing Japanese status; use existing Jellyfin ID, metadata/genre, authenticated artwork, never invent file names or create folder structures.
- [ ] Independently type `Step Brothers` in search; multi-select from both grid and search, selections persist across category/page changes; one batch for 3 horror + 2 comedy + 1 action films.
- [ ] Prefer direct reused catalog/Jellyfin endpoints; no bespoke indexing engine or redesign.

### P2 — New-media incremental automation (only after P0 established)
- [ ] Refresh/diff Jellyfin IDs periodically (simple incremental ingestion first), enqueue newly-added items missing JA; don't repeat searches for already covered media; respect quotas and existing sidecars.
- [ ] Report per-title success/held/retry in dashboard. Start scheduling only with owner consent after demonstrated reliability. PLaMo remains manual last resort.

## 5. Handoff / rules for next new chat (copy this section into your working plan)

1. **Do not ask the user to repeat the history.** Read this roadmap and issue #89, code, and the Nov 11 audit above. The owner is frustrated with many prior 'fixes' that did not increase usable subtitle yield.
2. **Prove host version before interpreting logs.** Latest measured host search worker is v4, not v3. If newer code committed but not installed, say exactly that. No unannounced deployments.
3. **Do not start with another massive scan** or another arbitrary matching-regex patch. First do per-provider metadata/response/cached-evidence and native downloader analysis, one representative acceptance case.
4. **Respect separate goals:** the immediate goal is high-quality, human-authored Japanese with actual ALASS sync and Jellyfin playback. Job progress and arbitrary mixed-movie batches are P1 usability features, not cosmetics. Genre poster grid and auto-new media are P2; record them, don't derail P0.
5. **Maintain consistent status for every stage:** discovery `searched`, `provider_skipped`, `none` vs `deferred`, `correct_title`, `candidate_review`, `stageable`, `staged`, `aligned`, `published`, `Jellyfin_playback_verified`. Never conflate.
6. **Protect owner media:** private credentials, no overwrite, no unsolicited folder creation, no removing known-good subtitles, no PLaMo launched by negative search; inspect existing host directories. Preflight tests and backups for changes.
7. **Update THIS document and issues #89/#90 after each major result.** Record commit, host installed?, provider credits used?, candidate IDs observed (without copyrighted subtitle text), actual publication/playback and next unblocked step. Future chats should be able to resume with no archaeology.

## 6. Safe commands / source pointers

Read-only audit, executed by owner (known working):
```bash
ssh optiplex@100.121.156.34 'bash -s' <<'REMOTE'
set -euo pipefail
PIN="d41ca4ae51cf9742569552c6e15b63aefa9d304d"
TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT
curl -fsSL "https://raw.githubusercontent.com/SteezyMode/bruiser-subhub/$PIN/tools/audit_subhub_sourcing.py" -o "$TMP"
python3 -B "$TMP"
REMOTE
```

Code entrypoints: `tools/ja_first_catalog_manifest.py` (Jellyfin IDs/genre/media manifest), `tools/ja_first_search_pilot.py` (v4 source worker, history/identity), `tools/subhub_season_sources.py` (TV owner selected), `tools/ja_first_stage_saved_batch.py` (current OS-only stage gate), `tools/ja_first_publish_queue.py` (ALASS/ffsubsync), `tools/ja_first_autofill.py` (systemd orchestrator), `tools/ja_first_source_tracker.py` (journal progress), `tools/subhub_dashboard_server.py` and `tools/subhub_dashboard.html` (dashboard).

External sources examined: Sublarr v1.18.0 `backend/routes/providers/search.py`, `backend/providers/opensubtitles.py`, `backend/providers/subdl.py`, `backend/providers/opensubtitles_fetch.py`, `backend/providers/search_coordinator/cache.py`, and `backend/services/provider_budget_modes.py`. Compare newer versions before upgrades. **Do not assume github issue checkboxes imply deployments.**

---
**Owner's definition of success:** When new media is added to Jellyfin, the system obtains a verified, actually playable Japanese subtitle with minimal intervention. Manual selection and review remain available, across movies/genres/series. Near-term success must be measured on actual Jellyfin files, not dashboards or GitHub commits.
