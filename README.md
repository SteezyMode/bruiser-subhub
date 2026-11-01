# Bruiser SubHub

Local-first English-to-Japanese subtitle translation coordinator for a personal media server. **Public-source development repository; currently an OptiPlex-specific working pilot, not a portable installer.**

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
