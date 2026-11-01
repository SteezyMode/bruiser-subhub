# Current state and next actions

**Last context refresh: 2026-11-01 (JST).** This is a GitHub handoff, not live server telemetry. Update after each meaningful engineering PR/deploy. Public repository: `SteezyMode/bruiser-subhub`.

## The project in one sentence

Daily-use, local-first subtitle translation for a personal media library: English source cues → natural Japanese Gemma translation → safely checkpointed, structurally validated `.ja.srt` sidecar; optional diagnostic HY sample.

## Source of truth

- GitHub `main`: versioned **development baseline** for SubHub 1.0, not proof of server installation state or a portable installer.
- Server: known pilot source at `~/bruiser-pilot/subhub1`, SQLite/runtime state at `~/bruiser-pilot/subhub1-state` (separate from Git).
- Earlier household worker: separate legacy `~/bruiser-pilot/subhub-household` state and translation memory. Do not delete/overwrite it.
- **User-reported live snapshot, 2026-11-01:** `status` showed **3/10 published** (Primate, 28 Years Later, Obsession); **3 with one exhausted/untranslated cue each** (Heretic 1608/1609, Birth/Rebirth 1130/1131, Hokum 1285/1286); The Descent 829/829 with `publish_hold`; Strange Darling still translating at 510/846; Whistle and A Nightmare on Elm Street queued. HY 0 across all titles. Hardware report: peak GPU 74°C, CPU 83°C, ~44.476 GPU Wh estimated. The user confirmed The Descent had earlier collaboratively authored Japanese subtitles predating this dashboard. **The actual stored `publish_hold` reason is not yet verified**; don't assume it comes from the editorial track without reading `jobs.last_error`. This is a historical snapshot, not a live feed.

## Verified engineering features in checked-in 1.0 source

- SQLite jobs/cues/events with WAL, per-cue translation checkpointing and bounded singleton retries.
- Import of legacy English source and prior Japanese cues by matching source hash (legacy queue is not edited).
- 12-cue Gemma calls, split/retry for missing cues, fallback singleton inference, no filler translation.
- Source hash/time/cue validation and verified English audio check before publishing, preservation of existing editorial track.
- `--publish` required for sidecar writes, per-run budget, temperature guards and single worker lock.
- Optional HY backtranslation **after** translation/publication. HY is diagnostic, never a gate.
- `export-review` writes a full, local EN/JA/HY CSV. `review_sampler.py` adds prioritized/contextual editorial JSON exports from SQLite without inference or DB changes.

Offline validation: **32 synthetic/mock tests passing locally**; GitHub Actions also ran the test suite. Neither establishes real-world Japanese translation quality.

## Next code change: editorial preservation and blocker diagnostics

The publisher previously archived and removed selected old Bruiser tracks, including `Bruiser Japanese Editorial v1`; it did not guard against an independent `.ja.srt` sidecar. A tested change merged in PR #3 makes publishing create-only, refuses duplicate Japanese/editorial sidecars, and never deletes previous subtitle tracks. A `diagnose_blocked.py` tool queries the live SQLite database **read-only** to report exhausted cues and stored job hold reasons; use `--show-text` for private cue-level context only. **Merged as PR #3**, commit `1f54506a` (2026-11-01); **not deployed** to OptiPlex. 32/32 synthetic offline tests passed locally and GitHub Actions passed on the PR branch.

## Critical limitations / unresolved questions

- Live subtitle quality, per-film finish status, translation speed and resource usage still require **actual server evidence**. Offline mocks prove mechanics only.
- `service.translation_call()` imports `bruiser_auto.py` and `service.hy_call()` imports `bruiser_hy_backtranslate_compare.py` from the older pilot. Standalone install is not yet possible.
- Initial library import still depends on a legacy JSON job list, Docker staging and hardcoded media roots.
- Translation context is primarily a short batch and manually approved memory; long-range film context, character voice and names need controlled evaluation.
- Heuristic review flags and HY output **are not semantic correctness scores**.
- No authenticated remote API or stable OptiPlex NOW integration yet; do not expose dashboard publicly.

## Next action sequence

1. Read-only inspect actual missing-cue errors for Heretic/Birth-Rebirth/Hokum and confirm The Descent's stored publication hold reason, without disturbing the active worker. Then inspect a completed film's subtitle cue alignment. **Do not restart a running worker.**
2. Export a local editorial packet with `review_sampler.py`, select 60 representative/problematic cues, evaluate source against Japanese with a human-language pass.
3. Save a tiny **synthetic** regression suite for structural bugs; keep real copyrighted film dialogue and private data outside Git.
4. Benchmark prompt/context modifications using a fixed, private set. Compare naturalness, meaning, names, negation, brevity, failures and throughput before changing the primary adapter.
5. Vendor/replace the legacy Gemma prompt adapter only once behavioral compatibility is established; then tackle independent source discovery and install/update/rollback scripts.
6. When known good and server idle, deploy a tested release using a backup/rollback procedure and update this file with the result.

## How to resume in a new chat

Open the GitHub repository, read `AGENTS.md`, `docs/CURRENT_STATE.md`, `docs/OPERATIONS.md`, inspect current open PRs, then work on the next translation-quality item. Do not spend the session redesigning the dashboard. Do not assume `main` changes are deployed. Ask for actual server logs/status only when it matters to the next irreversible action.
