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

The publisher previously archived and removed selected old Bruiser tracks, including `Bruiser Japanese Editorial v1`; it did not guard against an independent `.ja.srt` sidecar. A tested change merged in PR #3 makes publishing create-only, refuses duplicate Japanese/editorial sidecars, and never deletes previous subtitle tracks. A `diagnose_blocked.py` tool queries the live SQLite database **read-only** to report exhausted cues and stored job hold reasons; use `--show-text` for private cue-level context only. **Merged as PR #3**, commit `1f54506a` (2026-11-01); **PR #3 preservation behavior was part of the later deployed service.py batch fix; installed together on 2026-11-01.** 32/32 synthetic offline tests passed locally and GitHub Actions passed on the PR branch.

## November 1 engineering progress — merged, not deployed

- **PR #6 merged:** repaired the real malformed-SRT batch bug in `service.render_clip()`. SQLite row offsets accidentally emitted `job_id/cue_id/end_ms` instead of a valid SRT header/timing/English dialogue. Fixed to use named fields, local prompt IDs and mapping back to exact original IDs. This matches the previously reported `Malformed SRT block` retry logs. Offline mock-backed adapter tests pass, but the actual server's legacy parser and model output still require verification.
- **PR #7 merged:** added `tools/deploy_batch_fix.sh` and `tools/collect_review.sh` for one-command, guarded install and private English/Japanese quality sample. The installer checks both worker locks, verifies the installed legacy parser with real DB rows, refuses unexpected host code SHA, backs up service.py and does not touch checkpoints/media. Review collector is read-only and exports 80 cues.
- **37 synthetic tests** expected (32 preexisting + 3 adapter + 2 installer), CI passed for both PRs. Tests and GitHub merges are **not live deployment or semantic translation proof**.

**Next concrete action on the Mac mini:** from `~/Downloads/bruiser-subhub-repo`, `git pull --ff-only`, then `bash tools/collect_review.sh optiplex@HOST` to get real film EN/JA evidence, and `bash tools/deploy_batch_fix.sh optiplex@HOST` to install only if idle. If the guarded installer refuses, diagnose rather than bypass its checks. Upload private quality JSON to chat, never commit it to GitHub.

## Deployment update — confirmed from owner's 2026-11-01 Mac mini output

**Batch SRT fix deployed** to the actual OptiPlex `/home/optiplex/bruiser-pilot/subhub1/service.py`. Owner ran `bash tools/deploy_batch_fix.sh optiplex@HOST` after pulling `main`; full 37-test suite passed, real installed `bruiser_auto.parse_srt` accepted a 12-cue SQLite-derived batch, both worker locks were acquired, and the tool reported:
`INSTALLED service.py batch fix; backup: /home/optiplex/bruiser-pilot/subhub1/service.py.before-batchfix-20261101T124614Z`.
The command did **not** start a translation run, rewrite existing checkpoints, publish subtitles, or retranslate old output. This is a user-reported command log, not an independent SSH inspection. Live `main.py` and old Japanese checkpoints remain unchanged.

**Real editorial review sample collected privately on the Mac mini:** Primate 741/741 translated; 80 EN/JA cues sampled by `tools/collect_review.sh`; flags: negation 85, number 1, reading-speed 9, repeated-Japanese 16 (mechanical advisory counts over source cues, not verified errors). Private JSON was saved under `~/Downloads` on the Mac mini; **not attached to this chat yet, not reviewed linguistically, never commit to GitHub**.

**Immediate next step:** owner uploads that Primate editorial JSON to the private chat to assess translation fidelity, naturalness, compression, and context. Then compare the old singleton-heavy output with a properly batched result on a *fixed* subset, never overwriting editorial subtitles. Read-only inspect the three one-cue failures and Descent's stored hold reason using `diagnose_blocked.py` before attempting targeted recovery. HY optional.

## November 1 diagnostic: isolated cue failures confirmed

The owner supplied a read-only diagnose_blocked.py --show-text log. Four nearly finished movies each have a single exhausted cue, all after 5 singleton errors ("Invalid singleton fallback result"): Heretic (1608/1609), Birth/Rebirth (1130/1131), Hokum (1285/1286), Strange Darling (845/846). A fifth, Whistle, is 995/1233 with only one exhausted cue and 237 additional lines not attempted yet. Failed source cues were short letter labels, uppercase acronyms/names, a numeric countdown, and abbreviated speech. **Rejected model responses were not retained**, so script validation is a plausible cause, not proof.

The Descent is 829/829 but held because an **existing approved Bruiser Japanese sidecar differs**. The owner confirms a prior human-edited localization exists. It must not be overwritten; no legacy subtitle cleanup is authorized. The log was a user-supplied snapshot, not an independent server read.

**Recovery fix under review:** make the validator source-aware for exact 1–2-letter initials and numeral-only countdowns while rejecting untranslated sentences. Supply a private-manifest, source-hash-checked correction tool. Private source dialogue and repairs do not go in GitHub. The guarded installer upgrades only a byte-exact known source while both worker locks are free; recovery backs up SQLite, changes only listed cues, publishes fully completed titles if safe, and leaves remaining Whistle cues queued.

The owner has already collected a private 80-cue Primate EN/JA review packet on the Mac mini but has **not attached that packet to the chat**. Do not confuse the diagnostic log with the quality sample. Obtain the JSON for linguistic review.

## November 1 recovery tooling — PR #8 merged, not yet deployed

