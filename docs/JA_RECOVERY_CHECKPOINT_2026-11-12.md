# Japanese subtitle recovery checkpoint — 2026-11-12

**Purpose:** owner-verified results and next work for the household Jellyfin Japanese subtitle pipeline. This is a factual checkpoint, not a promise that automated synchronization is always right.

**Evidence:** owner-pasted OptiPlex output from `ja_first_publish_queue.py --apply` for three exact Jellyfin IDs. Each emitted `PUBLISHED:`, a final SHA-256, and `BRUISER_PUBLISH_ITEM: ... "result":"published"`. These are actual sidecars, **not** merely dry-run successes. Neither video nor previously present Japanese subtitles were overwritten; all three writes were create-only. No provider download or translation ran during these three commands.

## Confirmed newly published

| Film (year) | Exact Jellyfin ID | Saved subtitle ID | Structural repair | Engine / correction | ALASS reference | Final sidecar SHA-256 |
| --- | --- | --- | --- | --- | --- | --- |
| **Smile 2 (2024)** | `16ac71e85c3fe012b9aae7ffeba3229c` | `10759142` | One 1.627-second adjacent reversal; swap complete timestamp+text pairs at original cues 144/145. **1,202/1,202** Japanese cues retained. | ALASS **+0.008s**, uniform | `video_audio` | `22d36305854f7b62da217e66f7ab4c2a0535c5e2010e8f0bd4939ebd2b077cc9` |
| **The Autopsy of Jane Doe (2016)** | `23472ea0b137c0dc6ce4f4be1bdf7ce1` | `1186756` | **600** timed slots → **589** text-bearing cues, removed **11 empty** entries, all Japanese dialogue retained. | ALASS **+1.212s**, uniform | `video_audio` | `70afb111c8a9b537fd0036b92dd790f2eef9a04f6a31895666ebaba099e7a519` |
| **Spirited Away (2001)** | `a487ec22c37efbe5cc03bd50a63cbf44` | `4793285` | Removed exactly **three U+001A** control characters. **1,130/1,130** Japanese cues retained. | ALASS **+0.580s to +0.869s**, bounded | `same_video_embedded_english` | `6a07ffe562343d6ae66d30d72a5950b85a6efdf58e353bf28be7267dd48b9774` |

### Exact published locations

- **Smile 2:** `/mnt/2TB/Plex Expansion/Movies/Horror/Smile 2 (2024) [1080p] [WEBRip] [5.1] [YTS.MX]/Smile.2.2024.1080p.WEBRip.x264.AAC5.1-[YTS.MX].ja.srt`
- **The Autopsy of Jane Doe:** `/mnt/BigDisk/Video/Movies/Horror/The.Autopsy.of.Jane.Doe.2016.HDRip.XViD-ETRG/The.Autopsy.of.Jane.Doe.2016.HDRip.XViD-ETRG.ja.srt`
- **Spirited Away:** `/mnt/BigDisk/Video/Movies/Animated/[AnimeRG] Studio Ghibli Film Collection (Movies From 1984-2016) [1080p] [BD] [Multi-Audio] [Multi-Sub] [HEVC] [x265] [Batch] [pseudo]/Studio Ghibli/[AnimeRG] Spirited Away (2001) Sen and Chihiro's Spiriting Away [MULTI-AUDIO] [1080p] [x265] [pseudo].ja.srt`

**Important QA distinction:** `SOURCED_GROSS_QA: pass` and a successful ALASS reference are *not* a Japanese translation editorial review or actual playback audit. Playback in Jellyfin has **not** been reverified in the supplied logs. Refresh library/track selection if necessary and watch representative passages before claiming perfect dialogue synchronization.

## General-purpose pipeline fixes — locked into code

