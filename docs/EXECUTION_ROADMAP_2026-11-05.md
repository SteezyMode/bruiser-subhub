# SubHub execution roadmap — 2026-11-05 (CURRENT ACTION PLAN)

**One mission:** maximize the number of **usable, naturally translated, correctly timed Japanese subtitles** ready before viewing on the household's existing Jellyfin media. The result, not the number of generated tokens/searches/models/commits, is the success criterion.

**THIS IS THE CURRENT OPERATING PLAN.** Read it before starting new subtitle-related development. The earlier American Dad/E4B/Hy-MT/CAT experiments remain historical evidence, not ongoing priorities. See [previous research stop decision](TRANSLATION_RD_STOP_DECISION_2026-11-05.md), [source-vs-DIY policy](HYBRID_JAPANESE_SOURCE_VS_DIY_POLICY_2026-11-05.md), [SubHub architecture](WHAT_IS_SUBHUB_AND_HOW_TO_USE_IT_2026-11-05.md), and [PLaMo test protocol](PLAMO_3_TRANSLATE_EVALUATION_2026-11-05.md).

## Locked objectives and scope

1. **Source Japanese first, efficiently.** Keep existing human/editorial Japanese. Search OpenSubtitles, download credible Japanese tracks, automatically fix *actual-release* timing, create-only publish. The existing **working** host timer stays enabled.
2. **Local DIY for source misses.** Only use matched, verified English to make separately labeled Japanese drafts. The immediate R&D candidates are new **PLaMo 3 Translate 0.8B Q4_K_M and 2B Q4_K_M**. Do not revive older E4B prompt-tuning loops.
3. **Minimize source download quota use.** According to OpenSubtitles' official API docs, *searches are not capped per day by allowance; downloads depend on account rank*. Searches can still be slowed/throttled. Search once and cache; spend downloads on promising candidates. Never treat our software 600-search ceiling as a provider's allowed download quota.
4. **No GPU disruption.** The source-only worker requires no local translation model. PLaMo test is isolated; actual DIY inference should yield to gaming, Wolf, Jellyfin transcodes, desktop use. Test CPU-only mode separately if gaming coexistence matters.
5. **No extra Bruiser complexity.** SubHub stays an **independent background server utility**, not a mandatory OptiPlex NOW/Bruiser dashboard feature or a Jellyfin plugin. No consumer installer is claimed at this stage.
6. **Keep public repo robust:** tests, immutable evidence records, release/pin information, safe deploy and rollback procedures, no user media/subtitles/passwords committed.

## Verified baseline — Thursday November 5

Owner's finished **100-search test** from the OptiPlex source-only timer/controller, as reported in uploaded read-only monitor log:

| Metric | Outcome | Caveat |
|---|---:|---|
| Provider searches | **100/100** | Plus cached evidence from earlier interrupted run |
| Subtitle staging downloads | **50/51** | Includes older saved candidates; *not* 50 matches from only the 100 new searches |
| New Japanese sidecar publications | **37** | QA/timing/provenance passed; **not** independently Japanese-viewer-rated |
| Earlier sidecars recognized | **5** | Not new publications |
| Publication holds | **14** | Need category summary before adjusting gates |
| Unique titles examined for publication | **56/56** | Finished stage |
| Search errors | **0** | As reported in monitor |
| Run time | Roughly **38 minutes** | Snapshot-based; verify exact systemd elapsed for historical reports |

*You Were Never Really Here* is an actual playback-proven case where a sourced Japanese track that was badly timed in Plex was repaired by SubHub for this specific file. Don't infer all 37 publications are editorially good solely from mechanical QA.

**Current schedule:** daily host-local ~05:15–05:35 JST via systemd timer, 600/200/200 software ceilings (search/stage/publish); actual provider download quota and eight-hour service cap may stop earlier. The owner's one-time 100-search override was consumed by the successful test if the one-time-budget completion marker was emitted; **verify**, don't assume any subsequent timer budget setting is missing. The scheduled timer is already live. No host changes follow from this doc commit.

