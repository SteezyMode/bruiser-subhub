# Bruiser automated batch operator — November 6, 2026

**Why:** The 12,386-media, 15,852-task private coverage queue exists, but the owner correctly identified that manually running small individual shells and deciphering terminal logs is **not** an automated system. Start large, independently running batches on demand and inspect actual state at any time. This is a **current development contract**, not another optional dashboard idea.

## What is implemented in GitHub

[`tools/bruiser_batch.py`](../tools/bruiser_batch.py) is one host-local CLI with four primary commands:

| Command | Function |
| --- | --- |
| `bruiser-subs start --cycles 5` | Start a **detached** source-only systemd user service **now**, with up to 5 cycles × 600 OpenSubtitles search attempts (software maximum 3,000; actual eligibility and failures vary) |
| `bruiser-subs status` | Show service's **actual running/stopped/interrupted** state, current cycle/phase, per-stage counter, current title, staging successes, detected published sidecars, QA holds and provider-limit events |
| `bruiser-subs status --json` | Emit machine-readable live snapshot, suitable for later Bruiser GUI integration |
| `bruiser-subs logs --lines 60` / `logs --follow` | Read detailed private log, including exact holds; follow only attaches, Ctrl-C **does not stop** worker |
| `bruiser-subs stop` | Stop the detached user service and all its child source processes; preserve existing search/staged data and queue history |

The controller is a thin orchestration layer using **the already installed proven pipeline**, not a replacement subtitle engine. It acquires the existing daily-service source lock to ensure no concurrent scheduled/manual provider cycle. It checks Sublarr's safe source-only settings, refreshes the normal Jellyfin manifest only when old, then:
1. Tries **previously downloaded Japanese** through existing ffsubsync/quality/no-overwrite publication gates. Per-title publication holds are persisted in the existing coverage queue, rather than indefinitely retried in the same batch.
2. Runs up to 600 **OpenSubtitles Japanese searches** per cycle, preserving SQLite search history and 30-day cooldowns.
3. Reconciles the coverage queue with newly saved plausible matches. Stages up to 200 matched subtitles per cycle while respecting the OpenSubtitles account's **real download quota** and stopping on API 429/quota exhaustion.
4. Synchronizes and attempts create-only publication with existing ffsubsync; records per-title publish/hold events and counters.
5. Repeats on remaining eligible titles for requested cycle count. Already-finished searches, downloaded files and verified sidecars persist; interrupted batches can be restarted with `start` without redoing an entire library census.

**Live status is not made up:** phase/action counts come from captured worker stdout lines and actual publisher callbacks, written atomically to `~/bruiser-pilot/batch-control/current.json`; detailed logs are private `~/bruiser-pilot/batch-control/batch-*.log`. Current queue is `~/bruiser-pilot/coverage-queue/coverage.sqlite3`. A live systemd user service, not a Python process dependent on the SSH terminal, owns work after launching.

**Download budget reality:** the OpenSubtitles search API may allow requests today, but downloading new subtitles requires unspent account allowance; the controller reports `quota_exhausted` and continues **search-only** cycles until the provider's UTC-day reset. It never fakes successful downloads or bypasses the provider cap. 09:15 JST next-day timer remains configured, though the source lock prevents duplicate concurrent work while a manual batch is active.

**Timing correction:** All staged Japanese source subtitles still pass the existing audio-based ffsubsync (bounded shift/drift, intact dialogue) and trusted embedded-reference alternatives before create-only publication. A modest constant offset is repairable rather than cause for rejection. Malformed/incompatible subtitles remain held with a reason; don't globally disable validation.

