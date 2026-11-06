# Bruiser whole-library EN-text / missing-JA inventory

**Status (2026-11-06): code committed; not yet executed on the owner's OptiPlex.** This is a READ-ONLY *media/provider/translation* audit. Only new report files are written privately under `~/bruiser-pilot/coverage-audits/`. Existing Jellyfin authentication is reused. There is **no subtitle-provider request, AI inference, service or timer change, video write, source subtitle change, or automatic translation launch.**

## Why this exists

The owner wants **maximum usable Japanese subtitle coverage over the entire library**. Do not confuse the separate PLaMo American Dad batch with a source-search objective; do not exclude any series globally or favor TV over movies purely for testing. The November 6 sourcing results (see [postmortem](SUBHUB_COVERAGE_POSTMORTEM_AND_STRATEGY_2026-11-06.md)) exposed 9,981 items ready for Japanese source search and an independent English catalog with 12,399 records, but they do **not** establish how many titles already have complete English **text** that can be used for later English→Japanese translation.

A private, actual-library inventory is needed before designing a generalized Bruiser translation queue, allocating local model time, or making decisions about where the subtitle-provider download quota will have the most benefit.

## Source of truth

- **Jellyfin API** enumerates all registered movies and TV episodes; same catalogue accessor as the existing English-source tool, with bounded pagination and host-allowlisted real file paths.
- **Media-adjacent sidecars** are checked using exact video-stem and explicit language tags, not fuzzy title matches. Japanese existing tracks, including editorial and current `.ja.PLaMo8B.srt`, are excluded.
- **Jellyfin media-stream metadata** is used to identify Japanese subtitle tracks (forced-only Japanese does not count as full dialogue) and text-based English embedded/external tracks (bitmap PGS/VobSub alone does not qualify). Missing stream metadata invokes bounded `ffprobe` on only that item rather than guessing.
- **Named external English SRTs** must parse through SubHub's existing strict English source reader and cue-count gate before being reported as `source_text_ready`. This means *structurally usable English*, **not** verified audio alignment or a professional English transcript.
- **Embedded English text** and ASS/VTT files remain candidates requiring extraction/conversion and timing checks at the next stage. An exact video hash match is NOT required merely to inventory already present tracks, but publication still requires proper validation.
- **Unlabeled SRTs** and unreadable/invalid English files are kept in separate unresolved reports rather than being silently assumed English.
- The existing English sourcing SQLite table is read in **read-only** mode to mark items previously classified `jellyfin_only`, enabling targeted recovery of the 72 observed cases without another provider search.
- **Original audio language** is recorded. A title with Japanese audio but no Japanese subtitle can appear in this requested list; flag it separately and avoid prioritizing English→Japanese translation without need.

## Result files (private, 0600; folder 0700)

Run `tools/run_english_no_japanese_audit.sh` on the OptiPlex using a pinned GitHub commit. It verifies existing controller dependencies, syntax checks the new utility, backs up prior copies if any, and executes the read-only audit.

The user-owned host files have names like:

- `en-no-ja-YYYYMMDDTHHMMSSZ.csv` — one row for each movie or episode with an English text-source candidate and **no detected Japanese subtitles**. Fields: media type, show, season, episode, title, exact path, Jellyfin ID, source type, source path/index/codec, cue count when validated, audio language, readiness and prior Jellyfin-only flag.
- `en-no-ja-YYYYMMDDTHHMMSSZ.json` — same candidates, unresolved records and full-library classification counts in a versioned machine-readable format for a future Bruiser source queue.
- `en-no-ja-YYYYMMDDTHHMMSSZ.unresolved.csv` — items needing language/stream/source validation, including prior Jellyfin-only cases that still lack an accessible English source.

**No library filenames, video paths, subtitle text, private credentials or raw catalogue exports belong in this public repository.** The owner can share the private report back for further analysis when ready.

## Verified baseline census — November 6, 2026 (actual OptiPlex)

