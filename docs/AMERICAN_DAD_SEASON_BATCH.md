# American Dad season batch — watch the cartoons, not the translator

**Household goal:** Produce Japanese-only subtitles for one or two *actual American Dad seasons* already in the user's media library, using the installed local Gemma translator and working SubHub 1.0 queue. **Season 8 is the default because the user asked about it.** Season 9 is optional. Seasons 19/20 were merely historical experiment sources and are not special production targets. Existing dual-sub playback is already solved and out of scope.

## One MacBook command — Season 8

    cd ~/Downloads/bruiser-subhub-repo
    git pull --ff-only
    bash tools/run_american_dad_seasons.sh optiplex@100.121.156.34 8

For **two seasons**, deliberately choose both:

    bash tools/run_american_dad_seasons.sh optiplex@100.121.156.34 8 9

The command runs offline regressions, stages **only three new/isolated helper scripts** in ~/bruiser-pilot/american-dad-season-code, prints a read-only plan of the **real matched episodes**, and launches the translation campaign as an independent background process on the OptiPlex. It does NOT edit installed SubHub 1.0 code, translate an unrelated film, replace accepted subtitles, start new A/B tests, touch old v009–v013 pilots or change Jellyfin/dual-sub configuration.

## Read the actual campaign's progress

    ssh optiplex@100.121.156.34 \
      'tail -60 ~/bruiser-pilot/subhub1-state/american-dad-seasons.log'

And for the existing cue queue and specific holds:

    ssh optiplex@100.121.156.34 \
      'python3 ~/bruiser-pilot/subhub1/main.py --root ~/bruiser-pilot/subhub1-state status'

Key log messages: SEASON_PLAN and SEASON_PLAN_SUMMARY list *available episodes* and what is currently missing; SEASON_QUEUED is an episode whose English SRT was imported; GEMMA x/y shows already checkpointed translated cues; PUBLISH / SEASON_RESULT confirm a completed Japanese sidecar. SEASON_NEEDS_SOURCE means embedded/sidecar English text is missing or corrupt, not that the episode is translated; SEASON_REVIEW means previously held, conflicting or exhausted checkpoints; SEASON_INTERRUPTED means busy locks, exhausted time, or host/GPU problem. **SEASON_SUMMARY** is the final count. A successful START alone is NOT proof that a full season finished.

Run the **same MacBook command again** after a stopped/limited batch. It uses existing source SHA + per-cue translated checkpoints, checks real existing Japanese subtitles first, and continues the remaining season. It does not retranslate completed episodes or reset a failed cue's retry count. If an episode needs review, it records that and moves on to other available episodes, rather than hanging the whole season.

## Actual policy

- Only video files from existing approved mounted media roots with a real *American Dad* name/path and **S08E01** or **08x01** style filename match. S08 and S09 are not aliases for some "scene-numbered" alternative season: the read-only plan shows which actual episode IDs matched. The program never creates fictional season/episode IDs to reach an expected 20 episodes.
- For duplicate releases, skip if **any copy already has recognized Japanese** as a same-video sidecar or embedded track. Also skip episodes already published in the existing SubHub queue, including other historical job names.
- Require verified **English primary audio** from ffprobe, an existing **named English SRT** or a real non-forced **embedded English text subtitle** track. Extract with ffmpeg to stdout, verify valid cue numbers/timecodes, stage input to SQLite through the existing SubHub job import. Never OCR or fabricate missing sources.
- Run **one episode at a time** with tools/daily_worker.py; it invokes existing main.run() after filtering the in-process Store.jobs() view to just the episode ID. This preserves the already-tested Gemma model, worker locks, GPU thermal safeguards, 120-minute per-episode cap, per-cue checkpoints, existing source identity and create-only JA SRT publisher. In particular, unrelated *Bottoms*/horror queue jobs cannot run.
- Campaign is single-instance locked, defaults to max 50 episode attempts and max 480 minutes of campaign wall-clock budget, and obeys the existing PAUSE flag. If the host becomes busy/unavailable/too hot, it stops and resumes with the same launch command. Exhausted/held episodes are **not** force-retried.
- All shell and program status output omits private subtitles and actual English dialogue. No input or translations are put into public GitHub. The one output artifact of success is a regular Japanese-only external SRT beside the episode, readable by Jellyfin.
- **This is a functional delivery improvement, not a claim of Japanese quality.** The current Gemma translates as well or badly as before: previously observed issues with comedy idioms and names remain possible. After Season 8 is published, actually watch an episode together and decide whether it is acceptable; do not change model prompts mid-season.

## First-run boundaries

Repo code and synthetic unit tests do not prove the installed OptiPlex deployment has compatible modules, that all of S08 exists, that every episode has usable English sources, or that the GPU can translate for hours under the current desktop workload. The read-only plan checks the real library; the batch log reports each actual result. A GitHub merge is **not** a host deployment. The user's MacBook command stages the helpers and begins processing.

No automatic nightly schedule or additional background monitoring is created. One explicitly launched, bounded season batch is sufficient for the present task.
