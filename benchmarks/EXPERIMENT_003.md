# Benchmark 003 — near-literal model-card configuration, controlled stale context

**PRE-REGISTERED; real local model run NOT YET PERFORMED.** Read measured [RESULTS_002.md](RESULTS_002.md) and [RESULTS_001.md](RESULTS_001.md) first. Goal: assess whether the installed subtitle-tuned model can improve beyond Benchmark 002 by honoring the model author's minimal prompt and avoiding irrelevant old context. This is NOT a general reoptimization of the whole subtitle pipeline and NOT a multi-pass system.

## Frozen inputs and model

- Exactly the same Primate job, source SHA `8967cfea3f6552c0a6b1645da13e0d79e62be2decb95c02c653e6a345c3b645a`, eight windows x 8 cues = 64 cue IDs as Benchmarks 001 and 002.
- Installed model must be `hf.co/17slever17/translate-gemma-4-sub-e4b-GGUF:Q4_K_XL` with Ollama ID `9ccfc3b07081`; abort if not installed/matching. No downloads, no changes to model weights.
- Both arms use the developer's [documented system/task style](https://huggingface.co/17slever17/translate-gemma-4-sub-e4b-GGUF) with `TASK: Translate English subtitles into Japanese.`, `STYLE: neutral.`, `CURRENT_SOURCE` and, if eligible, one previous `PREVIOUS_SOURCE`/`PREVIOUS_TRANSLATION` pair.
- Both arms use Ollama `/api/chat` `temperature=0`, `num_ctx=1344`, `num_predict=256`, `think=false`, `stream=false`. Context and output settings mirror the developer's llama.cpp Python example, but **Ollama remains a distinct runtime**. The source-language and target-language system statement matches the developer's template, optional RULES field is omitted since speaker name/gender is not reliably known, and no invented speaker metadata is injected.
- Current and previous source/translation cues are **real English and newly generated, structurally clean Japanese** from the same isolated arm/window; no old editorial Japanese or future lines enter the prompt. If immediate prior cue failed or was structurally malformed, context is omitted rather than reaching back to older unrelated speech.

## Exactly two arms

| Arm | Current subtitle | Previous subtitle pair | Difference |
|---|---|---|---|
| A `card_previous` | Same 64 source cues | Immediate previous successfully generated source/JA in same frozen block | Reference card-style context |
| B `card_previous_gap8` | Same 64 source cues | Same immediate prior pair **only if** the silent gap between previous cue end and current cue start is **at most 8.0 seconds** | **Only variable is the stale-context cutoff** |

The cutoff is **a predeclared hypothesis**, not a claim that eight seconds is the right boundary for film dialogue. Eight within-window transitions in Benchmark 002 crossed 8 seconds (including 23.54, 30.99, 44.22 and 45.18 seconds), so this is a useful measurable distinction. Block boundaries remain frozen like the prior experiments. Arms alternate first within the eight windows to reduce systematic model warmup bias.

**Benchmark 002 versus 003 is not a one-factor comparison.** Benchmark 002 had extra horror style guidance, up to two previous pairs and larger max generation/context settings. The controlled comparison in Benchmark 003 is strictly A vs B *within Benchmark 003*, with identical prompt, model and inference parameters. Relative to Benchmark 002, compare results qualitatively but avoid claiming causal attribution to any single parameter.

## Evaluation

- Numeric: 64 attempts per arm, response/validator counts, model-call errors, recognizable formatting anomalies, chars/sec (median; count >14), total reported model seconds; one cue per API call. Automatic checks do not judge actual Japanese quality.
- Manual: original meaning, speaker intent, omissions, idioms, slang/sexual/violent profanity, Japanese conversational fluency, scene-appropriate speaker voice and on-screen readability. Don't reward fewer chars if important dialogue is lost.
- The primary practical criterion is whether the more conservative model-card prompt produces better unsanitized, natural Japanese, and whether context gating removes wrong assumptions without degrading conversational continuity. **No native-speaker 8/10 score has yet been established.**
- If there is no clear improvement: stop prompt churn, keep the most reliable single-pass model and move toward a brief Japanese-only viewing trial. Optional selective multi-model review should be explored only if it demonstrates net improvement.

## Safe execution after code merges

From Mac mini: `cd ~/Downloads/bruiser-subhub-repo && git pull --ff-only && bash tools/run_model_card_003.sh optiplex@100.121.156.34`.

The command runs offline tests, copies only benchmark scripts into a **separate scratch folder**, preflights the frozen model and source, then holds both existing worker locks while running 128 small local Ollama calls. Private create-only JSON is copied to Mac mini Downloads. Nothing alters the actual translator, queue, model installation, SQLite cue data, Japanese subtitles or media. Do not run if the GPU is needed for gaming or another active Ollama job.

**Private input/output belongs outside public GitHub.** After uploading the resulting JSON privately, record only aggregate metrics and paraphrased failure classes in `benchmarks/RUN_LEDGER.md` and choose a practical path.

## Result

**NOT RUN AGAINST THE MODEL YET.** CI/unit tests demonstrate code mechanics, not Japanese subtitle quality.
