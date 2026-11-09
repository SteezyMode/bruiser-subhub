> **PERMANENT SUBTITLE PRIORITY — 2026-11-09:** For ALL movies and series, prioritize existing professional/human-authored Japanese subtitles over PLaMo. Provider discovery is broad and preserves plausible, uncertain and rejected matches for review; it must not silently erase old candidate evidence on a subsequent miss. An automated miss is NOT proof that Japanese subtitles do not exist. Verified identity, language, timing and create-only publication gates remain strict. Source from every configured provider, investigate release/episode numbering and review ambiguous results before declaring sourcing exhausted. PLaMo is a LAST resort, after a usable English source has been verified, and never a default follow-up to a single failed search. The November 9 source discovery fix preserves search evidence across both selected and routine jobs, but native staging/publication still only handles trusted OpenSubtitles candidates; other provider results require Sublarr/manual review. GitHub code is not a deployed host result.

> **CURRENT OWNER DIRECTION — 2026-11-09: USABLE DASHBOARD OVER EXISTING WORKERS.** One title search for any movie or series; select seasons or episodes; inspect missing Japanese coverage and saved candidate rejections; explicitly recheck only selected episodes against configured Sublarr providers; then send source-exhausted English-ready episodes to the existing PLaMo 8B worker in bulk. No new library-wide jobs, no hardcoded IASIP/American Dad controls, no overwrites, no false "perfect timing" claims. **GitHub implementation is not host deployment.** See [dashboard acceptance and limitations](docs/SUBHUB_DASHBOARD_SELECTION_2026-11-09.md). Earlier dashboard-freeze/Sublarr-audit notes below are historical.

> **CURRENT OWNER DIRECTION — 2026-11-09: SUBLARR-FIRST REPLACEMENT AUDIT.** Before expanding the custom dashboard or queue, evaluate whether upstream Sublarr can replace most or all of SubHub for the existing household Jellyfin library. The actual goal is **usable Japanese subtitles**, with real Japanese sourcing and synchronization **before** optional PLaMo translation as the last resort. SubHub's previous Nov 8 custom-dashboard P0 roadmap is **on hold pending the controlled audit**, not implemented or discarded. Do not overwrite published subtitles, change running host services, or disable timers without verified replacement and rollback. See [issue #87](https://github.com/SteezyMode/bruiser-subhub/issues/87) for verified 1.18.0 host state, 1.20.1 gaps and decision gates. Earlier contrary development priorities below are historical.

> **CURRENT OWNER DECISION — NOV 8, 2026:** [SubHub product vision and phased roadmap](docs/SUBHUB_PRODUCT_VISION_AND_ROADMAP_2026-11-08.md). **Functional dashboard rebuilding is P0**: current read-only and stale-job-centric controls prevent the owner from managing the subtitle workflow. Prioritize accurate active/completed/held status, one-click JA sourcing with EN acquisition/PLaMo fallback, actionable reviews, resuming/archiving/creating jobs and real provider download accounting. Preserve existing workers and checkpoints; no parallel orchestration. The Nov 7 dashboard freeze below is superseded. This is a planning decision, not deployed code.

# Bruiser SubHub

> **HISTORICAL NOV 7 DIRECTION (DASHBOARD FREEZE SUPERSEDED NOV 8):** [SubHub architecture and pipeline handoff](docs/SUBHUB_ARCHITECTURE_AND_PIPELINE_HANDOFF_2026-11-07.md). **Dashboard freeze rescinded Nov 8; prioritize a functional operator UI.** Stop adding batch-/show-specific UI and stop inventing new orchestration layers. Focus next on measuring and simplifying **actual source/translation throughput, cue recovery, provider use, resumability, and watchable-JA coverage**. A future permanent Overview / Library / Queue / Settings GUI is a *design direction*, not current implementation work. This decision supersedes older dashboard feature requests and outdated task-specific “next steps” below. PR code ≠ host deployment.


> **LIVE TERMINAL PROGRESS (2026-11-06):** [Read-only curses live progress viewer](tools/bruiser_live_view.py) — **one stable terminal dashboard, incrementally updated in place without clearing/reprinting the screen on every tick** for the running `bruiser-subs` batch, with filled bars for source cycles, OpenSubtitles searches and sync/publication, plus staged/published/held counters, quota flags and recent activity. [Guarded test-first installer](tools/install_bruiser_live_view.sh). After install: `ssh -t optiplex@100.121.156.34 '~/.local/bin/bruiser-live'`; Ctrl+C exits only the VIEW. No hot-patching the active source process. **GitHub code is ready; host viewer deployment not yet confirmed.**

