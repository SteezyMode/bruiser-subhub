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

## Live acceptance result and required behavior — Nov 8, after roadmap creation

**Owner observation:** A 15-episode Sunny S03 owner-initiated Japanese search ran to completion. Backend status became `active=false` with `SEASON_JA_DONE`, reporting **15 plausible candidates, 11 newly published, 4 held** due to `no_candidate_passed_trusted_sync_correction`. These are worker-reported results, not independently validated sidecar counts or provider download charges; `staged_not_published:15` appears ambiguous. Despite finishing, the dashboard did not visibly declare the job complete. The owner had to run repetitive SSH status checks.

**Explicit product requirement:** Every job shows a prominent durable terminal summary. For this run: **Completed — 11 published, 4 need attention**, 15 searched, item statuses and a direct **Review four held** action. A job reaching `active=false` is not itself evidence of success. Keep the completed item visible under recent/history; archive from active view separately. Refreshing the browser must not erase or regress the terminal status. Give a specific completion timestamp and per-episode outcomes.

**Held-subtitle lifecycle:** The current automatic sync attempt already ran and rejected four candidates. After a season finishes, schedule one **bounded, quota-free** recovery attempt for recoverable timing/format issues using the retained staged bytes (avoid extra provider downloads), with strict cue/text preservation, validated offsets and no-overwrite. If still held, keep the staged bytes and present the exact reason with actionable review/offset repair, retry or fallback to English sourcing and PLaMo translation. Record when automatic repair has been attempted so the UI cannot imply endless background work. Avoid any unbounded retry loop or silent quality relaxation. See [issue #64](https://github.com/SteezyMode/bruiser-subhub/issues/64) and [dashboard issue #86](https://github.com/SteezyMode/bruiser-subhub/issues/86).

**Beta testing discipline:** Treat every actual user-run test and complaint as acceptance evidence: observe what ran, count true publications and holds, record bugs and expected behavior in issues/docs, and connect to the next regression test. Never present a UI control without a working backend action or a correctly labeled unavailable state.

## Owner priority refinement — November 8: PLaMo should run continuously on eligible work

The owner explicitly wants **complete-series Japanese coverage for both It's Always Sunny in Philadelphia and American Dad**, not isolated season proofs or perpetual JA-provider searches. **Use available local GPU translation aggressively as soon as English text is ready.** Do not gate usable PLaMo work on first exhausting the provider's daily search quota or waiting for an otherwise unrelated episode to finish.

Priority policy, applied per episode without duplicate concurrent work:

1. If a verified, usable Japanese track already exists, mark covered; no provider request and no translation.
2. If a verified Japanese candidate is **already downloaded/staged**, attempt bounded, quota-free timing recovery and publication first. A failed sync must create actionable held state; don't re-download identical bytes.
3. If **verified local English text exists but Japanese doesn't**, queue PLaMo now (subject only to existing GPU temperature, Wolf gaming, model, checkpoint and one-worker safety rules). Japanese provider quota exhaustion is **not** a prerequisite.
4. While Japanese downloads remain available, Japanese sourcing continues for episodes with no ready EN, and for any still unserved items where acquiring human Japanese is more useful than translating; avoid racing providers against active PLaMo on the same media identity.
5. On **OpenSubtitles/SubDL download limit or cooldown**, immediately reallocate attention to all EN-ready missing-JA episodes; launch the existing safe PLaMo job(s) instead of stopping the entire subtitle program for the day.
6. If neither EN nor JA exists, search for English (and recover embedded text/OCR if applicable); as soon as EN is verified, dispatch to PLaMo, independent of next day's JA quota reset.
7. If a translated subtitle is held, preserve completed cue checkpoints and stage artifacts; recover/review rather than restarting from zero.

The **existing PLaMo translator is to be used**, not replaced with a new model or project-specific runner. Existing source and translation workers remain separate and independent, with one queue/identity for arbitration. Require exact episode identity, source subtitle completeness, alignment with video, stable checkpoint and strict create-only publication. No GPU work during active Wolf/game-stream sessions or unsafe thermals; resource limits are guardrails, not excuses to leave EN-ready work idle.

### Series completion acceptance

- Whole-series inventory for Sunny and American Dad: total unique canonical episodes / JA already present / staged JA recoverable / verified EN text ready for immediate PLaMo / EN needs acquisition or OCR / held/unresolved.
- Process all uncovered episodes across both shows over successive provider quota windows with no manual per-season launch; use PLaMo promptly on EN-ready episodes between and during provider runs, not only after all seasons are sourced.
- Per-episode terminal state and playable JA sidecar; an episode cannot be counted as done solely because a translation job completed or a source candidate was found.
- End result: full JA coverage for both available on-disk series, with truly unresolved items visibly held for action; zero duplicate downloads, reused checkpoints, no fake done counts.
- First recovery target: Sunny S03E03/E04/E07/E08 have 4 retained Japanese stage records and sync rejects; salvage if safe, otherwise EN->JA PLaMo instead of indefinite sync retries. Existing 11/15 sidecars must remain unchanged.

## Current owner workload priority — November 8 (supersedes general queue order)

**Priority media**: (1) all available episodes of **It's Always Sunny in Philadelphia**; (2) all available episodes of **American Dad!**; (3) the owner's **The Shining (1980)** file. Other library titles remain eligible for the ordinary background schedule but must not displace these three while the owner has explicitly prioritized them. No newly invented title-specific pipelines.

**Throughput goal**: substantial unattended television coverage, ideally dozens of correctly published Japanese episodes over time, using the existing PLaMo pipeline whenever validated English subtitle text exists. Do not promise 100+ episodes in a single outing without verified elapsed-time/GPU performance and usable English sources.

**Budget policy**: retain a small, configurable number of provider downloads for later movie requests; prioritize quota-free saved Japanese repair and local PLaMo translations for shows. Quota exhaustion is a signal to do English-ready PLaMo work, not to stop. Do not invent a concrete reserve without confirming remaining live quota; make reserve visible and operator-adjustable.

**The Shining cut**: owner's file is *possibly* the ~119-minute international/European edition, **not yet verified**. Determine actual host video duration with ffprobe and map to the verified file identity *before* downloading, aligning or publishing; US 144-minute captions must not be blindly applied to the shorter edit. Prefer valid already-local EN/JA or correctly matched EU-cut source over a wrong-edition US subtitle. Preserve existing video and subtitle files.

**Backend truth**: this is a GitHub priority decision, **not evidence that the running OptiPlex job queues or downloads have changed**. Any production change must first validate existing workers, locks, checkpoints, no-overwrite and quota gates.

## Optional future investigation — local English speech transcription (2026-11-09)

**Status: idea only, not a requirement, milestone, approved implementation, or change to the present priorities.** Current priority remains reliable JA source/EN recovery -> PLaMo 3 Translate 8B fallback and a usable Library/Work/Review UI. Do not add a separate ASR worker, scheduler, database, or Bazarr installation based on this note.

**Potential value:** Some library titles lack recoverable English text after checking embedded tracks, OCR, existing sidecars and subtitle providers. For English-audio media only, optional local speech-to-text could produce a timed English SRT which the existing PLaMo translation pipeline could then use. This is last-resort source recovery, not a replacement for authentic, correctly matched EN/JA subtitles. It may increase useful coverage but introduces recognition and timing errors, especially with accents, music and overlapping dialogue; do not claim it works on the present host without a test.

**Reuse existing software before coding:** The current Sublarr documentation describes built-in local `faster-whisper` (disabled by default), manual transcription, batch and configurable transcribe-on-provider-miss options, under Settings -> Providers -> Transcription. Check the **installed** `sublarr-pilot` version, configuration, model/GPU access and safe staging behavior before proposing integration. Standard Bazarr also offers Whisper through an external service, but depends on Sonarr/Radarr for indexing, so do not introduce a competing subtitle manager into this Jellyfin/Sublarr household stack. Optional external Subgen or another ASR model is only worth examining if Sublarr's existing transcription proves inadequate.

**Only if revisited:** Run a small, isolated test with a few known English-audio media samples, comparing output to reliable existing dialogue for omissions, hallucinations, word accuracy, timing, readable cue segmentation, runtime/VRAM and one downstream PLaMo-JA sample. Prefer temporary/private output and no overwrite. Do not scan/transcribe the entire library, enable scheduled transcription, or disturb Wolf/PLaMo GPU work merely for the experiment. Any future integration should reuse the established coverage queue, checkpointing, no-overwrite publication and observable job state.

References: [Sublarr transcription settings](https://sublarr.de/docs/user-guide/settings/transcription/), [Sublarr providers](https://sublarr.de/docs/user-guide/settings/providers/), [Bazarr Whisper provider](https://wiki.bazarr.media/Additional-Configuration/Whisper-Provider/), [Bazarr library dependency](https://wiki.bazarr.media/Getting-Started/How-Bazarr-Connects-to-Sonarr-and-Radarr/).
