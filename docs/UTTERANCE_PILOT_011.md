# SubHub v011 — sentence/utterance-aware Japanese pilot

**Status, Nov 2, 2026: CODE + OFFLINE TESTS ONLY.** No real v011 model calls, published Japanese tracks, or host deployment are claimed until the owner runs the one-command pilot. This is a distinct experiment; v009's five published tracks, v010's three published tracks, live worker/SQLite/media and existing editorial subtitles remain unchanged.

## Why this is the next experiment

The owner's private bilingual review of THREE REAL v010 American Dad episodes (1,315 cues, S19E07/E08/E09) found **cleaner mechanics but persistent semantic mistakes**, yielding a provisional text-only estimate ~6/10, still below desired personally watchable FROM-like ~7.5–8.5/10. Mechanical record: 0 automatically detected substantial future-JA overlap, 0 severe reading density, 3 >18 Japanese chars/sec. These flags do NOT measure story fidelity. The 32 selected bilingual failure examples are PRIVATE and must not be committed to GitHub.

General problems from evidence: sentences split across English cue boundaries, anaphoric replies that misinterpret prior negation, idioms and context-dependent word senses, two-speaker source cues condensed into one Japanese turn, and repeated meaning that evades exact substring duplication checks. A series context JSON note also failed strict list schema for its names field; the curated profile still worked. **New model tournament is NOT warranted from this evidence.**

## Generic mechanism: semantic_groups_011.py

A deterministic planner forms 1–3 cue **utterance groups** only if contiguous source IDs, close timestamps, reasonable combined length/duration and an unfinished English sentence (or a small set of short elliptical replies) support grouping. Hard barriers: speaker-turn cues, musical/non-dialogue breaks, long gaps and max 3 cues. It is a conservative heuristic, NOT NLP sentence parsing.

For groups of 2–3, one pinned tuned E4B call sees ALL English segments in the unit as **translation targets**, rather than passing 4 future cues as unrequested context. It must return a JSON object with exactly the original cue-ID keys and one Japanese value per source cue. Instructions forbid anticipatory reveals and repeating a full proposition in both outputs. For single cues, keep v010's known working cue-isolation prompt. No future dialogue outside the selected group is passed. The unit call may consider two previous English cues and one previously accepted JA caption.

Validators require exact keys, actual Japanese, source-supported SRT italics, preserved two-voice layout for explicit multi-speaker sources, no severe 26+ CPS output, and no exact or near-duplicate future-JA content. A conservative new overlapping **four-character n-gram** test catches long paraphrased JA repetition that the existing literal-substring detector misses; this is NOT a translation meaning classifier. Each unit gets up to three bounded model attempts, unresolved units HOLD the episode instead of inventing filler or silently publishing partial subtitles.

After the full pass, global QA checks adjacent spans across unit boundaries. Only flagged units get two bounded targeted repair attempts; original successful unit records remain immutable. Severe unresolved QA holds publication. Code/model/profile/source fingerprints protect resumability.

## Fresh American Dad trial only

New runner: tools/american_dad_utterance_011.py. Stages 3 **new** eligible verified-English episodes using existing safe v009 intake, skipping every title with existing Japanese (including v009 and v010), pinning the existing tuned E4B immutable model digest. Saves scratch-only manifests, source SRT, per-unit accepted JSON, failed-attempt metadata, private numeric quality reports and final SRT under ~/bruiser-pilot/american-dad-utterance-011. Never edits production code, running workers, service state, existing subtitles or original video. Uses BOTH existing subtitle locks and model-residency preflight.

Optional auto-series/episode context receives ONE retry if JSON is malformed (e.g. names field is string not list). If still bad it is omitted; no invented fallback series facts, no malformed cache. All actual subtitle text remains private.

Only fully completed, QA-accepted episodes get an explicitly versioned CREATE-ONLY *.Bruiser Utterance v3 Japanese.ja.srt next to their video for Jellyfin. No v009/v010 rewriting.

### Launch from MacBook after PR merge

    cd ~/Downloads/bruiser-subhub-repo
    git pull --ff-only
    bash tools/run_utterance_pilot_011.sh optiplex@100.121.156.34

The wrapper runs full offline tests, stages scratch code on OptiPlex, freezes fresh source hashes, translates using local GPU, saves ~/Downloads/american-dad-utterance-011.log, and prints read-only status. Running the same command again resumes accepted unit checkpoints; if any pinned inputs or code changed, it refuses an incompatible resume. The source episode selection is NOT recalculated once frozen.

If an episode is HELD, do not reset, delete or modify private checkpoints to force completion. Return the numerical error/QA log to the conversation for a surgical, versioned general fix.

### Review after real completion (read-only; no further inference)

    cd ~/Downloads/bruiser-subhub-repo
    bash tools/collect_utterance_review_011.sh optiplex@100.121.156.34

This verifies frozen English source hashes, exact EN/JA cue IDs and timings, and byte-for-byte equality with the published sidecars. Produces a PRIVATE tar.gz in Mac Downloads with complete English/Japanese pairs plus QA metrics; user uploads it in the conversation. Do not commit private subtitle dialogue into public GitHub.

## Validation and decision gate

Offline tests cover grouped source partition/timing, punctuation/anaphora grouping, exact JSON cue mapping, unexpected keys, source and publish protection, resume behavior, context schema-retry, density, near-duplicate warnings, multi-speaker visual separation, private exporter integrity. CI tests do NOT prove local model reliably emits correct JSON, nor that Japanese semantic accuracy improved.

Next empirical gate: real v011 three-episode run, bilingual editorial review of **NEW episodes** and ordinary household Jellyfin watching. Compare mechanics + specific recurring error categories; only if improved and personally watchable consider promoting the **generic semantic module** into SubHub proper. Do not translate 6 TB or run another model sweep prematurely.
