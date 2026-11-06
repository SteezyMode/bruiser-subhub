# Japanese subtitle coverage: source-first + separate DIY fallback — decision 2026-11-05

> **SUPERSEDED AS TO PRIORITY (Nov 6):** Follow [the canonical owner-confirmed policy](BRUISER_SUBTITLE_POLICY_CANONICAL_2026-11-06.md): existing subtitle preservation, **timing repair in either language**, cached/staged provider results, correct subtitle sourcing, English recovery, and **GPU-based PLaMo translation as a real, substantial last resort**. Do not interpret the earlier experiments as a reason to avoid GPU translation or repeatedly benchmark models.

## Decision

Keep the **working existing-Japanese-source acquisition/sync pipeline as primary**. Test local DIY translation as an explicitly distinct, low-priority path **only** for missing/unusable Japanese tracks with a verified, correctly timed English transcript. Do **not** translate the entire library simply because an English SRT exists.

This is a *policy document*, not activation of automatic translation. The user explicitly wants the provider-search/sync production worker left alone while exploring the newly released PLaMo 3 small translation models.

## Why
## Quota-aware decision detail (November 5)

**OpenSubtitles' public API documentation states that subtitle searches do not have a daily numeric allowance; downloads are quota-limited by account rank.** Requests may still face throttling/rate limits, Sublarr delays, or other provider-specific limits. Don't equate the existing SubHub software search budget of 600 with an OpenSubtitles "600 daily searches" allocation. Official source: https://opensubtitles.tawk.help/article/getting-started.

The optimal first move is usually one **non-download** lookup, not immediate machine translation. A cheap, non-quota-consuming search is valuable evidence of human Japanese availability even for a title with perfect English.

Before spending any provider download allowance:

1. Check the Jellyfin catalog and existing media-adjacent or embedded Japanese. If usable, stop.
2. Check the private **saved provider-search database** and cached plausible result metadata. If a strong matching Japanese candidate exists, prefer acquiring *one* high-confidence candidate and verifying it.
3. For unsearched titles, use **one metadata-correct provider search**. Strong Japanese candidate -> one prioritized download; no reliable candidate -> queue for DIY if English is already proven. No need to poll dozens of sources or download weak matches.
4. Record searched_none, review_needed, download_held, published, and diy_eligible as distinct **proposed workflow outcomes**. Present source code already has its own none, review, plausible, error history and a 30-day eligibility cooldown; do not assert the proposed unified router already exists.
5. When download quota is low, prioritize a confirmed match with likely human-authored subtitles and good identity over speculative alternatives. If a title has only ambiguous candidate metadata, hold it rather than spend downloads in a brute-force search.
6. Once English source is exact and Japanese searches have failed/are low confidence, **local translation becomes the default fallback** if native-viewed quality meets the household threshold. Prefer 2B/0.8B based on a measured subtitle trial, not the parameter count or model-vendor benchmark alone.
7. If English source is absent/untrusted and reliable Japanese sources are also absent, hold for English-source/OCR/ASR recovery; do not fabricate translated text.
8. Persist outcome/provenance and avoid repeated failed provider requests. Existing 30-day search history should eventually be upgraded to status-sensitive TTL (longer for reliable no-result, shorter for recoverable provider failures, reconsider when new providers are added), but **don't modify the live production search scheduler without a separate safe rollout**.

### Proposed economical priority (not coded)

| Availability / evidence | Work to do | Provider download cost |
| --- | --- | --- |
| Verified existing Japanese | Keep | 0 |
| Prior saved plausible JA candidate, no published sidecar | Download only the strongest and sync | Usually 1 |
| Unsearched title with accurate English | Search once; download if credible JA, otherwise DIY | 0 or 1 |
| Reliable no-JA search + exact English subtitles | DIY when model quality verified | 0 |
| Multiple weak Japanese matches + exact English subtitles | Hold or DIY; don't burn quota on multiple guesses | 0 |
| No EN and no useful JA | Recover an English transcription source or hold | 0 until evidence |

The user cares about **actual watchable Japanese coverage**, not minimizing search count at the expense of quality. Source-first does not mean quota-blind; local translation does not mean automatically better than human work.


