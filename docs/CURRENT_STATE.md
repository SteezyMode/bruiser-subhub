# SubHub — current state and next verified work (2026-11-10 JST)

**Read [../GOAL.md](../GOAL.md) first.** Historical records formerly appended here remain in the Git history; dated docs under docs/ are retained as archives, not competing priorities.

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
