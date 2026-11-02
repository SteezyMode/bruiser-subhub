# Bruiser SubHub — developer/assistant handoff

**Read this file, `docs/CURRENT_STATE.md`, and `docs/OPERATIONS.md` before proposing or changing code.** Treat the checked-in source as authoritative for implemented behavior; ask for a fresh read-only status snapshot before claiming anything about the live OptiPlex service.

## Current definitive experiment findings (read before new model work)

**Benchmark 004 COMPLETED with owner's uploaded private outputs (2026-11-02 JST).** Read `benchmarks/RESULTS_004.md` and `benchmarks/RUN_LEDGER.md`. Official Google TranslateGemma4B Gemma3 Q4_K_M gave 80/80 valid structural outputs but significantly more awkward, formal, too-dense Japanese and serious meaning/slang errors. On the **same sixteen previously-unseen cues**, Google median 9.0 Japanese chars/sec; tuned 17slever17 subtitle Gemma4 E4B native profile median 6.6, both with two >14 chars/sec; tuned generally more semantically faithful and natural, but still has errors. No independent native Japanese grade, therefore not 8/10-certified. **The Google trial is completed, not pending; do NOT propose or re-run it without new evidence.** All benchmark code ran in scratch and did not switch the live translation engine. Preferred provisional candidate is tuned E4B's native CURRENT_SOURCE/previous-pairs prompt of Benchmark 002, not legacy multi-cue JSON. Owner dislikes circular prompt tests and individual-film fixes. Next: watch a short film section with Japanese-only subtitles, obtain viewer feedback, then safe new-job library scale; multipass only if controlled net benefit.

## Owner-approved comprehensive translation test (Benchmark 005)

Owner explicitly wants systematic testing of **all viable November 2026 translation model candidates**, superseding earlier advice to stop after one native-Japanese viewing check. The frozen, publicly preregistered plan is `benchmarks/EXPERIMENT_005.md`; read it BEFORE changing weights, samples, prompts or score rubric. Run only by explicit owner command against own OptiPlex. FIVE arms: current native tuned E4B, final CAT 3.3B Transformers NF4, final CAT 7B GGUF, Hy-MT2 7B official GGUF (STQ compatibility may block), Google TranslateGemma 12B with CPU offload. Source = 64 NEW source-hashed Primate cues disjoint from 001–004. Separate private results plus blind review pack/identity key. No hallucinated test result, no beta CAT labelled final, no automatic replacement of production service/SRTs, and no unverified claim of actual 8/10 quality. Compare fidelity, unsanitized tone, Japanese naturalness, timing, runtime/cost; later verify on another film and native-Japanese viewer before bulk scale.

## Benchmark 005 partial REAL runs (2026-11-02): HONOR BLOCKERS

Real data in `benchmarks/RESULTS_005_PARTIAL.md`: Hy7, Google12, CAT7 each ran same 64 NEW English source cues. Hy-MT2 7B Q4 looks promising on human-like English→Japanese dialogue (assistant-only 61/64 tied/best), Google12 more formal/slower, CAT7's GGUF/Ollama implementation produces abundant `assistant` labels, translations mixed with explanations, two output token limit errors, only 59/64 valid. **IMPORTANT** CyberAgent specifically says CAT 7B needs a chat template DIFFERENT from other CAT models: confirm template mismatch before calling model weights bad. **TUNED control BLOCKED preflight; FINAL CAT3.3B CUDA lane BLOCKED/incomplete; no underlying failure log uploaded.** Do NOT claim benchmark complete or Hy beats the originally preferred tuned model until both share the same cue set.

One new `tools/diagnose_model_sweep_005.sh HOST` read-only command diagnoses both failed arms. Once user supplies output, fix precise compatibility cause and rerun JUST missing arms; don't redownload/retranslate successful HY/Google/CAT arms. All full film dialogue and unblinded model responses stay private. No production deployment or 8/10 native-Japanese score is established.

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

## Frozen next experiment

Read `benchmarks/EXPERIMENT_002.md` before new model or prompt work: the user approved **one native-format test** of already-installed subtitle-tuned Gemma e4b using the same 64 English cues as Benchmark 001. Use single CURRENT_SOURCE and up to two previous generated source/translation pairs (not historical Japanese), observe exact frozen model ID. This experiment is **not** a commitment to a multipass architecture. Keep all movie dialogue/model results private and log structural metrics + adjudicated conclusions in public `benchmarks/RUN_LEDGER.md` only after actual execution.

## Latest model-spec audit and bounded experiment

Benchmark 002 successfully used developer-style `CURRENT_SOURCE` and previous pairs, **but not strictly the card's minimal settings**. See `benchmarks/RESULTS_002.md` for exact measured 64-cue outcome, eight stale-context transitions and model/runtime differences. No actual 8/10 certification. Before making further prompt changes read `benchmarks/EXPERIMENT_003.md`: two arms use the same literal-ish card prompt, one prior pair and fixed generation settings; the *only* within-experiment difference is an 8-second stale-context cutoff. Both remain read-only Ollama tests. After benchmark 003 and short native Japanese viewing review, favor choosing a practical single-pass workflow; multi-pass remains optional only with proven net gain. Stop unnecessary prompt churn.

## Latest verified evidence and stop rule (Benchmark 003)

Benchmark 003 has **run on the user's Ollama** and its private 128-output JSON was reviewed: both arms 64/64 returned, zero format artifacts, 7 over 14 JA chars/sec, median 6.85; 8s stale-context cutoff changed 6/64 outputs with no compelling net benefit. Full result in `benchmarks/RESULTS_003.md`; community/author/model memory/japanese subtitle research in `benchmarks/COMMUNITY_RESEARCH_2026-11-02.md`. Do **not** rerun prompt micro-tuning, switch to bigger weights on the 6GB card without a supported reason, invent speaker names, treat Japanese as low-resource, or install multiple models by default. Japanese tier-1 trained; harder features are English slang, voice/register/omission, short timings. No native-speaker 8/10 evaluation yet. Highest-value next step: real Japanese-only short film viewing report, then proceed to guarded library processing or one substantive model/context intervention if genuinely needed.

## Frozen distinct-model test (Benchmark 004)

Before proposing any more prompt settings or multiple-model architecture, read `benchmarks/EXPERIMENT_004.md` and `benchmarks/RUN_LEDGER.md`. Owner explicitly approved one trial of Google's **official Gemma 3 TranslateGemma 4B Q4_K_M** using Ollama's documented language-specific single-user prompt, **not** the legacy Gemma4 batch prompt or custom profanity profile. Compare old 64 frozen anchor cues and two 8-cue held-out windows at IDs 515/625 with 16 corresponding fresh subtitle-tuned Gemma4 native outputs; privately evaluate actual semantic intent/sexual slang/profanity/fluency/readability. No model availability or quality is proven until owner runs command. No production changes, no mass retranslation, no hypothetical 8/10 grades. Model download is an explicit ~3.3GB owner-side action after source verification.

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