> **BATCH OPERATION (2026-11-06):** [Start/status/logs/stop control](docs/BRUISER_BATCH_OPERATOR_2026-11-06.md) + [guarded one-time installer](tools/install_bruiser_batch_controller.sh). A `bruiser-subs start --cycles 5` command launches **detached, observable, multi-cycle OpenSubtitles discovery/staging/ffsubsync/publication** immediately; `status --json` reports actual progress, holds and provider quota. **Host installation confirmed with 21/21 passing tests on November 6; live batch NOT started yet** because systemd user lingering is disabled. One-time fix: `sudo loginctl enable-linger optiplex` on OptiPlex, then `bruiser-subs start --cycles 5`. The earlier `Cycle: 3 / staged: 9` display was an old synthetic test fixture, NOT real batch progress. This is source-only; the separate substantial PLaMo GPU last-resort dispatcher remains future #63. Do not ask the owner to wait for the following day's small timer as the only way to process more titles.

> **ALREADY-DOWNLOADED JAPANESE RECOVERY (2026-11-06):** [Quota-free staged-JA publisher](tools/ja_first_publish_queue.py) has an optional `--queue-staged-only` filter and [guarded installer](tools/install_staged_ja_recovery.sh). It uses existing ffsubsync + strict no-overwrite gates to process the **21 pending staged-JA candidates before new downloads**. **Committed but not deployed or executed on host** until owner reports success; [steps](docs/BRUISER_COVERAGE_QUEUE_2026-11-06.md).

