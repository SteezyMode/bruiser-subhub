# SubHub: architecture decision and next-chat handoff — 2026-11-07

**Status: OWNER-APPROVED. Read this before proposing dashboard work or another subtitle worker.**

This is the **current direction for architecture, workflow and next priorities**. It supersedes older dashboard roadmaps, batch-specific UI plans and dated statements about what to work on next. For the *subtitle policy itself*, also read [the canonical coverage policy](BRUISER_SUBTITLE_POLICY_CANONICAL_2026-11-06.md) and [GOAL.md](../GOAL.md). Older notes remain historical evidence, not marching orders.

## The decision

**Freeze feature development of the current web dashboard. Keep it as a useful, disposable developer/owner diagnostic view while we improve the actual subtitle pipeline.** It is not yet the permanent product UI. The owner found the recent monitoring improvements useful and reasonably accurate; do not break those gains.

Why: the dashboard was incrementally shaped around **a single batch on a single day**. When that batch expired, headline progress bars were stale. Subsequent additions tracked one American Dad run and were about to create show-specific control buttons. That is the wrong abstraction. A general-use SubHub should let the owner manage *media and work*, not hardcoded scripts or yesterday's jobs. The user should not need ChatGPT or SSH to pick a title, but **that UI can wait until the underlying jobs are reliable**.

### Explicit non-goals for now

- No American Dad-specific, movie-specific, PLaMo-specific, or one-off batch buttons as permanent UI concepts.
- No new dashboard pages, front-end redesign, general library browser, drag-and-drop queue, custom scheduler, duplicated job database, or extra background services **now**.
- Do not replace working source-only services, checkpoints, sidecars, or the existing functional monitoring solely to make a prettier dashboard.
- Do not restart model tournaments, prompt twiddling, or episode-specific editorial loops unless real evidence justifies a bounded change.
- Do not confuse a GitHub commit, an offline test, an opened PR, or an installer with successful host deployment.

The branch `feat/subhub-basic-plamo-controls-20261107` contains an **abandoned bespoke American Dad control experiment**. Do not merge or deploy it. It predates this explicit owner decision.

## Longer-term general dashboard contract (DESIGN ONLY; do not build yet)

When the pipeline is stable enough to support it, design around four durable concepts:

| Screen | Long-lived responsibility |
| --- | --- |
| Overview | Actual running work, progress, recently completed work, errors, and stalls |
| Library | Real Jellyfin items and actual source/JA coverage; select movie, show, season, episode |
| Queue | Generic work items, ordering, retry/skip, start/pause/resume/stop; no title-specific affordances |
| Settings | Providers, safe download budgets, models, auto processing, resource/thermal policies |

A future **minimal job contract**, reusing existing workers and durable state, should be able to report: stable media identity, requested operation, phase, actual counts, checkpoint, last event, blocked reason, and valid owner actions. *Do not create another source of truth simply to support a UI.* Prefer the existing coverage queue, real checkpoints, and service/journal events; reconcile identities instead of copying state.

## Immediate priority: pipeline efficiency, reliability, real coverage

