# Bruiser SubHub — current owner operations (single reference)

**Maintained on `main`.** This is the canonical source of truth for deploying and operating the existing OptiPlex SubHub installation. Historical experiments and dated notes remain in Git but are **not** alternate installation or operation instructions. See [README](../README.md), [GOAL](../GOAL.md), and [correction-first rules](SUBHUB_CORRECTION_FIRST_POLICY_2026-11-10.md).

## What is installed, and where

- **Bruiser SubHub** is an existing collection of Python scripts, an owner dashboard, systemd user services, Jellyfin/Sublarr adapters and local state on **the OptiPlex**. **It is not currently distributed as a `.deb`.**
- **OptiPlex NOW / Bruiser client** is a **separate** Linux `.deb` application; updating its package does **not** update SubHub, and updating SubHub does **not** change the client package.
- Source-only SubHub modules: `~/bruiser-pilot/subhub-control/`.
- Dashboard modules: `~/.local/share/bruiser-subhub-dashboard/`, existing dashboard HTTP service on port 17876.
- Private catalog/search/stage state and provider caches: `~/bruiser-pilot/ja-first-inventory/`. Never commit media paths, secrets, logs, subtitles or private state to GitHub.
- Live human-authored Japanese subtitle acquisition uses existing OpenSubtitles/SubDL credentials and daily limits in Sublarr, caches verified release evidence, stages privately, synchronizes via ALASS or ffsubsync when defensible, validates, and publishes **create-only** Japanese sidecars beside the source video. Failed validation is a **hold**, not a published subtitle.
- **PLaMO is independent and last resort**; source-only cycles and saved-candidate recovery never invoke it. Existing backlog needs owner-triggered work, while newly added media may use its separately configured automatic path.

## One installation/update path — pinned `main`

**All supported host-side code corrections go through the existing `tools/install_global_ja_sourcing.py` installer.** It updates source scripts (including `subhub_saved_movie_recovery.py`) and dashboard modules as one tested revision, backs up replaced files, checks active units, and validates the live dashboard. Do **not** patch standalone files manually or use an unpinned download in normal operation.

From a Mac/Linux client with Tailscale/SSH access to the OptiPlex, use the **40-character main-branch commit SHA** you intend to install:

```bash
ssh -T optiplex@100.121.156.34 'bash -s' <<'REMOTE'
set -euo pipefail
PIN="<approved-40-character-main-sha>"
tmp=$(mktemp)
trap 'rm -f "$tmp"' EXIT
curl -fsSL \
  "https://raw.githubusercontent.com/SteezyMode/bruiser-subhub/$PIN/tools/install_global_ja_sourcing.py" \
  -o "$tmp"
python3 -B "$tmp" --commit "$PIN" --install-only
REMOTE
```

Use **`--install-only`** for an ordinary update. It replaces managed code without starting a sourcing pass, resetting provider budgets or rewriting catalog/queue state. It refuses code replacement if a managed source/translation worker is busy. Dashboard checks and an automatic local backup remain mandatory. Do not add `--start` unless the owner explicitly wants the timer enabled and a sourcing pass started. The installer prints the exact backup directory after success; preserve the path for rollback. `git main` and "installed on host" are separate states until the installer succeeds and the host verifies behavior.

After installation:

```bash
ssh optiplex@100.121.156.34 \
 'python3 -B ~/bruiser-pilot/subhub-control/ja_first_autofill.py status'
```

**Successful install is not a promise that any subtitles published.** Confirm actual sidecars and playback separately.

## Simple saved Drama/Horror recovery

**Read-only first**, without searching providers, downloading subtitles, running PLaMO or publishing:

```bash
ssh optiplex@100.121.156.34 \
 'python3 -B -u ~/bruiser-pilot/subhub-control/subhub_saved_movie_recovery.py --skip-title "The Master"'
```

To process **existing Japanese candidate IDs only**, with a strict cap, on the idle host:

```bash
ssh optiplex@100.121.156.34 \
 'python3 -B -u ~/bruiser-pilot/subhub-control/subhub_saved_movie_recovery.py --apply --skip-title "The Master" --max-attempts 25 --max-per-title 3'
```

The owner skip is optional, not a hardcoded exception; The Master's known video is unreadable (`ffprobe`: MP4 `moov atom not found`). The tool independently skips unreadable media, previously staged IDs, remembered failed OpenSubtitles downloads, wrong-duration stages and already-covered movies. It uses cached SubDL ZIP bytes where available. A new stage invokes the existing publication/sync checks. OpenSubtitles and SubDL quota failures stop attempts for that provider only. **No automatic retry of failed old staged groups; no new searches; no PLaMO; no overwrite.** Outcome lines include `New Japanese subtitle files`, attempted candidates and held reasons.

For broad discovery or selected TV episodes, use the existing dashboard or source-only controller, not this saved-movie utility.

## 2026-11-12–13: Verified on-host evidence and corrections

