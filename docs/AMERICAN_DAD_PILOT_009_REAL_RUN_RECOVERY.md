# American Dad pilot 009 — real five-episode result and 7-cue recovery

**Source:** user-uploaded `american-dad-pilot-009.log` after the real OptiPlex run on 2026-11-02. These results reflect actual local inference, not CI mocks or proof of native Japanese subtitle quality. Only aggregate technical data is committed; private subtitle text and media paths remain on host.

## Real production-adjacent pilot outcome

| Episode | English cues | Accepted Japanese | Result |
|---|---:|---:|---|
| S19E01 | 400 | 398 | incomplete; two unaccepted cues; not published |
| S19E03 — The Book of Fischer | 394 | 394 | **published_new_pilot**; new distinct Japanese sidecar |
| S19E04 — A Roger Story | 392 | 392 | **published_new_pilot**; new distinct Japanese sidecar |
| S19E05 | 359 | 355 | incomplete; four unaccepted cues; not published |
| S19E06 | 521 | 520 | incomplete; one unaccepted cue; not published |
| **TOTAL** | **2066** | **2059** | **2 published / 3 held / 7 missing** |

The published files have names ending `.Bruiser Pilot Japanese.ja.srt` and are intended for a Jellyfin metadata refresh and normal full-episode playback. **No native-speaker watchability verdict has been collected.** The pilot remains tuned E4B with optional automatic show/episode context and current-cue translation with neighboring English.

## Exact failure and minimal fix (PR #36)

Previous pilot code called the model only twice per problematic cue and saved both failed responses in private immutable per-attempt files. On a subsequent run, it always skipped attempts 1/2, leaving the cue unaccepted forever and thus suppressing publication of three almost-complete episode SRTs. The source log showed the seven missing cues, but **did not include their exact cause or English lines**; do not assert they were names, punctuation, or hard slang.

The updated runner attempts **up to four more times on previously unaccepted cues only (attempts 3–6)** with fixed simpler current-cue-focused prompts. It retains **the same model ID**, frozen source, timings, original per-cue Japanese checkpoints, old error records, private draft and existing published pilot SRTs. It never reruns valid cues. If a cue remains unaccepted after six total attempts, it remains held and reports only numeric missing cue IDs. No forcing English through the Japanese validator; no outside model; no editing of published SRTs.

## Owner next command (after PR merge)

```bash
cd ~/Downloads/bruiser-subhub-repo
git pull --ff-only
bash tools/run_american_dad_pilot_009.sh optiplex@100.121.156.34
```

Local regression suite and shell syntax run before staging files on the remote host. The `prepare` step reuses the existing immutable five-episode manifest. The runner immediately recognizes S19E03/S19E04 as already-published-identical, translates only the 7 missing cues on the other episodes, and creates a **new** Japanese subtitle sidecar only for each fully completed episode after source and existing-JA checks. The original MacBook log is **appended to**, not overwritten. Actual success/new sidecars are confirmed only by the next host run, NOT by merging CI code.

**Why this is aligned with user's priority:** finish complete American Dad episodes to watch naturally; no more movie benchmarking, huge blind review workloads, or Natsuyo test assignments.
