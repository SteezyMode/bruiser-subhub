# SubHub coverage: November 6, 2026 sourcing postmortem and next strategy

> **Current sourcing handoff — read before changing acquisition or scheduling.** This document records owner-supplied **live OptiPlex** log results from the November 6 morning runs, which supersede interim November 5 sourcing totals. The goal is **maximum *usable Japanese subtitle coverage* of the entire existing Jellyfin library**. Neither TV-first nor movie-first nor "avoid American Dad" is a standing product goal. New GitHub commits are **not automatically deployed** on OptiPlex. Do not alter PLaMo translation jobs while repairing source acquisition.

## Objective and boundaries

- Maximize the number of distinct playable library titles with complete, correctly matched and correctly timed, usable Japanese subtitles; preserve existing original, editorial and already-published Japanese tracks. The user and Japanese-speaking household member decide real viewing quality; a mechanical pass is not a native-viewer quality grade.
- Reuse trustworthy existing Japanese subtitles first; pursue accurate English dialogue only when it unlocks future translation coverage. Local PLaMo 8B is a **separate** running / recently running American Dad translation workflow, not part of the source-only scheduler. Its progress is not a sourcing success metric.
- Scope is **all** Jellyfin movies and shows, not a hard-coded series or season. Avoid wasting requests on any title with a usable Japanese track or an active, equivalent translation already producing an acceptable Japanese track. American Dad is **not globally excluded**.
- Do not add provider accounts, enable automatic AI fallback, degrade matching safeguards, change LACT settings, modify videos, or silently overwrite subtitles merely to make counters go up.

## Actual November 6 job results (JST, owner-supplied logs)

### Japanese source-only service

**Job:** `bruiser-ja-source-autofill.service`; completed **07:01:59 JST**, systemd `Result=success` / exit 0.

| Stage / outcome | Count | Correct interpretation |
| --- | ---: | --- |
| Provider discovery budget used | 600 / 600 | All allocated searches executed |
| Movies / episodes searched | 450 / 150 | Existing hard-coded **75% movie** discovery quota; NOT a measured coverage optimum |
| Discovery outcome: plausible | 144 | Metadata/evidence plausibly matches title/release; **not** proof of downloadable, usable Japanese |
| Discovery outcome: review | 80 | Insufficient identity confidence for auto-download |
| Discovery outcome: none | 376 | No acceptable candidate from that search |
| Selected from **saved** discovery for staging | 160 (budget 200) | Includes accumulated search history, not a one-run 600-to-160 conversion |
| Staging `staged_not_published` | 43 | Files successfully staged during this run; not yet playable publications |
| Staging `held` | 11 | Download/verification attempts held; exact reasons need classification |
| Staging `provider_limited` | 1 | Provider quota/cooldown prevented further staging; **stop is intentional and correct** |
| Publication queued | 57 staged candidates / 52 distinct titles | May combine prior and new saved staged entries |
| Publication `ready_ffsubsync` | 28 | Passed synchronization gate, then published |
| Publication `held` | 24 | All 24 need reason-classification and targeted recovery |
| **New Japanese sidecars published** | **28** | Real create-only `.ja.srt` files; **linguistic quality remains ungraded** |

Concrete evidence: *Terrifier 3* (2024) and *The Amityville Horror* (2005) received published Japanese tracks; *The Autopsy of Jane Doe* (2016) was held for malformed cue parsing / lack of a trusted synchronization correction. That last case is **not evidence that the downloaded Japanese is fluent or incorrect**: its timing/input validation failed.

At end-of-run, SubHub status reported: catalog **12,386 items**, **9,981 ready for JA search** in its manifest; **cumulative** source search history `none=448, plausible=198, review=127`; staging `published=74, staged=29`. **Do not equate historical 74 staged-publications with 74 new tracks on November 6**, nor assume staged 29 will publish successfully. The status includes `jobs.sqlite3` legacy-permissions warning; not proven causal for acquisition limits.

### Confirmed provider cap and scheduling mismatch (follow-up log)

The owner's follow-up log exposed the precise terminating message:

```text
[54/160] STAGING: The Black Phone (2022)
HELD: The Black Phone (2022) RuntimeError container_staging_blocked:OpenSubtitles download quota exhausted (resets: 2026-11-05T23:59:59.00...
PROVIDER_LIMIT_REACHED: stop further downloads for this cycle; staged files retained
```

**Confirmed cause:** the OpenSubtitles download allowance was exhausted; this was neither a SubHub software search-budget failure nor a hardware shutdown. The exact account quota ceiling was **not** present in the truncated message; 43 staged files does **not** establish a 43-download daily allowance. Other previously made downloads and held cases can contribute.

