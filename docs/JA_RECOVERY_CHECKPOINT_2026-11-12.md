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
