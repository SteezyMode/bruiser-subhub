# Benchmark 005 — partial real OptiPlex results (2026-11-02 JST)

**STATUS: 3/5 models completed; 2 arms blocked. Do not call this the final winner.** Owner uploaded `STATUS.txt`, `model-sweep-005-cat7-20261102T013757Z.json`, `model-sweep-005-hy7-20261102T013757Z.json`, and `model-sweep-005-google12-20261102T013757Z.json`. This public report contains only metadata and aggregate/editorial metrics. Full source-dialogue and model outputs remain **private**. Protocol: [EXPERIMENT_005.md](EXPERIMENT_005.md).

## Verified run identity and comparability

All three returned `schema=bruiser-private-model-sweep-005-v1`, `benchmark_id=primate-64-new-cues-native-model-sweep-v1`, `complete=true`, `stop_reason=null`, frozen source SHA-256 `8967cfea3f6552c0a6b1645da13e0d79e62be2decb95c02c653e6a345c3b645a`. Their **64 cue IDs, English text, and timecodes match exactly** (eight 8-cue groups centered 91, 127, 175, 235, 303, 343, 543, 691, disjoint from Benchmarks 001–004). Benchmark source hash in all 3: `5f3260ca5f39ec8c1c92b64e3216fb58a37a9a4811cbf5d513b138f78f80f3bc`. Host Ollama version `0.32.1`. The NVIDIA RTX 3050 is reported as **6144 MiB total**; `nvidia-smi` reports 936–1108 MiB free at post-arm collection, **not peak GPU usage or proof of full-GPU operation**.

| Arm (actual installed ID) | Complete / accepted | Call errors | Format validator warnings | Cues >14 JA chars/sec | Median JA chars/sec | Sum of per-cue wall times |
|---|---:|---:|---:|---:|---:|---:|
| Tencent Hy-MT2 7B, Q4_K_M (`c98ad63514f7`) | **64/64** | **0** | **0** | **1** | **7.45** | **81.96s** |
| CyberAgent CAT-Translate 7B third-party GGUF, Q4_K_M (`03276fecdfd7`) | **64 attempted, 59 accepted** | **2** (256 token cap) | **2** missing (under-detects actual junk) | **21** | **10.05** | **81.83s** |
| Google TranslateGemma 12B, Q4_K_M (`c2f9a9ca1ec7`) | **64/64** | **0** | **0** | **6** | **8.95** | **256.92s** |

The three native-model workflows use different model families/prompt formats/default decoding and likely different CPU/GPU partitioning. These data compare deployable *workflows* on the same source—not model size under matched decoding, peak memory, or benchmark quality across an entire film. A model's status `complete=true` means **all 64 were attempted**, even if some cues failed.

## Critical finding: the current validator misses bad subtitle output

The CAT 7B JSON contains:
- **16/64 outputs containing recognizable `assistant`/`アシスタント` role leakage**;
- **13/64 containing long English word fragments** (some are proper names; the list also includes clear English contamination);
- **4/64 with recognizable dictionary/translator explanatory wording**, in addition to duplicated translations, spurious linguistic notes, and huge repetitions;
- **two explicit output-token-cap errors** (source cue IDs 175 and 343); three other outputs fail even the broad Japanese validator (IDs 88, 130 and 305).

The structural `format_flagged=2` count includes **only the two absent translations**. It does NOT account for the 16 role-label contaminated Japanese strings. Therefore a generalized validator that accepts 'contains Japanese characters' is not safe to publish subtitles automatically.

**Interpretation: do NOT declare CyberAgent CAT 7B's final source weights inherently poor on these results.** The developer explicitly warns that **CAT 7B's chat template is DIFFERENT from other CAT model sizes and MUST be correctly applied**: https://huggingface.co/cyberagent/CAT-Translate-7b . These runs used `hf.co/mradermacher/CAT-Translate-7b-GGUF:Q4_K_M` under Ollama `/api/chat`; verify whether the GGUF/Ollama template matched the final 7B model's intended template before attributing the junk to translation competence. Treat this particular runtime/package as **unfit for unattended subtitles** until verified.

## Provisional masked editorial comparison — NOT a native Japanese grade

The assistant first inspected the raw data for integrity, then independently **shuffled model labels for each cue** using a private fixed-seed key and reviewed all **64 × 3 = 192 outputs** against English/timecodes. One reviewer, obvious role contamination and model styles sometimes revealed likely identities; *not a fully independent blind study*. No partner/native Japanese continuous viewing test has happened.

