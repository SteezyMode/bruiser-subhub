# Bruiser SubHub — current owner operations (single reference)

**Maintained on `main`.** This is the canonical source of truth for deploying and operating the existing OptiPlex SubHub installation. Historical experiments and dated notes remain in Git but are **not** alternate installation or operation instructions. See [README](../README.md), [GOAL](../GOAL.md), and [correction-first rules](SUBHUB_CORRECTION_FIRST_POLICY_2026-11-10.md).

## P0 multi-provider gap — clarified 2026-11-13

**Not yet a guaranteed all-provider / best-of-all-subtitles pipeline.** The normal source-only cycle uses Sublarr's combined provider search but its saved provider health receipts inspect only **OpenSubtitles and SubDL**. A healthy provider is **not** proof it returned a result for an individual movie/episode. The daily cycle stages OpenSubtitles first, then SubDL, and can publish the first subtitle that passes trusted sync/QA without comparing every viable release across all enabled Japanese-capable providers. The separate owner-triggered Jellyfin batch can use Jellyfin's `provider any` path before Sublarr fallback; deep recovery only exhausts saved OpenSubtitles/SubDL evidence. Neither proves every enabled provider was individually checked for every title.

**Requirement:** collect all usable Japanese-provider candidates through existing providers and adapters, record per-item/per-provider confirmed participation and quotas, rank viable releases against the actual video, repair and synchronize, then choose the **best verified** Japanese sidecar before create-only publication. Rejection of one release must not halt the movie or batch; temporary quota is a **deferred** provider, not a negative subtitle search. PLaMO is a last-resort stage only after supported source routes and alternatives are genuinely exhausted. NEW media fully automatic; BACKLOG remains owner-selected.

**Owner's live provider audit (2026-11-13, read-only):** 28 enabled Sublarr provider entries; 18 initialized with health gate `ok`, 5 `not_initialised`, and 5 `no_pool_key`. Some healthy providers may not offer Japanese or relevant movies/TV. Of saved records currently marked missing JA: `none=3,258`, `review=177`, `plausible=72`, `partial=37`, and one `in_progress`. **3,043 of the 3,258 `none` records lack evidence both tracked core providers were healthy**; this is an incomplete/older health receipt, not proof none was actually contacted, and not source exhaustion. The saved search DB retained candidate releases beyond our two-stage adapters: OpenSubtitles 322, SubF2M 41, SubDL 28, AnimeTosho 26, Kitsunekko 2, Gestdown 1; different provider candidates are not unique movies. This confirms the gap from real host data, not a speculation. Online Sublarr docs describe a provider manager with search, scoring and download; validate the **installed host's** API and reuse its generic download mechanism rather than writing bespoke downloaders for all sources. Do not bulk rerun the 3,043 before trustworthy receipts and quotas exist. The issue #101 comment records the exact provider health breakdown. No source-code correction to support other providers has been installed yet.