> **QUEUE-DRIVEN OPENSUBTITLES SELECTORS (2026-11-06):** The owner installed the persistent 12,386-media / 15,852-task queue AND deployed the queue-driven JA discovery/staging selectors (5/5 tests passed; 8,736 source identities matched actionable pending tasks). [Source integration issue #62](https://github.com/SteezyMode/bruiser-subhub/issues/62) tracks the next live acquisition results. Both old 75%-movie quotas are removed **in deployed code**. The next OpenSubtitles source run is scheduled for November 7 at 09:28:45 JST. Running the installer does not start OpenSubtitles requests, change the timer, or run PLaMo. Timing rescue is retained by the existing publishing pipeline.

> **AUTHORITATIVE WORKFLOW — DO NOT RE-DEBATE:** [Owner-confirmed canonical subtitle coverage policy, November 6](docs/BRUISER_SUBTITLE_POLICY_CANONICAL_2026-11-06.md). Preserve good existing EN/JA; **repair adjustable timing first**; reuse staged/saved provider subtitles; source correctly matched missing subtitles through OpenSubtitles; recover accurate English if needed; **GPU/PLaMo translation is the final fallback and expected to see substantial use**. No new arbitrary TV/movie quotas. [Persistent source/repair/translation queue](docs/BRUISER_COVERAGE_QUEUE_2026-11-06.md) is the next durable implementation.

> **COMPLETE ENGLISH + JAPANESE SUBTITLE INVENTORY (2026-11-06):** [Full bilingual media matrix](docs/FULL_EN_JA_SUBTITLE_MATRIX_2026-11-06.md), including **both languages on the same file**. The earlier English-without-Japanese report is a subset, **not** the complete subtitle inventory. **Verified on host:** 12,386 items; **522 both EN+JA**, **2,563 English only**, **41 Japanese only**, **8,336 neither**, **924 uncertain**. Private full-matrix CSVs/JSON are on the OptiPlex; no more baseline-wide scans needed.

> **NEW — FULL-LIBRARY COVERAGE CENSUS (2026-11-06):** [Private English-text/no-Japanese inventory for Bruiser](docs/BRUISER_LIBRARY_COVERAGE_AUDIT_2026-11-06.md). Source code and offline tests committed; **executed on the host November 6**. This is an older *subset* audit, superseded for total coverage by the bilingual matrix. Report excludes existing JA, distinguishes validated EN SRT vs embedded/text candidates and flags prior Jellyfin-only cases. No automatic translation or provider calls.

> **CURRENT SOURCING STATUS (2026-11-06):** [Verified acquisition results, failure analysis and coverage-first recovery strategy](docs/SUBHUB_COVERAGE_POSTMORTEM_AND_STRATEGY_2026-11-06.md). 600 Japanese searches produced 28 new published tracks before provider quota stopped staging; 300 English searches produced 0 verified external SRTs. **Goal: maximum usable Japanese subtitle coverage across the entire library**—not a fixed TV/movie/series preference. This supersedes the provisional November 5 source-result narrative below; code changes in GitHub do not change the live host.

> **ACTIVE AMERICAN DAD HANDOFF (2026-11-05):** [Read this first in a new chat — 48-episode PLaMo 8B batch, Natsuyo playback acceptance, CPU/GPU cooling, current 24 W LACT cap, status commands, next steps](docs/AMERICAN_DAD_ACTIVE_BATCH_HANDOFF_2026-11-05.md). The owner's real host batch started and the thermal pause/resume was observed; it is **not confirmed complete**. This handoff **overrides older model-R&D and undeployed-pilot statements for the American Dad workflow**. Keep the existing source-only Japanese subtitle discovery timer separate. Avoid model tournaments and duplicate episode reviews.

> **Current verified purpose (2026-11-05):** standalone, OptiPlex-hosted Japanese-subtitle **source / synchronization / publication** utility for Jellyfin (and ordinary external SRT use in Plex). **Not** a Jellyfin plugin, not a downloadable GUI, and **not** a core Bruiser/OptiPlex NOW feature. DIY AI translation is an isolated optional experiment, **not** part of the running source-only timer.
>
> **General source-only roadmap:** [November 5 execution roadmap](docs/EXECUTION_ROADMAP_2026-11-05.md), preserved for the separate Japanese-first source service. **For the now-running American Dad PLaMo 8B batch, use the active handoff linked above rather than the older R&D task list.**
>
> **Start here:** [What SubHub is and how the current install runs](docs/WHAT_IS_SUBHUB_AND_HOW_TO_USE_IT_2026-11-05.md) · [Source-first versus DIY decision](docs/HYBRID_JAPANESE_SOURCE_VS_DIY_POLICY_2026-11-05.md) · [PLaMo 3 Translate 0.8B/2B research plan](docs/PLAMO_3_TRANSLATE_EVALUATION_2026-11-05.md) · [Translation R&D evidence/stop decision](docs/TRANSLATION_RD_STOP_DECISION_2026-11-05.md).
>
> The live source-only test is **deployed on the owner's OptiPlex**, unlike the historical "not deployed" statements below: an interim owner-provided 2026-11-05 monitor reported 100/100 new searches, 50/51 staged downloads and 18 newly published sidecars with 28/56 publication titles examined. **Not a final run result or a native-Japanese viewing certification.** Routine ceiling 600/200/200, actual provider quota enforced, with a one-time 100-search override used in the test.


**Mission: help one household watch its existing ~6 TB media library together by automatically producing genuinely good Japanese subtitles for English-language films and shows.** Free and local on the existing OptiPlex; preserve existing editorial subtitles. Dual-subtitle playback is already solved. **SubHub itself is optional and may be replaced by a better free application.** See [GOAL.md](GOAL.md).

Currently a local English-to-Japanese subtitle translation coordinator for a personal media server. **Public-source development repository; currently an OptiPlex-specific working pilot, not a portable installer.**

**NEW PRIMARY DIRECTION (NOVEMBER 5): [Japanese-first sourcing, sync and quality research](docs/JAPANESE_FIRST_SOURCE_SYNC_QUALITY_RESEARCH_2026-11-05.md).** First prove real Japanese coverage on 50 representative library titles via native OpenSubtitles/SubDL/Jimaku when relevant, verify full dialogue, stage and safely sync to actual videos, and hold questionable AI/partial sources. Installed Sublarr already has most required source/sync/health machinery. Slower local translation is a *last resort* after measuring actual source success; never infer quality from GPU use or complete cue counts. No deployment changes authorized by this document.

**AUTOMATION NOW IMPLEMENTED IN REPO:** [Sublarr Japanese-source activation + spoiler-free *You Were Never Really Here* rescue](docs/JAPANESE_FIRST_AUTOMATION_ACTIVATION_2026-11-05.md). This enables source search on all existing library roots, bounded scheduled work, ffsubsync correction, no automatic AI translation, and no subtitle upgrades. The movie-specific path can sync an existing on-disk Japanese sidecar into a separate corrected copy or find/download/screen/sync a new original-JA candidate. These are real code artifacts with CI tests, but **not yet deployed to the user's OptiPlex** and not an automatic linguistic-quality guarantee. Use the pinned tested command in that guide; no plot summaries or spoilers.

## R&D STOP / quality reality check — November 5, 2026

**READ FIRST: [Evidence audit and explicit STOP decision](docs/TRANSLATION_RD_STOP_DECISION_2026-11-05.md).** The installed subtitle-tuned E4B model is an **operational fallback**, not a proven ~8/10, independently rated, best-quality translator. Nine model arms already produced **2,457 outputs across 273 cues on three films** in Benchmark 006; the recorded independent native-viewer blind-quality decision remains incomplete. **Do not restart prompt/history/quantization/grouped-JSON/HTML-cleanup loops or scale unattended E4B translation to the full library.** Use existing 006 blind outputs first, prioritize verified native Japanese subtitle acquisition, and retain current E4B for clearly labeled rough drafts.

**Only noteworthy newly released candidate:** Preferred Networks' PLaMo 3 Translate 2B GGUF (released 2026-11-05; not yet tested), which warrants at most one strictly bounded, model-native evaluation *after* the 006 viewer decision, never another speculative E4B change. No production model is changed by this documentation update.

## PRODUCTION TRANSLATION MODEL — CURRENT DECISION (NOVEMBER 4, 2026)

**INSTALLED OPERATIONAL PRIMARY (QUALITY WINNER UNPROVEN): 17slever17 Translate Gemma 4 Sub E4B — subtitle-tuned, GGUF Q4_K_XL; pinned Ollama ID 9ccfc3b07081.**

**EXACT MODEL:** hf.co/17slever17/translate-gemma-4-sub-e4b-GGUF:Q4_K_XL

**AUTHORITATIVE MODEL CONTRACT, EVIDENCE, PROMPT AND DEPLOYMENT: [docs/PRODUCTION_TRANSLATION_MODEL.md](docs/PRODUCTION_TRANSLATION_MODEL.md). READ THIS BEFORE ANY MODEL CHANGE.**

Production must use the author's **native one-CURRENT_SOURCE chat protocol**, with optional previous English/Japanese context, not the old generic multi-cue JSON translator. Model-card baseline: STYLE neutral; temperature 0; context 1344; max output 256. Exact installed model digest and **100% GPU residency** are mandatory preflights. Old-model checkpoints must not be silently mixed with new results.

**DO NOT USE:** generic gemma4:e4b-it-qat for production; the general model generated the poorly rated Attachment (2022) track. **Hy-MT2 7B is a benchmark alternative, not production default.** Older November 3 text below the linked decision and older experimental model plans do NOT override this.

Model choice is **provisional but explicit**: the matched 64-cue review preferred tuned E4B 26 times versus Hy-MT2 15, with 23 ties, but neither has an independent native Japanese 8/10 viewing grade. Preserve full dialogue meaning, slang, profanity and register. The household target is ~8/10 practical viewing; no magic quality certification from completing a movie.

**GitHub source changes are not automatically deployed to the OptiPlex.** Use the guarded installer from the model-decision document, verify the live host model/profile first, and preserve all existing human Japanese subtitles. No automatic library-scale rollout until the tuned worker has been tested on a fresh title.

### Live progress tracker — standard workflow

The reusable read-only tracker is installed by [tools/install_subhub_tracker.sh](tools/install_subhub_tracker.sh), and is included in all new installs from [tools/install_ja_first_controller.sh](tools/install_ja_first_controller.sh).

From the Mac mini, attach to the currently running subtitle job (or inspect the most recent/pending job):

~~~bash
ssh -t optiplex@100.121.156.34 'python3 ~/bruiser-pilot/subhub-control/ja_first_cycle.py watch'
~~~

To start the next **already queued, verified** subtitle-tuned E4B job **and automatically watch that exact job**:

~~~bash
ssh -t optiplex@100.121.156.34 'python3 ~/bruiser-pilot/subhub-control/ja_first_cycle.py start-worker --apply --watch'
~~~

This shows actual SQLite cue progress, ETA from recent samples, current status, model provenance (or explicitly "unverified" for old checkpoints), worker/Ollama CPU and GPU utilization/VRAM/temperature/power. It never writes media or checkpoints; Ctrl+C stops only the display, **not** translation. Finishing all cues is not the same as passing publication QA. The watcher never silently launches another film.

### Attachment (2022): full corrected-model retranslation with progress

For the previously poorly translated *Attachment*, the dedicated one-command runner is [tools/start_attachment_e4b.sh](tools/start_attachment_e4b.sh), with [full safety and output details](docs/ATTACHMENT_E4B_RETRANSLATION.md). It reads **the same 1,276 original English cues**; runs **only pinned 17slever17 subtitle E4B** with the author-native single-cue prompt; stages **fresh isolated checkpoint state** and attaches an automatic live tracker. **No previous generic-model Japanese is reused**.

After full completion it creates a separately named **E4B Review Japanese** sidecar beside the film for Jellyfin A/B and a private EN+JA review archive. Neither original subtitles nor the original SubHub SQLite checkpoints are overwritten. This is a trial for qualitative review, **not automatic library-scale model certification**.

### Historical experiments

## Real S19E04: 27 private editorial corrections ready for QA and a separate Japanese track

The user provided the real remaining **27 flagged cues** from American Dad S19E04, including English, old Japanese, timing, and surrounding lines. Four contain obvious copied-ahead future dialogue (8, 52, 76, 77); many others have reasonable reading speeds but violate the current 18-Japanese-character line-width gate; cue 338 includes an intentional verbal contradiction that can look like a false future-text overlap.

A private, handwritten correction payload for all 27 cues was prepared **outside public GitHub**. The public `tools/s19e04_apply_private_editorial.py` combines the original 392-cue S19E04 Japanese pilot, **all saved accepted v1/v2 repair checkpoints**, and the private 27 replacement lines. It refuses to proceed unless original English/JA per-cue hashes match, checks the existing frozen manifest, and audits the COMPLETE reconstructed 392-cue file. If fully clean, it generates a create-only versioned `Bruiser Curated Japanese v2.ja.srt` track without modifying original media, previous JA files or checkpoints. This is a fast, no-model/no-GPU step. The private correction file must never be committed to this public repo.

Owner steps, from Mac Mini:

1. Download `s19e04_private_editorial_27.json` from the ChatGPT artifact link into `~/Downloads`.
2. Run:

```bash
cd ~/Downloads/bruiser-subhub-repo
git pull --ff-only
bash tools/apply_s19e04_editorial.sh optiplex@YOUR_HOST ~/Downloads/s19e04_private_editorial_27.json
```

The wrapper runs offline tests and host preflight, stages only isolated non-service code, safely transfers the user-private JSON over SSH, generates a private QA preview, then create-only publishes if **every** cue passes. `S19E04_EDITORIAL_PUBLISHED` is the only proof of an actual new watchable track. See [private editorial instructions](docs/S19E04_PRIVATE_EDITORIAL_27.md). A real host execution and Japanese playback check remain unverified.

## Repair the already-published American Dad S19E04 into a separate Japanese track

Real S19E04 viewing revealed oversized, prematurely copied future dialogue in old v009 Japanese captions. The new selected-season publication gate prevents more of that, but never rewrites old pilot files. The one-off `tools/repair_s19e04.py` repairs only suspicious cue IDs using the existing subtitle-tuned E4B model, a **current-cue-only** correction prompt, and immutable private checkpoints. It publishes a **separate versioned Japanese SRT** only after full-episode mechanical QA; the original v009 pilot remains in place.

```bash
cd ~/Downloads/bruiser-subhub-repo
git pull --ff-only
bash tools/run_s19e04_repair.sh optiplex@YOUR_HOST
```

The MacBook can disconnect after the host user systemd job is launched. If OptiPlex shuts off mid-run, re-run the **same command** after boot to use saved cue repairs (no nightly timer is added for this one-time editorial job). See [S19E04 repair instructions](docs/S19E04_VERSIONED_REPAIR.md). Only the first live host execution will confirm repair quality and whether a new track can be published.

## Japanese subtitle readability gate, safe resume after power loss

The owner found repeatedly unreadable Japanese subtitles while watching American Dad S19E04. The existing pilot audit already showed copied-ahead future dialogue and extreme reading density. New `tools/subtitle_publish_gate.py` now gates the actual selected-season worker's final publication: it rejects severe overlength, copied future dialogue, more than two lines, and excessive line/cue width. A held episode preserves completed SQLite cue checkpoints and stops the season rather than processing 21 more poor-quality episodes. QA-approved Japanese SRTs now use a **fsynced temporary file and atomic create-only hardlink**, so loss of power during publication cannot expose a half-written final subtitle. Existing approved Japanese and the faulty v009 S19E04 pilot are unchanged.

**Use the existing repair command** after CI/merge; it now deploys the systemd lifecycle fix AND the quality gate together:

```bash
cd ~/Downloads/bruiser-subhub-repo
git pull --ff-only
bash tools/repair_american_dad_worker.sh optiplex@YOUR_HOST
```

MacBook shutdown after the host service launches doesn't stop OptiPlex translation; OptiPlex power loss stops model work but safely committed SQLite cue batches persist and resume on a later timer run, assuming the disk remains healthy and user systemd manager runs. The in-flight cue/model call may be repeated. **No actual new S20 Japanese SRT has been verified yet**; expect the first episode to be held if output violates the gate. See [quality and shutdown details](docs/JAPANESE_READABILITY_AND_RESUME.md).

## Repair interrupted American Dad background worker (2026-11-02)

**Real host diagnosis:** the nightly user `Type=oneshot` service successfully selected S20, spawned an `american_dad_seasons.py` detached process, then exited. Its systemd cgroup ended too, terminating the season child before it could print or publish work. A successful launch PID was *not* successful translation. This revision replaces the maintenance launcher with **supervised foreground season execution** in a distinct systemd `Type=exec` service, Python unbuffered output, an 11-hour bound, and logs simultaneously in the journal and `american-dad-seasons.log`. The change upgrades only the **exact previously installed Bruiser unit**, saves its old content as a private backup and preserves all user timers and media services.

On MacBook after merge:

```bash
cd ~/Downloads/bruiser-subhub-repo
git pull --ff-only
bash tools/repair_american_dad_worker.sh optiplex@YOUR_HOST
```

This stages two repaired scripts and requests a new service run for the already-selected season. It does not re-download Whisper, re-run the entire Jellyfin source inventory, change Gemma prompts, or touch any videos. The command outputs the live service status and journal. If the maintenance service is already working, it does not interrupt it.

## American Dad: automatically select a workable season, fill missing English locally

**After the real Jellyfin scan:** 12,398 videos; 3,073 already have English text; 9,325 lack it. All 18 Season 8 attempts had no exact-provider hash match, and the later targeted subtitle download reported no usable English. To avoid picking an impossible season or asking you to fetch captions manually, use this one MacBook command:

```bash
cd ~/Downloads/bruiser-subhub-repo
git pull --ff-only
bash tools/auto_american_dad.sh optiplex@YOUR_HOST
```

It automatically checks the actual American Dad audio/subtitle tracks and existing Japanese sidecars across all seasons, selects the most watchable not-yet-translated season, and uses the already-tested Gemma E4B campaign. For remaining gaps it installs a separate local **CPU-only faster-whisper** English transcription fallback and creates **draft** English SRTs one episode per night at low resource priority, then resumes the selected-season Japanese translation. This is **not** another model/prompt experiment and does not translate the rest of Jellyfin. New ASR subtitles can contain misheard jokes and names; first actual episode needs viewing review. The code is tested offline but real provider/model performance requires a live host run. See [automatic season instructions](docs/AMERICAN_DAD_AUTOPILOT.md).

## Library-wide English subtitle inventory (permanent source shelf)

One MacBook command scans **all Jellyfin movies and episodes** for English text subtitle coverage, searches only missing sources through the existing installed Jellyfin subtitle providers, saves **only exact file-hash-matched English SRTs**, and enables a conservatively throttled daily user timer when possible:

```bash
cd ~/Downloads/bruiser-subhub-repo
git pull --ff-only
bash tools/stock_english_sources.sh optiplex@YOUR_HOST
```

The first pass allows at most 18 provider searches; automatic daily passes allow only 5. **American Dad S08 is first in the source queue.** Source acquisition never triggers library-wide Japanese translation; run the established S08-only translator separately after English sources are ready. If a provider offers no exact match, the video remains queued rather than receiving an uncertain subtitle. No existing caption or Jellyfin configuration is overwritten. See [full instructions](docs/ENGLISH_SOURCE_INVENTORY.md). Live provider coverage is unverified until the OptiPlex runs this.

## Get American Dad English sources from existing Jellyfin first

If the Season 8 plan shows all 18 episodes missing English subtitles, use Jellyfin's **existing** subtitle providers automatically, then launch the established season translator:

```bash
cd ~/Downloads/bruiser-subhub-repo
git pull --ff-only
bash tools/fetch_american_dad_english.sh optiplex@100.121.156.34 8
```

You may be asked **once** for your existing Jellyfin admin username/password in a hidden SSH terminal prompt; no separate account or subtitle-manager configuration is needed. The helper only searches matching S08 items, respects original Japanese tracks, uses Jellyfin per-item download APIs, and then runs the existing Gemma worker on newly available English SRTs. It does not start the whole-library subtitle task, Sublarr, or new prompt experiments. Provider results are unverified until the first live run. See [native Jellyfin source workflow](docs/AMERICAN_DAD_JELLYFIN_SOURCES.md).

## Watch American Dad — selectable season batch

The priority now is actual season subtitles for watching together, **starting with Season 8**, not more translation-format research. One MacBook command scans the real media library, skips episodes with existing Japanese, and runs the existing SubHub translator serially for all eligible episodes. It can resume an interrupted season:

```bash
cd ~/Downloads/bruiser-subhub-repo
git pull --ff-only
bash tools/run_american_dad_seasons.sh optiplex@100.121.156.34 8
```

For two seasons, append `9`. See [American Dad season-batch instructions](docs/AMERICAN_DAD_SEASON_BATCH.md). The current model's translation-quality limitations still apply; completed subtitles should be assessed by watching.

## Use it for one movie at a time

After updating the MacBook checkout:

```bash
cd ~/Downloads/bruiser-subhub-repo
git pull --ff-only
bash tools/daily_japanese.sh optiplex@100.121.156.34
```

This stages ONLY an isolated one-title intake/worker wrapper onto the host; it does not replace the installed SubHub service. It finds an English-audio title without Japanese, extracts existing English text subtitles if present, queues one title, and starts the existing translator in the background. Subsequent invocations resume an unfinished daily job before adding another. It refuses existing Japanese and unknown/bitmap-only English sources. **Real Japanese accuracy remains limited by the current model** and must be judged by viewing; not a claim of 8/10 quality. See [daily-use instructions](docs/DAILY_JAPANESE.md).

## Current implementation (SubHub 1.0)

- Resumable SQLite queue with per-cue Japanese checkpoints and bounded retries.
- Gemma 4 e4b via local Ollama for primary translation.
- Optional sampled HY-MT2 backtranslation for **advisory** review only; **not** a publishing gate.
- Full-source/timing structural checks before Japanese-only sidecar publication.
- Media audio-language verification before publication; existing editorial Japanese files cannot be overwritten by a differing machine output.
- Thermal limits, one worker lock, progress/event telemetry, and a read-only local dashboard.
- Explicit `--publish` needed for sidecar publication. Without it, a run can translate without publishing.

## Important limitations

**Not standalone yet:** `service.py` imports `bruiser_auto.py` for the Gemma prompt/response parser and `bruiser_hy_backtranslate_compare.py` for HY review from `~/bruiser-pilot`. `launch.sh` also reads the legacy `subhub-household/jobs.json` on initial import. These upstream files are not in this source snapshot. The media roots `/mnt/BigDisk/Video` and `/mnt/2TB/Plex Expansion`, Ollama models, and service layout are currently host-specific.

The offline tests prove queue/retry/publishing mechanics with mocked translators; they do **not** establish real-world Japanese localization quality or proof that the current server campaign finished successfully.

## Optional natural, uncensored Japanese quality test

`natural_8` preserves idioms, slang, profanity, sex/violence, sarcasm and adult character voice while gently encouraging concise Japanese for the available screen time. **It is NOT Netflix spec and never hard-truncates translations.** It is opt-in through `SUBHUB_LOCALIZATION_STYLE=natural_8` when a future tested deployment is appropriate; the current running worker is not changed by a GitHub merge.

For a safe comparison with already translated *Primate* passages, the Mac mini can run `bash tools/compare_primate_style.sh HOST PRIMATE_JOB_ID` after the worker is idle. This stages a temporary benchmark-only copy of the engine, calls the existing free local Ollama model on selected dialogue windows, and privately retrieves an English/existing-Japanese/candidate-Japanese report. **No published track or checkpoint is modified.** See [tools/README.md](tools/README.md).

## Read-only 6 TB library inventory

From the Mac mini checkout, `bash tools/library_census.sh optiplex@HOST` inventories both known video roots by filenames and ffprobe track headers. It **does not translate, import, publish, download, modify media, or start a worker**. Counts existing Japanese sidecars/embedded tracks, usable English subtitle sources, OCR-only sources and missing sources. Individual-title metadata can be saved to a **private** JSON only with explicit `--out`; no subtitles or media are copied. More details in [tools/README.md](tools/README.md).

## Offline tests (no Ollama / GPU / media library)

```bash
python3 -m unittest discover -p 'test_*.py' -v
```

## Running installation

The known pilot runs from `~/bruiser-pilot/subhub1` using state at `~/bruiser-pilot/subhub1-state`. Do not replace code while an active translation process is running. Do not put the state directory in Git, and do not rerun `launch.sh` just to update source files: it includes import and start actions.

Read-only status on the existing host:

```bash
python3 ~/bruiser-pilot/subhub1/main.py --root ~/bruiser-pilot/subhub1-state status
```

See [docs/roadmap.md](docs/roadmap.md) for safe next steps and [docs/security.md](docs/security.md) for privacy boundaries.


## Editorial quality review (read-only, no model calls)

The independent `review_sampler.py` selects dialogue across a film, prioritizing mechanical review cases such as numbers, negation, formatting and reading speed. It includes neighboring English cues for human context review. It **does not judge translations, edit checkpoints, call HY, or gate publication**.

```bash
python3 review_sampler.py --root ~/bruiser-pilot/subhub1-state --job JOB_ID
python3 review_sampler.py --root ~/bruiser-pilot/subhub1-state --job JOB_ID \
  --count 60 --out ~/bruiser-pilot/subhub1-state/review/JOB_ID.editorial.json
```

The first command prints summary counts only; the second explicitly creates a local JSON review packet. Exports contain private subtitle dialogue and must never be committed. See [docs/OPERATIONS.md](docs/OPERATIONS.md).

## Resuming development

Start with [AGENTS.md](AGENTS.md), [docs/CURRENT_STATE.md](docs/CURRENT_STATE.md), and open pull requests. Keep that handoff document updated as code is merged and deployed. **A GitHub commit is not an OptiPlex deployment.**

## Standalone SubHub Dashboard (v0.1, read-only)

A small browser dashboard now lives **separately from OptiPlex NOW**. It displays the same real batch counters as the terminal viewer, including new published Japanese subtitles, downloads, held items, activity, and future translation status. Its own loopback-only user service and desktop launcher do **not** control the source worker or require it to be restarted.

See [dashboard installation, SSH access, deployment boundary and AI worker contract](docs/SUBHUB_DASHBOARD_V01.md). The pinned installer is [tools/install_subhub_dashboard.sh](tools/install_subhub_dashboard.sh); an optional Linux remote SSH desktop shortcut is [tools/install_subhub_dashboard_client.sh](tools/install_subhub_dashboard_client.sh). Offline tests: [test_subhub_dashboard.py](test_subhub_dashboard.py). **Not installed on the host merely by committing to GitHub.** Read-only means Pause/Resume/Start/Prioritize are not yet available; [issue #66](https://github.com/SteezyMode/bruiser-subhub/issues/66) tracks controls and reboot recovery, and [issue #65](https://github.com/SteezyMode/bruiser-subhub/issues/65) tracks automatic new-media detection. OptiPlex NOW private-alpha features remain frozen.

## Source-exhausted Japanese → PLaMo8B handoff (guarded pilot)

The standalone SubHub translation handoff now has a queue-owned, opt-in single-item adapter: [tools/subhub_plamo_handoff.py](tools/subhub_plamo_handoff.py). It reuses the previously proven official PLaMo 3 Translate 8B Q4_K_M CUDA runtime, thermal limits, checkpoints and safe sidecar publisher **without starting a second model worker or modifying the existing American Dad batch**. Default CLI is read-only; an explicit source-verifying `--prepare` does not touch GPU; `--apply` is blocked while source jobs or the old translator are active.

See [integration/limitations](docs/SUBHUB_PLAMO_HANDOFF.md), [offline tests](test_subhub_plamo_handoff.py), and [pinned installer](tools/install_subhub_plamo_handoff.sh). **This pilot is code in GitHub, not an installed or fully autonomous translator.** Exact-match missing-English recovery/OCR, movie-length cue handling, safe dispatcher/boot recovery, and dashboard AI status remain upcoming work. The active 12-cycle JA source batch is unaffected.
