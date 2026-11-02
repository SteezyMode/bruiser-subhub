# American Dad: automatic season selection and local English ASR fallback

## Why this exists

The full Jellyfin inventory scanned **12,398** media items: **3,073** already have detectable English text subtitles, **9,325** currently do not. The owner ran the strict hash-match search on every one of the 18 American Dad S08 episodes and obtained **0 matches**. The later dedicated title/episode-matching search also returned **SEASON_NOT_STARTED no_usable_english_sources**. No Japanese translation failure caused this: the original English source was absent.

The user is willing to watch a different season and specifically requests automation that strengthens the server, not more prompt/model experiments.

## One command on MacBook

    cd ~/Downloads/bruiser-subhub-repo
    git pull --ff-only
    bash tools/auto_american_dad.sh optiplex@YOUR_HOST

This:
1. Runs all offline safety/regression tests.
2. Stages seven small scripts in ~/bruiser-pilot/american-dad-auto-code on the host. Neither the installed Jellyfin native service nor SubHub 1.0 is replaced or restarted.
3. Finds actual American Dad SxxExx/xxXyy media under the two approved host media roots. Verifies real English-audio and subtitle tracks with the **existing intake parser**; checks already-published Japanese across alternate copies and existing SubHub jobs. Chooses a season with at least 3 viable new/resumable episodes and 6 watchable episodes, ranked by proportion of watchable episodes and number of available episodes. Existing selection is sticky while episodes remain to be done. S08 is not forced when another season is more watchable.
4. Prepares an isolated Python venv and installs only pinned faster-whisper 1.2.1 if needed. It runs **CPU only** on small.en in int8 mode (max three CPU threads) and does not use the RTX 3050 at all. The model weights are downloaded to a private owner cache on the host; video audio is transcribed locally, not uploaded to a cloud speech service. This is the only new third-party dependency, separate from system Python.
5. Enables a separate **systemd user timer** at 04:30 local with random delay, 1 local ASR episode per nightly run, CPUQuota=250%, CPUWeight=10, Nice=15, MemoryMax=5G, idle IO scheduling. This preserves the existing Jellyfin English-provider timer and all machine services. If user systemd isn't available, the initial maintenance pass still launches as a detached process; the console clearly reports whether the repeating timer was enabled.
6. Starts one maintenance pass immediately. It computes the selected season, acquires **at most one** source for an episode lacking EN (only after verifying English primary audio), writes create-only VIDEO.Bruiser-ASR.en.srt once a full locally generated transcript passes SubHub SRT validation, and launches **only that season** through the existing Gemma E4B worker with unchanged translation prompts, locks, per-cue checkpoints, thermal guards and create-only JA publisher.
7. A nightly subsequent pass skips all existing JA and EN sources, uses a 3-day retry cooldown per failed ASR file, and handles another source episode. If a Gemma campaign is active it defers instead of overlapping with it. A PAUSE marker in the existing SubHub state stops maintenance.

**ASR source is a draft.** Model transcription can miss words, jokes, names, and speaker turns and should not be claimed as Hulu-quality captions. The Japanese model does not improve merely because the source is automatic. The first completed actual episode should be watched before treating the entire pipeline as high-quality. No speculative transcript is published if it is empty, has fewer than 50 cues, corrupt timestamps, or violates the video duration bounds (10 to 45 minutes).

## Safe boundaries

- It does not translate the full 12,398-title Jellyfin library; it only processes the **one selected American Dad season**.
- It does not modify existing English or Japanese subtitle files. The ASR output uses an explicit Bruiser-ASR.en.srt suffix and is installed by an atomic create-only hardlink after validation.
- It refuses unclear audio language, embedded Japanese, existing JA, missing video, symlinks, unauthorized file roots, or videos outside TV duration bounds.
- Runs one ASR job per nightly pass, with the heavy model on CPU at low priority. Separate from the existing nightly low-rate subtitle-provider searches.
- It does not automatically declare a full season done. ASR-generated English requires review, and provider-matched English is preferred whenever found.
- If the isolated venv cannot be set up, existing-subtitle season selection still works; the installer prints a specific ASR setup blocker. No sudo/system package mutation is attempted.

## Progress after the first command

Selection (read-only):
    
    ssh optiplex@YOUR_HOST \
      'python3 ~/bruiser-pilot/american-dad-auto-code/american_dad_autopilot.py'

Nightly maintenance and initial run:

    ssh optiplex@YOUR_HOST \
      'journalctl --user -u bruiser-american-dad-maintenance.service -n 60 --no-pager'

Progress in translation:

    ssh optiplex@YOUR_HOST \
      'tail -60 ~/bruiser-pilot/subhub1-state/american-dad-seasons.log'

If user systemd was unavailable, initial fallback maintenance log:

    ssh optiplex@YOUR_HOST \
      'tail -60 ~/bruiser-pilot/subhub1-state/american-dad-maintenance.log'

## Verification limitation

The new scripts passed offline synthetic tests in the repo before merge, but their actual operation, model installation, selected season, and first English ASR remain **unverified on the host until the user runs the command**. We cannot SSH directly. If the host has no usable VENV/pip/network access, the local ASR step is held, not silently declared complete. The existing full-library EN inventory/timer remains available regardless of this campaign.
