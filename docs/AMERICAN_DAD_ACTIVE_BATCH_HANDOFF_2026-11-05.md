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
4. Owner ran launcher pinned to **`0ab13b0a0d1989eff27aa0e1eed552e3ae583610`** and received **`STARTED background PID 2598336`** with `48` queued episodes. This PID is an **observed historical launch**, not proof the process is currently alive. The watch display showed **S20E01** being translated; it reached at least **266/352 cues** in the supplied log. **Do not claim subsequent episodes have finished unless the host is rechecked.**
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

## What to do in the NEXT chat

1. **First inspect live batch progress; don't refactor or experiment with models.** Let the 48-episode existing-English pass proceed if healthy. The user said it will take a while and wants to change chats.
2. If a genuinely reproducible failure appears (for example a stalled episode, detached process gone, GPU memory conflict, temperature sensor absent), troubleshoot minimally from host log and preserve completed SQLite cues and published SRT files.
3. Once the pass is complete, count truly published 8B sidecars and remaining blocked source cases. Only then tackle **English/Japanese source acquisition and release-specific synchronization for Seasons 3–18** (and remaining gaps), not a new translation model. The source-only Japanese provider timer may be running independently.
4. If the owner requests development heat/performance analysis, first attach/validate read-only historical telemetry; do **not** assume it was already collecting. Never promise a cap increase will necessarily speed sustained translation; thermal pauses can offset performance.
5. Respect owner preference: **minimal moving parts, no prompt twiddling, no repeated human episode reviews, and no long tool-call stalls**.

**Status as of last user-provided evidence:** Batch started, S20E01 in progress, auto THERMAL_PAUSE and THERMAL_RESUME working, GPU cap manually 24 W. **Do not claim the 48-episode run is finished.**
