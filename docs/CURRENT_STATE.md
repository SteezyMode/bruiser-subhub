# SubHub — current state and next verified work (2026-11-10 JST)

**Read [../GOAL.md](../GOAL.md) first.** Historical records formerly appended here remain in the Git history; dated docs under docs/ are retained as archives, not competing priorities.

## November 10 18:17 JST — owner-supplied live coverage database evidence

**Stop treating dashboard 78 missing / 62 PLaMo eligible as 78 failed searches.** The owner checked the live `~/bruiser-pilot/coverage-queue/coverage.sqlite3` (179 IASIP file records): `media.ja_present` marked only **12** as Japanese-present and **167** as missing. Among those 167: **52** with no active JA/review task, **50** `review_uncertain / pending` (reason `primary_audio_language_unverified`), **42** `validate_english_for_ja_fallback / pending`, **16** `recover_english_for_ja_fallback / pending`, and **7** `align_existing_staged_ja / held` with `no_candidate_passed_trusted_sync_correction`. English indexed for 106 of these raw DB-missing records and not indexed for 61.

At the same time the owner's *live dashboard* showed **101 / 179** with Japanese, **78** remaining, **62** selectable for PLaMo. Checked-in `subhub_translation_batch.py` `_already_covered()` specifically supplements stale `ja_present` with on-disk same-video Japanese sidecar checks. **89** extra dashboard-covered records may therefore be newly detected sidecars not yet reflected in the queue snapshot, but **reconcile actual disk paths before treating this as verified**. The 78/62 split is *two eligibility flags*, not a provider failure count or proof that exactly 16 lack English; importantly `owner_unlabeled` items can be PLaMo-selectable even when their English is not indexed. Current host code may differ from committed version; don't replace it blindly.

Immediate triage order: confirm exact-video sidecars and search-history results for the 78 genuinely disk-uncovered episodes; distinguish not searched, provider miss, candidate retained, metadata review, timing-held. The seven held Japanese stage candidates should get **existing standalone alass** recovery before PLaMo, once integration passes guarded on-host deployment and current source identity checks. Keep 50 unknown-primary-audio episodes in metadata review, not "failed"; never assume lack of Japanese follows. No repeat all-series provider searches or blanket 62-episode PLaMo run until these states are reconciled. **New alass pipeline is committed to GitHub but NOT confirmed deployed on the OptiPlex**.

## November 10 implementation: standalone alass + entire IASIP as acceptance workload

- Owner selected **every episode of It's Always Sunny in Philadelphia** as the *first* real end-to-end SubHub acceptance workload. Current live dashboard is still the operator UI. The target metric is **actual episodes with watchable, correctly synced Japanese in Jellyfin / all episodes in the existing library**, with source/repair/PLaMo/held results separately reported. Source original Japanese first, respect quotas, retain already working tracks, then PLaMo if verified English exists; do not blind-download every episode or overwrite good content. This is a first measuring stick, not proof other series/movies are identical.
- **Code only / NOT DEPLOYED yet:** `tools/ja_first_alass.py` integrates the *existing on-host* standalone alass v2.0.0 binary into the previously deployed staged-Japanese publication path. `tools/ja_first_publish_queue.py` now prefers this engine (including its nonuniform/split/framerate correction), retaining ffsubsync as fallback, no-overwrite/source validation, and reversible original/derived provenance. `tools/install_alass_into_subhub.sh` is the additive guarded installer: it inspects the installed publisher's Git blob before replacing it, blocks active jobs, backs up the old source, and checks imports/synthetic split correction without touching media or starting searches; if the deployed file is different it **must hold** rather than overwrite owner's changes. **Do not call it installed until host output confirms.** New offline tests `test_ja_first_alass.py` passed on GitHub CI; overall suite still has one pre-existing ffsubsync 4.82s-spread test regression, independent of the new alass tests.
- **Private four-PLaMo review collection ready, no actual QA yet:** `tools/collect_iasip_plamo_review.py` discovers published `.ja.PLaMo8B.srt` files in the user's two known IASIP roots, reuses pinned English manifests where available, and emits full English/Japanese cue text/timestamps only to the owner's local private JSON. Do not assume the precise four episode identifiers without host enumeration or count generated output as reviewed. Review jokes/slang/profanity/meaning and cold/middle/end timing from actual paired text.
- The earlier standalone alass result for S01E04 was favorably checked by the owner in VLC and is the existing successful pilot; do not regenerate it without reason. New ffsubsync preview sidecars (Reference/Piecewise/Audio) remain unverified and must not supersede it.
- No new dashboard, no new service, no new provider account, no automatic Bazarr migration, and no broad rollout of new timing outputs before examining a small playback-validated sample. Preserve current working custom UI and installed code.