**GPU fallback:** explicitly **NOT YET DISPATCHED BY THIS SOURCE CONTROLLER**. The owner wants local GPU/PLaMo for substantial long-tail coverage **after** sourced Japanese/English repair. Its queue handoffs exist, but connecting supervised, resumable GPU translation remains [issue #63](https://github.com/SteezyMode/bruiser-subhub/issues/63). Do **not** claim this source batch alone will auto-translate 8,336 titles lacking both languages. Retain the independent accepted American Dad PLaMo 8B pilot.

## One-time installation

[`tools/install_bruiser_batch_controller.sh`](../tools/install_bruiser_batch_controller.sh) is the guarded one-time installer. It downloads a pinned script and publisher/queue updates, parses them, runs offline regression tests, then backs up and installs under `~/bruiser-pilot/coverage-queue-code` and `~/bruiser-pilot/subhub-control`. Installs executable wrapper at `~/.local/bin/bruiser-subs`. **Installer makes no OpenSubtitles queries, downloads, inference, media writes or timer changes.** It refuses replacement while a batch or daily source service is running. It does not start work until a separate `start` call.

SSH usage from MacBook:
```bash
ssh optiplex@100.121.156.34 '~/.local/bin/bruiser-subs start --cycles 5'
ssh optiplex@100.121.156.34 '~/.local/bin/bruiser-subs status'
ssh optiplex@100.121.156.34 '~/.local/bin/bruiser-subs logs --lines 60'
ssh optiplex@100.121.156.34 '~/.local/bin/bruiser-subs stop'
```
Optional `--search-budget 1..600`, `--stage-budget 1..200`, `--publish-limit 1..200` and `--cycles 1..12`. **Budget maxima are software guards, not provider-account allowances.**

## Nov 6 baseline known about current 21 staged-JA candidates

The owner executed the previous interactive staged publication recovery script and shared partial logs (not a completed summary). Several private candidates were **held** for sparse dialogue, malformed SRT, excessive timing shifts, changed dialogue during synchronization, and ambiguous release timing. Those individual media names and private failure logs belong on the host, not in this public repository. Some checks could be overconservative or reflect actually incompatible tracks; **do not claim all of those Japanese subtitles are unusable or re-download blindly.** Record them as specific candidates for targeted timing/parser audit, not reason to restart a broad 12k-item census.

**Deployment state / verified installer failure (Nov 6):** The owner ran the first pinned installer, which stopped at its offline test stage **before any script installation**. Test result: **20 passed, 1 errored**. The error was `test_atomic_private_state_survives_restart`: `private_dir(folder=STATE)` bound the initial `STATE` value when the function was defined; an isolated test overriding `STATE` could not direct the state file to its private temporary directory. Fixed in `tools/bruiser_batch.py` by resolving `STATE` **at call time** (`private_dir(folder=None)`). No `~/.local/bin/bruiser-subs` wrapper had been created and **no background source batch started** when the owner tried status/logs/stop. The existing deployed source selectors and 09:28 next-day source timer remain unaffected. **Re-run the guarded installer pinned to the newer GitHub commit and check all 21 offline tests pass.** Do not assert actual batch start until the resulting `BATCH_STARTED` and `status` outputs are provided.

## Nov 6 deployment: controller installed, manual start blocked by systemd linger

Owner re-ran pinned installer at `d154fbb5677db8119b81798e03b2d2b5be99814d`: **21/21 offline tests PASS**, then `BRUISER_BATCH_CONTROLLER_INSTALLED` reported the command `~/.local/bin/bruiser-subs` installed on host.

**No live batch started.** The first `bruiser-subs start --cycles 5` correctly stopped at:

```text
BRUISER_BATCH_ERROR RuntimeError detached_batch_requires_user_linger: sudo loginctl enable-linger optiplex
```

User's `status` displayed `State: unknown | Current phase: search_opensubtitles | Cycle: 3 / None` and `{"staged":9}`. These are **stale synthetic state data left by the earlier failing state-directory unit test**, not actual downloads or work; no `BATCH_STARTED` or real batch log exists. The successful 21 tests used a temporary state directory and did not repeat that bug. A real successful `start` overwrites the dummy `current.json` atomically; no manual file deletion or batch reinstall required.

**One-time OptiPlex action**, from MacBook with an SSH TTY so sudo can request authorization:

```bash
ssh -t optiplex@100.121.156.34 'sudo loginctl enable-linger optiplex && loginctl show-user optiplex -p Linger && ~/.local/bin/bruiser-subs start --cycles 5 && sleep 3 && ~/.local/bin/bruiser-subs status'
```

Expected `Linger=yes`, `BATCH_STARTED` and real `State: running` / phase / cycle / logs. If the command fails, review its exact output rather than claiming work is running. **Do not rerun installation**; it already succeeded, and don't run a second batch until `status` indicates whether one is active.

## November 6 actual detached batch launched (owner-confirmed)

The user enabled lingering and started the host service successfully:

```text
Linger=yes
BATCH_STARTED batch-20261106T031534Z
BATCH_LOG /home/optiplex/bruiser-pilot/batch-control/batch-20261106T031534Z.log
BRUISER_BATCH_STATUS
  State: running | Current phase: queued | Cycle: 0 / 5
  Recent issue: source lock acquired; beginning now
  Scheduled daily source job: not active
```

The user independently reconnected and received the **same running service status**. This proves systemd accepted the detached batch and acquired the source lock, **not** that any new OpenSubtitles search, staged download, or Japanese publication succeeded yet. `queued / Cycle 0` refers to startup checks (`ensure_installed`, Sublarr config safety, scheduler idleness, potential Jellyfin manifest refresh) which currently do not emit granular status updates. **Do not call this a hang or assume work is complete from two near-identical early status samples.**

Next owner-visible checks are `~/.local/bin/bruiser-subs status` and `~/.local/bin/bruiser-subs logs --lines 50`; if `queued` persists after startup, inspect `systemctl --user status bruiser-subhub-batch.service --no-pager` and `journalctl --user -u bruiser-subhub-batch.service -n 40 --no-pager` for the real exception or slow stage, not generic unsupported guesses. The batch was launched at 2026-11-06T03:15:34Z (12:15:34 JST). Do not hot-patch/reinstall running source code or start a competing batch.

**Operational backlog:** Improve startup phase observability in a later safe deployment: surface `preflight`, `refresh_catalog`, `reconcile_queue` and failure events immediately so users aren't left staring at the misleading `queued` label. Keep per-title published/held events and provider allowance in the same status interface. GPU PLaMo last-resort integration remains a separate still-unimplemented production stage.

## Real live full-screen terminal progress bars (Nov 6)

The owner requested the proper progress bars that previous manual pilots displayed, not merely polling status text with `watch`. Implemented **[tools/bruiser_live_view.py](../tools/bruiser_live_view.py)**, a standalone read-only Python terminal viewer over the **already-running** `bruiser-subhub-batch.service`, its private `current.json`, and private event log. It is independent of the worker and can be installed/opened **while a five-cycle batch is active**; never hot-patch or restart a running worker for UI reasons.

Use the **[guarded viewer installer](../tools/install_bruiser_live_view.sh)** to fetch a pinned viewer and its regression tests, validate source syntax and run offline tests, then install `~/.local/bin/bruiser-live`. The viewer refreshes every 2 seconds, and **Ctrl+C exits the VIEW only, not the batch**. Open it from MacBook:

```bash
ssh -t optiplex@100.121.156.34 '~/.local/bin/bruiser-live'
```

It shows **filled/empty progress bars** for completed source cycles, actual searches out of configured *maximum* attempts, and the active stage. During publisher/sync stages, it derives a count of genuinely examined `MEDIA:` titles from the current phase of the private log; it never fabricates progress percentages if a stage is still awaiting its first event. It also distinguishes published subtitles, staged candidates, plausible searches, held titles/reasons, provider-quota events, current media and the recent real activity feed. If systemd is active but no JSON update appears for 120 seconds, it warns that the stage may be blocked instead of claiming it is progressing. `--once` provides a static diagnostic; `--interval 1..30` adjusts refresh.

**Important: first live batch** was confirmed started by the owner at `2026-11-06T03:15:34Z` (`12:15:34 JST`): `Linger=yes`, `BATCH_STARTED batch-20261106T031534Z`, `State: running`, `source lock acquired`. The two immediate status samples showed `queued / Cycle 0 of 5`, still in opaque startup; they do not prove provider activity. The viewer will show either actual subsequent progress or a startup-staleness warning. **Live viewer is committed to GitHub, not host-deployed until confirmed by owner output.**

## Nov 6, 12:28 JST — live dashboard deployed and first real results

Owner successfully installed `~/.local/bin/bruiser-live`; **6/6 offline viewer tests passed**, and the read-only full-screen display updated repeatedly at two-second intervals over the same running `batch-20261106T031534Z`. The first source-only recovery phase completed with **21 staged-Japanese media held**, **0 new JA published**; this is real low publication yield, not a display problem. The worker then entered `SEARCH OPENSUBTITLES`, cycle **1/5**, reporting **9 started** provider searches of up to **600** that cycle (up to **3,000** over five cycles), focused on pending TV entries. The same title remained in-flight for approximately 23 seconds across repeated snapshots; the request subprocess allows up to **110 seconds** before recording an error, so 23 seconds alone is not a stalled worker. Provider download attempts, newly staged files and new publications at this snapshot: **0**.

**Live-view telemetry issue:** Original viewer displayed plausible/no-match/error counters, but omitted **review-only search results**. Thus 9 searches started with zero plausible/none/errors does *not* prove zero searches completed: they may have been classified `review`. GitHub viewer code was updated to distinguish `Searches started`, `Completed`, `In-flight`, and `Review needed` alongside `Plausible`/`No match`/`Error`; test updated. This is **viewer-only and read-only**. The owner has **not yet installed this newer viewer revision**; its GitHub commit alone does not alter the currently open terminal.

**Source publication issue:** 21/21 held, including several source-format and timing-gate classifications. See [issue #64](https://github.com/SteezyMode/bruiser-subhub/issues/64) for targeted validation repair (including high-trust constant offsets beyond legacy ±2s), and **do not hot-patch or restart the running worker**. The original staged subtitle bytes and private per-title investigation evidence remain on host.

## Nov 6 terminal rendering fix — incremental curses dashboard, not repeated screen prints

Owner pointed out the first `bruiser-live` viewer visibly cleared and repainted the entire screen every two seconds. **That implementation was wrong for the requested interactive progress display.**

The viewer implementation has been replaced with `curses.wrapper(interactive_view,...)` and `draw_changed_lines`. After the initial TTY setup, **only changed terminal rows/cells are updated**, via `noutrefresh` and `curses.doupdate()`; there is no `ESC[2J` clear on each tick. An actual terminal resize may clear the viewport once. This preserves the single, stable chart with progress bars advancing in place. Added regression tests asserting no redraws or erase calls on unchanged frames, and only one updated row when a value changes. The viewer remains read-only, with no worker/service changes.

**Deployment:** New viewer code + tests committed to GitHub; owner must rerun the *same safe viewer-only installer* pinned to the latest verified commit while the active batch continues. Installation never restarts, changes or stops the current five-cycle batch. Ctrl+C exits the viewer only.

## New owner requirement — zero-touch new Jellyfin media intake (issue #65)

**Owner requirement confirmed Nov 6:** After adding a new movie or any show episode, the owner expects Bruiser to discover it and initiate subtitle acquisition and eventual local translation automatically, without manually starting a batch. This is the intended release behavior, **not implemented or installed on the host** as of this handoff.

Implementation tracked in [GitHub issue #65](https://github.com/SteezyMode/bruiser-subhub/issues/65). Prefer lightweight periodic Jellyfin discovery / durable checkpoint (e.g. 10 minute polling) without an extra plugin, wait for stable file and complete media metadata, check actual existing EN/JA tracks and sidecars, upsert **only the new item** into the persistent coverage queue, prioritize fresh items without starving backlog, and launch source/translation safely at an existing cycle boundary or when the unified worker is idle. Strict no duplicate provider calls, no overwrite, account-quota and GPU/game-session safeguards, and expose new media intake in the same in-place curses viewer. Bulk new season imports become multiple independently tracked episodes. Do not hot-patch the running 12-cycle job.

Current gaps proven from repo: `ja_first_autofill.refresh_manifest()` may reuse a catalog for 20h, `bruiser_coverage_queue.py init` reads an old snapshot, and unseen media are placed behind the existing queue at fallback rank 300. Thus automatic immediate event-driven ingestion **does not currently exist**; do not imply the daily timer already performs it.

## Nov 6 — Standalone dashboard v0.1 IMPLEMENTED IN GITHUB (not host verified)

Owner clarified OptiPlex NOW is frozen for private alpha; SubHub is **independent**, with optional Bruiser plugin only much later. The first real standalone dashboard code is committed to the SubHub repo: `tools/subhub_dashboard_server.py`, `tools/subhub_dashboard.html`, offline `test_subhub_dashboard.py`, pinned `tools/install_subhub_dashboard.sh`, optional remote desktop launcher installer `tools/install_subhub_dashboard_client.sh`, and [dashboard operator documentation](SUBHUB_DASHBOARD_V01.md).

**v0.1 release boundary:** read-only HTTP server bound strictly to `127.0.0.1:17876`, user `bruiser-subhub-dashboard.service`, refreshes live from the same private batch `current.json` and bounded event log, real search/staged/published/held counts, no provider calls, no worker restarts, no OptiPlex NOW changes. It exposes `translation.state=not_connected` until actual GPU integration. Desktop launcher on OptiPlex opens browser; optional MacBook Linux shortcut reaches it using SSH local port forwarding. User must run the **pinned installer**, which downloads code, validates, runs 9 offline tests and only then deploys the independent dashboard service. Neither source worker nor active 12-cycle job is touched by the installer.

**Do NOT claim installed/running yet.** GitHub code is not the host. First verify owner installation output, HTTP health and live counts equal the curses tracker; fix any deployment/test failures before moving on. GUI controls are intentionally **not present in v0.1**; spec and reboot-safe worker state tracked in [issue #66](https://github.com/SteezyMode/bruiser-subhub/issues/66). New-media detection [issue #65](https://github.com/SteezyMode/bruiser-subhub/issues/65); timing salvage [issue #64](https://github.com/SteezyMode/bruiser-subhub/issues/64). The transient 12-cycle batch **does not auto-resume on power loss**; dashboard service itself is persistent independently. AI translation integration is next priority after dashboard verification.

## Nov 6, 13:59 JST — dashboard self-refresh and stale Bowfinger title fix

Owner confirmed browser dashboard is installed and viewed, but the *Current activity* display remained on `Bowfinger (1999)` while the **same live source worker** progressed in publication **8/29 at 13:53 → 14/29 at 13:59**. The web UI already auto-polls `GET /api/status` every 3s; source worker `last_item` remains from last `STAGING` because publisher emits `MEDIA:` and `RESULT:` events without updating `last_item`. Thus *Title* was stale even though publication progressed.

Fix committed in `tools/subhub_dashboard_server.py` and `tools/bruiser_live_view.py`: in a publish/recovery phase, derive real progress from latest phase log, display `Validating subtitle N/total (title not yet reported)` until the publisher's real `RESULT` title appears, then label `Last evaluated: ...`. Never claim the last staged title is the active publication. Web recent activity also includes `RESULT:` names. Regression tests added to both offline suites. Installer `tools/install_subhub_dashboard.sh` explicitly restarts **the independent dashboard service only** on reinstall; old `enable --now` would not update an already-active web process. Terminal viewer gets its own existing guarded viewer installer. Neither tool modifies the running 12-cycle publisher. **Both display fixes are committed in GitHub but NOT host verified until owner re-installs pinned revision and sends test output**. No need to reinstall MacBook SSH shortcut when updating web service.

## Nov 6 — TRICK false JA search eligibility (verified host audit)

Owner spotted Japanese series TRICK in Japanese-first sourcing, despite believing it had English and Japanese subtitles. Read-only audit of ja-intake-20261106T031627Z.json returned 43 text matches (one unrelated Pilot: Trick or Treat); TRICK S01E01–03 show actual AC3 audio tracks with ffprobe language=unknown and no embedded subtitle tracks in output, yet catalog status ready_ja_search. S01E01–02 queued JA search_ja; S01E03 had plausible JA search, staged work was held. Existing external sidecars are NOT yet verified. **Root cause:** catalog distinguishes missing MediaStreams from unknown audio tags, but erroneously accepted unknown-tagged original audio as JA-search eligible; coverage queue may also translate such a title when category is neither/english_only.

Repo-only fix committed, tracked in [issue #68](https://github.com/SteezyMode/bruiser-subhub/issues/68): catalog assigns review_audio_language_unverified, coverage queue assigns review_uncertain without JA/EN provider or AI, final JA search refuses unknown/JA audio even with old manifest. New offline tests test_subhub_audio_language_gate.py and test_bruiser_coverage_queue.py validate both unknown and known language cases. **Not host-deployed/tested yet; do not hot-patch active 12-cycle batch**. After job idle, run unit tests, update installed source scripts through a guarded process, refresh Jellyfin intake manifest and reconcile queue. Preserve prior staged files for forensic provenance. Long term automatically resolve untagged audio with verified language evidence; never guess from title to authorize spend or inference.

## Permanent developer instructions

- Start and inspect batches using the CLI, not dozens of bespoke scripts. Operator progress must be observable without interpreting raw logs.
- Use actual subtitle publications as delivery metrics, not plausible matches or API calls.
- Never change movie/TV quotas back to 75/25 or re-enable automatic source-only AI.
- Do not demand a new prompt to permit provider searches; only account limits, source identity and file QA are blockers.
- Advance the separate, real GPU fallback into an integrated stage next; do not treat "last resort" as "avoid entirely."
- As the system matures, build an optional Bruiser UI over `status --json`, without making one a prerequisite for running unattended batches.
