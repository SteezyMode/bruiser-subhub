# Instructions for work on Bruiser SubHub

**First read** [GOAL.md](GOAL.md), [docs/CURRENT_STATE.md](docs/CURRENT_STATE.md) and [docs/SUBHUB_CORRECTION_FIRST_POLICY_2026-11-10.md](docs/SUBHUB_CORRECTION_FIRST_POLICY_2026-11-10.md). These are the only current cross-project direction documents. Old dated docs and issue titles are evidence, not authority. Earlier versions of this long handoff are recoverable from Git history.

## Non-negotiable decision discipline

- This is household software to get **watchable Japanese subtitles**, not a startup, product or software portfolio. Time spent coding is a cost, not an achievement.
- **Don't defer architecture to the owner.** Their experience is evidence, not technical analysis. Independently investigate existing tools and configuration, then recommend the smallest reliable solution based on results. No yes-manning, no speculative features.
- The custom dashboard currently performs better **for the owner** than the installed Sublarr UI, but is far from satisfactory. Keep it running for now; **neither permanently endorse it nor force a Sublarr migration**. Compare the actual workflows under protected conditions, explicitly including **Bazarr + Sonarr/Radarr** and a correctly configured Sublarr. Do not let prior effort spent on the custom dashboard influence the result. **Bazarr must receive a serious, fairly scoped trial.** Sonarr/Radarr provide its catalog and can import existing media without taking over downloads. Their setup costs are not disqualifying when compared with the sprawling custom SubHub codebase. Use an isolated scratch-library trial, with no download clients/indexers, no existing host media writes, and Bazarr subtitle-upgrade/cleanup automation disabled until proven safe.
- Reuse the already installed Jellyfin, Sublarr, ffsubsync and existing worker/checkpoint functionality. No new databases, second schedulers, bespoke synchronization algorithms, dashboard redesigns or show-specific controls without evidence the current stack cannot do the job.
- **No code-only victories:** report the exact distinction among code committed, host installed, job executed, sidecar published, and playback verified. Never claim an improvement worked on the user's media without evidence.

## Subtitle workflow

1. Confirm actual video/episode/edition and existing Japanese (embedded and sidecar). Keep human-authored and previously approved subtitles.
2. Search broadly for Japanese, preserve candidate bytes and identification evidence, handle numbering variants and release mismatches. A single provider miss or stage rejection isn't absence.
3. Proactively inspect embedded/sidecar **native-language text**. Acquire and cache a properly matched external reference when worthwhile. **Do not block Japanese sourcing/repair on native/English availability.** If a reference is missing, show a reference-specific diagnostic; Japanese remains independently actionable. Avoid needlessly consuming quotas on untouched library items.
4. Reuse proven subtitle tools for sync. ffsubsync can reference video/audio or an already-synced subtitle. Preview before changing; do not infer actual sync from bilingual cue-start coincidences. Check opening/middle/ending dialogue and runtime. A simple constant offset will not fix edited cuts or variable drift.
5. Repair/verify before publication; preserve originals and rollback. Unrecoverable bad published tracks may eventually be withdrawn after independent review, not silently on an automatic metric.
6. PLaMo is last resort, using a verified appropriate dialogue source and the existing guarded/checkpointed worker. No speculative model contests.

## Execution / safety

- Current first job: IASIP S01E04 mistimed cold open; S01E05 comparison. Both have embedded EN; regional cue audit is inconclusive. Next move is **non-destructive repair preview + dialogue check**, not another threshold or full-library scan.
- Backlog after that: five staged S02/S03 Japanese candidate provenance holds; four completed PLaMo output comparisons; make saved reference and repair flows generic.
- For any change, inspect **the deployed host** before touching services. Preserve live jobs, existing folder names and sidecars, private config, source/download history and GPU thermal guards. Don't create new folders inside media libraries without identifying the established location.
- Prioritize one real-media acceptance test and clean rollback over broad refactors. If off-the-shelf tools deliver a better result, retire redundant custom code carefully; do not erase working data.
- Never upload film dialogue, downloaded subtitles, API credentials, private local paths or personal QA to a public GitHub commit.
