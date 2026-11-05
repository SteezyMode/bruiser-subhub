# American Dad — active PLaMo 8B batch: new-chat handoff (2026-11-05 JST)

**Read this first in a new chat before touching the OptiPlex.** This document supersedes older *American Dad* and PLaMo experiment notes **for the current household batch**. It is a running private-install pilot, not a general-purpose product release. Keep the source-only Japanese subtitle acquisition pipeline separate.

## Owner's actual goal and decisions

- The user and Natsuyo want to watch *American Dad!* with usable Japanese subtitles. **Natsuyo watched S19E13 with PLaMo 8B Japanese subtitles and approved the viewing experience.** This—not another model benchmark—is the acceptance criterion.
- **Model decision closed:** Keep **PLaMo 3 Translate 8B Q4_K_M** as default. PLaMo 2B was tested on the same S19E13: **392/392** cues in **86.647 seconds including startup**, but editorial comparison found more comedic/idiom/sexual-joke misses, despite some wins. The 2B version is a separate optional track. **Do not ask Natsuyo to rewatch episodes repeatedly or restart model tournaments.**
- Translate **every episode after Season 2 with existing usable English text**, without a small arbitrary batch limit. Priority is **Season 20, then 21, then remaining 19**; the owner particularly dislikes S19 but authorized all English-ready episodes. For older seasons 3–18, source Japanese first, then try obtaining matching English from providers **in a subsequent phase**. Do not claim English sourcing has already run for those seasons.
- Existing Japanese subtitles always win: **no replacement/overwrite**, separate named machine tracks only. Jellyfin's existing dual-subtitle plugin is already solved and irrelevant to this batch. No extra GUI/show guide.
- **Current GPU cap is 24 W, set manually by owner using LACT.** Never silently change it. Previously it was 32 W; some launcher text still refers to 32 W but **the scripts do not set the cap**. User values cool/quiet hardware over speculative speed increases. CPU is i7-9700 in OptiPlex SFF; GPU RTX 3050 6 GB LP.

## What has been verified on the actual host

1. S19E13 “The Fast and the Spurious”: Japanese provider lookup found no identity-checked Japanese subtitle; 392 embedded English cues translated 392/392 using 8B; sidecar `.ja.PLaMo8B.srt` published. Natsuyo found it acceptable for real watching.
2. The same 392 cues were translated by PLaMo 2B with its own `.ja.PLaMo2B.srt` alternate and private paired comparison JSON; 2B wall time **86.647 s**. Keep 8B default.
3. **Before the new batch, owner conducted a read-only per-season inventory**: 13 American Dad episodes already had JA, 48 English-ready episodes lacked JA (**22 in S20, 17 in S21, 9 in S19**), and **300** episodes lacked *local/embedded* English subtitles in the scanned library. The missing 300 are not proof that provider subtitles are unavailable. No Japanese observed locally for S03–S18.
4. Owner ran launcher pinned to **`0ab13b0a0d1989eff27aa0e1eed552e3ae583610`** and received **`STARTED background PID 2598336`** with `48` queued episodes. **Later owner-supplied monitoring showed 2/48 published, S20E03 at 116/440 cues, then `BATCH_PAUSED S20E03 model_did_not_translate_spoken_cue_117` and no active batch process.** This is an isolated model-output classification failure, not a thermal abort. The old PID is historical; do not mistake it for a currently running process. **These are last-uploaded results, not a fresh live host check.**
5. **Thermal pause/resume demonstrated on real host**, while S20E01 was in progress:
   - CPU hit **79–80°C** and GPU **65–66°C** when the software paused;
   - resumed with CPU **55°C**, GPU **57°C** after cooling.
   - Thresholds in batch code: pause at CPU **79°C** or GPU **73°C**, resume at CPU <= **73°C** and GPU <= **67°C**. Additional abort bound CPU **90°C**, GPU **83°C**. Checks are at intervals of about 10 spoken subtitle cues and between episodes, **not instant hardware thermal locks**. The batch checkpoint is per cue.
   - 8B GPU placement is **28 GPU layers**, **2 CPU threads** in the *batch*. User does not want to raise GPU cap merely because temp pauses exist.