Under the pre-registered 4 (meaning) + 2 (unsanitized tone) + 2 (naturalness) + 2 (readability) subjective rubric, the assistant's per-cue **best-or-tied** choices were:
- **Hy-MT2 7B: 61/64 cues**
- **Google TranslateGemma 12B: 19/64 cues**
- **CAT 7B: 13/64 cues**

These add to greater than 64 because ties are allowed. **Unique best**: Hy-MT2 **35**, Google 12B **1**, CAT 7B **2**, with **26 ties**. This is a relative assistant preference ranking, **NOT** a calibrated `9/10` native-Japanese watchability score.

Qualitative observations (no copyrighted speech reproduced):
- Hy-MT2 typically gives short, idiomatic Japanese for ordinary family chat and urgent action. It keeps several shouted insults/commands and usually avoids generic corporate register. It still demonstrably misconstrues a physical grip/holding action as emotional endurance (cue 546), makes a tense/intent shift in an apology relay (cue 129), and can lose contextual details of earlier conversation. Thus it is **not proven 8/10 and not an automatic production winner**.
- Google 12B produces mostly coherent text but is often **too formal and longer** for casual/urgent movie speech. Its translations sometimes reverse or confuse who is being addressed, omit a command or sexual/violent nuance, or insert translator alternatives. It is approximately **3.1× slower in total measured call wall time** than Hy 7B on these short cues.
- CAT 7B's chat-run frequently produces **assistant role labels, explanatory notes, duplicated Japanese, irrelevant continuations and gibberish**. That is a wrapper/template or generation-behavior problem until diagnosed; no defensible quality verdict about the unquantized final CAT 7B under its verified native template can be made from this specific Ollama output.

## Remaining blocks — inspect, do NOT guess

The uploaded status file explicitly says:
- `cat33 BLOCKED or incomplete — see separate output`. **Follow-up read-only diagnostics confirmed all five pinned package imports, CUDA available, ~5.7 GiB free VRAM, correct source SHA and successful CAT 3.3B source/environment preflight.** The problem occurs *after* preflight (model download/loading or inference). **Exact error remains UNKNOWN** because no failed-run traceback was supplied. No complete JSON; do not count this as a test.
- `tuned BLOCKED preflight`. **ROOT CAUSE CONFIRMED:** installed tag `hf.co/17slever17/translate-gemma-4-sub-e4b-GGUF:Q4_K_XL`, exact expected Ollama ID `9ccfc3b07081`, `/api/show` `family=gemma4`, `parameter_size=7.52B`, **`quantization_level=Q4_K_M`**, despite its **tag** containing Q4_K_XL. Benchmark 005 incorrectly demanded reported `Q4_K_XL` and rejected the known working model. Fixed harness now requires the EXACT model ID, `gemma4` family and ACTUAL Ollama-reported `Q4_K_M`, preserving source tag. No model repull/requantization necessary.

**DO NOT choose Hy 7B over the previous subtitle-tuned E4B** until the tuned arm completes on the EXACT 64 new cues. Earlier E4B results are from different source windows. The scientific next task is to fix/read those two block reasons, rerun only the missing arms, then compare Hy vs tuned (and final CAT 3.3B if feasible). Do not need to rerun successful Hy/Google/CAT7.

## Next engineering checks

1. **Read-only diagnostics completed (2026-11-02):** tuned metadata mismatch is confirmed and corrected in benchmark source only; CAT3.3 environment passes. Next run `bash tools/run_model_sweep_005.sh optiplex@100.121.156.34 missing` after merge and checkout pull; this explicitly runs only tuned+CAT3.3 and retains `cat33-run.log` privately if CAT fails after preflight. Do NOT rerun the other three models.
2. Once tuned native control runs on same cues, score first-pass output without model names, compare paired semantic/tone failures and density, then use a **continuous 10–15 min Japanese-only scene** to test practical watchability.
3. Investigate CAT 7B template-specific packaging before any more CAT7 full-suite run; model's official card says the 7B template is special.
4. Keep live SubHub Python, published subtitles and SQLite checkpoints unchanged; all private text stays outside GitHub. Do not force a multipass pipeline.

**This is a partial data record, not a terminal experiment conclusion.**
