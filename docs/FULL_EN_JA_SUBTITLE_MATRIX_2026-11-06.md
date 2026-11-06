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

The new full matrix now does the appropriate independent classification. **Actual full-matrix counts are unknown until run on the host.** Do not simply add 2,270 and 573; their overlap was not measured.

## Code and deployment

- [`tools/audit_full_subtitle_matrix.py`](../tools/audit_full_subtitle_matrix.py) — full bilingual matrix; read-only catalog and exact-stem sidecar detection, reuse existing verification results.
- [`test_audit_full_subtitle_matrix.py`](../test_audit_full_subtitle_matrix.py) — offline bilingual, forced, bitmap, missing/stale metadata and language-unknown tests.
- [`tools/run_full_subtitle_matrix.sh`](../tools/run_full_subtitle_matrix.sh) — guarded one-command installer and execution on the existing OptiPlex host; no changes to timer or PLaMo.

**Note:** Repository code is not live-host deployment. After executing the pinned wrapper, use `SUBTITLE_MATRIX_SUMMARY` and the private `subtitle-matrix-*.both.csv` / `.english_only.csv` / `.japanese_only.csv` / `.neither.csv` / `.unknown.csv` as Bruiser's source-of-truth inventory. No public GitHub upload of the resulting private media file paths.

Next development task after the matrix: review these counts by language/source and prioritize genuine **new playable Japanese coverage**—not another redundant broad subtitle extraction experiment.
