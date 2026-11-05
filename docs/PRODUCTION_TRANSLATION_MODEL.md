# PRODUCTION TRANSLATION MODEL — AUTHORITATIVE DECISION

**Decision: November 4, 2026. Status: INSTALLED operational E4B default; quality winner unverified.**

> **NOVEMBER 5 RESEARCH QUALITY OVERRIDE:** [Read the completed historical experiment audit and STOP decision](TRANSLATION_RD_STOP_DECISION_2026-11-05.md). Nine distinct model configurations already produced 2,457 translations on the new three-film Benchmark 006 corpus; its native-Japanese quality winner was never established. The November 4 "best-supported" language below describes an **operational default** and does **not** supersede Benchmark 006's blind-viewing requirement, justify scaling, or approve more E4B prompt tuning. Preserve the currently installed model unchanged while research is paused.

**Chosen model: 17slever17 Translate Gemma 4 Sub E4B, GGUF Q4_K_XL.** Do not silently substitute generic Gemma 4, Hy-MT2, Google TranslateGemma, or any other candidate.

Exact Ollama model name (copy literally):

    hf.co/17slever17/translate-gemma-4-sub-e4b-GGUF:Q4_K_XL

Pinned installed Ollama digest prefix: **9ccfc3b07081**. Family: **gemma4**. Model-card quantization tag: **Q4_K_XL**. The exact known installed model previously reported Q4_K_M in Ollama /api/show despite its Q4_K_XL tag; this metadata mismatch alone is not a reason to redownload it, change versions or reject its verified digest.

**Official author instructions:** https://huggingface.co/17slever17/translate-gemma-4-sub-e4b-GGUF

**Primary current code:** [tools/subtitle_tuned_production.py](../tools/subtitle_tuned_production.py), [service.py](../service.py), [main.py](../main.py), [tools/daily_worker.py](../tools/daily_worker.py).

## Why this model is our selected primary

It is the **best-supported provisional single-pass choice for this household's EN→JA spoken subtitle workload**, not a proven universal winner or independently verified 8/10.

Our matched 64-cue, real-OptiPlex paired test found:

| Metric | Subtitle-tuned E4B | Hy-MT2 7B |
| --- | ---: | ---: |
| Same cues completed | 64/64 | 64/64 |
| Format issues | 0 | 0 |
| Median Japanese characters/second | 6.6 | 7.45 |
| Cues above 14 characters/second | 0 | 1 |
| Model-call time | 61.98 seconds | 81.96 seconds |
| Assistant-only preferred | **26** | 15 |
| Assistant-only ties | 23 | 23 |
| Native Japanese household viewing grade | NOT MEASURED | NOT MEASURED |

Source: [the recorded paired comparison](../benchmarks/RESULTS_005_TUNED_HY_PAIRED.md). Earlier [Benchmark 002](../benchmarks/RESULTS_002.md) found 64/64 native-formatted model outputs with zero recognized formatting artifacts, though semantic issues remained. [Benchmark 004](../benchmarks/RESULTS_004.md) favored subtitle-tuned E4B over Google's smaller official TranslateGemma on natural dialogue. The *Attachment (2022)* generic Gemma run produced a published but roughly 5.5/10-reviewed track; its translation model was **NOT** subtitle-tuned E4B.

Hy-MT2 7B remains an interesting **research alternative**. The separate November 3 experimental Hy-MT2 clean baseline was promising on 30 cues, but its full-episode chunked SRT path stopped on a structural issue. Neither model has been certified by a native Japanese viewer at 8/10.

**Decision precedence:** This November 4 production decision **supersedes** the November 3 Hy-MT2 experimental recommendations in earlier README, GOAL and docs/TRANSLATION_MODEL_BASELINE. Those older results remain historical evidence, not current production instructions. The user subsequently chose subtitle-tuned E4B for practical use and viewing. No future assistant should use an older benchmark's “current best” wording instead of this decision.

## Exact developer-trained subtitle interface

One **single CURRENT_SOURCE cue per model call**. Previous context is **never** translated or returned as output.