1. **Audit the actual execution path**: source Japanese -> stage/download -> align/validate/publish; English-source recovery where needed -> PLaMo EN-to-JA fallback. Draw one honest dataflow from the currently installed services/scripts to files and state. Find duplicate loops, stale/manual-batch assumptions, repeated requests, multiple competing locks, preventable reprocessing, and bottlenecks. Simplify rather than adding another orchestrator.
2. **Make translation finish useful work unattended.** American Dad PLaMo 8B is acceptable for household viewing (some Japanese is wordy), but the earlier batch completed **0/9 published, 9 held** in an owner-provided Nov 7 log because individual cues repeatedly returned non-Japanese output. Successful cue checkpoints survived. Bounded recovery and clear held-line reporting have been developed in [PR #71](https://github.com/SteezyMode/bruiser-subhub/pull/71); actual *post-recovery* host throughput, accepted quality and publication need verification. Do not assume a PR fixed production. Do not throw away completed cues. Keep existing thermal safeguards and owner LACT GPU powercap.
3. **Measure throughput and decisions, not just activity**: new *watchable* JA tracks per day, total library coverage, queued/blocked counts by reason, source success, actual provider downloads used, per-cue model failure rate, cue readability, media time per completed job, GPU/CPU time, temperature pauses, and unattended recovery. Distinguish observed counts from estimates and old manual batches.
4. **Prioritize already available work**. Reuse correctly timed existing Japanese first; reuse previously staged source files. The November 6 bilingual matrix reported 12,386 files: 522 both EN+JA, 2,563 EN-only, 41 JA-only, 8,336 neither, 924 uncertain; these categories do not imply every EN track is usable plain-text subtitle input. Existing verified English text provides a substantial quota-free PLaMo candidate pool. Apply the canonical source-first/English-recovery policy without gating ALL translation on new JA-provider downloads. Preserve good editorial captions, source/media files, and create-only publication.
5. **Get provider-quota reality from evidence**, without pretending that search budgets are download allowances. A Nov 6 owner-provided batch journal reported **43 staged Japanese subtitle files, then provider quota exhausted and 11 held** for that run. This does not prove the account's full daily allowance or total per quota period. Earlier evidence included 99 staged in a different batch snapshot; do not sum without reconciling time windows. The current API-key-only account cannot use the username/password-dependent /infos/user probe as previously written. Do not deploy code that fails closed and accidentally disables normal sourcing because of this probe. Favor measured server responses and actual request history; keep quota research out of the dashboard critical path.
6. **Validate improvement on fresh work.** Use an actual cross-section of movies/episodes, compare published watchable Japanese and throughput before/after, and stop unproductive tuning. PLaMo 8B remains the acceptable current working EN->JA choice; do not switch models casually. Wordiness is real but secondary to completing more safely usable tracks.

## Current status: what is known and not known

- Working web monitoring improved substantially after the owner ran updates from [dashboard PR #70](https://github.com/SteezyMode/bruiser-subhub/pull/70). The owner said it was a **big improvement**; this is user-reported, not an independently inspected fresh host deployment hash. It monitors current journal progress and saved PLaMo checkpoints. Existing owner source start/stop controls are limited and *not* a general-purpose library queue.
- The earlier dashboard displayed stale manual progress as if it were current work; the new separation is necessary and should remain. Treat the running scheduled source worker and the PLaMo translation worker as independent.
- PLaMo American Dad batch produced watchable subtitles in earlier viewing; the later 0/9 held log preceded proposed cue-continuation fixes. Do **not** claim the batch is running or healed now without fresh host output.
- [PR #69](https://github.com/SteezyMode/bruiser-subhub/pull/69) is a draft overlap with PR #70 and experimental quota detection; do not blindly merge it. [PR #70](https://github.com/SteezyMode/bruiser-subhub/pull/70) concerns the dashboard; [PR #71](https://github.com/SteezyMode/bruiser-subhub/pull/71) concerns bounded PLaMo cue recovery. At the time of this handoff, these changes are on PR branches, **not in main**; installed host code can differ from both.
- Existing full-library coverage/matrix and source queue are already in the repo under [FULL_EN_JA_SUBTITLE_MATRIX_2026-11-06.md](FULL_EN_JA_SUBTITLE_MATRIX_2026-11-06.md), [BRUISER_COVERAGE_QUEUE_2026-11-06.md](BRUISER_COVERAGE_QUEUE_2026-11-06.md), [BRUISER_BATCH_OPERATOR_2026-11-06.md](BRUISER_BATCH_OPERATOR_2026-11-06.md). Read these **before inventing a new inventory/queue architecture**.

## Start of the next chat: efficient recovery protocol

1. Read **this document**, [GOAL.md](../GOAL.md), the [canonical policy](BRUISER_SUBTITLE_POLICY_CANONICAL_2026-11-06.md) and the latest source/translation batch docs. Treat older contradictory "current" claims as dated snapshots.
2. Check GitHub **main vs open PRs vs what is actually installed**. Never say PR-only code is deployed. Do not launch workers, change the GPU cap, or write media simply because this handoff exists.
3. Start with a read-only real-host diagnosis if available: source worker, PLaMo jobs, coverage-queue counts, last logs/exit reasons, actual output sidecars, and current hardware safety status. Ask only for the **single most useful command output** when remote access isn't available; avoid endless shell troubleshooting.
4. Suggest the **smallest generalizable pipeline fix** with offline tests, unchanged checkpoints, guarded installation and measured pre/post results. Favor removing complexity. No dashboard redesign until repeated workflows establish a durable job contract.
5. For the user's new-chat request “continue SubHub,” **default to pipeline audit/throughput/reliability**, not dashboard polish or a new American Dad batch.

## Hard safety / product invariants

Personal household library; source media is never modified. Existing good EN/JA and user-edited JP sidecars are never overwritten; write new properly labeled, verified subtitle tracks only. Subtitle playback/dual-subtitle plugin is already solved. No raw private media dialogue, API keys or credentials in this public GitHub repo. Don't silently mutate system services, passwords or LACT power limits. Keep independent source-only and GPU-translation workers isolated, bounded, checkpointed and observable.

**Owner decision recorded: 2026-11-07.** This is a source-of-truth *architecture and priority decision*, not proof of a deployed change or an instruction to perform automated work.
