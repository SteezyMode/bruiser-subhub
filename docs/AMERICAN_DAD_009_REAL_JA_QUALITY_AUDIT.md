# Benchmark 009 — five REAL American Dad subtitle pairs: quality audit, not model winner

**Reviewed November 2, 2026.** Owner uploaded PRIVATE `bruiser-american-dad-five-episodes-review.tar.gz` containing English source and Japanese pilot SRT pairs for S19E01, S19E03, S19E04, S19E05, S19E06. The assistant parsed **all 2,066 cue pairs** and manually examined a substantial set of contextual scenes in each; no native-Japanese film viewing was conducted. **Source text, translations, raw flagged cues and user media paths are NOT committed.**

## Editorial finding

**FULL-EPISODE technical generation succeeded (5/5 published), but editorial quality is NOT yet acceptable for library-wide adoption.** Assistant's *provisional text-only* viewing estimate is **~5.5/10**, noticeably below the user's previous *FROM* personal-use benchmark around **7.5–8.5/10** against professional streaming subtitles. This is a reasoned initial judgment, **NOT** an independently measured Japanese-speaker score, nor a rating of model weights alone.

| Episode | Cues exactly aligned | Suspected future-dialogue overlap | Clear exact-copy subset | Cues >20 visible characters/sec | Provisional editorial score |
|---|---:|---:|---:|---:|---:|
| S19E01 | 400 | 25 | 20 | 19 | 5.0/10 |
| S19E03 | 394 | 9 | 6 | 7 | 6.0/10 |
| S19E04 | 392 | 10 | 6 | 6 | 6.0/10 |
| S19E05 | 359 | 10 | 8 | 9 | 6.0/10 |
| S19E06 | 521 | 30 | 21 | 25 | 4.5/10 |
| **Total** | **2066** | **84** | **61** | **66** | **~5.5/10** |

- All 2,066 Japanese files/records maintain the source cue IDs, exact start/end timestamps, sequence order; all contain nonempty Japanese script.
- **110** individual cues exceed 14 visible chars/second; **66** exceed 20; extreme examples exceed **50–100 chars/second**. Thresholds count code points after stripping markup and placement tags.
- **84** candidate cases of current-cue Japanese containing large portions of immediately future cue translations (61 are exact nested copied spans). These are auto-detected *review flags*, not 84 independently proven errors; legitimate sentence continuation may inflate the count. Across overlap OR >20 chars/sec there are **89 unique cue IDs (~4.3%)**. Manually inspected examples in every episode confirm recurrent severe premature dialogue and duplicates, strongly indicating **raw next-4-English-cue context leakage into current-cue output** despite the prompt's 'current only' instruction.
- Some genuine semantic/idiom failures persist outside these: **witness protection** rendered as probation; repeated **chopping it up** conversational metaphor literalized as cutting; the **shit hosed** drinking joke lost; **bankrupt/on the skids** contrast collapsed; occasional factual term swaps and inconsistent name/localization choices. These examples were observed in the uploaded paired English/Japanese and are NOT a measured semantic-error rate.
- Many short routine conversations are understandable and can feel natural; the five-episode output and exact timing alignment are real improvements. The problem is not simply that Gemma E4B is too small or that the basic JA validator is too strict.

## Action priority — no new ten-model sweep

1. **Do not point the current pilot at the whole library**, and do NOT declare it Hulu-quality from structural acceptance. Keep the 5/5 published v1 SRT sidecars untouched, and do not overwrite existing approved Japanese.
2. **Fix cue isolation.** For a bounded recovery pass, remove raw **future English cue texts** from the model generation prompt; keep the curated series bible, automatic episode summary and preceding English context. If a separate scene-level context summary is useful, generate it as a short advisory note, not raw future dialogue asked alongside the current line.
3. Add **post-generation repeated-future-output detection and reading-density gating**. Flag only suspicious cues and regenerate them using a strict current-English-only prompt, with verification of no significant overlap and watchable character counts. Avoid blindly shortening meaning-critical lines. Preserve all nonflagged accepted Japanese and full original timecodes. Write a **new versioned pilot SRT sidecar**, not overwriting the v1.
4. Add a few sourced, verified glossary entries for persistent misread jokes/terms; never accept auto-series-bible speculation over original dialogue. Don't build a massive internet show-lore crawler.
5. Repeat the **full-episode ordinary-viewing** quality check on corrected SRTs. Do not assign Natsuyo a burdensome blind-comparison workload. Only if the repaired workflow still misses the user's practical 7.5–8.5/10 target consider a **new full-episode** challenger (e.g. CAT3.3 or Index2B), not another mini-sample tournament.

## Provenance and boundaries

- Private full report and flagged 89-cue rows were produced in the assistant's current container session and returned only to user as downloads. They must **never** be checked into the public GitHub repo.
- No new host GPU inference, source/Japanese sidecar mutation, model switch or production SubHub deployment was performed during the audit.
- Unlike QA completion scores, the editorial score is based on text and context, and requires normal human viewing to validate entertainment value/character voice.

**Current next step:** surgical context-leakage repair of 009 outputs into separate versioned SRT sidecars. This is the largest demonstrated improvement opportunity; do not mistake five complete episodes for five professionally localized episodes.