**Important scheduling finding:** OpenSubtitles' API describes its reset as `reset_time_utc`. For the shown 23:59:59 UTC reset, that is **08:59:59 JST on November 6, 2026**. The Japanese source timer fired around **05:23 JST** and finished 07:01 JST, **before the allowance refreshed**. This means the 05:15 + 0–20 min nightly schedule can be strategically misaligned with the provider's renewal window. **Repository fix prepared (NOT DEPLOYED):** `tools/ja_first_autofill.py` now schedules Japanese sourcing for **09:15 JST + 0–20 minutes jitter**, after the OpenSubtitles reset. It allows guarded migration of only the known old 05:15 timer; `tools/retime_ja_source_after_quota_reset.sh` is the one-command OptiPlex migration. The host remains on the old schedule until the owner executes the guarded installer. This does **not** increase the provider's actual allowed downloads. First determine if other configured subtitle providers have different quota resets; seek reliable quota remaining before spending. Avoid representing the published 28 as the maximum obtainable in a refreshed allowance.

OpenSubtitles API reference: https://ai.opensubtitles.com/api-docs (the `/download` response includes `requests`, `remaining`, `reset_time` and `reset_time_utc`). This timestamp is a *reset time*, not proof of a specific daily numerical cap. If it is exposed through a Sublarr response or log, record exact quota remaining and reset time **without** exposing secrets.

### English source fallback service

**Job:** `bruiser-english-source.service`; completed **07:10:13 JST**, systemd `Result=success` / exit 0. The unit's actual `ExecStart` was verified with `--budget 300 --provider-delay 1`; early English timer disabled; run occurred after the Japanese service.

| Outcome | Count | Interpretation |
| --- | ---: | --- |
| Search attempts | **300 / 300** | Configured budget completed |
| `no_hash_match` | 228 | No source meeting strict `IsHashMatch=true` plus SRT/identity gate |
| `jellyfin_only` | 72 | Provider POST returned but **no validated, media-adjacent external English SRT** was seen; may have landed in Jellyfin metadata, or no usable external output |
| `downloaded` as verified external English SRT | **0** | **0 newly usable English sources proven** |

English inventory at end: **12,399** records; `japanese_present=572`, `jellyfin_only=72`, `missing=8937`, `no_hash_match=261`, `ready=2557`. This differs slightly from Japanese catalog counts; independent tools / catalog snapshots must not be mixed as one denominator.

**Root limitations visible in code:** `tools/library_english_sources.py` only accepts exact video-hash-matching SRT matches; after Jellyfin's download API it looks for an external language-tagged `.en.srt` sidecar and records `jellyfin_only` if absent. Therefore **72 is not 72 delivered SRTs**, and **0 is not proof every provider lacked English dialogue**. The earlier American Dad S08 special search priority still exists in the deployed worker; it is a historical bias, not a user requirement.

## Failure analysis: confirmed versus unproven

**Confirmed from logs/code**

1. **Provider download allowance** cut short JA staging after 43 newly staged candidates and 11 held staging attempts; 160 entries were selected. Increasing stage/download ceilings cannot bypass provider allowance.
2. **Publication QA rejected/held 24 of 52 titles examined**. Example: malformed SRT cue and untrusted timing. Current pipeline correctly refuses unsafe publication. The 24 may have multiple distinct causes; do not simply loosen all sync gates.
3. **600/300 search limits are software budgets, not delivery counts**. 450 movie / 150 episode allocation is hard-coded in `ja_first_search_pilot.py`; staging similarly uses a 75/25 movie/episode split. This is not proven optimal.
4. **English acquisition's external-file yield was zero** despite 72 Jellyfin-only outcomes. Need to determine storage location / actual files and metadata semantics **before** repeating 300 searches.
5. **No linguistic QA yet** on the new 28 tracks. `SOURCED_GROSS_QA: pass` and `FFSUBSYNC` certify limited structural/timing properties only.

**Hypotheses that need evidence**

- Quota is constrained specifically by current account download allowance versus a cooldown / provider transient failure; need read-only *limit reason*, not an attempt to circumvent.
- Some of the 72 Jellyfin-only subtitles could be recovered without another provider download by inspecting Jellyfin metadata storage, text track accessibility, and allowed export capabilities.
- Some held Japanese files may be salvageable via safely constrained parsing or release-specific offset correction; some may simply be incompatible versions.
- Alternative existing providers / better subtitle identifiers might improve coverage, but this requires provider-specific evidence; do not assume OpenSubtitles, Jimaku or SubDL coverage in advance.
- A 75/25, 25/75, or 50/50 category quota is optimal: **none of these claims is supported** until yield is broken down by media type and provider.

## Complete EN/JA matrix finished on owner host (November 6)

