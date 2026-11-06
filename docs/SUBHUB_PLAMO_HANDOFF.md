# SubHub PLaMo 8B queue handoff (guarded pilot)

Status Nov 6 2026: code committed, **not installed or GPU-tested on the OptiPlex**. This is a one-item source-first adapter, not yet the entire unattended recovery and translation pipeline.

The existing working PLaMo 8B translator is specific to American Dad episodes; it has proven 28 GPU layers, 2 CPU threads, an official Q4_K_M model, thermal limits, SQLite per-cue checkpoints and create-only publication. We now reuse those components from tools/subhub_plamo_handoff.py while selecting exact Jellyfin media from the one existing coverage queue. No new translation framework or model experiments.

## Safety and modes

- Default no-argument mode: read-only listing of up to 15 source-exhausted Japanese subtitle tasks; no GPU/provider/media actions.
- --prepare --jellyfin-id EXACT-ID: check trusted media path, absence of JA, EN audio and matching EN source. Extract embedded text or ffsubsync-audit external EN. Save immutable private English cue source and SHA/video/model identity. No GPU start or published sidecar. First pilot accepts only 150–1500 cues; other cases hold.
- --apply --jellyfin-id EXACT-ID: requires source batch and daily source worker inactive and prior American Dad translator inactive. Uses installed PLaMo 8B engine with measured GPU offload and thermal safety, commits every translated cue, recovers from checkpoints, validates entire output and creates a Japanese sidecar only when none exists. Do not use until after owner verifies preflight and test installation.

The pinned installer tools/install_subhub_plamo_handoff.sh runs AST preflight and 12 isolated offline tests, checks the previously installed PLaMo runtime without replacing it, and provides the local command ~/.local/bin/subhub-ai. Installing does not start GPU work, change any source batch, or alter OptiPlex NOW.

## Still needed for completely unattended operation

1. Exact-identity English subtitle recovery for missing-EN queue entries and bitmap subtitle OCR, with strict timing validation.
2. Safe translation of longer movies and appropriate routing for non-English audio; first adapter only covers EN-audio to JA with 150–1500 cues.
3. One durable controller-owned dispatcher with job claiming, cooldown and boot recovery, not an additional scheduler; never launch two PLaMo workers.
4. True translation progress in the standalone dashboard and zero-touch Jellyfin intake of new media.

Issue #67: https://github.com/SteezyMode/bruiser-subhub/issues/67

Do not change the live source worker or claim this adapter is host-deployed merely because it is committed.