System message (copy this entire message; source English, target Japanese; STYLE neutral is from the author's documented styles):

~~~text
TASK: Translate English subtitles into Japanese.
STYLE: neutral.
Translate only CURRENT_SOURCE. PREVIOUS_SOURCE and PREVIOUS_TRANSLATION are context only. Preserve meaning, tone, slang, profanity, uncertainty, repetitions and incomplete speech. Return only the final translation without labels or commentary.
~~~

User message when an immediately previous, same-source, same-model translated cue exists:

~~~text
[PREVIOUS_SOURCE]
previous English cue

[PREVIOUS_TRANSLATION]
previous Japanese cue

[CURRENT_SOURCE]
this cue's English text only
~~~

If previous valid context doesn't exist, supply **only** the CURRENT_SOURCE section. The production adapter supplies at most **one immediately preceding cue**, including across arbitrary native 12-cue worker batches. Never inject future dialogue, inferred speaker genders, unverified glossaries, legacy-model Japanese or whole-film translations as context. No invented RULES block is used. An optional verified glossary is a separate documented decision, not a default.

**Runtime:** Ollama /api/chat, separate system/user roles, stream=false, think=false; **temperature 0**, **num_ctx 1344**, **num_predict 256**, keep_alive 5m. The author's llama-cpp-python example uses temperature 0, 1344 context, and 256 maximum output. Ollama instead of llama.cpp is a runtime substitution because of the existing OptiPlex host. Verify /api/show has a nonempty chat template and record its hash. That is NOT proof of exact byte-for-byte runtime equivalence with llama.cpp.

The earlier Benchmark 002 extended the author's example with an extra adult-horror style phrase, 2 prior pairs, 4096 context and 320 max tokens. Those choices were experimental **not the literal author example**, and are deliberately not copied into the current production profile.

## Hard operational rules in code

1. **Model identity is pinned** by exact name, digest prefix 9ccfc3b07081, and family gemma4; no generic Gemma fallback.
2. **100% GPU model placement must be verified before new translation**, or the job is held. The 5.13 GB Q4 model can be tight on a 6 GB RTX 3050; if it does not fit, report the truth rather than silently offload to CPU, change quantization, or alter context.
3. **Never blend old model checkpoints.** Before any new translation/resumption, create/validate a private source-hashed per-job model profile tied to the model, prompt checksum, context, generation limit and previous-context policy. Old JA cues lacking a matching profile are held, not reused or published as E4B.
4. **Preserve native safety**: existing worker locks, GPU/CPU thermal limits, SQLite cue checkpoints, verified English source, no existing JA overwrite, create-only JA publication. These are file-handling rules, not translation prompt modifications.
5. **No rewrite, second model, critic or sanitizing postprocessor**. The existing structural validator may reject malformed outputs, but cannot prove semantic fidelity. Translation errors require real dialogue review and a separately preserved correction.
6. **The actual OptiPlex host is not updated merely by a GitHub commit.** Use the guarded deployment procedure, then verify model ID, reported GPU placement, and live one-cue prompt before queueing a new title. The already published Attachment remains unchanged.

## Guarded OptiPlex deployment

After a code update, run the version-pinned installer on the OptiPlex as its normal user. It checks the existing installed core code's Git blob identity, runs offline tests **before** replacement, refuses to swap live worker files, and saves backup copies. **It never downloads a model or starts a translation job**.

- Installer: [tools/install_production_subtitle_model.sh](../tools/install_production_subtitle_model.sh)
- Controller installer: [tools/install_ja_first_controller.sh](../tools/install_ja_first_controller.sh), which now pins the same subtitle-tuned worker instead of restoring the older generic one.
- Source is committed and CI tested; the actual OptiPlex must separately confirm `--preflight` model ID, GPU placement, runtime chat-template fingerprint and model-generated Japanese.

**If host source fingerprint differs, STOP and inspect the diff. Do not force overwrite unrecognized local code.** The user should not have to rediscover the model selection; always read this file before changing translation settings.

## Standard live progress for EVERY translation

Use the permanent read-only progress tracker, not repeated temporary downloads. Install once with [tools/install_subhub_tracker.sh](../tools/install_subhub_tracker.sh) or as part of fresh Japanese-first controller installation.

- **Watch current translation:** `python3 ~/bruiser-pilot/subhub-control/ja_first_cycle.py watch`
- **Start a queued E4B translation and follow it automatically:** `python3 ~/bruiser-pilot/subhub-control/ja_first_cycle.py start-worker --apply --watch`

For Mac mini terminal access, prefix either command with `ssh -t optiplex@100.121.156.34` and quote the remote command. The tracker reads the actual cue checkpoints and model profile, plus GPU/CPU telemetry, every 10 seconds. Closing it does not interrupt the worker; no old job is retransmitted, and no new job is queued merely by watching. It distinguishes translated cue completion from final `published` state. Historical jobs without profile metadata are marked **unverified** instead of being falsely attributed to current E4B.

## Validation

Offline checks in the repo:

~~~bash
python3 -m unittest test_subtitle_tuned_production test_subhub1 test_daily_worker -v
python3 tools/subtitle_tuned_production.py --self-test
~~~

Host read-only identity/GPU check after installing the module:

~~~bash
python3 ~/bruiser-pilot/subhub-control/subtitle_tuned_production.py --preflight
~~~

That preflight may load the model into GPU memory for a tiny sample, but does not read, modify or publish media or queue records.

**To change models later:** require a fresh matched, source-hashed, model-native EN→JA quality comparison and explicit user decision. GPU utilization/VRAM alone does not establish meaning or viewing quality. Update this document, model source and host deployment together.
