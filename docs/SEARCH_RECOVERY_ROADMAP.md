# Search recovery & operating roadmap — 2026-11-11 JST

> **START HERE FOR ANY SEARCH/PUBLISH WORK. Priority P0.**
> Maintained handoff for future ChatGPT sessions, owners, and AI coding agents.
> The user has repeatedly lost progress when chats filled up. **Do not restart investigation from scratch, invent a show-specific fix, or claim unit tests prove on-host search yield.**
> Read [GOAL](../GOAL.md), [AGENTS](../AGENTS.md), [CURRENT_STATE](CURRENT_STATE.md), [issue #89](https://github.com/SteezyMode/bruiser-subhub/issues/89), and [issue #90](https://github.com/SteezyMode/bruiser-subhub/issues/90).
>
> **Owner's current explicit order:** (1) fix reliable Japanese subtitle search and publication end-to-end; (2) all jobs need real dashboard progress, and manual batches must be possible; (3) Jellyfin-style movie poster grid with genre browsing/multi-selection; (4) eventually incremental source-on-add. No enterprise/startup framing. Do not build attractive controls that fail to deliver Japanese subtitles.

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
