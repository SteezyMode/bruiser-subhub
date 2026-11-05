# Source-only Japanese autofill — November 5, 2026

> **LIVE STATUS ADDENDUM (later Nov 5):** This document's earlier "not yet deployed" language describes the state when its first version was written. The owner subsequently deployed the daily source-only timer, verified real downloads and publication, and used a one-time 100-search test. Interim observed totals: 100/100 searches, 50/51 staged candidates, **18 new published .ja.srt files at 28/56 publication titles examined**. Full cycle completion and quality remain unverified in the available snapshots. **Current service ceiling is 600 searches / 200 staging attempts / 200 publications**, not the original 8/2 pilot. See [current architecture](WHAT_IS_SUBHUB_AND_HOW_TO_USE_IT_2026-11-05.md) and [hybrid roadmap](HYBRID_JAPANESE_SOURCE_VS_DIY_POLICY_2026-11-05.md).


## Purpose

Source **existing Japanese subtitles first**, reject obvious junk, automatically verify/fix timing against the actual video, and deliver a create-only Japanese sidecar for Jellyfin (also usable by Plex when the same library paths are available). No DIY translation, new cloud credentials, media rewriting, subtitle replacement, or unrelated account creation.

**Previously confirmed live:** film *You Were Never Really Here* passed real playback; later The Simpsons S04E17, Die Hard 2, and What We Do in the Shadows S05E02 were mechanically synchronized and published by the host queue. Eight staged OpenSubtitles SRTs passed the deliberately permissive garbage check. Translation/naturalness of the other titles was not independently reviewed.

**New in this commit:** an optional single daily host source-only controller with authoritative Jellyfin catalog refresh, safe native Sublarr search-scheduler handoff, duplicate-run lock, bounded acquisition and publication, and completed-row retirement. New scheduling has passed offline CI, **not yet verified live on the OptiPlex**.

## Why one scheduled host worker?

Installed Sublarr v1.18 has six library roots and its own 24-hour periodic provider-search job. Sublarr's media binds are read-only, so the verified automatic sidecar publication path is on the OptiPlex host. Running both independent provider schedulers consumes provider quotas twice without bringing equal playback benefit.

Sublarr officially supports `wanted_search_interval_hours=0` to disable only the **periodic provider searches**. Library inventory scanning and interactive search remain available. The host-side pipeline uses the already configured OpenSubtitles credentials via Sublarr, while publishing through the same existing create-only host gate.

The handoff script changes **only two** existing Sublarr API settings: `wanted_search_interval_hours=0` and `wanted_search_on_startup=false`. It checks that auto-translation and upgrades are disabled, verifies the result, and enables one user-level systemd timer. If timer activation fails it attempts to restore the previous native-search settings and disables the new timer. No root privileges or Docker remounts.

## Deployment, one-off live verification

1. Install current pinned controller from `tools/install_ja_first_controller.sh` on OptiPlex. Installer **does not** enable any timer or perform provider requests.
2. Read-only preflight: `python3 ~/bruiser-pilot/subhub-control/ja_first_autofill.py status`.
3. Explicit activation: `python3 ~/bruiser-pilot/subhub-control/ja_first_autofill.py enable --apply` (switches scheduled provider searches from Sublarr to the host, while preserving Sublarr scans).
4. Live bounded source-only check: `python3 ~/bruiser-pilot/subhub-control/ja_first_autofill.py once --apply`. No extra API keys or AI.

The one-shot controller holds an exclusive host lock. It uses the saved Jellyfin token and source manifest to refresh a catalog older than 20 hours, then runs a production-scale source cycle: **up to 600 sequential provider searches, up to 200 new Japanese subtitle staging attempts, and up to 200 new sidecars**, with each step using durable state and the native provider's actual daily account limits. These numbers are software ceilings, not a claim of 200 available downloads on this account. OpenSubtitles quota/cooldown errors stop subsequent download attempts for the cycle. Existing 30-day search history prevents repeated searches of already-tested titles. The new queue retirement moves verified completed stages to status `published`, while retaining their original files and provenance; staged/acquisition logic recognizes both pending and published, so a completed file is not downloaded again.

## Scheduling

Daily user systemd timer at **05:15 host local time plus up to 20 minutes**. Search selection allocates roughly 75% of requests to movies, prioritizing horror/drama/suspense, and targets The X-Files and It's Always Sunny in Philadelphia before unrelated TV. `Persistent=false` avoids an immediate backlog-triggered run when initially activated. The service logs to the user journal and uses low CPU/I/O priority, an 8-hour upper bound for a large batch, and a no-new-privileges flag. The timer requires user systemd to be active; if the OptiPlex user session ends and linger is not enabled, scheduled execution may stop. The code does not silently change linger or create root services.

Check: `systemctl --user list-timers bruiser-ja-source-autofill.timer` and `journalctl --user -u bruiser-ja-source-autofill.service -n 80 --no-pager`.

## Guardrails and limitations

- New sidecar only when exact identity/provenance, lightweight quality screen and automatic ffsubsync QA pass. Both original film and original provider subtitle remain untouched. Existing Japanese tracks block replacements.
- Avoid conflating Japanese-script ratio with translation quality. Fluent poor translations can pass the coarse gate.
- Acquisition adapter currently supports **OpenSubtitles**. Sublarr itself also has providers such as Jimaku and SubDL, but integrating their download metadata and authenticity checking into this host staging pipeline is not done. Do not imply simply toggling them in Sublarr automatically extends this verified path. Another provider may require a new account; avoid imposing that burden without a clear yield.
- The daily budgets are deliberately conservative until actual provider quota/candidate yield is known, not a promise to complete 10,000+ titles quickly.
- **Plex** may see these sidecars if it indexes the same media files and is configured to recognize external subtitles. The system has not verified an independent Plex integration.
- New feature is **not live verified** until the owner executes activation and a cycle. If the native scheduler cannot be disabled and verified, the host source cycle refuses to make duplicate provider calls.

## Longer term

Monitor new published subtitle count and actual viewing quality before increasing budgets, prioritizing requested titles, or expanding providers. Keep the source-first path production; local Gemma translation remains an explicitly requested, separate fallback.