6. Previous progress status of “log not found” was **before the batch was started**. It was resolved by actually invoking the launcher. Current private host log exists at `~/bruiser-pilot/plamo3-ab/american-dad-existing-english-batch/batch.log` as confirmed by launch output.
7. The batch's *Roger* bug workaround is scoped: it changes Japanese `了解` to `ロジャー` only when English begins with an addressed `Roger,`/`Roger!`/`Roger.` etc. It **does not globally replace valid `了解`**. The approved S19E13 track predates this correction and stays unchanged.

## Source of truth: installed host status, not GitHub CI

**GitHub CI is offline unit/syntax testing; it does not verify real media, temperatures, live running state, or whether a finished sidecar is playable.** Ask the owner for fresh host status if making claims beyond the log above.

Host paths:
- SSH target: `optiplex@100.121.156.34` (Tailscale; may change).
- Private runtime: `~/bruiser-pilot/plamo3-ab`
- Batch: `~/bruiser-pilot/plamo3-ab/american-dad-existing-english-batch/`
- Batch log: `batch.log`; batch PID: `batch.pid`; immutable-ish queue denominator: `queue.json`
- Per-episode source and cue SQLite checkpoints: `SxxExx-<path-hash>/episode.json`, `source.en.srt`, `progress.sqlite3`
- Outcome lines: `run-status.jsonl`. Preview/status program: `~/bruiser-pilot/plamo3-ab/american_dad_batch_progress.py`.
- New tracks are external `<video-stem>.ja.PLaMo8B.srt` beside each original movie; none of the videos is rewritten.

**Inspect status from Mac mini (no code changes):**
```bash
ssh -t optiplex@100.121.156.34 \
  'python3 -u "$HOME/bruiser-pilot/plamo3-ab/american_dad_batch_progress.py" --watch'
```
Close **only the display** with Ctrl+C; detached batch continues.

Quick log:
```bash
ssh optiplex@100.121.156.34 \
  'tail -n 45 "$HOME/bruiser-pilot/plamo3-ab/american-dad-existing-english-batch/batch.log"'
```

**Do not restart an already-running batch.** If genuinely stopped, investigate latest `BATCH_PAUSED`, `SOURCE_HELD`, `THERMAL_PAUSE`, errors and exact checkpoint state before rerunning. The pinned installer launcher used for this session is:
`tools/run_plamo8b_american_dad_existing_en_batch.sh`;
known working pin `0ab13b0a0d1989eff27aa0e1eed552e3ae583610`.
Launcher re-downloads pinned helper code, may show stale text about the old cap; it **does not modify LACT settings**. Avoid relaunch just to refresh UI or label.

## Repository implementation

- `tools/plamo8b_american_dad_existing_en_batch.py`: existing-English scan, priority order, no-JA override, the name repair, individual checkpoint directories, 8B llama.cpp worker, cooling gate.
- `tools/run_plamo8b_american_dad_existing_en_batch.sh`: background launcher, dependencies, pin, state and status installation.
- `tools/american_dad_batch_progress.py`: read-only episodes bar + current cue bar from actual saved SQLite and installed sidecars, status COOLING/RUNNING/PAUSED.
- `tools/plamo3_watch_american_dad.py`, `tools/plamo3_source_first_american_dad.py`: verified single-episode engine and Japanese-first sourcing; batch reuses their inference logic.
- `tools/american_dad_batch_telemetry.py`: **experimental read-only 15-second CSV sampler committed to GitHub but NOT confirmed installed or attached on the running host.** Intended development measurements: CPU package °C, GPU °C, GPU power/draw/driver-reported cap, GPU utilization, VRAM, RAM, CPU busy %, timestamp, episode/cue count. **Do not claim historical CSV telemetry exists** until attached and verified. It does not control LACT. The owner's later preference was to stop pointless power-cap tweaks and simply let the existing long-running batch proceed.
- No private subtitle text, media content, passwords, or connected account credentials should be copied into this public repo.

