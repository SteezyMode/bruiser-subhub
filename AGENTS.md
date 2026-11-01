# Bruiser SubHub — developer/assistant handoff

**Read this file, `docs/CURRENT_STATE.md`, and `docs/OPERATIONS.md` before proposing or changing code.** Treat the checked-in source as authoritative for implemented behavior; ask for a fresh read-only status snapshot before claiming anything about the live OptiPlex service.

## Mission

Bruiser SubHub is a daily-use, **local English → Japanese subtitle localization service** for a personal media server, not a dashboard project. Primary value is accurate, natural, context-sensitive Japanese with durable per-cue progress and safe media publishing. A future OptiPlex NOW integration is optional; keep the translation engine and its release lifecycle independent.

## Non-negotiable decisions

- Primary translation: local Ollama / Gemma 4 e4b, currently through the legacy `bruiser_auto.py` adapter. **Preserve working prompt behavior** until a measured A/B benchmark supports replacing it.
- HY-MT2: **optional, sampled, advisory**. It can be misleading. Never require HY approval to publish or automatically replace Japanese with HY suggestions.
- Preserve original cue identity/timing. Do not fabricate Japanese for missing cues.
- Existing human/editorial Japanese subtitles must not be overwritten. No destructive library scans or migrations without explicit approval and rollback plan.
- The live pilot runs separately from this Git repository. Creating a PR or changing `main` **does not deploy** to the server.
- Do not restart active translation, alter SQLite checkpoints, or run `launch.sh` as an upgrade command. `launch.sh` imports jobs and starts inference.
- Keep media, SRT contents, local SQLite, checkpoint snapshots, IPs, server logs, tokens, and translation memory out of GitHub. Only synthetic examples in tests.

## Working practice

1. Recover context from GitHub: source + `docs/CURRENT_STATE.md` + open issues/PRs. Check if the user has newer live status; never infer that the last known worker is still running.
2. Make one focused change per PR on a branch, preferring translation correctness/reliability over cosmetic UI.
3. Add offline regression tests, run `python3 -m unittest discover -p 'test_*.py' -v`, and report the actual count and limitations.
4. Keep `docs/CURRENT_STATE.md` current with decisions, tested functionality, unresolved risks, and *next action*; distinguish **developed**, **merged**, and **deployed**.
5. Explicitly state whether a feature was tested against Ollama/media. Mock-based tests cannot establish translation quality.
6. Provide exact, reversible deployment instructions only after confirming the live worker is idle and the user wants a deploy.

## Current development priority

Obtain a representative full-film EN/JA editorial QA packet from the existing checkpoints, review concrete meaning/naturalness failures, then compare improvements to the Gemma prompt/context on a fixed evaluation set. Avoid imposing an unproven automatic scoring gate. The read-only `review_sampler.py` supports that process; it does not substitute for an editor.
