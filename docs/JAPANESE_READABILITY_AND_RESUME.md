# Japanese subtitle readability gate and power-loss recovery (S20)

## Problem observed during Season 19 playback

Owner watched American Dad S19E04 and reported repeated Japanese captions far too long to read. The earlier real paired audit counted 392 aligned cues, 10 future-cue overlap flags, 6 copied-future cases and 6 cues over 20 characters/second in S19E04. Cue #52 (about 00:02:43) incorporated later dialogue and reached approximately 61 Japanese characters/second. Cue/time matching alone was not viewing-quality certification.

## Implemented safeguards

- New tools/subtitle_publish_gate.py reuses subtitle_quality_010's reading speed and future-cue overlap checks. For American Dad daily jobs, publication is held when ANY cue is severely dense, potentially contains upcoming dialogue, exceeds two visible lines, exceeds 18 visible characters per line, or exceeds 32 characters in total. This may hold valid subtitles for review; it does NOT delete or truncate dialogue.
- The selected tools/daily_worker.py intercepts the native publication function only inside its own process and only for the requested daily job. Underlying service.py and main.py are not modified. Native source-fingerprint, media, English-primary-audio and protected-existing-JA checks still run.
- On failure, existing main.publish_ready records publish_hold without creating a Japanese SRT. All completed SQLite translation cue checkpoints remain. The season campaign stops immediately on this hold rather than processing the other 21 S20 episodes.
- On success, publication writes a complete hidden temp SRT, flushes/fsyncs it and uses an atomic create-only hardlink to the final Japanese filename. The DB marks the title published only after the new name is on disk. A hard shutdown mid-write does NOT leave a half-written named .ja.srt file: the final name appears fully written or not at all. An unrecognized incomplete hidden temp might remain and is harmless for playback.
- This does NOT repair or replace already-published S19E04 pilot subtitles. A separate versioned repaired track is needed for that episode. It prevents mass publication of more unreadable Japanese meanwhile.

## One MacBook command after CI and merge

    cd ~/Downloads/bruiser-subhub-repo
    git pull --ff-only
    bash tools/repair_american_dad_worker.sh optiplex@YOUR_HOST

This stages the corrected user maintenance worker, strict QA module, existing quality heuristics and season runner, safely upgrades the exact original user systemd service from Type=oneshot to Type=exec, and requests a new S20 run. Existing Jellyfin, Caddy, Ollama, SubHub 1.0 system Python, other timers, media, and Japanese tracks are unchanged.

A real S20 episode may be fully translated and then fail the gate. That is an intentional hold, NOT published or yet viewable. Check actual journal and season log for SEASON_RESULT, JA_READABILITY_GATE_PASS or PUBLISH HOLD.

## Shutdown and recovery

- MacBook shutdown after host service launch: does not stop remote OptiPlex processing.
- OptiPlex shutdown or power loss: stops the job; the established SubHub worker records complete translated cue batches transactionally to SQLite, so already-committed cues survive as long as disk/database integrity holds. The current in-flight model call/batch can be lost and recomputed after restart. This is not truly zero-work-loss.
- Existing separate user systemd timer has Persistent=true. When the user systemd manager becomes active again it can catch a missed run; otherwise the next nightly timer run resumes. Automatic launch at every cold boot is NOT guaranteed without the user's systemd manager or linger.
- Final SRT publication uses atomic hardlink after fsync; a power loss after link but before SQLite commit is recoverable by recognizing the exact full file on restart, without overwriting it.
- An explicit PAUSE file in the SubHub state stops bounded work checks, but it must be removed to resume. Never forcibly kill a worker in the middle of filesystem operations unless needed.

## Limits

These checks detect severe readability and repeated-future text; they do not ensure Japanese cultural/semantic quality or prove that the existing S19E04 subtitle was improved. First actual S20 viewing review still required.
