# Permanent English subtitle source shelf (Jellyfin to SubHub)

**Goal:** inventory every Movie and Episode in native Jellyfin, discover missing English subtitle sources, and download only verified video-file-hash-matched English SRTs through Jellyfin's existing subtitle providers. Keep a persistent retry queue so repeated checks advance rather than hitting the same titles.

**Not a translation engine.** Does not invoke Gemma, HY, Whisper, Sublarr, or Jellyfin's full-library subtitle scheduled task. Japanese translation remains selected-season-only. Previously requested American Dad S08 is first in English-source search priority.

## One command on the MacBook

    cd ~/Downloads/bruiser-subhub-repo
    git pull --ff-only
    bash tools/stock_english_sources.sh optiplex@YOUR_HOST

This runs all offline tests, stages only isolated helpers under ~/bruiser-pilot/english-source-code on OptiPlex, and performs a full metadata inventory of Jellyfin Movies and Episodes. It may prompt one time for the EXISTING Jellyfin administrator username/password in the SSH terminal. The password is hidden and never stored or logged; only a private access token is kept (0600) at ~/.config/bruiser/jellyfin-english-source-auth.json.

The initial pass searches at most **18** missing-source videos through the existing Jellyfin providers, prioritizing S08. Only provider results where Jellyfin explicitly reports IsHashMatch=true for the **video file** and the result is a non-forced English SRT with no contradictory episode identity are automatically downloaded. Ambiguous/non-perfect results are never installed automatically. The new English sidecar must actually exist beside the video and pass the existing SubHub SRT validator before being counted as ready. No Japanese or English sidecars are overwritten.

The Mac command also attempts to enable a nightly *user-level systemd timer* for daily **03:30 local** maintenance with **5 provider searches/day**. The terminal explicitly prints EN_TIMER active or EN_TIMER not_active. A failed timer setup does not discard the first scan; you can rerun manually. A user-level timer may not fire after full logout when lingering is disabled; no privileged settings are changed.

## Monitor

    ssh optiplex@YOUR_HOST \
      'python3 ~/bruiser-pilot/english-source-code/library_english_sources.py status'

Aggregate metrics only:
- EN_INVENTORY — actual Jellyfin media catalog size, eligible local paths, missing/ready/metadata errors, and count reused from the earlier local inventory
- EN_FILL — one provider search outcome, without a movie filename
- EN_FILL_SUMMARY — number attempted and actual external English SRT downloads
- EN_STATUS — counts by state and distinct American Dad S08 coverage

A strictly metadata-only scan (no external provider calls):

    ssh -tt optiplex@YOUR_HOST \
      'python3 ~/bruiser-pilot/english-source-code/library_english_sources.py scan'

A further explicitly bounded source search:

    ssh -tt optiplex@YOUR_HOST \
      'python3 ~/bruiser-pilot/english-source-code/library_english_sources.py fill --budget 10'

## Rules and scope

- Scan Jellyfin Movie and Episode records. Only regular actual files in the **approved local media roots** are considered. Symlinks and absent/off-root files are skipped.
- Detect named external English text subtitles and embedded English text tracks from Jellyfin metadata, falling back to ffprobe if Jellyfin supplies no streams. Files with existing English text are not sent to provider searches. Embedded PGS bitmap is not wrongly claimed to be a text SRT.
- Prioritize American Dad S08, then all other TV episodes, then movies.
- Do not assume a matching title or matching episode number is sufficient for automatic acquisition. Require exact Jellyfin file-hash match, EN language, SRT format, non-forced, and no explicit season/episode contradiction. This is intentionally conservative and may miss usable releases.
- Provider misses sleep **7 days** before retry, transient errors **1 day**. HTTP 429 or 503 ends the current batch immediately. All requests are serialized and bounded to prevent flooding providers.
- Maintain a small private SQLite state in ~/bruiser-pilot/english-source-inventory. Unchanged videos and subtitle sidecar sets reuse cached classification. Any media/sidecar fingerprint change causes recheck. A lock prevents overlapping acquisition runs.
- A Jellyfin result saved only in internal metadata rather than an external SRT is reported as jellyfin_only, not yet a usable SubHub source.
- Jellyfin settings, passwords, provider accounts, system services, existing media/JA captions and model prompts remain unchanged. The systemd user timer is a separately named Bruiser unit; if installation encounters an existing different unit it refuses overwrite.

## Next step once S08 English source files exist

Use the already-built Season 8 Gemma translator:

    cd ~/Downloads/bruiser-subhub-repo
    bash tools/run_american_dad_seasons.sh optiplex@YOUR_HOST 8

English acquisition across the entire library NEVER translates all titles into Japanese. Japanese remains a deliberately selected queue, starting with S08.

## What is not verified yet

Offline tests pass or fail in CI before merge; the actual full Jellyfin library has **not yet been inventoried by this new module**. Live provider results and Jellyfin save-to-sidecar behavior can only be confirmed after running it on the OptiPlex. Exact hash matching may cover only a small proportion of old torrent releases. Missing sources then require deliberate provider matching or local speech-to-text fallback, never silently lowering the automatic confidence threshold.
