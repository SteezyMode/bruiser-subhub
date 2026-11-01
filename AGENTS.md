# Bruiser SubHub — developer/assistant handoff

**Read this file, `docs/CURRENT_STATE.md`, and `docs/OPERATIONS.md` before proposing or changing code.** Treat the checked-in source as authoritative for implemented behavior; ask for a fresh read-only status snapshot before claiming anything about the live OptiPlex service.

## Mission

**Read [GOAL.md](GOAL.md) first.** The user and his wife need to watch their existing nearly 6 TB English-language media library with natural, accurate Japanese subtitles. Dual subtitle playback is already solved. Subtitle downloads have been insufficient. The free, local *result* matters; SubHub may shrink or disappear if existing software works better. Do not optimize for product differentiation, dashboard polish, or preserving custom code. OptiPlex NOW integration is optional and not relevant to the immediate goal.

## Current directive after the 10-film pilot

Owner explicitly requested **no more disproportionate work on individual movie edge cases**. Latest report: seven of ten pilot films published, The Descent protected due to existing approved Japanese subtitles, Whistle and Nightmare queued, and the structural contamination scan clean. The next priority is **quality evaluation and library-scale coverage**. Work should produce concrete watchable outcomes for the ~6 TB library, not endless repairs or new dashboards. See the top of `docs/CURRENT_STATE.md` before proposing any engineering.

## Non-negotiable decisions

- Primary translation: local Ollama / Gemma 4 e4b, currently through the legacy `bruiser_auto.py` adapter. **Preserve working prompt behavior** until a measured A/B benchmark supports replacing it.
- HY-MT2: **optional, sampled, advisory**. It can be misleading. Never require HY approval to publish or automatically replace Japanese with HY suggestions.
- Preserve original cue identity/timing. Do not fabricate Japanese for missing cues.
- Existing human/editorial Japanese subtitles must not be overwritten, removed, or silently superseded by an extra machine track. An existing independent Japanese or editorial sidecar must cause a safe publication hold; no automated cleanup of legacy subtitle files. No destructive library scans or migrations without explicit approval and rollback plan.
- The live pilot runs separately from this Git repository. Creating a PR or changing `main` **does not deploy** to the server.
- Do not restart active translation, alter SQLite checkpoints, or run `launch.sh` as an upgrade command. `launch.sh` imports jobs and starts inference.
- Keep media, SRT contents, local SQLite, checkpoint snapshots, IPs, server logs, tokens, and translation memory out of GitHub. Only synthetic examples in tests.

## Do not re-run prompt experiments without checking the ledger

Before any further model, prompt, or language-quality change, read `benchmarks/RUN_LEDGER.md` and the frozen methodology `benchmarks/EXPERIMENT_001.md`. Owner explicitly requested proper A/B controls and permanent GitHub records. Historical published cues are not a fair baseline: they were partially created through a broken SRT batch path. **Fresh baseline, same source, same adapter, same batch sizes, different models/profiles** is the test.

Don't select a model/profile based solely on speed, compression or syntactic validity. Record actual outputs privately, evaluate meaning and unsanitized character voice, record public conclusions with source/model digests and dates. No copyrighted film dialogue or private EN/JA output may be committed to public GitHub.

## Latest translation benchmark caveat

Read `benchmarks/RESULTS_001.md` and `benchmarks/RUN_LEDGER.md` before comparing further models. Real 256-output Benchmark 001 complete: 14 recognized formatting anomalies despite all outputs passing current Japanese validator; no native speaker score or certified 8/10 result. The tuned Gemma 4 Sub model was tested using a GENERIC batch-JSON prompt, not the model author's recommended previous-context/current-segment native prompt. Do not call it a fair model-native comparison or reject the tuned model without testing that format. Official Google TranslateGemma is a different, untested family. Multipass is **optional** and must show net fidelity improvement rather than become an assumed architecture.

## Working practice

1. Recover context from GitHub: source + `docs/CURRENT_STATE.md` + open issues/PRs. Check if the user has newer live status; never infer that the last known worker is still running.
2. Make one focused change per PR on a branch, preferring translation correctness/reliability over cosmetic UI.
3. Add offline regression tests, run `python3 -m unittest discover -p 'test_*.py' -v`, and report the actual count and limitations.
4. Keep `docs/CURRENT_STATE.md` current with decisions, tested functionality, unresolved risks, and *next action*; distinguish **developed**, **merged**, and **deployed**.
5. Explicitly state whether a feature was tested against Ollama/media. Mock-based tests cannot establish translation quality.
6. Provide exact, reversible deployment instructions only after confirming the live worker is idle and the user wants a deploy.

## Urgent translation pipeline defect (found 2026-11-01)

The shipped `service.render_clip()` used positional indexes on SQLite rows. Actual columns begin with job_id, so the model batch input was malformed (`job_id / cue_id / end_ms`). A fix changes to named `timing`/`english` fields, locally renumbers batches and remaps model output back to original cue IDs. This may explain observed `Malformed SRT block` and singleton-heavy fallback. **Merged GitHub code is not a live server deployment.** Verify a real batch against `bruiser_auto.parse_srt` after the worker is idle; do not rewrite existing checkpoints.

## Practical language-quality target (owner clarified November 1)

Target **~8/10 enjoyable Japanese subtitles, clearly better than generic SubtitleCat-style ML output**, rather than professional Netflix 10/10. **Do not sanitize profanity, sexual references, insults, violent threats, slang or sarcasm.** Match social register, speaker intention and tone. Shorten awkward phrasing and filler only while preserving important nuance and punchlines. Favor meaning over word-for-word idioms. A hard character threshold must never delete meaning or block a good line.

An optional `natural_8` profile supplements the existing model system prompt; default production behavior remains unchanged. Benchmark it privately on actual fixed English cues before selecting it for the worker. Synthetic unit tests and character counts cannot establish native Japanese quality.

## Current development priority

Obtain a representative full-film EN/JA editorial QA packet from the existing checkpoints, review concrete meaning/naturalness failures, then compare improvements to the Gemma prompt/context on a fixed evaluation set. Avoid imposing an unproven automatic scoring gate. The read-only `review_sampler.py` supports that process; it does not substitute for an editor.
