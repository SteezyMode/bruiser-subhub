# Readability repair for the already-published American Dad S19E04 pilot

## November 3, 2026: real first-pass result — 113 held cues, bounded v2 recovery

The owner ran the real one-episode v1 repair overnight. The OptiPlex journal contains many `S19E04_REPAIRED` and `S19E04_HELD` cue messages, ending at 00:41 local in **113 unresolved cues/113 remaining readability flags**, so **no new repaired JA sidecar was published**. The previous CLI returned code 3, which systemd rendered `3/NOTIMPLEMENTED` and marked failed. This is the old script's intentional quality hold, not an unsupported operating-system feature.

The new bounded recovery v2 **reuses every already accepted private cue checkpoint**. Its second pass tries a lossless Japanese **line-break-only reflow** for cues where text is already short enough (never deletes/replaces dialogue). Remaining missing cues receive at most **two distinct** current-English-only Gemma requests with explicit duration-based display budgets, preserving negation/punchline/meaning. Already rejected v2 requests are recorded **immutably** by cue, prompt hash and frozen original-source manifest, so rerunning the command does not endlessly retry the same rejected response. A transient local-model failure is not mistakenly marked as a completed rejected inference. If still overlong, it remains held for targeted review—never silently truncated or published.

The same command also clears the previous failed transient **S19E04 repair user unit only**, permitting a new systemd job after the first held run. A quality hold now prints `S19E04_REPAIR_RESULT held published False` and exits normally (0); **only** a visible `S19E04_REPAIR_PUBLISHED` means the new optional track actually exists.

Run on MacBook after PR merge:

    cd ~/Downloads/bruiser-subhub-repo
    git pull --ff-only
    bash tools/run_s19e04_repair.sh optiplex@YOUR_HOST

Monitor live:

    ssh optiplex@YOUR_HOST 'journalctl --user -u bruiser-s19e04-repair.service -n 35 --no-pager; python3 ~/bruiser-pilot/s19e04-repair-code/repair_s19e04.py status'

The original pilot, accepted v1 checkpoint files, and unrelated S20 media remain intact. Neither this repair nor PR #57 ensures perfect comedic localization; one real playback test is still required after a new versioned SRT is published. If many cues remain held after v2, the next appropriate step is a targeted editorial review of those cues, not an infinite automatic model loop.

The owner observed repeated oversized Japanese subtitle blocks during actual viewing of S19E04, and the real 009 paired audit identified copied-ahead future speech and incorrect idioms. PR #57 prevents unreadable NEW S20 tracks from publishing, but does not change the existing Japanese S19E04 pilot.

This repair is a separate **single-episode, versioned, resumable** correction with NO replacement of the old Japanese subtitles.

## MacBook: one command

    cd ~/Downloads/bruiser-subhub-repo
    git pull --ff-only
    bash tools/run_s19e04_repair.sh optiplex@YOUR_HOST

The wrapper runs offline tests, copies isolated code to the OptiPlex, performs a read-only selection/source check, and uses a transient **user systemd service** to perform the actual local-model repair. The model runs on the OptiPlex even if MacBook SSH disconnects or the MacBook shuts down after the service starts. No new credentials, APIs, or installed providers are needed.

The repair selects **only the original video bearing the S19E04 Bruiser Pilot Japanese.ja.srt**. It must find exactly one copy or it refuses to guess. It parses and requires exact alignment of the 392 actual English and Japanese subtitle cues. It freezes the source SHA, old Japanese SHA, video size/mtime, pinned Gemma E4B identity and existing v010 quality-rule hash in a private manifest. Existing source, media, or old published subtitles changing is a hard stop.

Only cues with extreme reading density, excessive screen width/height, suspected copied-ahead future dialogue and the previously documented S19E04 idiom error at cue #54 are considered for correction. The existing one-cue-only v010 **repair** prompt is used, with NO future dialogue included. The first pass's other accepted cues are preserved verbatim. Each accepted repair is saved as a private immutable create-only checkpoint. If the local model returns an invalid, too-long or copied-future candidate, the cue is held rather than guessed or silently truncated.

The completed episode is re-audited. Only when **no quality holds remain** will a new create-only video-stem-matched subtitle sidecar appear:

    VIDEO.Bruiser Readability Repair v1 Japanese.ja.srt

The existing VIDEO.Bruiser Pilot Japanese.ja.srt is always retained intact. In Jellyfin choose the new versioned Japanese track when it appears (after a library refresh if necessary). New track's semantic and humor quality still requires real viewing; checking text length cannot guarantee it is funnier or more accurate.

## Safe interruption

- MacBook shutdown/disconnect: transient systemd-run service continues on the OptiPlex.
- OptiPlex shutdown or power failure: the local model stops. Previously accepted per-cue private repair JSON files remain on disk (atomic create-only writes). Running the **same command** after reboot reuses compatible saved corrections and continues from the missing cues; no whole-episode retranslation.
- Final repaired SRT is written/fsynced into a private hidden temporary file, then atomically linked into the library with create-only semantics. Interrupted writes are not exposed as final SRTs. A leftover hidden .tmp in the private area is not used as a subtitle.
- The repair does NOT have its own nightly timer. A hard host shutdown **requires rerunning the same command** after reboot. This keeps a one-time editorial correction from becoming another permanently scheduled background workload.
- Existing worker locks are respected. If the selected-season Gemma worker is active, the repair refuses concurrent model inference rather than disrupting either job.

## Monitoring without exposing dialogue

    ssh optiplex@YOUR_HOST 'journalctl --user -u bruiser-s19e04-repair.service -n 35 --no-pager'

The log reports S19E04_REPAIR_PLAN, S19E04_REPAIRED cue ID, S19E04_REPAIR_HOLD or S19E04_REPAIR_PUBLISHED; it does not print Japanese or English text.

Limitations: The repair modifies only mechanical/readability and flagged semantic cases, not a complete human editor pass on all 392 lines. A quality hold indicates incomplete work, not publication. If the source track does not exactly match the old pilot, the program safely refuses operation. All paths remain private on the OptiPlex.