## Overnight recoverability fix — repository change, not automatically installed

The log showed S20E03 stopping at cue 117 with only 116/440 verified cues checkpointed, while S20E01 and S20E02 were already published. This is an **episode-level quality problem**, not evidence of a systemic CUDA or overheating failure. There must be no partial S20E03 Japanese publication.

The added source and test artifacts are:
- `tools/plamo8b_american_dad_existing_en_batch.py`: one identical replay on a non-Japanese/malformed model response (same 8B, creator-native prompt, history, temperature=0). If that cue remains invalid, record `EPISODE_HELD` and continue to the next episode. This does **not** write an untranslated cue, bypass subtitle QA, or discard existing SQLite checkpoints.
- `tools/american_dad_batch_progress.py`: count `episode_held` in the progress display.
- `tools/resume_plamo8b_american_dad_overnight.sh`: pinned, owner-invoked, **refuses a still-running worker**; downloads/tests only two public code files; makes private backups; appends rather than wipes `batch.log`; resumes existing queue and per-cue state.
- `test_plamo8b_overnight.py`: offline tests for retried/held cue, critical failures and cooling behavior.

Cooling changed from 20-second to **5-second** polling and only requires a sensor to hit its hysteresis resume threshold if that sensor actually crossed its pause threshold (including during the cooling interval). CPU 79°C/73°C, GPU 73°C/67°C, emergency abort CPU 90°C/GPU 83°C, GPU 28 layers, CPU 2 threads, Q4_K_M model, PLaMo native prompt, and user-controlled 24 W LACT cap remain unchanged.

**A model-server crash, temperature sensor failure, thermal emergency, invalid checkpoint, or storage fault still stops the batch.** An isolated bad subtitle cue does not. No attempt has been made to install this change on the OptiPlex from GitHub; actual host deployment and post-resume progress need owner verification.

To deploy after merge, read `tools/resume_plamo8b_american_dad_overnight.sh`, pin both the download URL and its one required argument to the same tested **40-character commit SHA**, and run over SSH from the Mac mini. Do not launch the old `0ab13...` code for overnight use or relaunch a running process.

## What to do in the NEXT chat

1. **First inspect live batch progress.** Last uploaded state was STOPPED / PAUSED at S20E03 cue 117, 2/48 published. If it is still stopped for that reason, use the tested, pinned overnight resume script above. If another worker is now running, leave it alone. Don't experiment with other translation models.
2. If a genuinely reproducible failure appears (for example a stalled episode, detached process gone, GPU memory conflict, temperature sensor absent), troubleshoot minimally from host log and preserve completed SQLite cues and published SRT files.
3. Once the pass is complete, count truly published 8B sidecars and remaining blocked source cases. Only then tackle **English/Japanese source acquisition and release-specific synchronization for Seasons 3–18** (and remaining gaps), not a new translation model. The source-only Japanese provider timer may be running independently.
4. If the owner requests development heat/performance analysis, first attach/validate read-only historical telemetry; do **not** assume it was already collecting. Never promise a cap increase will necessarily speed sustained translation; thermal pauses can offset performance.
5. Respect owner preference: **minimal moving parts, no prompt twiddling, no repeated human episode reviews, and no long tool-call stalls**.

**Status as of last user-provided evidence:** 2/48 8B episodes published; S20E03 checkpoint 116/440; stopped at non-Japanese cue 117. Thermal auto pause/resume was working; GPU cap remained owner-managed at 24 W. **The GitHub resilience fix is tested offline but has NOT been verified deployed on the host. Do not claim the 48-episode run is finished or restarted without fresh host output.**
