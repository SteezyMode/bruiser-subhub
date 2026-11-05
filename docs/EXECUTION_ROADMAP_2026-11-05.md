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

**Status:** benchmark runner and bootstrap code committed and Python tests passed; **not executed on OptiPlex** until owner runs it.

- Use the pinned standalone installer [install_plamo3_small_ab.sh](../tools/install_plamo3_small_ab.sh) and [Python benchmark](../tools/plamo3_small_ab.py). Private working root: \`~/bruiser-pilot/plamo3-ab\`.
- Download exact PFN official Q4_K_M model files **0.8B (~0.57GB)** and **2B (~1.81GB)**. Use a pinned, locally extracted llama.cpp CUDA 12.8 build; no Ollama/model replacement, root package installation, or media writes.
- Both run in sequence on **the same 16 original, non-movie English dialogue samples** using PFN's actual PFML3 translation prompt, temperature 0 and stop tokens. Include idioms, negation, register, sarcasm and threats. Preserve English cue timecodes. Capture raw JA, latency, provenance, simple mechanical flags and GPU preflight.
- STOP for runtime incompatibility, missing CUDA libs, unverified weights, insufficient VRAM or active gaming. Don't forcibly unload any other model; no automatic fallback to different models.
- **Exit criterion:** both model servers start, 16/16 returned without truncation/empty or non-Japanese replies per arm, private run records created and no source-only worker changed. This is a **smoke test only**, NOT quality certification or proof of 8/10 Japanese.

**Command on Mac mini:** see bottom of this document or a future answer. User may close terminal only *after* the foreground model test completes. The source-only timer continues independently.

### Task 2: Real subtitle A/B, 80–120 continuous cues (SAME DAY if smoke test passes)

**Status:** not run. A real source must be selected and its provenance verified first.

- Select ONE *fresh* real English-dialogue scene in a horror/drama title with reliably matched existing English SRT: avoid previously overstudied *Primate*, the four sealed Benchmark 006 scenes, and familiar benchmark prompts. Source selection is read-only; record original English SRT SHA256, title identity, selected cue IDs/timing, media hash or trusted binding.
- Run **the same frozen 80–120 English cues** through each small PLaMo model using the developer-native PFML3 contract. Save both raw outputs and Japanese draft SRT with original timestamps to PRIVATE review storage. Do **not** add model text to public GitHub or publish media-adjacent JA.
- Inspect obvious meaning reversals, omissions, idioms/profanity, register, names, repeated/spillover lines, reading speed. Ask a Japanese-speaking viewer to watch **one small blind scene**, not 36 runs. A small number of severe plot-reversing errors can disqualify an arm despite 100% structural completion.
- **Exit criterion:** useful side-by-side private candidate files and time/VRAM metrics; explicit verdict \`0.8B viable\`, \`2B viable\`, \`both draft-only\`, or \`optional 8B comparison warranted\`. Aim for ~7.5–8/10 ordinary viewing quality; no automatically inferred grade. If both disappoint, STOP model prompt fiddling and keep source-only coverage expansion moving.

### Task 3: Operational source-run report

**Status:** 100-search cycle finished; final summary figures above recorded.

- Save counts, typical hold categories, cache hit rate, current OpenSubtitles account's actual remaining download allowance (if obtainable safely without printing secrets).
- Sample a handful of newly published Japanese tracks in Jellyfin for timing and naturalness, including a title with difficult accents/slang. Do not attempt to "fix" everything from day-one.
- **Exit criterion:** clear reason codes for the 14 held titles and confirmation that repeat search/download no longer consumes allowance on already published titles. If no evidence of a real bug, leave source code alone.

## TOMORROW — Friday November 6

### Task 4: Let scheduled source-only cycle run normally

- No manual second 600-search command while scheduled service is active. Verify \`systemctl --user list-timers --all bruiser-ja-source-autofill.timer\` and, after the run, summarize \`journalctl --user -u bruiser-ja-source-autofill.service -n 100 --no-pager\`.
- Observe whether the daily software **600-search cap** and provider quota cause a full publication phase within the **8-hour** service limit. If discovery throughput varies, shorten daily search batch *via a deliberate one-time setting*, rather than losing publication to a timeout.
- **Exit criterion:** report searches actually made, plausible/review/no-result, actual downloads, newly published, deduped, held, elapsed, provider allowance exhausted (if any), and top error/hold causes. Avoid projecting 37/100 as stable long-run coverage.

## NEXT IMPLEMENTATION — after the PLaMo A/B evidence

### Task 5: Unified router / economical source-or-DIY queue (new feature, NOT LIVE)

**Routing per media ID**, with durable SQLite transitions and a small, auditable number of states:

\`\`\`text
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
\`\`\`

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
4. Check private PLaMo results under \`~/bruiser-pilot/plamo3-ab/results/\`. Do not claim a quality win without Japanese viewer feedback.
5. Advance the *first uncompleted* task and update status here **with exact evidence**, not speculative guesses.
6. Keep all scripts/tests pinned and immutable for any run. Unit tests + syntax check before deployment. Never apply a broad installer while the production source service is running.

**A successful day:** actual JP subtitles are added by the existing source worker, both PLaMo small models produce measurable *private* results, and the next step is obvious without needing to reconstruct prior chats.

## Official external references

- PLaMo 3 Translate official model card: https://huggingface.co/pfnet/plamo-3-translate-0.8b-GGUF
- Developer release/benchmarks (2026-11-05): https://www.preferred.jp/en/blog/tech/plamo-3-translate-weight-release
- OpenSubtitles API search vs download allowance: https://opensubtitles.tawk.help/article/getting-started
