# SubHub product vision and execution roadmap — 2026-11-08

**Status: current owner direction.** This updates the GUI direction in `SUBHUB_ARCHITECTURE_AND_PIPELINE_HANDOFF_2026-11-07.md`: the existing dashboard remains a disposable diagnostic stopgap, but a cohesive, functioning operator UI is now an explicit product goal. **Owner correction, Nov 8: the dashboard freeze was premature and is rescinded. The existing UI is actively preventing the owner from understanding and controlling the pipeline. Functional dashboard redevelopment is P0 work now, in parallel with finishing sourcing and translation.** Preserve working workers, checkpoints and media while upgrading the operator experience; do not wait for perfect pipeline stability. This document is the current product-level direction; canonical coverage policy and production safeguards remain authoritative.

## The job SubHub exists to do

For any Jellyfin movie, show, season, or episode: **get usable Japanese subtitles** with minimal operator involvement and show what happened. This is a focused household task tool, not an admin console or collection of batch scripts. The independent SubHub service remains separate from the frozen OptiPlex NOW private-alpha client. Dual-subtitle playback is already solved and out of scope.

The default user journey:

1. Select a movie / series / season / episode from the library, see honest coverage immediately.
2. Click **Get Japanese subtitles** once.
3. Reuse suitable existing JA -> search Japanese providers -> if unavailable or unsuitable, acquire/validate English text -> locally translate with the existing PLaMo pipeline -> validate/repair timing and cue output -> publish verified JA without overwriting good files.
4. A visible job tracks each phase, real progress and which episodes now have JA. If held or interrupted, show why and offer actual correction, retry or resume actions.
5. The system works when the browser is closed; scheduled and manually requested work use the same source of truth.

**Important distinction:** Absence of *local* English text must never block a *Japanese subtitle search*. A missing English source is a fallback acquisition step, not grounds to declare a title permanently blocked. Display sourcing eligibility and translation readiness independently, without mixed contradictory messages.

## Information architecture (no more batch-specific pages)

- **Library (default)**: Jellyfin search/browse, movie/show/season/episode drill-down, compact per-item status: JA ready, EN only, missing, needs review, running. Always show the actual selected media path/edition in an optional details disclosure. One action: **Get Japanese subtitles**. Allow explicit rescan/retry without requiring a manually preassigned automatic queue task.
- **Work**: sections for **Active**, **Needs attention**, and **History**. Real status: queued / sourcing JA / sourcing EN / translating / validating / held / published / failed / paused; title, item count, current item, last event and blocked reason. Functional start, pause, resume, cancel, retry, reprioritize, and enqueue from Library. Separate background schedule from an owner-invoked job; don't confuse them.
- **Review**: held source subtitles and PLaMo lines/cues with reason code, original EN, draft JA, surrounding context, timestamp, editable JA, approve/publish, retry bounded repair, or explicitly dismiss. No read-only 'review needed' placeholder.
- **Settings / diagnostics**: provider accounts and per-provider *actual* downloads used/remaining/reset when obtainable (OpenSubtitles, SubDL); search counts separately; model/thermal limits, schedule and detailed worker logs. Keep raw API keys out of browser output and GitHub. Preserve useful existing diagnostic views behind Details rather than headline clutter.

The UI should be **compact**: results and available actions first, long file paths/events/technical JSON behind disclosures. Never force the user to decipher old logs to learn whether a batch has finished.

## Job state and invariants

One durable job identity per requested operation and stable Jellyfin/media identity. Reuse existing coverage queue, staging, checkpoints and worker ownership: **do not add parallel databases, schedulers, provider download loops or publishers just to make a UI**. Define a thin adapter that reads authoritative state and exposes legal commands.

Minimum contract: `job_id, media_id, operation, scope, state, phase, items_total, items_done, published, staged, held, failed, last_activity, last_error, active_worker, checkpoint, valid_actions, provider_usage`. Values must come from observed job state and persisted events, not inferred from the presence of old logs.

- **Completed/archived:** Hide old American Dad runs from Active, allow archive/clear-from-view without deleting finished subtitles, checkpoints or audit history.
- **Interrupted:** Show unfinished Child's Play and other jobs with an actionable resume or retry only where underlying checkpoint logic supports it.
- **New work:** Enqueue any library selection rather than relying on manually named, show-specific scripts.
- **Accurate finish signals:** prominent RUNNING / COMPLETED / FAILED / HELD plus timestamp and exact per-item publication/coverage results. An inactive transient systemd unit is not evidence of successful completion.
- **No false download counts:** 600 *searches* is not 600 downloads. Show successful downloads by provider and day, failed attempts separately, observed server quota if supported and clearly marked unknown values when not. Preserve dated reports so the last two days' totals can be reconstructed where logs support them.
- **Safe source-first fallback:** JA discovery does not depend on locally existing EN; EN sourcing and PLaMo are unattended fallbacks. Preserve existing good subtitles, protected user edits, strict no-overwrite and timing safeguards.
- **No stale-duplicate regression:** media rows are reconciled when Jellyfin removes paths; don't create duplicate episodes or leave dead media records. Current owner audit Nov 8: Sunny BigDisk video cleanup finished, Jellyfin indexed 12,388 valid files, but manual sourcing still required a separate patch because the automatic planner did not create JA tasks. Explicit owner selection must remain a usable independent entry point.

## Roadmap, ordered by value