- `tools/ja_first_srt_normalize.py` creates a **working copy** while retaining original stage bytes/SHA: strips nontext control bytes, removes genuinely empty timed entries, detects mismatched timestamp counts, recognizes a *strictly identified technical first-cue release timing note*, and permits at most **one adjacent ≤2.0s start-order reversal** by swapping whole cue records, only when resulting chronology is valid. Cannot drop real dialogue, silently reorder a film, or infer a correct edit from duration alone.
- Standard `ja_first_alass.prepare()` and `ja_first_ffsubsync.prepare()` use the same normalization before their unchanged health/no-clobber/timing gates. Original provenance stays available; derived output is recorded as a correction, not silently called an original.
- `test_ja_first_alass.py` pins the complete **1,202-cue** *Smile 2*-shaped regression (1.627s adjacent reversal and +8ms correction) through ordinary ALASS preparation; separate tests cover the ffsubsync path, metadata note exclusion, changed dialogue, nonadjacent clock inversions, and rejected unsafe repairs.
- Follow-up GitHub changes (PR #91 after the live host install) also normalize the older **trusted-embedded constant-offset fallback** so the release note cannot be a blocker in that third path; a separate regression covers it. The optional `tools/subhub_opening_note_audit.py` inventories other opening release annotations in **saved stages only**; audit has not been run on owner host yet. Translator credits are *not* categorically deleted.

**Deployment distinction:** Host install-only log confirms `6098d124e7f9738fbaaec4177ca30a524d17d5d2` installed (dashboard smoke tests passed); these three publications came through that host version. The later PR #91 fallback consistency and opening-note audit commits are **GitHub-only** until a subsequent owner install is confirmed. Original preinstall backup: `/home/optiplex/bruiser-pilot/subhub-control/.ja-library-source-backup-165p56n0`. Existing stopped source/translation jobs were **not** started.

## Remaining staged holds

- **The Golden Glove (2019)**, JID `b22c78a89691b6643488fcb982776c6d`, stage `5326151`: one empty final cue, **805** nonempty cues including an opening technical note `「1：50：50の動画に合わせていますが、若干のズレあり」`. After excluding that annotation from a private alignment copy, ffsubsync retained **804/804** spoken dialogue cues, global timing medians approx **−20.09 / −21.41 / −23.43s** by thirds, **5.99s correction spread** exceeded current 5s acceptance gate. ALASS rejected extreme shifts; no trusted same-video English reference established. **Not published.** Do not loosen threshold or assert that a nominal 50-second edition difference proves a missing scene.
- **Martyrs (2008)**, JID `307172e4bcac46d1222f7e763c14efc3`, stage IDs `10592630` and `8539468`: **identical SHA/source bytes** across two provider IDs; ALASS extreme-shift hold, ffsubsync variation hold, and no trusted independent EN reference. **Not published**. Try a genuinely different source/reference, not another identical download.
- **Castle in the Sky (1986)**, JID `1cc1aa59ea86139a6bbe28c252b7b2fe`, stage `9146157`: subtitle ends about **9,195.77s** vs video duration **7,474.77s** and opens with a presenter message; probable mismatched broadcast/release. Held, not a safe constant offset.

## Next batch, then maintenance

The prior **191-film source-failure audit** reconstructed four categories in the *saved snapshot*: **118** with only provider-rejected results, **37** without saved credible Japanese results, **30** with credible-looking Japanese provider candidates **not staged**, and **6** with staged records but unpublished. **These figures are historical, not a recalculated live backlog**; publishing the three above changes real coverage, and all new scans must distinguish snapshots from current state.

1. **Prioritize the 30 unstaged candidates as one batch**. Determine whether stageability was blocked by release identity, provider/quotas, malformed formats, download handling or a code gate. Do not infer that all 30 are good subtitles and do not spend provider quota simply to rediscover cached results. Extend generic staging path where justified and measure `staged → aligned → published` outcomes.
2. Then inspect the 118 rejected-provider group; distinguish real wrong-title hits from recoverable candidate-selection logic. The 37 with no credible saved result may require new provider search or English→Japanese fallback after actual source exhaustion.
3. **Code cleanup follows working coverage recovery**, with scope in GitHub issue rather than another bespoke overhaul: consolidate three normalizing/sync entry paths, provenance and QC, remove redundant experiments once superseded, reduce misleading or duplicated statuses, test against representative real saved media, and keep ordinary UI simple with technical detail collapsed. Keep existing Sublarr where it solves the problem; no compulsory Ollama, new model or startup-style framework.

**Links:** [PR #91](https://github.com/SteezyMode/bruiser-subhub/pull/91) · [existing candidate recovery issue #64](https://github.com/SteezyMode/bruiser-subhub/issues/64) · [search recall issue #89](https://github.com/SteezyMode/bruiser-subhub/issues/89).


## Follow-up: two more confirmed published + SubDL content rejection (Nov 12)

Owner installed pinned revision **6695f9d39b09d795d053091aa2be81fbcaf3e47a** using `--install-only`, with backup `/home/optiplex/bruiser-pilot/subhub-control/.ja-library-source-backup-qvay0o3b`. Dashboard passed live health checks, workers stayed stopped.

- **Late Night with the Devil (2024), confirmed PUBLISHED**: Jellyfin `c56f7de05115e6162920b9295e2218d7`, OpenSubtitles `10806108`; **1,343 cues**, ALASS same-video embedded English, **+15.755 s**. Create-only `.ja.srt` location: `/mnt/BigDisk/Video/Movies/Horror/Late.Night.with.the.Devil.2023.1080p.AMZN.WEBRip.1400MB.DD5.1.x264-GalaxyRG[TGx]/Late.Night.with.the.Devil.2023.1080p.AMZN.WEBRip.1400MB.DD5.1.x264-GalaxyRG.ja.srt`. Final SHA256 `80854d70b5e85dcc35a71989b15790b6004a33a8f836db1d904900d28a5655b0`, `BRUISER_PUBLISH_ITEM result=published`, `published_new:1`.
- **The Witch (2016 catalog; video 2015), confirmed PUBLISHED**: Jellyfin `aa41799d85d1f138a4d56b2385fd00fc`, OpenSubtitles `10285361`; **868 cues**, ALASS video_audio, **−15.542 s**. Create-only `.ja.srt` location: `/mnt/BigDisk/Video/Movies/Horror/The Witch (2015) [1080p] [YTS.AG]/The.Witch.2015.1080p.BluRay.x264-[YTS.AG].ja.srt`. Final SHA256 `4dad6aaf1f2faff5016fdb12937422b20ffd05435eea500a03d86baa51b38d29`, `BRUISER_PUBLISH_ITEM result=published`, `published_new:1`.
- **Double Blind**, SubDL `3746725-8668631`: after fixing pre-HTTP ledger route, the next attempt reached actual SubDL ZIP/archive inspection. It **failed** `subdl_no_correct_episode_japanese_srt`, i.e. no usable member passed the existing SRT selector/validator. **No stage created, not published.** The archive was fetched in this attempt; it may have consumed one SubDL download allowance. Exact ZIP member names/validation failure are unknown, because the current implementation discards detailed rejection causes. Do not call it a successfully staged title or assume the video lacks an appropriate release.
- **Green Room** remains staged and held for `staged_srt_multiple_timestamps_per_block`. A subsequent owner command to inspect structural defects raised `ModuleNotFoundError: No module named 'subhub_source_failure_audit'` because the inspection-only script is not in the installer SOURCE_FILES. **No Green Room content inspection occurred.** Correct approach: fetch that read-only audit script directly to a private temp path and run `find_structural_defects` on the known staged original; do not modify original or publish from a guessed separator fix.

**Cumulative verified result for this recovery effort: five actual new Japanese sidecars published** (Smile 2, Autopsy of Jane Doe, Spirited Away, Late Night with the Devil, The Witch). No editorial Japanese translation scoring or Jellyfin playback spot check was provided; don't confuse synchronization-gate `pass` with a qualitative translation grade.

Next: diagnose Green Room's exact multi-timestamp blocks from its saved file (no network/quotas). For SubDL, add safe, specific archive-member and content-rejection diagnostics and consider a bounded original-ZIP cache to prevent repeated quota-consuming downloads, rather than blindly redownloading. [REC] remains duration-held.

---
## Five-film owner staging pilot — later Nov 12, 2026

Owner installed source revision 93fa0a3fcef4f33077d8c38a1b8fc953a9e942fc with --install-only; backup /home/optiplex/bruiser-pilot/subhub-control/.ja-library-source-backup-auxco34y. Health checks passed, workers stayed stopped. Saved candidates were downloaded/staged only; publication passes were dry-run; **no new media sidecars published in this pilot**.

| Movie | Saved release | Actual result |
| --- | --- | --- |
| **[REC] (2007)** | OpenSubtitles 8693762 | Downloaded and privately staged as **held_duration_mismatch**. 1,052 cues, 9,067 JA characters; SRT ends 5221.58s vs 4514.12s video (ratio 1.157). Not eligible for standard publication; normal queue shows zero active stage rows, but saved held bytes exist. |
| **Green Room (2016)** | OpenSubtitles 4247924 | Staged 1,307 timestamp entries, 14,053 Japanese characters, ratio 0.971. ALASS/ffsubsync held **staged_srt_multiple_timestamps_per_block**. Need inspect exact damaged blocks before any repair; no Japanese dialogue loss authorized. |
| **Late Night with the Devil (2024)** | OpenSubtitles 10806108 | Staged 1,343 cues; **ready_alass** in actual publisher dry-run. Same-video embedded English reference; uniform +15.755s. Aligned SHA256 80854d70b5e85dcc35a71989b15790b6004a33a8f836db1d904900d28a5655b0. **Not published yet.** |
| **The Witch (2016)** | OpenSubtitles 10285361 | Staged 868 cues; **ready_alass** in actual publisher dry-run. video_audio reference; uniform −15.542s. Aligned SHA256 4dad6aaf1f2faff5016fdb12937422b20ffd05435eea500a03d86baa51b38d29. **Not published yet.** |
| **Double Blind (2024)** | SubDL 3746725-8668631 | Saved candidate found, but **pre-HTTP ValueError** prevented its first SubDL download. Shared ledger rejected the literal route **sublarr_native_subdl** invoked by the native SubDL stage worker. No bytes downloaded or stage recorded in this attempt. |

### Confirmed common bug fixed in GitHub, not yet deployed

- Added the missing **sublarr_native_subdl** route to subhub_download_ledger.ROUTES. The stage worker called ledger.begin before the provider request, so this exactly accounts for the observed generic ValueError; this specific attempt consumed zero provider downloads.
- Added test_subhub_download_ledger regression for native SubDL route and unknown-route refusal, and safer fixed-code error reporting from ja_first_stage_subdl. New test passed; overall CI baseline remains four historical failures and eight errors.

### Next owner verification

1. Create-only publish the two actual ready_alass candidates (Late Night with the Devil ID c56f7de05115e6162920b9295e2218d7; The Witch ID aa41799d85d1f138a4d56b2385fd00fc). Do not mark published until owner output shows PUBLISHED.
2. Install the new SubDL ledger fix using the pinned source installer in --install-only mode with worker-idle preflight, then retry Double Blind SubDL stage once and run publisher dry-run. This can spend **one** real provider download allowance; no automatic publication.
3. Inspect exact Green Room malformed SRT blocks using the existing read-only subhub_source_failure_audit.find_structural_defects before designing general lossless separators repair.
4. Keep [REC] held for a different edition or credible reference, not a relaxed runtime threshold. The subtitle/video ending discrepancy is about 707 seconds.
5. Broader batch recovery remains the goal; measure actual stage → ready → published yield and preserve original downloaded files.

## SubDL archive cache and explicit validation errors (GitHub-only)

**Implemented and regression-tested after the last owner log, not yet installed on OptiPlex:**

- Native SubDL now saves the first **valid downloaded ZIP archive** in an owner-only private cache under `~/bruiser-pilot/ja-first-inventory/staged/subdl-source-zips/<sha256-id>.zip`. This does not stage or publish the ZIP as a subtitle. An identical release is subsequently read from cache without another provider GET; malformed, symlinked or insecure cache paths fail closed.
- The archive validator now reports distinct stable reasons: `subdl_archive_no_srt_members`, `subdl_archive_no_matching_srt_member`, and `subdl_archive_srt_rejected:<validation-reason>`, instead of the ambiguous `subdl_no_correct_episode_japanese_srt` umbrella. This preserves all original downloaded bytes and avoids making guessed subtitle-format changes.
- Five new tests covering missing SRT, wrong movie name among ZIP members, invalid Japanese content, one-GET caching, and rejection of symlinked caches all passed on CI Python 3.11. The full suite retains the same historical 4 failures and 8 errors (1018 total, 3 skipped); no new code failures.
- The previous Double Blind SubDL request was made **before** this cache existed and did not leave a reusable ZIP behind, so a single subsequent attempt will consume quota again. After this new version, another attempt against the same release should reuse the cached original ZIP without network.
- Inspect Green Room with a temporary copy of `tools/subhub_source_failure_audit.py`; it is intentionally **not included in the normal installer SOURCE_FILES**, so prior `ModuleNotFoundError` is expected from that incorrect command.

---

## New general-purpose source-only re-pass and lossless merged-cue repair

**Code committed and tested in PR #91; newest code is not yet installed on the OptiPlex.** The previously stopped Finish/PLaMO job remains untouched and no new batch outcome is claimed.

**Green Room original SRT actual read-only defect inspection (host):** 94,728 bytes; **1,306 blank-separated blocks / 1,307 timestamp lines**, exactly **ONE merged block (#1233)** and zero unparseable blocks, empty dialogue blocks or control characters. That block contains `1234`, `01:21:22,245 --> 01:21:23,444`, Japanese line `投げ捨てろ`, then **no blank cue separator**, then `01:22:22,604 --> 01:22:24,104` and `"犬に注意"`. This is a real mechanical defect, not a cue to invent dialogue. Original staging bytes unchanged.

- **Implemented in `tools/ja_first_srt_normalize.py`:** any block containing multiple complete standalone SRT timestamps can be split into separate complete cues **only if every segment has dialogue** and no ambiguous numerical index or malformed clock. All timestamp lines and dialogue text are preserved, indices re-numbered in a private working copy, count validated against original timestamp count. New provenance metrics: `merged_blocks_repaired` and `merged_cues_recovered`. ALASS and ffsubsync already invoke this shared normalizer; no per-film special case. Regression tests reproduce Green Room lines and refuse ambiguous/missing-dialogue blocks. This makes Green Room eligible for another real alignment dry-run, **not automatically published**.
- **Implemented in `tools/ja_first_stage_subdl.py`:** the SubDL ZIP archive validator now calls the **same** structural normalizer before Japanese-content QA, and records `original_zip_member_sha256` + structural repair report. Downloaded original bytes remain in the private cache. A synthetic complete 80-cue Japanese ZIP with one merged block now passes and preserves **80/80** cues; the old raw parser silently accepted the malformed source but counted **79**, demonstrating the need to normalize BEFORE validation. This is not proof that the actual Double Blind ZIP is repairable; that cached source still requires a new local validation attempt.
- **Implemented `tools/subhub_plamo_source_repass.py`:** exact historical Finish/PLaMO cohort re-read via saved state and systemd journal (the owner previously verified **191/191**), with **read-only default** and a bounded `--apply` mode. Re-check local Japanese sidecars and currently staged sources, attempt actual strict create-only ALASS/ffsubsync publication for already-staged candidates first, then try saved identity-eligible OpenSubtitles/SubDL releases within `--stage-budget` and `--publish-attempt-budget`. Always prefer existing bytes and no duplicate held-duration/known-invalid download. No PLaMO jobs, no live provider search, no new source-exhaustion or job-control changes; one provider's quota does not block the other; actual busy source units must be idle. Every historical title is counted, including no-result/unselected cases, and current completed sidecars are skipped. Can be rerun because it rechecks host state. This is **not the full automatic Finish loop** and does not translate anything. A later pass can refresh missing provider searches if desired.
- **Installer now ships both the read-only source-failure audit and this bounded source re-pass** with standard source modules. Historic journal scope derives from saved Finish `started_at`, avoiding a frozen Nov 11 cutoff. Regression coverage checks identity gating, duplicates/holds, zero writes in dry-run, source budget and no translation path.
- Latest focused tests all pass in Python 3.11 CI; full suite **1,026 tests with four historical failures and eight historical errors**, three skipped (suite not green). See issue #92 for deferred cleanup/merging.

**Next owner action:** Install the latest pinned PR commit with `install_global_ja_sourcing.py --commit <full SHA> --install-only` (backs up and refuses active source/translation workers); run `subhub_plamo_source_repass.py` once without `--apply` for a full 191-title classification; then `--apply --stage-budget 30 --publish-attempt-budget 190` for a source-only, sequential, quota-bounded recovery. Record actual `REPASS_*` counters and published hashes from the next owner log. Then inspect actual Double Blind ZIP if it stays held, and fix more general format defects without blindly widening safety gates.

---