The owner completed [the full read-only matrix](FULL_EN_JA_SUBTITLE_MATRIX_2026-11-06.md), **not** merely the earlier English-without-Japanese subset. All **12,386** Jellyfin items were classified: **522 both**, **2,563 English only**, **41 Japanese only**, **8,336 neither**, **924 uncertain**. Independent detection totals are **3,112 English** and **572 Japanese**, including ambiguous-category cases. Previously verified embedded English: 2,270; stale Jellyfin English metadata mismatches: 265; unlabeled subtitle sidecars: 675. No provider calls or subtitle writes occurred in this inventory.

**Actionable backlog already exists privately:** `subtitle-matrix-20261106T015513Z.english_only.csv` contains the full **2,563 English-only** titles/episodes. Do not order another blanket catalog or ffprobe audit to regenerate these numbers. Begin with source-text/codec verification *only when an individual title is selected* for Japanese translation; use existing per-title source validation and never overwrite JA. Continue Japanese-first provider acquisition for the **8,336 neither** records subject to actual quota; avoid treating unresolved/unlabeled as definitely without subtitles.

## Implementation strategy — maximize incremental playable coverage

### P0 — Do not spend additional quota blindly

- **Keep existing daily jobs / provider protection until evidence is reviewed.** The November 6 source runs completed successfully; no evidence that restarting identical 600+300 jobs immediately improves coverage.
- Count **distinct newly playable titles** from filesystem and Jellyfin visibility, not `plausible`, `staged`, `ready` or API POST alone. Record catalog denominator, date, sample media type and provenance.
- Recover already-held and already-downloaded evidence before spending another scarce provider download. No hash/mismatch bypass to force publication.

### P1 — Inspect real Japanese output and classify holds

- Export a **private** review bundle of the November 6 newly published Japanese SRTs plus *existing exact-video English sidecars if present*. The public helper `tools/collect_sourced_ja_qa.py` was added to the repo on November 6, but **has not been deployed or verified on the live host**. It only reads files and journals; it does not infer translation quality.
- Evaluate representative titles across film/TV and source types: complete dialogue, cue alignment, punctuation, readability, missing lines, accidental machine artifacts, tone/meaning, and actual Jellyfin playback. Compare with accurate English or audio where available; label "not assessable" rather than assigning unsupported 8/10 scores.
- Classify every one of the **24 publication holds** and **11 staging holds** into malformed source, wrong release / identity, absent reliable sync reference, large timing drift, permissions / I/O, quota / transient provider, or other recorded evidence. Keep originals. Measure how many salvage passes produce truly publishable tracks.

### P2 — Investigate English `jellyfin_only=72` and avoid another zero-yield run

- Examine a **bounded sample** of cases with read-only Jellyfin media/stream metadata and filesystem checks. Determine where the downloaded subtitle is actually stored, whether it is text, language-tagged, accessible, readable, and safe to materialize externally.
- If eligible, implement **create-only, validated external English export** using the already downloaded exact source. Retain strict video identity, proper English detection, cue validity and timing verification. Never overwrite earlier tracks.
- Next, consider a **strictly guarded release/title fallback** where hash matches are absent. An unverified filename match is NOT an automatic download/publish acceptance. Check episode/year/release conflicts, cue plausibility and synchronization; hold ambiguity. Test against wrong-episode/release cases before applying to thousands.
- Record `searched`, `provider_post_accepted`, `external_written`, `external_verified`, and `fallback_eligible` separately. Stop treating "Jellyfin-only" as a successful external subtitle acquisition.

### P3 — Use measured yield to choose what to search next

- Keep **both movies and episodes eligible**, with no global series exclusion. A title with verified existing Japanese skips all work; an already accepted in-progress AI track should not trigger duplicate acquisition without an explicit reason.
- Improve discovery ranking from **observed per-type/per-provider conversion**: plausible search -> downloadable candidate -> structurally valid -> correctly synced -> played/accepted. Prioritize old saved plausible searches with high confidence and not-yet-staged candidates.
- Remove the special **American Dad S08 English priority**, which was tied to an obsolete isolated-season experiment; treat that show under the same global coverage/no-duplicate rules as other shows.
- Avoid replacing the 75%-movies default with a reflexive 75%-TV rule. For initial policy, allocate fairly across eligible movies/episodes when yield evidence is missing; rebalance by *measured new playable publications per provider search and per allowed download*. Report any starvation by content type.
- Treat provider "no-result" history and 30-day cooldown as useful anti-repeat safeguards, with a *measured* recheck strategy only on metadata/source/provider changes. Use no additional credentials without explicit approval.

### P4 — Monitor outcomes and roll out carefully