Owner executed the pinned audit and shared its exact `COVERAGE_AUDIT_SUMMARY`:

- Jellyfin movies/episodes: **12,386** inspected.
- **2,552 English text / no detected Japanese**: 2 parsed external SRT, **2,550 Jellyfin text-stream metadata candidates only** (NOT yet confirmed extractable).
- 573 titles with Japanese detected (not human quality-graded).
- 8,640 with no English text detected from the audited sources.
- 620 unlabeled same-stem SRTs needing language check, 1 invalid labeled English SRT.
- 72 previous `jellyfin_only` outcomes remain unresolved and **were not added to the 2,552 candidate count**.
- 120 of the 2,552 candidate titles have Japanese audio; treat them as a separate policy case rather than automatically prioritizing translation.
- 693 unresolved rows overall (620 unlabeled + 72 prior Jellyfin-only + 1 invalid source).
- Private reports were saved on the host: `en-no-ja-20261106T011929Z.json`, `.csv`, `.unresolved.csv` under `~/bruiser-pilot/coverage-audits/`. **Do not commit those reports or private paths/contents to GitHub.**

**Key uncertainty:** Jellyfin's `MediaStreams` metadata labels 2,550 potential English text tracks. It does not prove the real video contains extractable dialogue text. Counting those all as translation-ready would significantly overstate usable input.

### Second pass implemented (repo only; NOT run on host yet)

[`tools/verify_english_coverage.py`](../tools/verify_english_coverage.py) checks all 2,550 metadata-only candidates by reading actual media stream headers with `ffprobe`, explicitly ignoring forced Japanese subtitles. It then extracts and structurally validates an approximately film/TV-balanced *40-track sample* using `ffmpeg` in memory. It creates private JSON and CSV reports identifying real embedded English text, Jellyfin external-subtitle mismatch, missing/invalid media, extraction failures, and sampled successful SRTs. This does **not** auto-extract/publish all 2,550 and is not a new translation queue.

Run on the OptiPlex using pinned [`tools/run_verify_english_coverage.sh`](../tools/run_verify_english_coverage.sh); it consumes the previously saved private audit, checks controller/file safety, downloads only this script from pinned GitHub, then writes private reports. **No provider API, no subtitle publication, no new services, no model/GPU work.** Record `ENGLISH_MEDIA_STREAM_VERIFICATION` after execution before making claims about translation-ready totals.

## Interpretation and next action

| Result | Meaning | Next step |
| --- | --- | --- |
| `source_text_ready` | External English SRT parsed with acceptable cue IDs/count | Verify real video timing, then eligible for controlled translation queue |
| `verify_extract_before_translate` | Jellyfin lists embedded or externally stored English text but no validated SRT sidecar | Extract or resolve through Jellyfin/ffmpeg; validate cues/timing; do NOT auto-translate on metadata alone |
| `validate_and_convert` | Named English ASS/VTT/SSA sidecar present | Convert into safe SRT in isolated scratch; verify and preserve original |
| `identify_language_and_validate` | Unlabeled same-stem SRT present | Inspect language/content, do not automatically claim English |
| `needs_source_repair` | Named English SRT fails structural parser | Hold and inspect; never repair/copy over original |
| `has_japanese` | Usable-looking JA sidecar or unforced JA track already present | Exclude from EN→JA candidate list, no overwrite |
| `missing_english_text` | No confirmed English text source | JP-source first; later English provider/OCR/ASR only if warranted |

**Do not automatically queue every reported item for local AI translation.** Use the report to measure exact source availability, diagnose recovered English sources, prioritize full-library coverage and distinguish reliable input from metadata-only candidates. Preflight each candidate before model work.

## Deployment separation

Writing or committing these tools does not mean they were deployed. This audit is intended to run independently from the Japanese source timer (now scheduled after the provider quota reset) and separately from any PLaMo job. The host wrapper must be run and the resulting `COVERAGE_AUDIT_SUMMARY` inspected before numerical coverage claims are made.
