# PLaMo 3 Translate: November 5, 2026 research plan (NOT deployed)

## Why revisit translation at all?

> **Live OptiPlex smoke-run update, November 5 (17:31 JST):** both Q4_K_M models loaded using pinned llama.cpp CUDA and returned 16/16 Japanese-script responses with zero runtime errors: **0.8B: 0.702 seconds aggregate; 2B: 2.162 seconds aggregate** for the same short synthetic 16 English phrases. Before inference, GPU reported **5,678 MiB free, 0% utilization, 32 W configured power limit**. These figures exclude model load and **do not establish linguistic fidelity, peak power, VRAM requirements during gaming, or film-length throughput**. Private outputs: `~/bruiser-pilot/plamo3-ab/results/plamo3-small-ab-20261105T083115759228Z/`. Do not commit subtitle text. The next gate is manual inspection of the actual Japanese outputs, then an unseen real-dialogue SRT test; see [current execution roadmap](EXECUTION_ROADMAP_2026-11-05.md).


Preferred Networks released **PLaMo 3 Translate** on **2026-11-05**, after SubHub's earlier frozen experiments. It is a *new family* of Japanese-focused translation models, not an invitation to repeat the old 4B Gemma prompt tweaks. The developer reports strong English/Japanese benchmark performance from even the 0.8B model, but those **vendor evaluations are not independent Japanese subtitle-viewing scores**.

Developer material, checked Nov 5:

- Official release: https://www.preferred.jp/en/news/pr20261105
- Detailed training/quantization/benchmarks: https://www.preferred.jp/en/blog/tech/plamo-3-translate-weight-release
- Model card and official runtime instructions: https://huggingface.co/pfnet/plamo-3-translate-0.8b-GGUF
- 2B model: https://huggingface.co/pfnet/plamo-3-translate-2b-GGUF
- 8B model: https://huggingface.co/pfnet/plamo-3-translate-8b-GGUF

Under the PLaMo Community License, private hobby/noncommercial use is free without prior registration. Commercial use has different registration/income conditions; check current license before shipping a consumer product or redistributing weights.

## Size and hardware tradeoffs

**Official GGUF Q4_K_M weight files** (not total runtime VRAM):

| Model | Q4_K_M weight file | 6GB RTX 3050 practical expectation |
|---|---:|---|
| 0.8B | 0.57 GB | Easy GPU residency, possibly CPU-only background mode |
| 2B | 1.81 GB | Plausible full-GPU residency; primary experiment candidate |
| 8B | 5.28 GB | Not a good full-GPU option when desktop/gaming/streaming run simultaneously; possible CPU offload |
| 31B | 19.53 GB | Inappropriate for GPU-only execution on this card |

Total resident GPU memory includes CUDA/llama.cpp runtime buffers and KV-cache, varies with context and GPU driver. Small weight file size does **not** prove harmless background game streaming: running inference consumes GPU compute/memory bandwidth and competes with Wolf encoding and games. A 0.8B or 2B benchmark must measure real GPU residency and impact, rather than promise simultaneous AAA gameplay. Benchmark on idle host first; only then test coexistence at a verified low-priority limit.

Developer benchmark reports near-BF16 translation scores at Q4_K_M. Avoid Q2_K solely to reduce footprint: official card flags quality loss on some metrics.

> **IMPLEMENTATION UPDATE (later November 5):** The isolated [small-model runner](../tools/plamo3_small_ab.py), [pinned CUDA/GGUF bootstrap](../tools/install_plamo3_small_ab.sh), and [authoritative execution roadmap](EXECUTION_ROADMAP_2026-11-05.md) are committed and tested offline. Model weights have **not been downloaded or run on the host** by these GitHub commits. The 16-line demo is only a runtime/speed check; a real private English-SRT sample and Japanese viewing comparison remain the decisive next step.

## Exact model-native prompting contract

PFN provides a **separate \`chat_template.jinja\` file** beside each GGUF. Their card specifically warns that the *legacy embedded GGUF template does not handle translation history correctly*. Their GGUF **Chat Completions** route ignores system-role messages; reference context belongs in supported \`chat_template_kwargs\`. They recommend **PFML3 + Completions API** for production integrations. Their history mechanism uses alternating previous **source/translation** messages and translates **only the final user/source** message.

Do not reuse the Gemma system prompt, old 8-cue JSON translation, raw next-four-English context, or arbitrary custom formatting. A first clean trial must follow PFN's official examples, pinned exact GGUF weights and template, with \`source_lang=en\`, \`target_lang=ja\`, \`temperature=0\`, documented stop tokens and bounded \`max_tokens\`. Save the exact model and template SHA-256 and runtime version. Preserve media SRT timestamps in the **host adapter**, not by asking the model to emit new timestamps.

Illustrative **developer-supported** llama.cpp server invocation (not executed; test only in an isolated port with a private model download and adequate GPU free memory):

\`\`\`sh
# After a separate download of Q4_K_M and chat_template.jinja,
# using the official llama.cpp CUDA build and a model-specific workdir:
llama-server -m plamo-3-translate-0.8b-Q4_K_M.gguf -c 16384 \
  --port 8000 --alias plamo-3-translate \
  --chat-template-file chat_template.jinja --no-prefill-assistant
\`\`\`

Follow official card for options. Do **not** install or start a second model server on the already running source-only job by copying this illustration. Context 16384 in the card is an *example*, not a required minimum or safe gaming co-residency setting.

## Frozen, small paired test — before any full-film or auto production

- **A:** PLaMo 3 Translate **0.8B Q4_K_M**
- **B:** PLaMo 3 Translate **2B Q4_K_M**
- **C:** Installed subtitle-tuned 17slever17 E4B Q4 as reference, *only if an existing comparable private output is available*. Do not rerun old familiar Primate cue sets merely to rank models.
- **Optional D:** 8B Q4_K_M with CPU offload, *only* if smaller-model quality is meaningfully ambiguous and hardware overhead is acceptable.

Use a frozen unseen English subtitle sample with actual video and reliable English timing, about **80–120 consecutive cues** containing simple dialogue and hard translation cases (horror/drama, interruptions, colloquialisms, register, negation, threats/jokes). Prefer one or two **new scenes** that are not the familiar Primate/E4B tuning corpus, and keep the previous Benchmark 006 blind corpus intact.

Use the *same cue source and model-native generation policy* for both PLaMo arms (the same official history setting, if used). Do not edit Japanese to make either model look better. Capture format errors, output truncation, calls/sec, real wall time, VRAM, GPU load and CPU usage. Mechanical acceptance is **not** linguistic quality.

Build paired blind SRTs with the **original English timecodes**, preserving output for offline review. A normal-viewing Japanese-language assessment (meaning, register, naturalness, readability, tone fidelity, important missed/added information, and problematic jokes) is the decisive test. It should be a **manageable** household review, not 36 viewings of nine arms. Do not unblind scores before recording them. No claims of ~8/10 without evidence.

## Explicit scope boundaries

- **No model downloaded, inference run, CLI service modified, subtitle generated, or media file touched by this document.**
- Keep the confirmed sourced-Japanese daily path, timer and existing Japanese tracks untouched.
- Do not call the 2B the winner until results exist.
- If both small models are linguistically poor, **stop** rather than tweak prompts indefinitely. Focus on sourced Japanese and optionally reconsider 8B only with a clear quality question.
- Any future DIY-generated Japanese must carry model provenance and be a separate draft; it is not silently published as equivalent to a sourced or curated subtitle.
