# ContextSafe v010 — REAL three-episode host result and private review

**November 2, 2026.** Owner-provided 27-line pilot log confirms NEW, actually-published Japanese subtitle tracks.

| Episode | Accepted cues | Future-JA overlap flags | Severe density | >18 JA chars/sec |
|---|---:|---:|---:|---:|
| S19E07 | 454/454 | 0 | 0 | 2 |
| S19E08 | 455/455 | 0 | 0 | 0 |
| S19E09 | 406/406 | 0 | 0 | 1 |
| **Total** | **1,315/1,315** | **0** | **0** | **3** |

All episodes returned published_new_contextsafe, zero repairs and zero unresolved cues. These are engineering checks, NOT independent Japanese-language or entertainment scores, nor proof of FROM-grade 7.5–8.5/10 output. Prior v009 had 84 overlap candidates over 2,066 cues, with next-four-English generation context. Fresh v010 has no detected carryover. Its screening thresholds also differ slightly; comparisons are suggestive, not controlled quantitative quality conclusions.

One nonfatal anomaly: series auto-context generation failed strict schema validation with ValueError Context field must be a short list: names. The curated series guide and current/previous source prompts still applied; do not assume per-episode context failed. Do not regenerate the completed 1,315 cues just to address this optional note; fix future auto-context output handling separately based on evidence.

## Next owner command (MacBook, after merge)

    cd ~/Downloads/bruiser-subhub-repo
    git pull --ff-only
    bash tools/collect_contextsafe_review_010.sh optiplex@100.121.156.34

This read-only SSH operation verifies the frozen source SHA, exact English/Japanese cue IDs and timings, and the byte-identical already published sidecars before streaming a PRIVATE English+Japanese three-episode tar.gz into MacBook Downloads. It neither calls Ollama nor modifies the host state, media, subtitles or database.

Upload that private archive in the conversation for actual bilingual dialogue inspection, and watch episodes normally in Jellyfin for independent household assessment. Copyrighted English/Japanese scripts and private media paths MUST NOT be checked into the public repo. Do not promote v010 into the live 6TB library-wide worker based on mechanical success alone.