## Work order — TODAY, Thursday November 5

### Task 1: Isolated PLaMo compatibility + speed smoke test (DO NEXT)

**Status: COMPLETE — actual OptiPlex smoke run 2026-11-05 08:31 UTC (17:31 JST), owner-provided terminal log.** Both official GGUF Q4_K_M variants downloaded and ran with pinned llama.cpp b12119 CUDA build. Model-generated Japanese text has **not yet been manually examined**; this is runtime/format evidence only.

| Model | Successful cues | Aggregate inference time | Mean per cue | Errors |
|---|---:|---:|---:|---:|
| PLaMo 3 Translate 0.8B Q4_K_M | **16/16** | **0.702 s** | **0.044 s** | **0** |
| PLaMo 3 Translate 2B Q4_K_M | **16/16** | **2.162 s** | **0.135 s** | **0** |

Host pre-test GPU telemetry: NVIDIA RTX 3050, **5,678 MiB free**, 0% GPU utilization, **32.00 W configured power limit**. This is **not** actual inference power consumption or peak VRAM. Models ran in sequence, not simultaneously. Generation-call times exclude server/model loading. Files: `~/bruiser-pilot/plamo3-ab/results/plamo3-small-ab-20261105T083115759228Z/` (PRIVATE, never commit). Source-only systemd service unchanged and no Jellyfin sidecars published. **Immediate next step: read and inspect the 16 actual EN/JA pairs to catch nonsense before a larger real-dialogue trial.**

- Use the pinned standalone installer [install_plamo3_small_ab.sh](../tools/install_plamo3_small_ab.sh) and [Python benchmark](../tools/plamo3_small_ab.py). Private working root: `~/bruiser-pilot/plamo3-ab`.
- Download exact PFN official Q4_K_M model files **0.8B (~0.57GB)** and **2B (~1.81GB)**. Use a pinned, locally extracted llama.cpp CUDA 12.8 build; no Ollama/model replacement, root package installation, or media writes.
- Both run in sequence on **the same 16 original, non-movie English dialogue samples** using PFN's actual PFML3 translation prompt, temperature 0 and stop tokens. Include idioms, negation, register, sarcasm and threats. Preserve English cue timecodes. Capture raw JA, latency, provenance, simple mechanical flags and GPU preflight.
- STOP for runtime incompatibility, missing CUDA libs, unverified weights, insufficient VRAM or active gaming. Don't forcibly unload any other model; no automatic fallback to different models.
- **Exit criterion:** both model servers start, 16/16 returned without truncation/empty or non-Japanese replies per arm, private run records created and no source-only worker changed. This is a **smoke test only**, NOT quality certification or proof of 8/10 Japanese.

**Run the pinned smoke test from the Mac mini (actual code, not just a plan):**

~~~bash
ssh optiplex@HOST 'bash -s' <<'REMOTE'
set -euo pipefail
SCRIPT="$(mktemp)"
trap 'rm -f "$SCRIPT"' EXIT
PIN="387fdf7dcb888c4adc772578c994883d7c62e02d"
curl -fsSL --retry 3 \
  "https://raw.githubusercontent.com/SteezyMode/bruiser-subhub/$PIN/tools/install_plamo3_small_ab.sh" \
  -o "$SCRIPT"
bash -n "$SCRIPT"
bash "$SCRIPT"
REMOTE
~~~

Replace `HOST` with the OptiPlex SSH IP/hostname. This downloads roughly 3–4 GB of pinned model/runtime assets and tests **both** models sequentially on GPU; the shell must remain attached through the test. Smoke-test results stay in `~/bruiser-pilot/plamo3-ab/results/`. If host CUDA/VRAM is incompatible, it stops without changing source-only service. The source-only timer continues independently. A GitHub document cannot install/run models on the user's host by itself.