### P0 — Fix the operator experience NOW, alongside current sourcing
1. Immediately replace misleading sourcing and translation summary panels with truthful live job state, progress, completion/failure/held markers and compact per-episode JA/EN coverage. Display and wire working controls for the actions already supported; eliminate inert actions and old completed-job clutter from Active. Don't postpone this until backend research is complete.
2. Make Work/Review functional in bounded increments: archive completed American Dad jobs from view, resume/retry unfinished Child's Play only with verified checkpoints, create work from selected library media, inspect/edit/approve held cues. Prioritize controls that remove actual operator blockers.
3. Let the current Sunny S03 Japanese sourcing run finish; report exact JA sidecars published / held / not found across all 15. Verify SubDL is actually used by Sublarr, not merely configured. Don't claim download usage without evidence.
4. Connect the missing EN acquisition -> PLaMo translation fallback for uncovered episodes (existing issue #67), using existing workers and checkpoints.
5. Make held subtitle/PLaMo results actionable at least via reliable existing backend operations; preserve completed cues (issues #4, #64, #71 PR evidence). Finish existing American Dad / Child's Play work safely before spawning duplicate jobs.
6. Ensure worker state, crash/reboot recovery, and provider accounting are genuinely persisted (issue #66), with compact tests.

### P1 — Stabilize the generic operator API behind live UI controls
1. Map existing coverage queue, Sublarr provider flow, PLaMo job storage, systemd units and on-disk outputs into a documented **single job state projection**.
2. Implement generic enqueue, inspect, pause/resume, retry, review/edit/approve, archive-from-view as operations backed by existing durable state. Reject unsupported actions rather than drawing inert controls.
3. Add tests for cases encountered Nov 7–8: stale BigDisk IDs/duplicate episodes; explicit JA search without EN or preassigned JA task; failed/unavailable JA -> EN search -> local translation; quota exhaustion; two providers; held cue recovery; completion accounting; old completed jobs; interrupted Child's Play.
4. Add provider attribution per successful download and request (not just 600-search batch budgets), plus safe quota reset handling and historical reports.

### P2 — Complete and polish the replacement dashboard, not its working backend
Build compact **Library / Work / Review / Settings** on the stable API. The normal workflow must require no SSH, no terminal, no knowledge of provider internals or PLaMo job IDs. Existing advanced diagnostic data remains optional. Test on the actual 4:3 and desktop client layouts. No hardcoded Sunny/American Dad/Child's Play controls.

### P3 — Reliability and maintenance pass
Unify duplicated adapters where safe, remove obsolete UI code only after tests, document deployment/rollback and operator procedures, and verify true watchable-JA coverage over representative titles. Keep the current standalone app and stable source/translation workers.

## Priority correction (Nov 8)

The owner explicitly rescinds the Nov 7 freeze: **the bad dashboard is alienating them from the pipeline and preventing understanding of progress and work management.** Functional UI work is not optional future polish and must start immediately. The freeze was too conservative. Roll out operator improvements incrementally against the stable existing backend while work continues, without pausing the media pipeline to build unnecessary infrastructure.

## Concrete owner complaints recorded on 2026-11-08

- Browser is **too wordy** despite a working library view; has weak at-a-glance JA/EN coverage and no true one-click media processing.
- Sourcing/translation panel says **15 blocked (English not ready)** while **15 Japanese searches are accepted and running**, which is contradictory.
- No clear 'finished sourcing' status; needs item progress and durable, human-readable completion report.
- Current PLaMo section is mostly **read-only**, cluttered with stale completed American Dad jobs and an incomplete Child's Play job; cannot clear history, resume/retry unfinished work, create work, or action reviews.
- 'Needs review' is not an editor; user cannot correct held translations and publish.
- After two full days of provider searches (up to 600/day), the owner **could not obtain the number of actual downloads**. Searches vs download attempts vs staged/published files and time windows must be reported separately and accurately.
- Real Sunny S03 sourcing failed because stale BigDisk records were retained, then due to missing task assignments; two days were spent on file management and diagnosis before all 15 were eligible. Avoid similar recurring operator intervention.
- This is conceptually much simpler than the OptiPlex NOW ecosystem: **prefer a focused task tool**, not a screen of disconnected technical services.

## Acceptance / definition of good

A user selects Sunny S03 from Library and presses **Get JA**; all eligible episodes advance through source-first then EN/PLaMo fallback automatically, or surface an actionable, truthful hold. The UI shows `15 total / N published / N held / N still missing`, provider downloads used by provider/day, and a clear finished state. Users can open any held cue, repair/approve, resume an interrupted movie, archive completed American Dad jobs from view, and add new work without terminal or assistant assistance. The same controls work for any media, with existing privacy, no-overwrite and thermal limits preserved.

## Code and operational boundaries

- Documentation/roadmap is **not code implementation**, nor proof of host deployment. Do not restart the current source worker to implement UI features.
- Canonical source-first policy: [BRUISER_SUBTITLE_POLICY_CANONICAL_2026-11-06.md](BRUISER_SUBTITLE_POLICY_CANONICAL_2026-11-06.md).
- Prior architecture handoff: [SUBHUB_ARCHITECTURE_AND_PIPELINE_HANDOFF_2026-11-07.md](SUBHUB_ARCHITECTURE_AND_PIPELINE_HANDOFF_2026-11-07.md).
- Existing issues: [#66 standalone controls/reboot recovery](https://github.com/SteezyMode/bruiser-subhub/issues/66), [#67 EN recovery/PLaMo](https://github.com/SteezyMode/bruiser-subhub/issues/67), [#64 held-source salvage](https://github.com/SteezyMode/bruiser-subhub/issues/64), [#65 new media intake](https://github.com/SteezyMode/bruiser-subhub/issues/65).