- Maintain a small **single-page post-run report**: attempts, credible matches, staging downloads, provider-limit reason, published distinct titles, held per reason, externally verified English, Japanese viewing acceptance, duplicate/skip counts, and remaining coverage. Record by movie/episode/provider, with traceable private IDs, not private subtitle text in GitHub.
- Require offline tests for priority consistency, source provenance, media path safety, correct release / episode, 429 stop, publish create-only, resumption, and no double counting. Run on a small live sample before enabling broad automatic rollout.
- Keep live host deployment separate from GitHub commits. Deploy only verified changes, preserving checkpoints/timers and the independent PLaMo batch. If a change reduces actual coverage or produces misaligned subtitles, revert that component without discarding saved evidence.

## Implementation added November 6: all-English / missing-Japanese census

A **new read-only whole-library census** is committed as [`tools/audit_english_without_japanese.py`](../tools/audit_english_without_japanese.py), together with [offline tests](../test_audit_english_without_japanese.py), a [guarded host runner](../tools/run_english_no_japanese_audit.sh) and a [usage/interpretation guide](BRUISER_LIBRARY_COVERAGE_AUDIT_2026-11-06.md). It enumerates every Jellyfin Movie/Episode and produces private CSV/JSON candidates for Bruiser: parsed English SRT, unverified embedded English text, other text subtitle formats; excludes known Japanese sidecars/streams, flags Japanese-audio media and previous `jellyfin_only` cases, and exports unresolved metadata separately. It does **not** automatically download, sync or translate anything. **Not executed on the real host yet; no candidate totals established.** A host census is the next authoritative step before designing batch translation scope or English fallback export.

## New evidence: full-library English/no-Japanese census

The owner ran the read-only audit on the OptiPlex November 6: **12,386** movies/episodes, **2,552** English text candidate/no-JA, of which **2,550 are Jellyfin metadata-only text tracks** and **2 validated external SRTs**. Japanese was detected for 573 items, 8,640 had no English text detected, 620 had unlabeled SRTs, 72 prior `jellyfin_only` cases remained unresolved, and 120 potential English-source candidates have Japanese audio.

**Immediate priority:** do not silently infer that 2,550 metadata streams are extractable English dialogue. The guarded second-pass verifier checks real video subtitle stream metadata across all 2,550 and extracts a balanced sample to validate actual SRT text. See [Bruiser coverage audit and verified census](BRUISER_LIBRARY_COVERAGE_AUDIT_2026-11-06.md). This is the most useful next step before designing an entire-library local translation queue.

## Next development session: actionable order

1. **QA without altering running work:** privately export a sample of the 28 Japanese publications and inspect their text/playback; identify any actual quality faults.
2. **Classify the 24 held publications and 11 staging holds:** start with most frequent fatal reason; fix the cause only if the candidate is recoverable.
3. **Sample the 72 English Jellyfin-only cases:** determine whether reuse/export is feasible from existing downloads, without new provider calls.
4. **Fix obsolete S08 preference; design evidence-driven fair library coverage**, not another arbitrary category split. Avoid altering production jobs merely to change a header.
5. Trial a small source-run at the next legitimate provider allowance, compare **new usable Japanese titles per request/download** to Nov 6 baseline, then roll out with repeat-safe state.

## Evidence and repository pointers

- Owner's live transcript: November 6 systemd sourcing journal and short stage summary (private conversation; **not committed**). Source-only finished 07:01, English fallback 07:10, both exit 0; completion says nothing about desired coverage yield.
- Runtime: `bruiser-ja-source-autofill.service`, `bruiser-english-source.service`, existing private `~/bruiser-pilot/ja-first-inventory/` and `~/bruiser-pilot/english-source-inventory/`.
- `tools/ja_first_search_pilot.py` — currently fixed 75%-movies discovery and search history.
- `tools/ja_first_stage_saved_batch.py` — saved candidate staging, actual provider-limit stop, currently 75%-movies stage quota.
- `tools/ja_first_publish_queue.py` — creates validated new sidecars and reports held titles.
- `tools/library_english_sources.py` — exact-hash English acquisition, Jellyfin-only case, prior S08 preference; current run was deployed `--budget 300 --provider-delay 1`.
- `tools/collect_sourced_ja_qa.py` — newly authored *read-only private* QA exporter; deploy and verify separately; no subtitle dialogue belongs in public GitHub.
- `docs/AMERICAN_DAD_ACTIVE_BATCH_HANDOFF_2026-11-05.md` — **separate** translation workflow. Do not infer its status from sourcing logs, or restart it for source-related changes.

**Operating principle:** "service exited 0" and "budget spent" are engineering uptime measures. The product measure is **net growth in watchable, rightly timed Japanese-subtitle coverage across the owner's entire library**.