## November 10 later evidence: alass success, stop re-testing S01E04

**This section updates the earlier status paragraphs below.** The owner reports that standalone **alass corrected IASIP S01E04** and that the correction was satisfactory in VLC; ffsubsync was not the successful repair method for this case. The owner has not yet supplied evidence that the successful alass output is installed and selected as the working Jellyfin subtitle. Do not call the episode fixed in Jellyfin until that is checked. Locate and preserve the exact alass output before any new searches or alignment attempts.

The Nov 10 follow-up ffsubsync trial generated three **separate preview sidecars** for S01E04 (BruiserSyncReference, BruiserSyncPiecewise, BruiserSyncAudio). Those were produced after the successful alass experiment and shifted cues by less than one second; they are *not* verified as better. Original JA remained untouched. Do not rerun the same experiment, promote these previews as good, or delete a preview without inspecting the real files.

**Owner's immediate architectural priority:** keep the existing usable SubHub dashboard/queue while reusing existing tools instead of rebuilding them. Integrate **standalone alass as a reversible candidate-generation step** for mistimed external Japanese subtitles, preserve its full per-cue/split/frame-rate corrections, and reserve ffsubsync as an alternative. Sublarr's documented built-in multi-engine orchestrator may apply only a measured offset and reject timeline stretching: do not equate its `alass` option with standalone alass's full correction behavior without a verified end-to-end trial. Source missing Japanese with already configured providers, fall back to existing PLaMo with verified English dialogue, and publish only after checking identity/timing and preserving originals. Bazarr/Sonarr trial remains isolated; four Sunny episode provider searches returned zero Japanese results, and OpenSubtitles.com entered an AuthenticationError cooldown. No further provider-account setup or duplicate architecture experiments without a specific new evidence-based reason.

**Next operational acceptance:** locate the already VLC-verified alass correction for S01E04, make it a selectable, non-overwriting track in Jellyfin, verify opening/middle/end there. Then insert one reusable alass preview path into the existing general SubHub work queue; do not build a second UI, scheduler, search database or model runner.

## Decision

**No architecture winner has been proven yet. Bazarr is an active, high-priority candidate alongside properly configured Sublarr and the existing dashboard.** The owner's current custom dashboard is more usable *in practice* than their installed Sublarr interface, but both fall short. Keep running functionality undisturbed. Independently test whether configuring/upgrading Sublarr, using its sync/editor/provider components, using Bazarr with its Sonarr/Radarr dependencies, or retaining a slim custom dashboard achieves the actual subtitle goal with least upkeep. Do not assert either custom or off-the-shelf wins without protected host results. No new dashboard redesign while source/repair is the blocker.

**Native-language reference policy:** inspect existing embedded/sidecar text first; proactively seek/capture an exact-release reference *for items being processed* where useful. Japanese sourcing and correction remain independent; missing English is **not** a missing-Japanese failure. Only EN->JA last-resort translation needs verified English source dialogue. Reuse cached references and don't squander provider quotas on a full-library prefetch.

## Verified evidence from owner-provided host output

- IASIP S01E04 *Charlie Has Cancer*: published JA sidecar **378 cues**, embedded EN **393 cues**, video duration **1360.277 s**. Four-region read-only audit: cold open suggested +3.5 s with 0.500 coincidence fraction; early +1.2 s/0.460; middle +1.6 s/0.434; ending -8.0 s/0.314. **All inconclusive.** Owner reports cold-open dialogue visibly mistimed; this is stronger evidence than arbitrary timestamp matching.
- IASIP S01E05 *Gun Fever*: JA **491**, embedded EN **398**, duration **1293.168 s**. Four-region audit: +1.7/+0.5/+0.4/+0.3 s estimates; all under usable-confidence threshold. **Control only; not verified perfect**.
- The audit was run read-only; **no sidecars changed and no provider quotas used**. Both episodes **already have embedded English**, so reference acquisition is not the blocker in this pilot.
- Repo has active discovery, staging, publish, dashboard and translation code; **GitHub code != installed host code**. The Nov 9 newer dashboard completion workbench is reported as locally newer than checked-in source; do **not** replace it with the older GitHub HTML.
- Last documented host Sublarr instance was **1.18.0** with real media read-only mounts, compared with candidate 1.20.1 on Nov 9. This host version is **not a fresh Nov 10 verification**.
- Prior confirmed successes include real sourced-Japanese playback and sidecar publication; conversely, the custom dashboard is incomplete, some staged subtitles were held and published timing can be bad. No blanket claim of library readiness.

