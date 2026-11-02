# Benchmark 005 — paired tuned Gemma4 vs Hy-MT2 7B (2026-11-02)

**REAL host runs, SAME 64 frozen English cues.** Earlier three-model results: [RESULTS_005_PARTIAL.md](RESULTS_005_PARTIAL.md). New owner uploads: `STATUS(1).txt`, `model-sweep-005-tuned-20261102T022559Z.json`, `tuned-preflight.log`, `tuned-model-run.log`, and `cat33-run.log`. All complete source text, translated Japanese, identity shuffle and individual preferences remain **private** (not committed).

## Verified identity and integrity

- Source SHA-256 for both **exactly matches** `8967cfea3f6552c0a6b1645da13e0d79e62be2decb95c02c653e6a345c3b645a`. Both contain exactly the same 64 IDs, English strings and original timings; no overlapping old experiment cues. Eight 8-cue windows centered at 91, 127, 175, 235, 303, 343, 543, 691.
- Tuned control: `hf.co/17slever17/translate-gemma-4-sub-e4b-GGUF:Q4_K_XL`, exact Ollama ID `9ccfc3b07081`, `gemma4`, **Ollama-reported Q4_K_M** even though model tag suffix says `Q4_K_XL`; the model has NOT been repulled/requantized. Native `CURRENT_SOURCE` / previous generated translation prompt per Benchmark 002, temp 0. Corrected test preflight succeeded; 64 actual local inference calls returned.
- HY: `hf.co/tencent/Hy-MT2-7B-GGUF:Q4_K_M`, Ollama ID `c98ad63514f7`, family `hunyuan-dense`, actual Q4_K_M. Author-style translation-only prompt, temperature .7, top_p .6, top_k 20, repeat penalty 1.05. Run is from the already-completed original owner sweep; **not rerun**.
- Code SHA differs because the tuned benchmark source was fixed to correct a **metadata preflight error only**, not model prompt or source selection. HY source benchmark hash `5f3260ca5f39ec8c1c92b64e3216fb58a37a9a4811cbf5d513b138f78f80f3bc`; tuned run hash `44ddf45eab1677064851b402d7ff69383ab527fc816402b4bde379c486dd3238`. Model and original English/timecode integrity verified independently.

## Mechanical comparison (actual measurements)

| Metric | Tuned Gemma4 E4B | HY-MT2 7B |
|---|---:|---:|
| Attempted / broad JA-validator accepted | **64 / 64** | **64 / 64** |
| Ollama call errors | 0 | 0 |
| Recognizable format flags | 0 | 0 |
| Median JA characters per second | **6.60** | 7.45 |
| Number of cues >14 JA chars/sec | **0** | 1 |
| Summed per-cue wall time | **61.98 sec** | 81.96 sec |

On this exact run, tuned E4B has **24.4% lower sum of model-call wall seconds** than HY7, and is ~11.4% less dense at the median (6.6 vs 7.45 chars/sec). These are observations, not a controlled throughput study: model-native settings, generation tokens, caching and Ollama residency differ. The broad JA validator cannot detect nuanced semantic errors.

## Cue-identity-masked editorial screening (one assistant, NOT a native Japanese reviewer)

Each of the **64 paired** English/JA outputs was viewed with **A/B model identity shuffled independently per cue**; initial preferences selected from A, B, or tie, with specific notes for significant meaning/register cases. The identity mapping was revealed only after the preferences were determined. This is **single-assistant review** and NOT a formally independent blind human study. The frozen **4+2+2+2 10-point review rubric was NOT fully scored**; these preference counts must NOT be called that score or a numerical 8/10 quality assessment.

| Masked preference, revealed after selection | Cue count |
|---|---:|
| Subtitle-tuned Gemma E4B favored | **26** |
| HY-MT2 7B favored | **15** |
| No meaningful difference / tie | **23** |

**Meaningful observations:**

- **HY strengths:** on cue 89 it understands attractive/hot slang rather than physical heat; cue 236 correctly interprets calling people as a **telephone call** rather than summoning them; cue 235 and cue 542 use consistent Japanese transliteration of *Hannah* where tuned model sometimes drops a consonant or leaves the name in Roman characters; cue 306 retains the precise question about what someone is doing rather than recasting it as why they are present. These are genuine semantic/name advantages.
- **Tuned strengths:** more consistently short, idiomatic informal speech throughout the greeting/family conversations and emergency exchanges. HY drifts into unnecessary polite register on short reactions, questions and orders. Tuned keeps an immediate previous subtitle's conversational context and more often delivers an appropriate tense or direct action, though it sometimes assumes too much from context.
- **Shared CRITICAL ERROR at cue 546:** characters trying to physically maintain their grip while something pulls them backward; BOTH translate inability to hold onto something as inability to endure/put up with it. Neither model currently resolves this through our available context. A 64-cue structural/median-CPS score alone hides exactly this type of problem.
- **Other residual ambiguity:** cue 91's *out of town* becomes a short outing in HY versus a **business trip** in tuned (plausible from preceding line but more specific than original); cue 93's idiom about thinking the same thing is awkwardly literal in BOTH; an operator/caller emergency conversation makes speaker relationships and polite register uncertain without film context. Some English source cues break a sentence across multiple timecodes; separate-cue translation can miss dependent clause meaning.

## CAT final 3.3B rerun: exact failure now KNOWN (no model quality result)

The same owner run's `cat33-run.log` shows: source SHA check succeeded, all pinned CUDA/Transformers packages already installed, then **`Under 3GB free VRAM; stop competing inference before CAT 3.3B`** at the source/environment preflight. It **never reached Hugging Face model loading, CUDA weight allocation or translation**. Prior read-only diagnostics found ~5.7 GiB VRAM free while idle and successful CUDA import. The 2026-11-02 retry ran **tuned first**; tuned's native Ollama calls use `keep_alive=5m`, so model residency after test is a plausible reason that less than 3GB remained for CAT; a concurrent GPU process is also possible. **No `ollama ps`/GPU process evidence was captured at the exact failure time, so do NOT assert the specific consumer as fact.** No traceback or model incompatibility has yet been found.

**Controlled recovery:** run `cat33` alone when `ollama ps` and GPU inventory show no active competing jobs and VRAM >=3GB. Do not automatically `ollama stop` a model used by real SubHub/desktop work. New source/runner puts CAT FIRST in `missing` retry mode to avoid keeping tuned in VRAM before CAT. The user can run individual `cat33` mode and share the PRIVATE `cat33-run.log` if it fails after source/CUDA preflight. **Do not rerun already-successful tuned/HY/CAT7/Google12 models**.

## Decision

1. **Tuned E4B is the provisional front-runner** for conversational/subtitle-ready Japanese (26 masked preferences versus 15 HY and 23 ties) and is faster/shorter on the paired sample. **HY7 remains a meaningful challenger** because it fixes important slang/phone-call/name errors. Neither is certified 8/10 without Japanese-speaking viewer review.
2. **Do NOT turn on an automatic two-model pipeline yet.** A second model might rescue some critical semantic errors but both made other errors, including the SAME physical-hold misconstrual. Selective second-pass review would need a fixed, genuinely better net result.
3. Finish CAT3.3 final under sufficient free VRAM if practicable; then score a continuous 10–15-minute native translation scene with a Japanese-speaking viewer and test a second film before making library-scale production changes.
4. All existing published subtitles, queue/checkpoint SQLite and source media were **unchanged**. Test harness source and public result reports only.

**Status: 4 of 5 arms have real returned data, final CAT3.3 still not tested.**