### Task 1B: Review actual Japanese from the 16-cue synthetic test — COMPLETE (November 5)

**Evidence:** owner pasted all 16 English cues and both unmodified PLaMo outputs from private `0.8b.json` and `2b.json`. This was an **unblinded, assistant-only, text-only** review, not Japanese native-viewer playback and not a formal accuracy score. No subtitles or models were modified.

**Findings:** Most lines are grammatical and largely faithful; both models successfully render *out of the woods*, *you've got some nerve*, *make a scene*, and negated testimony. 0.8B is sometimes more natural in terse horror dialogue (basement); 2B is sometimes more idiomatic (showing up) and correctly interprets `Keep your voice down` as reducing voice level, while 0.8B's `声を低くして` can imply pitch instead. **Both fail `If this goes sideways, we walk` by translating `we walk` literally as walking rather than withdrawing/aborting.** Both render `Well, that's just great` literally; sarcasm cannot be established without real scene context. Both weaken the *It can hear us* warning by eliding the external listener.

**Decision:** Both 0.8B and 2B **ADVANCE to a fresh real-video English-SRT scene test**. No evidence that 2B wins reliably over 0.8B; no evidence either reaches 8/10 viewing quality. **Do not prompt-tweak the 16 demo cues** or change the production source-only pipeline. Next test must use 80–120 consecutive cues and actual viewing, not another synthetic phrase tournament.

### Task 2: Real subtitle A/B, 80–120 continuous cues (SAME DAY if smoke test passes)

> **IMPLEMENTATION READY, NOT YET RUN on the host (2026-11-05).** The one-command runner is [`tools/run_plamo3_real_film_ab.sh`](../tools/run_plamo3_real_film_ab.sh), calling the [real-film evaluator](../tools/plamo3_real_film_ab.py). Both scripts are in GitHub with offline tests. **Do not falsely mark the real-film test complete until owner submits actual OptiPlex output.**
>
> **Exact vendor contract checked against PFN's Nov. 5 GGUF model card:** [PLaMo 0.8B developer page](https://huggingface.co/pfnet/plamo-3-translate-0.8b-GGUF). Use `llama-server` GGUF with **direct handwritten PFML3 → /v1/completions**, not a Gemma/Ollama system prompt, not forced JSON/SRT outputs and **not** a chat template (PFN recommends the direct PFML3 format for integrations). The input contains `dataset=translation`, `input lang=en`, previous `input(en)/output(ja)` pairs exactly as shown in PFN's *Specifying translation history in PFML3*, and only then the current `input(en)` with empty `output lang=ja`. Model receives **at most TWO immediately preceding generated source/translation pairs**. No future English, speculative story summaries, invented style commands, second-pass fixers or model critics. `temperature=0`, `max_tokens=512`, stop `<|plamo:tag|>` and `<|plamo:bos|>` follow the official Completions example. No manual `<|plamo:bos|>` prefix (llama.cpp adds it). Keep the current 0.8B and 2B Q4_K_M weights and pinned llama.cpp b12119 runtime from the successful smoke test. Max inference context 4096 for this bounded two-pair test. Every SRT timestamp is retained in file-handling code, never generated by PLaMo.
>
> **Source and safety:** Automatically select **one Movie** from the last private Jellyfin catalog with correct host path/IMDB metadata, confirmed primary English audio, no existing Japanese, and an explicitly tagged **embedded English text subtitle** in that same media file. Prefer recorded Japanese provider no-match titles and horror. Safely extract SRT via ffmpeg stdout, preserve **100 consecutive original cue IDs and times**, snapshot SHA256 in a private output manifest. An embedded source is release-bound but the test does **not** independently certify every dialogue cue's audio synchronization. If no safe source is found, **hold** rather than choosing a guessed English file, running speech-to-text or silently switching movies. Save source, both raw JSONs and review-only Japanese SRTs under `~/bruiser-pilot/plamo3-ab/real-results/` (0700). No media writes, Jellyfin publication, account calls or source service changes.
>
> **From the Mac mini once CI passes:** 
>
~~~bash
ssh optiplex@100.121.156.34 'bash -s' <<'REMOTE'
set -euo pipefail
PIN="9464493c5eccfd1eaba6f4053c67aa05e60c25d1"
SCRIPT="$(mktemp)"
trap 'rm -f "$SCRIPT"' EXIT
curl -fsSL --retry 3 \
  "https://raw.githubusercontent.com/SteezyMode/bruiser-subhub/$PIN/tools/run_plamo3_real_film_ab.sh" \
  -o "$SCRIPT"
