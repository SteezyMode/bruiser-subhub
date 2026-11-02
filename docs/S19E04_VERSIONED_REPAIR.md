# Readability repair for the already-published American Dad S19E04 pilot

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