**Track as [issue #101](https://github.com/SteezyMode/bruiser-subhub/issues/101)** (also [#89](https://github.com/SteezyMode/bruiser-subhub/issues/89) for source recall and [#90](https://github.com/SteezyMode/bruiser-subhub/issues/90) for new-media/backlog behavior). Do not mistake the cached SubDL structural pass rate (14 ZIPs inspected on Nov 13) for overall Japanese subtitle coverage or proof of actual all-provider participation. **This is a documented unresolved product gap, not an installed fix.**

**Live API safety finding (2026-11-13, Sublarr 1.20.1):** Host OpenAPI lists combined `/providers/search`, interactive wanted/episode `search-providers`, and `download-specific`. At upstream 1.20.1, combined search returns at most **50** releases per request (even if `total` is larger). The `download-specific` API writes the chosen subtitle to a video-side path and may trigger further processing; **never call it for private SubHub staging on production media**. Sublarr's internal `ProviderManager.download(SubtitleResult)` instead returns provider subtitle **bytes** without an output-library write. Reusing that requires a guarded generic stage adapter **and** generalization of SubHub's `ja_first_stage_timing_audit.py` and `ja_first_publish_staged.py`, which currently accept only OpenSubtitles, SubDL and Jellyfin stage names/provenance. The existing publisher also stops at the first verified ALASS/ffsubsync candidate instead of comparing every suitable, verified track. This is a pending coordinated engineering change, **not deployed**. Exact v1.20.1 source and acceptance criteria are recorded in [issue #101](https://github.com/SteezyMode/bruiser-subhub/issues/101). Do not silently bypass no-overwrite, title identity, timing or Japanese-text QA in order to support new providers.

## Generic Sublarr provider private-stage pilot (reviewed code, host install pending)

The candidate-only path in `tools/ja_first_stage_sublarr.py` reuses the **actual Sublarr 1.20.1 `ProviderManager.search(...,early_exit=False)` + `ProviderManager.download(result)`** from inside the running Sublarr container for **saved, strictly identity-matching Japanese SRT candidates** from other providers (SubF2M, AnimeTosho etc.). It does not invoke the write-capable `download-specific` API, write into Jellyfin folders, start PLaMO or run publication. The host caps and hashes the returned bytes, validates Japanese SRT content/clock preservation, and creates a `0600` private stage entry with actual provider identity, original saved candidate metadata and movie/episode identity. The shared timing auditor and publisher now recognize precisely one new `sublarr` stage class and recheck its saved-release provenance before any existing ALASS/ffsubsync/QA/publisher action. Existing three stage classes retain their original rules. The provider download ledger recognizes individual provider names only on this approved route.

**Find eligible saved candidates from the host without API requests or downloads:**

```bash
ssh optiplex@100.121.156.34 \
 'python3 -B -u ~/bruiser-pilot/subhub-control/ja_first_stage_sublarr.py --list-candidates'
```

**Inspect a specific exact media item, no API call:**

```bash
ssh optiplex@100.121.156.34 \
 'python3 -B -u ~/bruiser-pilot/subhub-control/ja_first_stage_sublarr.py --jellyfin-id <32-hex-jellyfin-item-id>'
```

**Owner-initiated bounded acquisition only after reviewing the candidate and ensuring no workers run:**

```bash
ssh optiplex@100.121.156.34 \
 'python3 -B -u ~/bruiser-pilot/subhub-control/ja_first_stage_sublarr.py --jellyfin-id <32-hex-jellyfin-item-id> --max-attempts 1 --apply'
```

This **stages only**; a normal trusted publisher would still need to validate timing and create the JA sidecar in a **separate explicit step**. Do not start the source cycle or turn on scheduled retries as part of this test. Saved Search DB may contain candidates from non-core providers, but source availability can expire; candidate re-search failures are not proof subtitles don't exist.

**Not yet implemented:** a verified per-provider search-participation matrix for all enabled JA-capable sources; newly discovered provider candidate preservation into the search DB; a global best-verified-candidate choice after synchronization; routine use by new-arrival or backlog pipelines; host proof of actual non-core subtitle publication. Keep [P0 issue #101](https://github.com/SteezyMode/bruiser-subhub/issues/101) open, and do not label this a complete all-provider solution.

**Host-verified install (2026-11-13):** Commit `78237804566f283e92c851d34a46393eb04917d5` successfully installed with `--install-only`; dashboard write probe and /api/status passed. Backup: `/home/optiplex/bruiser-pilot/subhub-control/.ja-library-source-backup-z2cpyj_w`. Generic staging **read-only** census: only 3 ready-to-source titles, 6 identity/format-eligible non-core saved releases (AnimeTosho 5, Kitsunekko 1): *Kiki's Delivery Service*, *The Tale of the Princess Kaguya*, *Whisper of the Heart*. Previous saved results included many more hits from SubF2M and AnimeTosho, so a **read-only exclusion-cause audit** is needed before spending provider quota or widening filters. These three were originally Japanese-language films: validate their actual stored audio and subtitles before selecting a test. **No generic Sublarr download, staging, synchronization or publication was performed or confirmed**. See [issue #101](https://github.com/SteezyMode/bruiser-subhub/issues/101). The issue remains open; all-provider end-to-end sourcing is not yet deployed.

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

## 2026-11-13: Confirmed host installation and first successful forced-track recovery

The owner ran the **pinned single installer** for `main` commit `888945ff4c256d59cf97b1012c52077d80a951af` with `--install-only` on the OptiPlex. The guarded installer successfully installed the changed `ja_first_stage_subdl.py` and newly managed `subhub_saved_movie_recovery.py`, restarted the existing dashboard, and passed both the sandbox private-job write probe and `/api/status` check. Host installer backup: `/home/optiplex/bruiser-pilot/subhub-control/.ja-library-source-backup-wkxz6h0c`. It did **not** start any source service, refresh the catalog, reset quotas, or trigger translation.

The follow-up host recovery used `--apply --skip-title "The Master" --max-attempts 10 --max-per-title 3`. It inspected 77 saved review/plausible movie results, attempted 7 previously saved SubDL candidates, and **published TWO new Japanese subtitle sidecars**: **Black Christmas** (Jellyfin ID `e3b08936647e8a68efdc44fe1fa67ea2`) and **Prey** (Jellyfin ID `9f7cc3bac3716c023a4d6e3620cc2b8f`). They were privately staged from the cached SubDL ZIPs, then accepted by the **existing normal publisher**, which printed `DEEP_SOURCE_PUBLISHED` for both. No fresh provider searches, quota blocks, or PLaMO work occurred. New subtitle sidecars are real; **Jellyfin playback and manual beginning/middle/end dialogue timing remain unverified**.

The same run held five releases: *A Nightmare on Elm Street 3*, *The Dream Child*, *Double Blind*, *The Rule of Jenny Pen*, and *We Are Still Here*. The first, second, and fifth report `staged_srt_block_malformed` from cached ZIPs. *Double Blind* and *The Rule of Jenny Pen* report `unparseable_srt_timestamp` at the strict publication validation stage despite earlier successful structural parsing. **Do not claim those five are recoverable or relax content/timing checks without comparing the exact parsed timestamp representation and strict validator.** One more movie was already covered at runtime and skipped. This is a verified operational correction, not seven successful releases.

The owner's entire point is functional playback: the measured result is **2 newly published Japanese subtitles**, not seven attempted stages, and the repaired selector is now part of the single standard installer.

## Remaining investigation; criteria for success

1. After a guarded `main` install, rerun the saved-candidate recovery **without new searches** and verify whether *Black Christmas* and *Prey* can stage from their cached ZIPs; **still require ALASS/ffsubsync and trusted publication checks**.
2. For *The Rule of Jenny Pen* and *Double Blind*, inspect the later Japanese-density/runtime checks and decoding path. Their structural inspection passed but does not establish they are usable Japanese subtitles.
3. Diagnose exact malformed SRT blocks for the three 1-arrow-mismatch films without discarding or fabricating dialogue.
4. Investigate the **221 missing** in-scope Drama/Horror movies and 42 coverage-queue holds; don't blindly reset 30-day search history or consume quota re-querying all 221.
5. Review newly published tracks in Jellyfin; a pass from timing/structural checks isn't a subjective translation-quality grade or verified playback.

## General-purpose repair, retry, and measurement policy (2026-11-13)

**Normal case: do not hold an entire title because one candidate is unusable.** The source-only cycle must treat a bad SRT as a **rejected release**, try other saved identity-matching candidates within the bounded provider allowance, and continue to the next media item. A title remains **pending Japanese sourcing** until actual Japanese sidecar/audio coverage is verified or *all* viable acquisition paths are reasonably exhausted. Quota/cooldown/network errors mean **retry later**; they are not a negative result. A malformed source cannot be made publishable by loosening the dialogue identity, density, sync/timing, no-overwrite, or provenance gates.

**PLaMO is a later processing state, not the only "hold".** It becomes a legitimate next action only after sufficient Japanese provider/search/alternate-release evidence and a matching English source suitable for synchronization. An old "none" search, 429, failed container, unparseable SRT, or one failed release is not proof of source exhaustion and should never automatically force PLaMO. Truly unreadable/partial video, ambiguous movie identity, unsafe or changed staging media, and unverified matching English source may require an exceptional **needs-attention** state rather than a fabricated subtitle or endless loop; these must not stall unrelated titles.

**Reusable code, not a one-off success script.** General SubDL ZIP forced-track handling, SRT timestamp normalization, multiple saved-release fallthrough, and deterministic bad-ZIP cache invalidation all belong to the **existing installed source workers** (not merely `subhub_saved_movie_recovery.py`). No independent cron/service, separate package, or hand-copied host patch. A cached structurally bad ZIP is skipped on subsequent runs while its bytes, target-video identity and validator implementation are unchanged; the next validation-code change invalidates that specific failure receipt automatically. The normal daily batch prints stable release failure reasons separately from *title-level coverage*.

**Read-only wide-library audit (no provider quota, no file writes):**

```bash
ssh optiplex@100.121.156.34 \
  'python3 -B -u ~/bruiser-pilot/subhub-control/ja_first_stage_subdl_batch.py --audit-cached --scope all --audit-limit 2000'
```

For Drama/Horror only, use `--scope horror-drama-folders`. The report distinguishes missing titles, cached provider releases available, ZIPs inspected, subtitle content structurally valid, known invalid formats and uncovered errors. **Structural/content passing is not a published subtitle, good timing, good translation or Jellyfin playback.** Measure actual coverage independently with the existing dashboard counts; never compute a supposed 80% title failure rate using a denominator of repeated skipped candidates or quota-limited searches. No broad live API scan is authorized by this audit.

**Regression gates:** cached full Japanese SRT paired with forced tracks, explicit year mismatch, other distinct editions, full Japanese text density, malformed timestamps, canonical Unicode spacing and clock fractions, genuinely missing timestamps, 3-candidate same-title fallback, memoized bad cached ZIP skipped while later good candidates remain eligible, read-only audit invariants. Focused tests must pass on GitHub before merge, and `main` must be installed via the guarded pinned installer for behavior to change on OptiPlex. Until then, host still runs the prior code.

## Development and documentation discipline

- One `main` branch as the install source. PRs are intermediate review surfaces, not separate installed versions.
- Keep **this file current** with each relevant correction: changed modules, root cause, host evidence, test result, install commit, and what is still unresolved. Record code-merged vs actually host-installed vs personally playback-verified distinctly.
- Test concrete regressions and preserve fail-closed media, search, subtitle identity, origin, quota, duration and no-overwrite checks. Existing unrelated model-card/legacy translation tests sometimes fail in full CI; do not claim green full-suite status if they still fail.
- No extra `.deb` packaging project or new dashboard controls just to deliver a Python fix; one installer suffices.
