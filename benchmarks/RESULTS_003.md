# Benchmark 003 — measured strict-card and context-gap results

**Real local run completed 2026-11-02 01:38 JST (2026-11-01 16:38:55 UTC), user supplied the private JSON `primate-model-card-003-20261101T163706Z.json`.** This public report includes metrics and paraphrased error descriptions, not copyrighted English dialogue or model-generated Japanese. [Frozen methodology](EXPERIMENT_003.md), [Benchmark 002 results](RESULTS_002.md), [Benchmark 001 results](RESULTS_001.md).

## Exact run metadata

- Benchmark ID: `primate-model-card-one-prev-gap-v1`, schema `bruiser-private-card-prompt-benchmark-v1`, **complete=true**, no stopping error.
- Model: `hf.co/17slever17/translate-gemma-4-sub-e4b-GGUF:Q4_K_XL`, Ollama ID `9ccfc3b07081`.
- English source SHA-256 `8967cfea3f6552c0a6b1645da13e0d79e62be2decb95c02c653e6a345c3b645a`; same fixed 64 cues as Benchmarks 001 and 002.
- System-prompt SHA-256 `61a302c51aa6a36d5b95741f50e8f140e65b477a52b02b7df1e8664559c19ac0`.
- Benchmark source SHA-256 `8ca98f4b3a681f5e266648eba41530efce569aedf3b825c249ede8fedb8fe61a`; service SHA-256 `24b8c20a4149c520a300eb7ce909f4a80928eb7da3f54e18898811fe3a8fa45c`.
- Ollama `/api/chat`, temperature 0, `num_ctx=1344`, `num_predict=256`; this is *closer* to the developer's llama.cpp example but is **not a byte-for-byte or runtime-identical replay**.
- Both arms use the same `TASK: English-to-Japanese subtitle translation; STYLE: neutral` system instruction and at most ONE preceding successfully generated cue pair. Arm B omits the pair if silence since immediately preceding cue is >8 seconds. It does **not** fix artificial 8-cue block resets or translate in true full-scene dialogue context.

## Observed results (not predictions)

| Arm | Responses/accepted | Format suspicions | Context used | >14 JA chars/s | Median JA chars/s | Summed model-call time |
|---|---:|---:|---:|---:|---:|---:|
| `card_previous` | 64/64 | 0 | 56/64 | 7 | 6.85 | 55.81 s |
| `card_previous_gap8` | 64/64 | 0 | 48/64 | 7 | 6.85 | 52.57 s |

- **128/128 local Ollama calls succeeded, no structural formatting artifacts identified.** These checks do not measure semantic accuracy, tone, naturalness or native-speaker approval.
- Exactly **eight cues lost previous-context input** under the 8-second cutoff: IDs 204, 206, 210, 383, 427, 428, 431, 468.
- **Only six out of 64 cue translations changed** between arms: 204, 427, 428, 429, 430, 431. Four changed at a cue where context was dropped (204, 427, 428, 431), and two were downstream differences (429, 430) because the model used earlier generated Japanese from its own arm. The other **58/64 outputs were text-identical**.
- Differences were small and mixed: interrogative style changed on 204; a shouted negative shifted between *don't/no* and *no* on 427; line wrapping changed on 428; gendered pronoun shifted on 429 and explicit pronoun was removed on 430; an object-retrieval command became wordier on 431. **No measurable net quality improvement** from the 8-second gate in this restricted sample. The ~3.24s summed call-time difference is not compelling evidence of better inference efficiency.

## Practical language-quality assessment, not a fabricated number

The **simplified neutral one-previous-cue configuration did not outperform Benchmark 002's earlier native configuration** on the material that matters:

- Cue **265**: Earlier native Benchmark 002 had a correct past-tense denial of having *said* something. Both 003 arms changed it back into a generic denial of having *done* something. This is a semantic regression.
- Cue **379**: An angry challenge and threatening statement about an animal became unusually formal/polite. The underlying killing/euthanasia implication was retained, but the social register was weaker.
- Cue **71**: The idiom about reluctantly correcting another person's seat assignment still reads literally and awkwardly in Japanese.
- Cue **73**: Both arms retained an unnatural Japanese particle combination; a grammar/fluency error that the structural validator does not detect.
- Cue **466**: Modern slang referring to an attractive woman/person was rendered as *bad women*; neither current arm captured the idiom. Earlier Benchmark 002 had a different but equally inappropriate translation of that slang.
- Cue **35**: ~23.8 Japanese chars/sec, plus multiple speakers packed into one cue; **207**: ~31.2 chars/sec; **465**: ~19.7 chars/sec. All remain hard to read at their original display times, and 003 did not remedy that.
- Some plain dialogue and explicit profanity/threats did remain accurate and readable. The test does **not** justify dismissing the model; it does show the *remaining error ceiling* is not fixed by micro-adjusting context or generation tokens.

This is an **unblinded assistant evaluation against English source**, not a native Japanese viewer assessment. **No configuration is certified as 8/10**. Original historical Japanese subtitles were partly generated through an older broken batch path and are not a fair scientific baseline.

## Decision: stop prompt churn

1. **Do not adopt the 8-second gating rule.** Within this sample it changed only six outputs and offered no consistent semantic or readability benefit. It is not evidence that stale context is universally useless, only that this arbitrary cutoff was not productive here.
2. **Do not replace Benchmark 002's native tuned configuration with the strict-card 003 version.** Benchmark 002 was cleaner on some important meaning/tone cases (including past-tense denial); 003 introduced formal/polite voice and longer hard-to-read cues. Still, this is a limited and risk-enriched sample, not proof 002 is globally better.
3. Keep the existing live production engine untouched pending a practical viewing trial. **No automatic retranslation of seven published movies or queued launch of 2,026 candidate English-source files.**
4. **Next highest-value test is 10–15 minutes of uninterrupted Japanese-only viewing** of one of the completed films with the intended Japanese-speaking viewer. Record intelligibility, tone, distracting errors and whether the film remains enjoyable *without* reference to English. If the viewer finds the machine track usable, select a sensible native single-pass profile and start a small controlled library batch.
5. If the viewer identifies recurrent material errors, consider ONE substantive improvement (for example a different translation model, scene-aware context, or selectively invoked second-model critic), **only if a fixed comparison proves net improvement without introducing hallucinations or excessive cost**. Multi-model/multipass is optional, not assumed.
6. Keep the artifact as a private file. Future engineering must read `benchmarks/RUN_LEDGER.md` before revisiting same model/prompt choices. No more rounds of 2-versus-1 previous cue / token-count micro-tuning without new quality evidence.

**Benchmark 003 status: COMPLETE and analyzed.** No production translation code, published subtitle, queue, film or database was changed by this benchmark.
