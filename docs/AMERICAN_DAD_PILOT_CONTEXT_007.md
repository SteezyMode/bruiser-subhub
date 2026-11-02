# American Dad: series context policy for a real viewing pilot

**Decision (2026-11-02): use compact, advisory show context. Do not build an Internet-research agent.**

The goal is **five complete, previously untranslated American Dad episodes** with a single-pass subtitle-tuned Gemma E4B candidate, watched normally over several evenings. No Natsuyo QA work, blind nine-model comparisons, or further repetitive sample selection is required. This is an **operational pilot design**, not yet a deployed producer or a claim that five episodes have translated.

## Three deliberately small layers

1. **Permanent, locally stored series bible** at `tools/series_profiles/american_dad.json`. Covers who recurring characters are (Stan, Francine, Hayley, Steve, Roger, Klaus, Jeff), canonical-name hints, relationships, and tone. Roger's disguises/personae must **not** be rewritten to Roger when an alias is active. Series notes are advisory and must not invent the speaker of an unlabeled subtitle.
2. **Episode context**: infer at most a few tentative bullet points from that episode's English subtitles, not web research. Do not claim to know the plot if the source lacks evidence. Save the note with source SRT hash; never regenerate behind the viewer's back or inject old Japanese as source.
3. **Cue neighborhood**: show the translator the preceding ~4 and next ~4 source English cues and at most two previously translated Japanese cues. This should help resolve references, incomplete sentences, and punchlines without producing a second Japanese translation or rewriting other cue timings. The English CURRENT cue always overrides all broad background context.

## Quality over pedantry

Natural concise Japanese and idiomatic adaptation are desired; **not** exact word-for-word EN mapping. Do not soften adult language, sexual jokes or profanity. Never invent extra abuse or introduce new plot details. Existing Japanese subtitles remain authoritative and are never replaced.

## Practical rollout boundaries

- Do **not** alter `service.py`, `main.py`, existing production queue, SQLite, published JA, or any existing media. First trial should be a **separate, create-only subtitle runner**.
- Find episodes only when English-primary audio is verified and English SRT can be extracted from an embedded text stream or English sidecar. Skip any episode with an existing Japanese or editorial sidecar or embedded Japanese subtitle.
- Candidate model pinned to `hf.co/17slever17/translate-gemma-4-sub-e4b-GGUF:Q4_K_XL`, known installed digest prefix `9ccfc3b07081`. No silent model downloads or switches.
- Freeze source hashes, SRT and context profile; save per-cue checkpoints privately. Publish only a complete file under **a distinct create-only pilot sidecar name**, e.g. `<episode>.Bruiser Pilot Japanese.ja.srt`; never overwrite existing files. Confirm Jellyfin recognizes it before scaling.
- Respect both production worker locks and other GPU residents, and cap simultaneous work to one episode/candidate; limit number of titles per trial.
- First success gate is simply: several natural episodes can be watched end to end without obvious distracting errors. Viewer may mention issues in ordinary conversation. No separate grading task or elaborate experiment.
- Escalate to Index2B, CAT3.3 or multi-pass **only if** these actual episodes are unsatisfactory. Do not add a giant franchise bible, external Web API, or long pre-translation research phase unless specific recurring context failures justify it.

**Status:** profile created and policy recorded; the separate episode discovery/extraction/translation/publishing runner has **NOT been committed, deployed or tested on real American Dad episodes** in this change. Do not report it as ready or give a launch command until code and offline safety tests exist.
