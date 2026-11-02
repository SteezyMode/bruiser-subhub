# SubHub Utterance v011 — REAL incomplete host run; diagnose before repair

**November 2, 2026.** Owner uploaded the actual 15-line three-episode v011 run log.

| Episode | Source cues | Accepted before stop | Unaccepted at stop | State |
|---|---:|---:|---:|---|
| S19E10 | 372 | 219 | 153 | incomplete |
| S19E11 | 409 | 192 | 217 | incomplete |
| S19E12 | 408 | 346 | 62 | incomplete |
| **Total** | **1189** | **757** | **432** | **no published sidecars** |

**CRITICAL:** 432 unaccepted cues are NOT 432 individually failed inference attempts. The original v011 runner stops after 12 accumulated failed cue IDs per episode, leaving the remainder unattempted. The log's numeric missing-cue list includes large unattempted tails. Per-attempt error descriptions are saved privately under attempts/*.json on the host, NOT in the MacBook log. Do not guess whether failure was JSON mapping, language validation, density, model length, or network without reading them.

Original v011 allows attempts 1–3, persists failed attempts create-only, and skips those same attempts after a restart. Accumulated failures can leave a rerun perpetually stalled. Never delete good unit checkpoint JSON or reset the episode. Never silently rewrite original v011 frozen runner files: pipeline_sha specifically pins the exact original three source modules.

## Owner command — READ ONLY, no inference

Run on MacBook after merging this change:

    cd ~/Downloads/bruiser-subhub-repo
    git pull --ff-only
    bash tools/diagnose_utterance_011.sh optiplex@100.121.156.34

It pipes a standalone Python inspector to host Python via SSH; it does not stage host files, call Ollama, or change checkpoint state. It validates source hashes, expected group partition, stored unit identities, attempt numbering and frozen runner fingerprint. Output contains counts of accepted/failed/not-attempted units, grouped failure categories and numeric cue IDs, but NO English/Japanese text, media paths, model raw replies or secrets. The wrapper saves a timestamped MacBook JSON under ~/Downloads/utterance-011-diagnostic-<UTC>.json. Upload that JSON to the conversation.

## Next code change — after identifying actual failure category

Build a separate v011 recovery adapter preserving the ORIGINAL runner and accepted 757 cue checkpoints; do not overwrite existing source/translated media or retranslate good units. Inference recovery should be bounded and specific to failed groups, under both existing subtitle locks and model-residency preflight. Fix structured JSON handling only if real errors implicate it. A guarded fallback may be reasonable, but requires evidence. Do not repeat full runs or launch a new model tournament.

Only after complete QA and bilingual review do we have any basis to assess v011's Japanese quality versus v010 or promote a generic layer to live SubHub.
