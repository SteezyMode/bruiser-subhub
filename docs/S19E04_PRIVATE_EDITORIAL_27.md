# S19E04: private editorial correction of the final 27 cues

## Actual source

Owner submitted a real private JSON report generated from S19E04 on November 3, 2026: **392 real cues, 27 remaining flagged after v1 and bounded v2**. The report included cue IDs/timings, original English/Japanese and following lines. A private editorial correction JSON was prepared for exactly those 27, not committed to public GitHub.

Four of the remaining cues (8, 52, 76, 77) visibly contained copied-ahead dialogue. Most remaining cues were longer than the overly rigid 18-characters-per-line / 32-per-cue formatting gate even at comfortable Japanese characters-per-second. Cue 338 was a legitimate original negation-vs-affirmation repetition that the old future-overlap heuristic could falsely flag. Versioned line-level editing is more appropriate than repeating exhausted model prompts indefinitely.

## Inputs and safety

- Public code: `tools/s19e04_apply_private_editorial.py` and `tools/apply_s19e04_editorial.sh`.
- **Private payload:** `s19e04_private_editorial_27.json` is distributed directly to the owner through the conversation, NOT this repository. Contains only 27 corrected JA texts, each original English SHA256 and original Japanese SHA256, and cue numbers. Private payload should NOT be git-added, shared publicly or used to retrain a model.
- Each correction must match the **original** English and Japanese from the actual pilot for that exact cue. Unexpected cue numbers, missing/extra edits, unchanged source fingerprints, abnormal QA output or changed media all prevent publication.
- The patch reconstructs all **392** Japanese cues by combining the immutable original S19E04 pilot, preexisting accepted v1/v2 cue checkpoints, and the owner's private 27-cue editorial corrections. No private accepted checkpoints are rewritten. The frozen original manifest must still match video size/mtime, English SHA, original Japanese SHA, model and original quality SHA.
- Runs full existing `subtitle_publish_gate.audit`, including screen-line limits, reading speed and copied-ahead detection. If ANY cue still fails, it records a concise hold and publishes nothing.
- After full QA, renders a **complete 392-cue SRT**, preserving original cue IDs/timing, writes a *private create-only preview*, then optionally atomically publishes the **separate** `VIDEO.Bruiser Curated Japanese v2.ja.srt` alongside the original `VIDEO.Bruiser Pilot Japanese.ja.srt`. Existing pilot, earlier versioned repairs and checkpoint files remain intact. The source video is unchanged.
- The tool is deterministic and makes **zero model/GPU calls**. There is no timer or background process; the MacBook remains connected while it runs. It also refuses if the live S19 repair or S20 maintenance systemd service is active.

## Mac mini command after merge

1. Download the private file `s19e04_private_editorial_27.json` from this conversation into `~/Downloads` on the Mac mini.
2. Run:

```bash
cd ~/Downloads/bruiser-subhub-repo
git pull --ff-only
bash tools/apply_s19e04_editorial.sh optiplex@YOUR_HOST ~/Downloads/s19e04_private_editorial_27.json
```

The wrapper runs synthetic offline tests, stages isolated code and private corrections under user-owned host folders, checks 392 real cues and old original hashes, generates a private preview, runs whole-episode QA, then creates the separate versioned external JA SRT only if clean. It does **not** modify Jellyfin settings; Jellyfin may require a library rescan before the new subtitle track becomes selectable.

A successful actual run must show **`S19E04_EDITORIAL_PUBLISHED`**, not just `S19E04_EDITORIAL_PRIVATE_PREVIEW` or green tests. If held, inspect numeric remaining reasons and return to only those specific cues. This has not been run on live OptiPlex until the owner executes the command.

This is an editorial first-pass on the 27 remaining flagged cues, not a full 392-cue human linguistic QC pass. Source comedic details, cultural notes, and longer scene context may still need evaluation by a native Japanese speaker after selecting the new track in Jellyfin.