PR #8 merged as commit 116d64bc. GitHub Actions passed. Source-aware short-cue validator and guarded private-manifest repair tool are on main, but owner has **not yet run** the recovery command on the OptiPlex. The previously deployed malformed-SRT batch fix remains installed (see earlier note), and existing subtitle files are unaffected.

A **private JSON manifest** (not in GitHub) specifies six reviewed edits: five missing cues across Heretic, Birth/Rebirth, Hokum, Strange Darling, Whistle, plus correcting the existing Heretic "A." label. The exact English and Japanese dialogue belongs only in that private manifest. On execution, tools/repair_pilot.sh verifies the installed source blob, locks, new validator, current cue text, existing source SHA and prior Japanese, then backs up SQLite, applies only these edits, and safely publishes fully completed jobs. Whistle still has 237 additional untranslated cues; this recovery does not start a worker. The Descent must remain untouched. Real Primate EN/JA review file remains unprovided; translation quality is still unverified.

## 2026-11-01 22:01 JST — recovery attempted; guarded deployment aborted

Owner ran `bash tools/repair_pilot.sh ... ~/Downloads/bruiser-subhub-private-repairs-20261101.json`. The **42 offline tests passed**, but the **actual host update stopped safely before changing production**:

`SAFE ABORT: RuntimeError Live service.py differs from known installed version (896b245357a9e3b1d72e7be83cd5268108d8da20); refusing overwrite`

Root cause: `tools/deploy_validator.py` erroneously expected Git blob `691286...` (the pre-batch-fix version). The observed live SHA `896b245...` exactly matches `service.py` in main at commit `7cb3b8b` (the previously installed valid batch-fix version). **No live validator update, manual recovery, or publishing happened in the failed run.** A small follow-up PR fixes the expected hash, with a dedicated regression test. After CI and merge, retry the **same** Mac mini `git pull --ff-only` and `bash tools/repair_pilot.sh` command with the already downloaded private JSON. Do not reset checkpoints or modify the server by hand.

## Critical limitations / unresolved questions

- Live subtitle quality, per-film finish status, translation speed and resource usage still require **actual server evidence**. Offline mocks prove mechanics only.
- `service.translation_call()` imports `bruiser_auto.py` and `service.hy_call()` imports `bruiser_hy_backtranslate_compare.py` from the older pilot. Standalone install is not yet possible.
- Initial library import still depends on a legacy JSON job list, Docker staging and hardcoded media roots.
- Translation context is primarily a short batch and manually approved memory; long-range film context, character voice and names need controlled evaluation.
- Heuristic review flags and HY output **are not semantic correctness scores**.
- No authenticated remote API or stable OptiPlex NOW integration yet; do not expose dashboard publicly.

## Personal-use architecture review (2026-11-01)

Read [free/local workflow audit](PERSONAL_USE_AUDIT_2026-11-01.md) before implementing major changes. **The goal is best free EN→JA subtitles for one household**, not product differentiation. Compare the already-installed free alternatives and translation models using a private A/B benchmark before extending the custom engine. For 2026 tool research, Subtitle Edit 5.2, Sublarr, Lingarr and TranslateGemma are relevant; do not conflate tool availability with proven superior output. No production changes were made during this audit.

## Translation batch corruption found during real-code audit (2026-11-01)

`service.render_clip()` constructed a supposed batch SRT with `r[0],r[1],r[4]` from SQLite `cues` rows. Those indices mean **job_id, cue_id, end_ms**, not SRT cue/timing/dialogue. This directly matches the user's repeated `ValueError: Malformed SRT block` events in Strange Darling. The legacy batch parser failed, and the singleton fallback likely completed much of the movie without context. The new fix uses explicitly named columns, numbers prompt-local cues 1..N, and maps replies back to original cue IDs. Offline tests prove serializer+mapping; **real Ollama output quality not yet tested**. Do not assert the historical 3 published films have high-quality Japanese without editorial review. **Do not deploy until the current worker is idle**.

The project's actual user goal is [GOAL.md](../GOAL.md): good free local Japanese subs for almost 6 TB of family media, without maintenance overhead; dual subtitles already handled. SubHub is expendable if another free solution is better.

## Next action sequence

1. Read-only inspect actual missing-cue errors for Heretic/Birth-Rebirth/Hokum and confirm The Descent's stored publication hold reason, without disturbing the active worker. Then inspect a completed film's subtitle cue alignment. **Do not restart a running worker.**
2. Export a local editorial packet with `review_sampler.py`, select 60 representative/problematic cues, evaluate source against Japanese with a human-language pass.
3. Save a tiny **synthetic** regression suite for structural bugs; keep real copyrighted film dialogue and private data outside Git.
4. Benchmark prompt/context modifications using a fixed, private set. Compare naturalness, meaning, names, negation, brevity, failures and throughput before changing the primary adapter.
5. Vendor/replace the legacy Gemma prompt adapter only once behavioral compatibility is established; then tackle independent source discovery and install/update/rollback scripts.
6. When known good and server idle, deploy a tested release using a backup/rollback procedure and update this file with the result.

## How to resume in a new chat

Open the GitHub repository, read `AGENTS.md`, `docs/CURRENT_STATE.md`, `docs/OPERATIONS.md`, inspect current open PRs, then work on the next translation-quality item. Do not spend the session redesigning the dashboard. Do not assume `main` changes are deployed. Ask for actual server logs/status only when it matters to the next irreversible action.
