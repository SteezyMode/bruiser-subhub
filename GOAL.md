# The actual goal

This is **not a software product**. The user has nearly 6 TB of existing movies and television on an OptiPlex media server. The user is a native English speaker; his wife is a native Japanese speaker. They want to watch that media together, especially English-audio films, with **good, natural Japanese subtitles**.

Good existing Japanese subtitles are often difficult to find and have already been pursued. Dual-subtitle playback has **already been solved** and is not part of this project. The user's existing edited Japanese subtitles are valuable and must be preserved.

## Success condition

Choose an English-language movie already in the library, press Play in Jellyfin, and have accurate, readable Japanese subtitles available—without needing to manually request translations, fix one-cue hangs, or babysit the system. Repeat that across the library in unattended batches.

## Non-negotiable priorities

1. **Translation quality first.** Fidelity, natural Japanese, character/scene context, brevity, correct negations/numbers/names; no fabricated dialogue.
2. **Free and local.** Prefer running on the existing RTX 3050 6 GB, preserving its other server/desktop workloads. No paid API dependency.
3. **Library-scale automation.** Preserve the existing ~6 TB file organization; find English embedded/sidecar tracks, acquire where needed, translate and publish only missing Japanese; checkpoint and recover.
4. **Preserve human work.** Existing Japanese/editorial tracks are authoritative; never overwrite, delete or silently supersede them.
5. **Minimize software maintenance.** Use off-the-shelf free tools wherever they work better. **SubHub/Bruiser code is disposable**; stop developing it if existing tools solve the goal with less work.
6. **No irrelevant scope.** Dual-sub playback, OptiPlex NOW commercialization, dashboards, product naming, HY model experiments and feature parity are not blockers. HY remains optional and advisory only.

## Stop building and start proving

The immediate task is to get actual EN→JA samples from one already translated film, review quality, and run a controlled batch comparison after fixing malformed-SRT input. Only then should we scale automatic translation or change the model.

**This file outranks older growth/product language in roadmaps.** Development progress is measured by movies people can actually watch together, not commits, test counts or number of deployed services.
