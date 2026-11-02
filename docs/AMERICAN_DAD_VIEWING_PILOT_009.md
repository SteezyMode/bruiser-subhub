# American Dad full-episode viewing canary 009

**Goal:** stop model-sweep microclips; create up to five complete, natural Japanese subtitle tracks for American Dad to watch normally with an existing household Jellyfin player. **Provisional single-pass model** is subtitle-tuned Gemma E4B GGUF, pinned digest prefix `9ccfc3b07081`. No claim of verified Japanese-native quality.

## What is implemented

- `tools/american_dad_intake_009.py`: scans only the two configured media roots and recognizes SxxEyy American Dad video files. Verifies English-primary audio with ffprobe, rejects any embedded Japanese subtitling, rejects existing Japanese/editorial sidecars, and extracts verified English **text** tracks via ffmpeg (embedded subrip/ASS/WebVTT/mov_text) or verifies an EN SRT sidecar. Does not fetch pirated or online subtitles. Skips unverified audio/empty sources.
- `tools/american_dad_pilot_009.py`: freezes up to five eligible distinct episode paths, English source SRT SHA-256, cue counts, video size/mtime, series-profile hash, and exact model ID in a PRIVATE create-only manifest. Resume always uses this manifest; the same five are not reselected based on later changes.
- `tools/american_dad_core_009.py`: takes both live worker locks before any model calls and refuses an incompatible loaded Ollama model. Builds concise structured character notes from the curated American Dad series bible, calls the generic Context Engine to generate an advisory **cached** show note and per-episode note using the same local E4B model. For every cue, includes 4 preceding and 4 upcoming English lines, plus two previously accepted JA lines, but translates ONLY the current English line. No internet lore and no compulsory human reviewer.
- Every accepted cue is saved separately in a PRIVATE create-only checkpoint; each cue gets up to two attempted translations. After 12 failed cues in an episode, the runner stops that episode rather than publishing malformed text and continues to remaining selected episodes. A restart resumes accepted cues; failures are preserved with reasons.
- After a fully valid 100% Japanese episode SRT is complete, creates a private draft, then re-verifies original video and English subtitle track content against frozen source hash, and (only with explicit `--publish`) writes a **NEW** `*.Bruiser Pilot Japanese.ja.srt` beside the episode with create-only/no-follow semantics. Existing approved or machine JA is never edited, overwritten, deleted, renamed or silently superseded. Filename differentiates pilot from preexisting Japanese. Jellyfin may need a metadata refresh before external subtitles appear.

## One owner command, from MacBook

```bash
cd ~/Downloads/bruiser-subhub-repo
git pull --ff-only
bash tools/run_american_dad_pilot_009.sh optiplex@100.121.156.34
```

The command runs offline Python regression tests locally, stages ONLY the isolated trial code in `~/bruiser-pilot/american-dad-pilot-009-code/` on the host, freezes the episodes, runs the pinned E4B translator sequentially in the foreground, and requests create-only pilot publication. It does NOT install a service, change a production worker, update SubHub SQLite, or touch previous human Japanese subtitle files. Its local console log is saved as `~/Downloads/american-dad-pilot-009.log`. Host-private checkpoints are under `~/bruiser-pilot/american-dad-pilot-009/`.

To check progress without retranslating anything:

```bash
ssh optiplex@100.121.156.34 'python3 ~/bruiser-pilot/american-dad-pilot-009-code/american_dad_pilot_009.py status'
```

Re-running the same MacBook command reuses already frozen selected episodes and accepted cue checkpoints. An episode marked `incomplete` has no newly created Japanese sidecar; a later retry won't silently regenerate previously accepted lines or replace the existing approved output.

## Boundaries and known limitations

- **Nothing has been run on the user's actual host in this PR.** The tests are offline, with synthetic English dialogue and mocked translations, so they prove structural safeguards, NOT Japanese naturalness, episode inventory, live GPU capacity or Jellyfin ingestion.
- The first five accessible eligible episodes are deterministic by media-path iteration; older episodes, duplicate versions, unavailable/untagged audio, subtitle-less files, and those with existing JA are skipped. If only 2 eligible episodes exist, the runner selects 2 and reports that; it does not invent 5. Some videos with untagged English streams may need a separate verified intake workflow later.
- New-source discovery currently walks the configured roots and can take time on a large library; follow-up use of Jellyfin's library index can be an optimization later. No live worker alterations are needed for this pilot.
- This run deliberately does not add a second translator, multi-model election, automated dialogue rewriting, automatic alias-research agent, or viewer score sheet. The criterion is actual full-episode viewing during ordinary use. Advance to more of the library only after the result is acceptable.

