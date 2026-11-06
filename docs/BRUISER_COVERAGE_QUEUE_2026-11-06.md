# Persistent Bruiser coverage queue — installation, behavior, and next steps
**Owner-approved priorities codified in [the canonical contract](BRUISER_SUBTITLE_POLICY_CANONICAL_2026-11-06.md).** This page is an **implementation handoff**, not another speculative plan or model benchmark.

## Baseline and state

A full English/Japanese inventory was verified on the OptiPlex on November 6 (12,386 files): 522 both EN+JA, 2,563 EN-only, 41 JA-only, 8,336 neither, 924 uncertain. The private source-of-truth manifest is:

`~/bruiser-pilot/coverage-audits/subtitle-matrix-20261106T015513Z.json`

The private persistent queue is:

`~/bruiser-pilot/coverage-queue/coverage.sqlite3`

This **does not require rescanning** the library, reviewing 40 test videos again, copying subtitles, or restarting PLaMo. The queue imports all 12,386 inventory rows, knows current language presence, reads previous Japanese OpenSubtitles search results and previously staged subtitle files **read-only**, and builds prioritized **per-title/per-language work items**.

It is currently a **planning and resumable-state database**, not an automatically connected provider executor or a model dispatcher. DO NOT say it already downloads/subtitles/translates on its own. In particular, the deployed Japanese source timer still uses its earlier search scheduler and quotas; connecting this queue to the source timer is the **explicit next implementation**.

## Firm action priority

1. `repair_existing_timing` — **highest** when a good existing English or Japanese subtitle has a known fixable alignment problem. Never overwrite the source; bounded verified correction and a separate create-only versioned output. **Must be flagged from evidence**; it is not inferred from a codec name.
2. `align_existing_staged_ja` — a previously downloaded Japanese subtitle is already on the host. Try safe synchronization / hold on untrusted timing; no download quota.
3. `download_saved_ja` — a previously saved, high-confidence OpenSubtitles candidate exists. Use matching release identity, download only when needed, then correct timing and QA.
4. `review_saved_ja` — identity uncertain. Clarify *before* download.
5. `search_ja` — conduct bounded new OpenSubtitles search for missing Japanese. **No global movie/TV ratio.** Aim for distinct usable new coverage per provider download; use the already scheduled post-09:00 JST daily allowance.
6. `validate_english_for_ja_fallback` or `recover_english_for_ja_fallback` — no trustworthy Japanese source in cooldown window: check/obtain correct English text, including repairing its timing. These are **handoffs for eventual GPU translation**, not dead ends.
7. `search_en` — for Japanese-audio originals missing English, or for third-language originals missing English; existing sources and timing repair apply equally. `check_audio_then_source_en` when original spoken language is unknown.
8. `review_uncertain` — do not pretend unlabeled/ambiguous subtitle presence is absent; resolve language before spending quota.

*Soft preference tie-breakers*: horror/drama/suspense movies and *The X-Files* / *It's Always Sunny in Philadelphia*. All other media, including American Dad, remain eligible, except already covered items which are correctly skipped. **GPU-based PLaMo translation is the final but expected heavy-use production route**, activated in a later separate controlled worker with checkpoints/thermal safeguards. The source-only service remains model-free until intentional integration.

## Installation on the actual host

Source: [`tools/bruiser_coverage_queue.py`](../tools/bruiser_coverage_queue.py) plus [guarded installer](../tools/install_bruiser_coverage_queue.sh).

On a remote Mac, use one pinned wrapper command:

```bash
ssh optiplex@100.121.156.34 'bash -s' <<'REMOTE'
set -euo pipefail
PIN="REPLACE_WITH_CURRENT_VERIFIED_40_CHARACTER_REPO_COMMIT"
SCRIPT="$(mktemp)"
trap 'rm -f "$SCRIPT"' EXIT
curl -fsSL --retry 3 \
  "https://raw.githubusercontent.com/SteezyMode/bruiser-subhub/$PIN/tools/install_bruiser_coverage_queue.sh" \
  -o "$SCRIPT"
bash -n "$SCRIPT"
bash "$SCRIPT" "$PIN"
REMOTE
```

The host wrapper checks that the matrix exists and is private, syntax-checks the new script, installs the queue controller with a prior-code backup and imports the existing matrix in a transaction. Re-running against the **same exact snapshot** yields `reconciled_existing_snapshot`, with **no duplicate tasks or snapshots**. The reconciliation intentionally reads newer saved OpenSubtitles search/staging evidence; when a concrete next action changes (e.g., `search_ja` → `download_saved_ja`), it resets the old hold to `pending`. Otherwise existing `held`, `candidate_found`, `ready_for_translation` states and notes survive. Tasks retire **only when a future actual media inventory establishes newly present subtitles**. This script does **NOT** modify any systemd service or timer, and does not run ffmpeg/ffprobe/provider/model jobs. **Until owner runs it, state is NOT DEPLOYED.**

## Host commands after installation

```bash
Q="$HOME/bruiser-pilot/coverage-queue-code/bruiser_coverage_queue.py"
python3 "$Q" status
python3 "$Q" next --limit 20
python3 "$Q" next --filter-action search_ja --limit 30
```

If an already existing subtitle is decent but has a documented adjustable delay/drift, **do not redownload**. Flag its corresponding Jellyfin media ID as a highest-priority timing repair:

```bash
python3 "$Q" flag-timing --jellyfin-id ACTUAL_JELLYFIN_ID \
  --language ja --reason 'Verified adjustable delay; preserve dialogue'
```

Same for English: `--language en`. Flagging makes a queue task; it does **not** modify media. The queue refuses a timing-repair flag if no subtitle for that language is known to exist. Read `next` to obtain task IDs and titles.

Record an investigation outcome (no video/media changes):

```bash
python3 "$Q" set-state --jellyfin-id ACTUAL_JELLYFIN_ID \
  --language ja --queue-state held --note 'Wrong video edition; cannot safely align'
```

Allowed progress states: `pending`, `held`, `candidate_found`, `ready_for_translation`. **No manually asserted `completed` state**: only real verified new playable subtitles in a later matrix may count as new coverage. The queue preserves historical snapshots and prior notes. This avoids the repeated discovery and rework that previously consumed time across chats.

## Next engineering change — do not substitute another audit

**Integrate the queue into the existing source-only Japanese cycle** ([tracked as GitHub issue #62](https://github.com/SteezyMode/bruiser-subhub/issues/62)). In order: pick `align_existing_staged_ja` → `download_saved_ja` → identity review → `search_ja` according to available allowance. Remove the historic 75% movie / 25% episode quotas from *both* discovery and staging after tests, replacing them with ordered eligible work and measured publish yield. Keep search-history cooldowns, strict media/episode identity, provider download quota, ffsubsync bounds, on-disk source QA and create-only publication. The 9:15 JST source timer is already deployed and should not be changed merely to integrate selection.

After sourcing/salvage, integrate a separate, explicitly enabled GPU fallback ([tracked as GitHub issue #63](https://github.com/SteezyMode/bruiser-subhub/issues/63)) pulling **verified** English sources for `validate_english_for_ja_fallback`; use the established PLaMo checkpoints and thermal policy, without interfering with gaming/streaming. GPU fallback is central to covering the library's long tail, even though it is the last acquisition method.

This implementation and these decisions must be read directly from GitHub at the start of a new chat. **Do not ask the owner to choose the order again.**