bash -n "$SCRIPT"
bash "$SCRIPT"
REMOTE
~~~


**Status:** isolated host runner is prepared and CI-tested; **not yet executed on actual film**. The script will automatically select and verify an embedded English SRT using the current private catalog, then execute both model-native 100-cue arms; no model comparison has been measured on this data yet.

- Select ONE *fresh* real English-dialogue scene in a horror/drama title with reliably matched existing English SRT: avoid previously overstudied *Primate*, the four sealed Benchmark 006 scenes, and familiar benchmark prompts. Source selection is read-only; record original English SRT SHA256, title identity, selected cue IDs/timing, media hash or trusted binding.
- Run **the same frozen 80–120 English cues** through each small PLaMo model using the developer-native PFML3 contract. Save both raw outputs and Japanese draft SRT with original timestamps to PRIVATE review storage. Do **not** add model text to public GitHub or publish media-adjacent JA.
- Inspect obvious meaning reversals, omissions, idioms/profanity, register, names, repeated/spillover lines, reading speed. Ask a Japanese-speaking viewer to watch **one small blind scene**, not 36 runs. A small number of severe plot-reversing errors can disqualify an arm despite 100% structural completion.
- **Exit criterion:** useful side-by-side private candidate files and time/VRAM metrics; explicit verdict `0.8B viable`, `2B viable`, `both draft-only`, or `optional 8B comparison warranted`. Aim for ~7.5–8/10 ordinary viewing quality; no automatically inferred grade. If both disappoint, STOP model prompt fiddling and keep source-only coverage expansion moving.

### Task 3: Operational source-run report

**Status:** 100-search cycle finished; final summary figures above recorded.

- Save counts, typical hold categories, cache hit rate, current OpenSubtitles account's actual remaining download allowance (if obtainable safely without printing secrets).
- Sample a handful of newly published Japanese tracks in Jellyfin for timing and naturalness, including a title with difficult accents/slang. Do not attempt to "fix" everything from day-one.
- **Exit criterion:** clear reason codes for the 14 held titles and confirmation that repeat search/download no longer consumes allowance on already published titles. If no evidence of a real bug, leave source code alone.

## TOMORROW — Friday November 6

### Task 4: Let scheduled source-only cycle run normally

- No manual second 600-search command while scheduled service is active. Verify `systemctl --user list-timers --all bruiser-ja-source-autofill.timer` and, after the run, summarize `journalctl --user -u bruiser-ja-source-autofill.service -n 100 --no-pager`.
- Observe whether the daily software **600-search cap** and provider quota cause a full publication phase within the **8-hour** service limit. If discovery throughput varies, shorten daily search batch *via a deliberate one-time setting*, rather than losing publication to a timeout.
- **Exit criterion:** report searches actually made, plausible/review/no-result, actual downloads, newly published, deduped, held, elapsed, provider allowance exhausted (if any), and top error/hold causes. Avoid projecting 37/100 as stable long-run coverage.

## NEXT IMPLEMENTATION — after the PLaMo A/B evidence

### Task 5: Unified router / economical source-or-DIY queue (new feature, NOT LIVE)

**Routing per media ID**, with durable SQLite transitions and a small, auditable number of states:

```text
existing usable JA ────────────> done / preserve
           │ none
           ▼
saved JA candidates? ── strong ─> download ONE credible candidate → ffsubsync → QA → publish
           │ absent/weak                      │ held
           ▼                                  └──────┐
one fresh metadata search (if warranted)            │
           │ strong ──────────────────────────────────┘
           │ no/weak
           ▼
verified exact English source?
           ├─ no  ─────────────> source_recovery_needed (EN OCR/ASR later)
           └─ yes ─────────────> diy_eligible → idle local PLaMo → labeled draft
                                                              │
                                        deliberate validation and future approval
                                                              │
                                                   create-only JA sidecar
```

- **Priority:** source evidence and existing Japanese > highly plausible human Japanese file > DIY if high-confidence Japanese not available and exact English exists > held source recovery.
- **Rate-limit scarce resources:** downloaded candidates per provider allowance; PLaMo inference by idle/GPU allocation. Never spend several download credits testing weak candidates when a proven English-to-Japanese fallback is viable.
- **Avoid repeat work:** reuse 30-day cache; later make cooldown reason-sensitive (no-match longer; transient error shorter). Cached results can be reassessed when providers or matching rules change. Do not claim this router is implemented until tested.
- **No silent downgrade:** AI drafts are distinguishable from sourced/curated tracks, never overwrite them and should not block later better human Japanese.
- **Exit criterion:** offline state-machine tests with simulated source and model decisions, then a 10-title read-only dry run; no media writes until reviewed.

### Task 6: Background local translation (only after Task 5 + quality gate)

- Separate systemd service/timer from provider sourcing; independent lock, queue and checkpoints, configurable CPU/GPU idle budget and override.
- Do not start while Wolf/game streaming or heavy transcoding consumes GPU; measured CPU-only alternative may be preferable for 0.8B.
- Draft outputs create-only and separate from published sourced Japanese. User selection/QA before adopting unattended publication policy.
- **Exit criterion:** a full unfamiliar episode or film independently reaches the household's acceptable viewing standard with clean timing/consistent characters; benchmark speed and hardware impact.

## Scope we are explicitly *NOT* doing now

- No separate SubHub Electron app, mandatory Bruiser tab, or Jellyfin plugin rewrite.
- No 8B/31B multi-model arms unless the 0.8B/2B evidence justifies them.
- No speculative "three reviewers", backtranslation committees, elaborate prompt recycling, arbitrary model-generation cascades, or new account signup maze.
- No auto translation triggered by the currently running sourced-Japanese timer.
- No overwriting original subtitles, altering the media library, deleting failed experiments, or checking user-owned dialogue into GitHub.

## Status handoff checklist for later assistant / Codex session

At the **START** of each new session, consult:

1. This file first, then [source-vs-DIY policy](HYBRID_JAPANESE_SOURCE_VS_DIY_POLICY_2026-11-05.md).
2. Check actual OptiPlex source service status and read-only progress; GitHub code ≠ live deployment.
3. Confirm last complete source-only cycle's counts from the journal and current provider allowance, without exposing API credentials.
4. Check private PLaMo results under `~/bruiser-pilot/plamo3-ab/results/`. Do not claim a quality win without Japanese viewer feedback.
5. Advance the *first uncompleted* task and update status here **with exact evidence**, not speculative guesses.
6. Keep all scripts/tests pinned and immutable for any run. Unit tests + syntax check before deployment. Never apply a broad installer while the production source service is running.

**A successful day:** actual JP subtitles are added by the existing source worker, both PLaMo small models produce measurable *private* results, and the next step is obvious without needing to reconstruct prior chats.

## Official external references

- PLaMo 3 Translate official model card: https://huggingface.co/pfnet/plamo-3-translate-0.8b-GGUF
- Developer release/benchmarks (2026-11-05): https://www.preferred.jp/en/blog/tech/plamo-3-translate-weight-release
- OpenSubtitles API search vs download allowance: https://opensubtitles.tawk.help/article/getting-started