A single provider query and downloadable Japanese SRT normally uses orders of magnitude less compute than local translation of hundreds or thousands of cues. A properly sourced human-authored Japanese subtitle is usually the better quality candidate; a mistranslated or edited-for-a-different-release SRT is not automatically good just because it was downloadable. ffsubsync can often correct timestamp drift when video editions are compatible, but cannot fix missing dialogue, alternate scene order, semantic errors, or poor translations.

A genuinely clean English subtitle matched to the user's actual video **removes DIY transcription and timing-alignment work**. A translation can reuse each original cue's timecode exactly; the remaining difficulty is natural, faithful, readable Japanese within the same display intervals, not synchronization.

## Proposed (not yet implemented) priority rules

1. If a good Japanese subtitle already exists, **keep it**. Never silently overwrite or auto-upgrade curated/human sidecars.
2. Search Japanese providers using current library metadata and source-first schedule. Prefer plausible **correct-title/correct-episode** candidates. Download, run text/identity checks, synchronize via ffsubsync, validate against actual media and create-only publish.
3. If no acceptable Japanese survives this process and a verified, accurately timed **English** source is already present, mark the title \`diy_eligible\`. This is a **queue state proposal**, not an existing production status or an automatic action.
4. Source work and DIY work use **separate queues, budgets, job identity, filenames and histories**. A failed source search may be retried according to provider availability without blocking a later DIY draft indefinitely; likewise a DIY draft must never suppress later legitimate human Japanese finds.
5. Run a chosen translation model when the server is idle/under a configured load limit, with checkpointing and exact cue/timing validation. Do not compete for GPU/VRAM with Wolf, games, Jellyfin transcodes, or other user applications by default.
6. Create a **clearly labeled AI draft** in isolated review storage. Publishing a track directly alongside the video is a separate, source-provenance-checked decision. No AI draft silently replaces a sourced or curated Japanese track.
7. If a good sourced Japanese track becomes available later, prefer it after actual checks; preserve any earlier AI draft and keep the user-visible language/track provenance unambiguous.

## Compare quality as well as compute

| Factor | Sourced Japanese + ffsubsync | DIY on matched English |
|---|---|---|
| External requests | Search and download quota | None for inference, assuming English on disk |
| Local processing | Small text checks and fast sync | Model generation for every translated cue |
| Source timing | May require sync against actual video | English cue timings already aligned |
| Japanese linguistic quality | Potentially professionally translated, or variable/poor | Model-dependent; may miss idioms, jokes, politeness, negation, implications |
| Coverage | Limited to actual source availability | Broad wherever real matching English dialogue is available |
| Video edition differences | Candidate may be unusable | Not relevant if source English was verified against exact video |
| Extra Japanese subtitles | Keep separate source and DIY variants | AI label; never claim professional quality from successful output |

Neither approach is "always better." Only a viewing test can establish what is usable for the household. A mechanical accepted/published count cannot assign a Japanese-quality grade.

## Critical automation and failure protections

- No source-only job should spawn a model by itself; no auto switch to model mode after search miss until an explicitly reviewed separate setting exists.
- Search and download OpenSubtitles limits are different; rely on current provider allowance, not assumptions about the API key.
- Never download a second equivalent candidate without reason after a verified, published track succeeds.
- A complete Japanese text file must still be checked for cue structure, numbers, negation, untranslated source leakage, long/short display times, and contextual mistranslations in blinded film scenes.
- Known limits: 2026-11-05 production sourced-QA is intentionally permissive and **does not certify Japanese semantics**; PLaMo has not been run on the OptiPlex.
- Use the user's actual experience (*You Were Never Really Here* sourced SRT repaired for their file) as the reference for whether automation improves playback.

## Near-term implementation priority

Finish the current 100-search end-to-end acquisition/publish cycle and record final yield. Independently compare **PLaMo 3 Translate 0.8B and 2B** on a fresh frozen set of English subtitle cues (see [model research plan](PLAMO_3_TRANSLATE_EVALUATION_2026-11-05.md)). Do not retrofit the model into the live daily service or restart it to conduct the benchmark.

Only after measured Japanese viewing quality and actual idle/GPU performance should we implement the \`diy_eligible\` queue and an optional generation schedule.
