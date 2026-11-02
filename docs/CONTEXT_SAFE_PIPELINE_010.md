# Bruiser ContextSafe v010 — reusable subtitle cue isolation + new full-episode trial

**Status 2026-11-02:** Code implemented and **156 offline CI tests passing on Python 3.11 and 3.12**; owner has not yet launched real v010 GPU inference. This is a NEW separate trial, not a revision of the earlier five American Dad episodes.

## Engineering lesson from actual 009 subtitles

Pilot 009 translated/published five complete American Dad episodes, but the assistant's *text-only* bilingual quality audit found substantial future-dialogue leakage and overlong lines. The source of the worst problem: the current-cue translation request included the **next four raw English lines**, which the model occasionally translated **along with** the current subtitle. True semantic errors also occurred, but repeatedly polishing the same five episodes does not test whether Bruiser has solved the general problem.

**The correct next experiment is to translate a small fresh set with a better general pipeline, not keep editing the same five tracks or run a ten-model tournament.**

## Generic module: `tools/subtitle_quality_010.py`

- **Prompt isolation**: Only the CURRENT English cue is requested; up to 2 *preceding* English and 1 accepted Japanese cue may be context. **NO future raw dialogue is passed to the translating model**. Previously generated local series/episode notes remain optional and explicitly advisory; the actual English source always wins.
- **High-speed Japanese screening**: measures visible characters per source-timed second, ignoring standard SRT markup; warns above 18 characters/sec and treats extreme cases (more than 26 chars/sec with at least 15 visible characters) as serious QA flags, not automatic permission to delete a translation.
- **Cross-cue duplicate screening**: after translating every cue, checks whether a substantial later **Japanese** cue is already embedded in an earlier Japanese cue. Requires at least 9 matching normalized Japanese characters, excludes short repeated names/interjections, and checks up to three upcoming cues. Flags are conservative heuristic indications, not guaranteed semantic mistranslations.
- **Selective repairs**: for serious QA flags, one or two constrained **CURRENT ENGLISH only** retranslation attempts; never retranslate an entire episode for a few bad lines. A severe unresolved overlap/reading-speed problem HOLDS the episode from publishing. Do not truncate Japanese blindly, silently borrow English or discard a necessary punchline.
- The module has no dependence on American Dad, file paths, Jellyfin, model vendor, networking, or production SubHub state. This can be reused as the quality layer when migrating to a whole-library translator.

## NEW American Dad preview — separate adapter `tools/american_dad_contextsafe_010.py`

- Uses existing safe English-primary audio and subtitle extraction from embedded tracks or EN sidecars to select up to **three NEW eligible episodes**. It skips every episode with any embedded/published/editorial Japanese track, including all five previous pilot 009 results. Actual episodes are selected based on the owner's real library, not invented.
- Pins the previously installed **subtitle-tuned Gemma E4B** model/digest; **no new model ranking**. Keeps local automatically generated series and episode context and the existing small curated American Dad bible, but removes lookahead from the *translation* prompt.
- Freezes a NEW v010 manifest under `~/bruiser-pilot/american-dad-contextsafe-010/`, with per-episode source hashes, exact pinned model identity, curated profile hash and **QA module hash**. Saves per-cue originals, per-cue exceptions and optional QA repair text as private, immutable, resumable records; quality snapshots are append-only by content hash.
- Uses the same existing **TWO subtitle worker locks** and a model-residency preflight to avoid interference with the owner host and ongoing AI use. No service install, no production worker/DB changes, no re-download of model weights.
- Publishes only fully completed QA-approved episodes, under new distinct **create-only** `*.Bruiser ContextSafe v2 Japanese.ja.srt` sidecars. Existing v1 subtitles and all source videos remain untouched. Jellyfin may need a metadata refresh after publication.

## Launch AFTER merged code (on the owner's MacBook)

```bash
cd ~/Downloads/bruiser-subhub-repo
git pull --ff-only
bash tools/run_contextsafe_pilot_010.sh optiplex@100.121.156.34
```

Runs local offline regression tests first, stages only independent scratch files on the OptiPlex, freezes the new three episodes, translates sequentially using E4B, makes bounded targeted QA repairs and requests create-only publication. Appends host output to `~/Downloads/american-dad-contextsafe-010.log`; host state stays private.

Read-only progress check without rerunning inference:

```bash
ssh optiplex@100.121.156.34 'python3 ~/bruiser-pilot/contextsafe-010-code/american_dad_contextsafe_010.py status'
```

Re-running the first command resumes the same frozen episode selection and all accepted cue checkpoints. If a marked line still cannot meet the QA gate after its bounded retries, the affected episode is HELD with numerical cue IDs in the log; it is **never silently declared complete**.

## Honest limits, next decision

Offline tests prove structural source handling, future-input isolation, source hashes, immutable accepted cues, duplicate/read-speed flags, attempted targeted corrections, create-only sidecars, and service isolation. They **cannot** prove that the new Japanese is better or that Ollama will succeed on actual hardware. The next meaningful evidence is the user's new full-episode EN/JA pairs and natural Jellyfin watching, not a big nine-model blind microclip assignment.

Only after this test should we decide whether the **generic** cue-isolation and QA rules belong in the core SubHub worker. Keep the original 009 artifacts for reference and never retrofit them automatically.
