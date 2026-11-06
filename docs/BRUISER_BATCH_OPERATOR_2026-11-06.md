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

## Permanent developer instructions

- Start and inspect batches using the CLI, not dozens of bespoke scripts. Operator progress must be observable without interpreting raw logs.
- Use actual subtitle publications as delivery metrics, not plausible matches or API calls.
- Never change movie/TV quotas back to 75/25 or re-enable automatic source-only AI.
- Do not demand a new prompt to permit provider searches; only account limits, source identity and file QA are blockers.
- Advance the separate, real GPU fallback into an integrated stage next; do not treat "last resort" as "avoid entirely."
- As the system matures, build an optional Bruiser UI over `status --json`, without making one a prerequisite for running unattended batches.
