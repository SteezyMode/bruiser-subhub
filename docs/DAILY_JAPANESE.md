# Daily Japanese subtitles — one household title at a time

**Purpose:** Pick an existing English-audio movie or episode in the OptiPlex's media library that does not already have Japanese subtitles, acquire its **existing** English text captions, add it to the existing SubHub 1.0 translation queue, and run **only that one title** through the existing local translator. No new model, no model experiment, no dual-sub feature, no replacement of existing editorial Japanese, and no second monolithic service.

## MacBook one-command workflow after merge

    cd ~/Downloads/bruiser-subhub-repo
    git pull --ff-only
    bash tools/daily_japanese.sh optiplex@100.121.156.34

The wrapper runs offline Python regressions, stages **only** tools/daily_japanese.py and tools/daily_worker.py into ~/bruiser-pilot/daily-japanese-code, and calls the intake helper on OptiPlex. It does **not** overwrite ~/bruiser-pilot/subhub1/main.py, service.py, legacy adapters, existing source/cues, or any accepted JA track.

Expected terminal signals:

- DAILY_SCAN: up to 30 actual ffprobe checks, skipping files already queued and filenames with recognized Japanese sidecars.
- DAILY_CANDIDATE: candidate video filename, English subtitle cue count, labeled SRT or embedded EN text origin.
- DAILY_QUEUED: immutable existing SubHub 1.0 queue job ID. One title maximum.
- DAILY_WORKER: detached process ID and daily-worker.log path. This means **started**, NOT necessarily translated, not necessarily published, and not a Japanese-quality verdict.
- DAILY_PENDING: prior daily job is still queued/translating/translated. **Reuses that job instead of queuing another**.
- DAILY_RESULT no_eligible_english_source_in_this_scan: scanned this bounded slice, no eligible English text; cursor advances to inspect later files on next run. NOT a claim that no videos in the library need JA.

Preview without mutation from OptiPlex (no queue, cursor or model call):

    python3 ~/bruiser-pilot/daily-japanese-code/daily_japanese.py --probe-budget 30

View actual daily job status:

    ssh optiplex@100.121.156.34 'python3 ~/bruiser-pilot/subhub1/main.py --root ~/bruiser-pilot/subhub1-state status'
    ssh optiplex@100.121.156.34 'tail -60 ~/bruiser-pilot/subhub1-state/daily-worker.log'

**A successful queue or detached start is NOT a completed Japanese subtitle.** Wait for status "published", then verify the new Japanese-only track in Jellyfin. The actual output comes from the pre-existing SubHub 1.0 translator and can still contain mistranslations. Watch one episode/film before considering any automatic scaling.

## Selection policy and safety

- Walk known media roots without following symlinked folders or videos. Scan candidates in deterministic order; persist a private scan cursor in the existing state only after explicit --apply, so consecutive daily invocations don't get stuck scanning the same first 30 ineligible films. On initial run, inspect first 30 unqueued, no-JA-sidecar candidates.
- Read video metadata with ffprobe. Require explicitly tagged English primary audio; do NOT infer English from a movie filename or speech. Skip any detected embedded Japanese or same-film Japanese/editorial subtitle sidecar (SRT/ASS/SSA/VTT/SUB/SUP, including symlinks).
- Prefer a named English SRT sidecar for the **exact video stem**, otherwise extract an English, non-forced, text-compatible embedded subtitle with ffmpeg (stdout only). No OCR, Whisper, subtitle acquisition, untagged guessing or copying video to scratch.
- Check SRT source count/IDs, reject sparse IDs that the legacy writer could renumber (preventing accidental subtitle time drift). Source is capped at 2 MB and 15–12,000 nonempty timed cues. No machine-made filler. Save a source snapshot into the existing SubHub 1.0 SQLite queue through its own Store.add.
- SQLite read-only checks avoid duplicate video jobs under a different ID. Before mutation, recheck video identity, audio/subtitle metadata and existing Japanese; respect both existing SubHub worker locks. A failure refuses mutation rather than forcing a concurrent writer.
- Start a tiny separate tools/daily_worker.py that invokes the **already-installed SubHub 1.0 main.run()**, replacing only its job listing **within this process** to expose the selected daily job ID. This is important: the standard main.py --max-titles=1 is a **completion counter**, not a strict job filter, so it could otherwise process an unrelated backlog when a title fails.
- That existing run() retains both locks, thermal/VRAM safeguards, bounded time (120 minutes), cue checkpoints, pause flag, and JA create-only publishing. HY review intentionally skipped. Runs in a detached process, logging to subhub1-state/daily-worker.log. Only the current daily title is considered.
- If a title remains queued or translated after interruption, the next command attempts that same title again without making another queue entry. Explicitly failed/held daily titles are left for review and are not repeatedly brute-forced.
- No source videos, existing Japanese, previous translation checkpoints, SubHub 1.0 code, Sublarr or Jellyfin settings are changed.

## Boundaries and next decision

This fixes **ingestion and single-title operation**, NOT quality. Existing local Gemma may remain approximately 6/10 on idiom-heavy comedy and worse on particular jokes. This is an intermediate way to get actual Japanese files into Jellyfin instead of running more translation-format pilots. Daily automation should not be enabled on a blind schedule or across the 6 TB library before verifying one real host run and viewing its output.

It does not find English subtitles externally. If no tagged English text is present, keep the title unqueued: existing subtitle providers/metadata acquisition should handle source availability separately. This tool is not a replacement for Subbuzz or Sublarr's source discovery.

**Deployment boundary:** a GitHub merge only updates code in the repository. The first real OptiPlex run must confirm installed ~/bruiser-pilot/subhub1/main.py, service.py, source mounts and ffprobe/ffmpeg are present and compatible. The helper never silently replaces them. A publishing error or missing model is visible in the daily worker log.
