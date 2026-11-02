# American Dad pilot 009 — all five actual episodes published (2026-11-02)

**Owner-confirmed from uploaded `american-dad-pilot-009(2).log`: five complete Japanese subtitle SRTs were published to the OptiPlex media library; 2,066/2,066 English cues have structurally accepted Japanese.** This establishes output completeness and successful create-only publication, **NOT Japanese native fluency, semantic fidelity or Hulu-comparable quality**.

## Real published episodes

| Episode | English/Japanese cues | Actual state |
|---|---:|---|
| S19E01 — Langley Dollar Listings | 400/400 | `published_new_pilot` at final cached-only run |
| S19E03 — The Book of Fischer | 394/394 | `already_published_identical` at final run |
| S19E04 — A Roger Story | 392/392 | `already_published_identical` at final run |
| S19E05 — Epic Powder Dump | 359/359 | `already_published_identical` at final run |
| S19E06 — American Dad Graffito | 521/521 | `already_published_identical` at final run |

The final blocked cue (S19E01 #321) was accepted from **existing saved real Japanese** after narrowly validating italic SRT markup; no Ollama translation call was needed. Source, successful checkpoints, old failure records, and published sidecars of the other four episodes were preserved.

## Next: real full-episode bilingual subtitle review

The user says the earlier hand-localized `FROM` tracks were rated roughly 7.5–8.5/10 relative to Hulu-style streaming subtitles, and found excellent for personal use. **That is a target, not a current measured score.** User wants the assistant to review these five full English/Japanese SRT pairs and report concrete context/joke/character/meaning issues. Do not assign a score from an `accepted_ja` pass or from `PILOT_SUMMARY` only.

Private source and Japanese SRTs are on the owner's host under `~/bruiser-pilot/american-dad-pilot-009/episodes/<episode>/source.en.srt` and `pilot.ja.srt`. A user-created tar archive should contain only `manifest.json` plus five pairs; DO NOT commit movie/subtitle dialogue into public GitHub.

MacBook one-command archive creation:

```bash
ssh optiplex@100.121.156.34 \
  'cd ~/bruiser-pilot/american-dad-pilot-009 && tar -czf - manifest.json episodes/S19E*/source.en.srt episodes/S19E*/pilot.ja.srt' \
  > ~/Downloads/bruiser-american-dad-five-episodes-review.tar.gz
```

This is read-only against the host, doesn't transfer video files, and makes one local private archive the owner can upload. Then assistant can assess all 2,066 cue pairs, targeted contextual dialogue sequences, name consistency, slang and comedy, punctuation, reading density and preservation of timecodes. Human native viewing still provides the best final entertainment/watchability signal, but no separate repetitive reviewer assignment is required.

**Current state:** 5/5 subtitle tracks exist according to host log. Actual Japanese SRT text has NOT yet been received or graded by the assistant in this turn. Jellyfin may need a metadata refresh to expose new external tracks.
