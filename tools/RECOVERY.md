# Recover isolated cue failures (private household pilot)

This repairs the specific short-dialogue problems shown in the owner's November 1 diagnostic, **without retranslating completed movies**. Short initials and numeric countdowns are now permitted when exactly supported by the source. Untranslated English sentences and long abbreviations still fail validation.

The real correction manifest contains private movie dialogue and is **not part of GitHub**. The owner receives it separately. The program checks each job ID, cue number, original English, prior Japanese (or null), and source hash before updating anything.

From the Mac mini GitHub checkout:

    git pull --ff-only
    bash tools/repair_pilot.sh optiplex@YOUR_TAILSCALE_IP ~/Downloads/bruiser-subhub-private-repairs-20261101.json

This command runs offline tests, stages the source and recovery script, then:

1. Atomically upgrades only the verified installed batch-fixed service.py. Both worker locks must be free; an unexpected source hash aborts. Old code is backed up.
2. Validates the **entire** private repair manifest without changing cues. Any stale item aborts all corrections.
3. Backs up live SQLite using SQLite's backup API and updates only the exact reviewed cues; clears their failure counters and records events.
4. Publishes complete films only through the create-only publisher. Existing Japanese/editorial sidecars are protected and a collision results in publication hold.
5. Leaves incomplete films queued (e.g. Whistle). It does not start inference or restart any worker.

**Important:** structurally publishing four movies is not a Japanese-language quality guarantee. Separately examine the private Primate EN/JA review sample to determine whether previous singleton-produced subtitles need replacement. Do not put any media, subtitle text, or the private repair manifest in GitHub.
