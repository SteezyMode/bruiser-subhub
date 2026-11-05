# Japanese subtitle coverage: source-first + separate DIY fallback — decision 2026-11-05

## Decision

Keep the **working existing-Japanese-source acquisition/sync pipeline as primary**. Test local DIY translation as an explicitly distinct, low-priority path **only** for missing/unusable Japanese tracks with a verified, correctly timed English transcript. Do **not** translate the entire library simply because an English SRT exists.

This is a *policy document*, not activation of automatic translation. The user explicitly wants the provider-search/sync production worker left alone while exploring the newly released PLaMo 3 small translation models.

## Why

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
