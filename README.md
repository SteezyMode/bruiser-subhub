# Bruiser SubHub

**Mission: help one household watch its existing ~6 TB media library together by automatically producing genuinely good Japanese subtitles for English-language films and shows.** Free and local on the existing OptiPlex; preserve existing editorial subtitles. Dual-subtitle playback is already solved. **SubHub itself is optional and may be replaced by a better free application.** See [GOAL.md](GOAL.md).

Currently a local English-to-Japanese subtitle translation coordinator for a personal media server. **Public-source development repository; currently an OptiPlex-specific working pilot, not a portable installer.**

## Library-wide English subtitle inventory (permanent source shelf)

One MacBook command scans **all Jellyfin movies and episodes** for English text subtitle coverage, searches only missing sources through the existing installed Jellyfin subtitle providers, saves **only exact file-hash-matched English SRTs**, and enables a conservatively throttled daily user timer when possible:

```bash
cd ~/Downloads/bruiser-subhub-repo
git pull --ff-only
bash tools/stock_english_sources.sh optiplex@100.121.156.34
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