## Next milestone: one real repair, not another diagnostic framework

**Target:** IASIP S01E04, with E05 as negative/control case.

1. Confirm live host versions, mounted media paths, existing original subtitle hashes, and which *installed* tools expose read-only Sync Compare / ffsubsync reference and audio modes. No service or media changes.
2. Produce a **temporary, reversible correction preview** from existing tools. Compare original JA and preview to the existing embedded EN reference and real spoken lines in cold open, middle and ending; check release/scene-edit differences. Do not treat ffsubsync's single offset as a cure for variable drift.
3. If improved, stage a versioned copy; verify in Jellyfin before an owner-authorized reversible promotion. Original sidecar must remain recoverable. If not, record the actual failure and try an available alternative engine/candidate rather than generating new alignment statistics.
4. Reuse the proven route for other published/pending Japanese sidecars only after this case works.

**Done only when:** the right Japanese captions follow dialogue in E04 from opening through ending in Jellyfin, correct text is preserved, and rollback is demonstrated. E05 is not regressed.

## Protected off-the-shelf comparison (in parallel only when it does not distract)

- Check installed Sublarr library, standalone roots, wanted/language profile, actual providers, search quotas, ASS vs SRT scoring, sync engines, editor and version. No account secrets in logs or GitHub. Its own docs show standalone Wanted, Sync Compare and multi-engine sync, but **availability on installed 1.18.0 is not assumed**.
- Test a newer pinned Sublarr against a *copy* of config and a scratch writable media directory, with duplicate scheduler disabled; keep production /config and media mounts intact. Compare the same real movie and episodes with the custom flow on identity, Japanese candidate yield, correction, safety, UI control and result in Jellyfin.
- **Bazarr is a serious alternative, not ruled out by Sonarr/Radarr.** The latter can import existing organized TV/movie libraries without configuring downloads. Test Bazarr + Sonarr first on a *scratch copy* of selected TV media, then Radarr for a movie if the TV workflow succeeds. Disable indexers/download clients, automatic subtitle upgrades, cleanup and mutating tasks; preserve the real library read-only during trials. Measure JA provider yield (OpenSubtitles/SubDL), manual search, timing correction, existing-subtitle safety, state reliability and work needed. The setup cost of two additional maintained applications must be weighed against the much larger custom stack.
- Keep only the best actual combination; retire duplicate code/jobs after proven replacement and rollback.

## Backlog, strictly in order

1. Recover the **five S02/S03 staged IASIP Japanese candidates** with missing provider provenance; preserve evidence and originals.
2. Review **four completed PLaMo IASIP outputs** against sourced Japanese for timing, tone and readability. Don't run more model tournaments.
3. Generalize reference acquisition, repair and reusable source-provider paths **only where proven needed**, then improve dashboard controls that block ordinary usage. No aesthetic rebuild.
4. Extend validated repair/audit to more real library items; report verified good, corrected and genuinely unresolved, never just searches/processed count.

**Project bookkeeping:** For each real item record original identity/hash, tool/config version, candidate source, attempted corrections, published path, playback result, and rollback. If host execution wasn't seen, mark it unverified.

Relevant issues: [#87](https://github.com/SteezyMode/bruiser-subhub/issues/87) off-the-shelf evaluation, [#64](https://github.com/SteezyMode/bruiser-subhub/issues/64) staged salvage, [#86](https://github.com/SteezyMode/bruiser-subhub/issues/86) dashboard; they are task history, not parallel architecture mandates.

Upstream references: [Sublarr Wanted](https://sublarr.de/docs/user-guide/wanted/), [Sync Compare](https://sublarr.de/docs/user-guide/sync-compare/), [Multi-Engine Sync](https://sublarr.de/docs/user-guide/sync-engines/), [ffsubsync reference types](https://ffsubsync.readthedocs.io/en/latest/reference_types.html), [Bazarr library integration](https://wiki.bazarr.media/Additional-Configuration/Settings/Library/).
