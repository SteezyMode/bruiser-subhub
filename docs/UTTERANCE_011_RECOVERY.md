# SubHub v011r1 — recover original v011 trial without discarding 757 accepted cues

**November 2, 2026.** Evidence: owner's actual private read-only diagnostic JSON from frozen S19E10 / S19E11 / S19E12. The original runner fingerprint and accepted unit identities are intact. Actual subtitle text stays outside public GitHub.

## Actual failure categories

| Episode | Accepted | Unaccepted | Exhausted units | Never-attempted units | Failed attempts due to output length cap |
|---|---:|---:|---:|---:|---:|
| S19E10 | 219/372 | 153 | 6 | 122 | 18 |
| S19E11 | 192/409 | 217 | 6 | 185 | 15 |
| S19E12 | 346/408 | 62 | 6 | 45 | 18 |
| TOTAL | **757/1189** | **432** | **18** | **352** | **51** |

These 18 exhausted units contain **37** cue IDs total. **395** other unaccepted cues were never reached: 141 in E10, 204 in E11, 50 in E12. Those are cue counts rather than units. There were five invalid-Japanese/speaker failures in E11 and one in E12. Across all records: 51 model_length_cap + 6 invalid_ja_or_speakers, i.e. **51/57 failed attempts**. Some failures are attached to units subsequently accepted, so don't equate attempts with blocked units.

The diagnostic supports an **output-length-limit failure in grouped model calls**. It does NOT reveal raw model replies, nor establish whether token budget, repetition, a template loop, or long prompts caused that limit. Do not guess GPU issues or semantic model quality from these mechanical errors.

## Versioned bounded recovery

New independent code in tools/rescue_utterance_011.py reads the ORIGINAL private v011 manifest and verifies its runner code fingerprint, source/model/profile identity, subtitle source hashes, and all saved accepted unit checkpoints. It NEVER modifies frozen original code, original manifest, accepted unit files or previous failed-attempt records.

It writes a separately versioned rescue manifest and new per-unit and per-cue checkpoints under ~/bruiser-pilot/american-dad-utterance-011-recovery, with its own code/model/source hashes. Both existing worker locks and pinned E4B residency preflight are preserved. Old successful units are reused **byte-identically**.

- **Previously failed unit:** do NOT repeat exhausted group attempts. Translate its member cues individually using v010's current-cue-only prompt, up to TWO attempts per cue, checkpointing each accepted cue create-only.
- **Never-attempted group:** ONE standard structured group call. If output is capped, invalid or too dense, privately record a sanitized error category and fall back to bounded current-cue-only translation. Successful groups retain v011 sentence-aware behavior.
- **All units:** continue past unsuccessful groups rather than stopping at 12 missing cues. Partially successful singleton checkpoints are retained; failure to complete any cue HOLDS episode publication. Never fabricate filler.
- **Post-pass:** check severe density, copied future Japanese, near-duplicate Japanese and explicit speaker-turn layout across the whole episode. Attempt at most TWO targeted isolated cue repairs for flagged cues, stored separately. Unresolved issues HOLD publication.
- **Publication:** only completed QA-approved tracks create NEW *.Bruiser Utterance Recovery v3 Japanese.ja.srt sidecars. Prior published v009/v010 subtitles, any editorial tracks, original video, live SubHub service, SQLite and original v011 attempt records remain unchanged.

**Tradeoff:** The handful of previously failed 2–3 cue units will use singleton fallback instead of grouped translation. This is an **operational recovery**, not demonstrated higher semantic accuracy.

## Owner MacBook command after merge

    cd ~/Downloads/bruiser-subhub-repo
    git pull --ff-only
    bash tools/run_utterance_rescue_011.sh optiplex@100.121.156.34

Runs offline tests on Mac, stages ONLY rescue_utterance_011.py under ~/bruiser-pilot/utterance-011-recovery-code/, executes local Ollama, and appends to ~/Downloads/american-dad-utterance-011-recovery.log. The ORIGINAL host folder ~/bruiser-pilot/utterance-011-code/ stays untouched.

Check RECOVERY_SUMMARY for published_new_recovery or already_published_identical. A command exit code alone does not establish publication. Rerun the identical command to resume valid checkpoints; a changed code or source fingerprint refuses incompatible resume.

## After real publication: private bilingual QA, no inference

    cd ~/Downloads/bruiser-subhub-repo
    bash tools/collect_utterance_rescue_review_011.sh optiplex@100.121.156.34

This read-only SSH export checks original source hashes, exact EN/JA cue IDs and timing, and byte identity with published sidecars. It creates a private tar.gz containing EN/JA SRTs and numerical QA under Mac Downloads. Upload privately to the chat; do NOT commit copyrighted dialogue to GitHub. Compare semantics with v010 and assess ordinary Jellyfin viewing before promoting any whole-library translation worker.

The real host/GPU recovery has NOT yet run. Synthetic offline tests support safety and resumability only; they cannot prove Japanese fluency or Hulu-level quality.