**Source-scope & dashboard deployment.** `main` revision `a289a0ce8e3c7f8118812a644137c7cda2fca72a` was installed on the OptiPlex on Nov 12 via the guarded installer; dashboard status/write probe passed. That code unified Action/Horror/Drama groupings across drives, added virtual genre browsing and Select all missing across pages, and reused saved failed-search history instead of immediately repeating it. Current scope still needs owner-level Jellyfin UI verification.

**Actual Drama/Horror run.** A host source-only pass on Nov 12 searched **zero** new movies, found previously saved candidate entries, and published exactly **one** Japanese subtitle: *The Beasts* (2022), with ALASS alignment. The new sidecar was created under the existing Drama/Suspense movie root. OpenSubtitles quota was previously exhausted; SubDL staged that single usable track. The catalog and saved history after investigation showed: 437 in-scope movies, **221 still missing Japanese**, all 221 already searched; saved search outcomes: 135 `none`, 58 `review`, 19 `plausible`, 9 `partial`; 42 were excluded by coverage-queue state. **Zero new searches is a selector/history state, not proof Japanese doesn't exist.**

**After quota reset.** The only OpenSubtitles candidate selected was *The Master*; it was held **before download** because the 1.31 GB MP4 returns `moov atom not found` to `ffprobe`. Do not delete, attempt to repair, or repeatedly retry that movie unless the owner chooses to replace it.

**Saved-candidate recovery.** `main` PR #98 added the bounded recovery utility. On-host run checked 77 movies with `review` or `plausible` results: 38 already-staged release entries, 3 known duration mismatch entries, 3 known invalid OpenSubtitles downloads; 8 remaining candidate releases across 8 movies; 1 was already covered; **7 SubDL candidate stages held**, **0 new sidecars published**, **no new provider searches** and **no quota reached**.

**Cached SubDL ZIP inspection (read-only):**
- *Black Christmas*: full Japanese file **934** cues and separate forced-only **26** cues. Both structurally parse. *Prey*: full Japanese **398** cues plus forced-only **4** cues. Both previously rejected because the archive selector required a year on the SRT filename when the ZIP had multiple files. This is a **selection defect**, not evidence the forced file is suitable. Correct the selector to distinguish the single full track from the labelled forced track while rejecting year conflicts beyond the established ±1 festival/theatrical tolerance and ambiguous multiple full tracks.
- *The Rule of Jenny Pen*: **1,074** recognized cues and structurally parsed; *Double Blind*: **1,246**. Their earlier stage holds are **not** explained by missing timestamp arrows; a later validation or incorrect decode remains to be established from new host output. Do not claim publication.
- *Nightmare on Elm Street 3*: 908 arrows / 907 recognizable timestamps; *The Dream Child*: 814 / 813; *We Are Still Here*: 645 / 644. Existing parser rejects a malformed block. **Do not silently drop unknown dialogue or invent a timestamp** to force publication. Any repair requires proof that all original timed dialogue survives, then the normal sync/QA gate.

**Implemented code correction (this change):** `ja_first_stage_subdl.py` now filters explicitly marked forced/signs SRT members *before* counting viable full-dialogue options, accepts a single movie-title-matching full SRT without embedded year when its ZIP companion is forced-only, and continues rejecting explicit year conflicts larger than one year, multiple ambiguous unforced releases, and content failing the Japanese-density/timing validation. Report the first real content-validation error when no file passes instead of prioritizing fallback-decoding noise. It uses the existing ZIP cache and standard publisher; **no changes to media, credentials, DB schema, or automatic AI behavior**. The existing installer now includes the prior saved-candidate recovery utility, eliminating a separate manual script download for future upgrades. **Host outcome pending reinstall and rerun; don't count these as newly published yet.**

## Remaining investigation; criteria for success

1. After a guarded `main` install, rerun the saved-candidate recovery **without new searches** and verify whether *Black Christmas* and *Prey* can stage from their cached ZIPs; **still require ALASS/ffsubsync and trusted publication checks**.
2. For *The Rule of Jenny Pen* and *Double Blind*, inspect the later Japanese-density/runtime checks and decoding path. Their structural inspection passed but does not establish they are usable Japanese subtitles.
3. Diagnose exact malformed SRT blocks for the three 1-arrow-mismatch films without discarding or fabricating dialogue.
4. Investigate the **221 missing** in-scope Drama/Horror movies and 42 coverage-queue holds; don't blindly reset 30-day search history or consume quota re-querying all 221.
5. Review newly published tracks in Jellyfin; a pass from timing/structural checks isn't a subjective translation-quality grade or verified playback.

## Development and documentation discipline

- One `main` branch as the install source. PRs are intermediate review surfaces, not separate installed versions.
- Keep **this file current** with each relevant correction: changed modules, root cause, host evidence, test result, install commit, and what is still unresolved. Record code-merged vs actually host-installed vs personally playback-verified distinctly.
- Test concrete regressions and preserve fail-closed media, search, subtitle identity, origin, quota, duration and no-overwrite checks. Existing unrelated model-card/legacy translation tests sometimes fail in full CI; do not claim green full-suite status if they still fail.
- No extra `.deb` packaging project or new dashboard controls just to deliver a Python fix; one installer suffices.
