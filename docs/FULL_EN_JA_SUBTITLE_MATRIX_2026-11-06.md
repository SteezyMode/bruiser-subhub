# Bruiser whole-library existing-subtitle inventory — November 6, 2026

**Corrected scope:** list **every** Jellyfin movie and episode and show whether **English**, **Japanese**, **both**, or **neither** are present. This explicitly includes titles that already have Japanese subtitles; do not filter them out. The earlier EN-without-JA census was a useful translation-candidate subset but not a valid total English subtitle inventory.

## Why and how

- Read Jellyfin's existing Movie/Episode catalog plus named media-adjacent subtitle sidecars; detect EN and JA independently, including embedded text and bitmap subtitles, metadata-tracked external subtitles, and generated `.ja.PLaMo8B.srt`.
- **Do not** perform another expensive full-library `ffprobe` or 40-title subtitle extraction sample. No provider calls, model use, or media file modifications.
- Ignore forced/signs-only subtitles when counting full-dialogue subtitle coverage. Preserve independently a list of unlabeled sidecars and mark language-incomplete cases `unknown`, not `neither`.
- Reuse the November 6 private 2,550-track verification report **without re-probing**: 2,270 embedded EN tracks were confirmed in real media, 265 Jellyfin-reported EN tracks were absent in ffprobe and 15 external tracks were unresolved. Flag these previously tested mismatches instead of counting them as confirmed English presence. Other, unprobed Jellyfin metadata is reported as *detected* but not verified.
- Output one comprehensive private row per file (full title, show/season/episode, file path, source details, subtitle formats, original audio language, prior verification flag), plus category CSVs for `both`, `english_only`, `japanese_only`, `neither`, and `unknown`. JSON mirrors complete result. Reports stay in `~/bruiser-pilot/coverage-audits` with 0600 files and 0700 parent.
- English bitmap subtitles count as English subtitle **presence**, not immediately as extractable English **text** for PLaMo. A source entry proves existence/metadata, not language quality, completeness, or exact synchronization.

## Baseline evidence already verified

The earlier narrower audit covered 12,386 files, found 2,552 **English text candidates without detected JA**, and identified 573 titles with JA (which the first audit excluded from its English inventory). Of the 2,550 Jellyfin metadata candidates, subsequent ffprobe verified **2,270 embedded English text tracks** (2,080 episodes and 190 movies). A 40-file extraction sample succeeded on 39 and failed on one. These counts **cannot** answer the user's requested total bilingual inventory because the 573 JA titles were never simultaneously classified for English.

The full matrix **was executed on the real OptiPlex** on November 6, 2026. This is the current baseline, superseding the earlier incomplete English-without-Japanese subset.

## Verified live bilingual census — November 6, 2026

**Actual host result:** `SUBTITLE_MATRIX_SUMMARY` processed **12,386 / 12,386** Jellyfin media files, with no reported inspection errors.

| Exclusive category | Count | What it means |
| --- | ---: | --- |
| Both English and Japanese | **522** | Both languages detected, including external and embedded tracks |
| English only | **2,563** | Primary candidates for new Japanese coverage; English subtitle presence is not always usable text |
| Japanese only | **41** | Japanese present; English absent by current classifier |
| Neither | **8,336** | No unforced, explicitly EN/JA subtitle tracks found; source discovery needed |
| Unknown | **924** | Includes unlabeled sidecars, earlier media/Jellyfin conflicts and cases where absence cannot safely be established |
| **Total** | **12,386** | Each file appears in exactly one category |

Independent presence totals **include some unknown-category rows**, so they do not equal the simple sums above:

- **English subtitles detected: 3,112** (including 27 uncertain-category records).
- **Japanese subtitles detected: 572** (including 9 uncertain-category records).
- **English text indicated: 2,791**; this is a presence/codec indicator, **not** 2,791 validated translation sources.
- **Japanese text indicated: 563** (no independent native-language viewing grade).
- **Prior media verification reused:** 2,270 actual embedded English text tracks confirmed, **265 Jellyfin metadata English-track mismatches flagged**. Do not count the latter as verified input.
- **675 files have unlabeled subtitle sidecars**, requiring language inspection before any absence/presence claim.
- **278 have Japanese audio** across the entire library; subtitle priorities should account for them. This is not the same as 278 unserved Japanese viewers.
- This was a **read-only baseline**, not new Japanese subtitle publication.

**Authoritative private outputs on the host** (never upload to this public repository):

```text
~/bruiser-pilot/coverage-audits/subtitle-matrix-20261106T015513Z.json
~/bruiser-pilot/coverage-audits/subtitle-matrix-20261106T015513Z.all.csv
~/bruiser-pilot/coverage-audits/subtitle-matrix-20261106T015513Z.both.csv
~/bruiser-pilot/coverage-audits/subtitle-matrix-20261106T015513Z.english_only.csv
~/bruiser-pilot/coverage-audits/subtitle-matrix-20261106T015513Z.japanese_only.csv
~/bruiser-pilot/coverage-audits/subtitle-matrix-20261106T015513Z.neither.csv
~/bruiser-pilot/coverage-audits/subtitle-matrix-20261106T015513Z.unknown.csv
```

**Stop repeating full-library ffprobe passes or extraction samples.** This is enough to organize development. The right next action is to use the **existing `english_only.csv` (2,563 items)** to assemble an opt-in, per-title validation and translation backlog, while preserving source-first acquisition for the 8,336 neither and addressing unknown/unlabeled separately. Do not mass-translate on the basis of a codec flag or override existing Japanese tracks.

## Code and deployment

- [`tools/audit_full_subtitle_matrix.py`](../tools/audit_full_subtitle_matrix.py) — full bilingual matrix; read-only catalog and exact-stem sidecar detection, reuse existing verification results.
- [`test_audit_full_subtitle_matrix.py`](../test_audit_full_subtitle_matrix.py) — offline bilingual, forced, bitmap, missing/stale metadata and language-unknown tests.
- [`tools/run_full_subtitle_matrix.sh`](../tools/run_full_subtitle_matrix.sh) — guarded one-command installer and execution on the existing OptiPlex host; no changes to timer or PLaMo.

**Deployment verified:** The owner ran the pinned wrapper successfully on November 6 and generated the private reports shown above. Future code changes are still not automatically deployed. No public GitHub upload of the resulting private media file paths.

Next development task after the matrix: review these counts by language/source and prioritize genuine **new playable Japanese coverage**—not another redundant broad subtitle extraction experiment.
