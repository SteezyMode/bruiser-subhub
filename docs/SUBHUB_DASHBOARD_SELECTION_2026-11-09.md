# SubHub owner dashboard — one search and exact selected-episode jobs (2026-11-09)

## Scope and purpose

User requirement: household Jellyfin Japanese subtitle coverage, not a software product. The same dashboard must work for **any** library movie or show, with one title search. IASIP S01–S05 and American Dad are acceptance tests, **not hardcoded UI workflows**.

The dashboard is standalone, loopback-only (127.0.0.1:17876), and does not modify Bruiser NOW. Current code is committed to GitHub; host deployment/runtime behavior must be verified separately.

## Dashboard actions

1. **Find** — one search field filters the full existing series catalog into a small result list; the same Find action checks existing movie files. No multi-thousand-title dropdown.
2. **Select TV series** — season checkboxes can choose one or multiple seasons. Per-season compact summaries show existing JA, source-pending, source-exhausted and PLaMo-ready, needs-English and review-hold counts.
3. **Review remaining episodes** — collapsed by default. Opening shows only missing episodes, status/reason, and optional saved candidate evidence. Checkbox selection is optional; no checked items means all eligible missing episodes of the selected seasons. Completed episodes remain hidden unless explicitly requested.
4. **Recheck Japanese sources** — explicit confirmation with exact count and provider-quota warning. The owner-selected IDs alone enter the existing season-only source worker. A recheck bypasses the global 30-day saved-search cooldown **only for selected episodes**; it asks the existing Sublarr provider search (all configured providers), maps the actual video path into Sublarr using live Docker mounts when possible, records accepted and rejected candidate metadata, stages trustworthy OpenSubtitles candidates through the existing pipeline and uses the existing conservative audio/embedded-reference publication gates.
5. **Send remaining to PLaMo** — exact selected episodes only, and only when the existing queue has transitioned to `validate_english_for_ja_fallback` with indicated English text and a valid Jellyfin identity. Each episode passes the existing exact-video English preflight, PLaMo 8B per-cue checkpoints, thermal safeguards and create-only JA publication. Missing-English, candidate-review, held, duplicate, and already-covered episodes remain excluded and visible as such.

Source scope can never silently spill to another season, show, or movie. The dashboard disables library-wide manual and automatic Start controls; independent preexisting scheduled timers are **not** modified by installing the dashboard.

## Provider reality

Sublarr's configured providers can return results from SubDL or OpenSubtitles. The existing source-download/staging/publishing code still only stages **OpenSubtitles** matches automatically. SubDL and filtered-out candidates are shown for inspection; a search hit is not an approved subtitle. A provider search returning zero approved candidates is **not proof** that no Japanese subtitle exists anywhere, particularly when filenames, edition, season numbering, or filters differ.

When Japanese tracks are absent, the explicit owner can initiate PLaMo for source-exhausted eligible episodes. Review or English-source holds must be resolved before automatic translation; don't bypass these silently.

## Timing

Automatic timing publication uses the existing ffsubsync and trusted-reference checks. Misaligned, wrong-cut, missing-reference or otherwise uncertain matches are held instead of being labeled 'perfect'. Perfect synchronization cannot be guaranteed algorithmically. The dashboard exposes review holds; do not reduce the acceptance threshold globally.

## Deployment / acceptance

- Installer: `tools/install_subhub_dashboard.sh <pinned-commit>`, guarded preflight and offline tests; restarts only the dashboard user service.
- PLaMo bridge, if absent: `tools/install_subhub_plamo_handoff.sh <same-pinned-commit>` installs the existing one-title `subhub-ai` handoff, no GPU work started.
- Both installers leave the stopped 12-cycle library-wide batch stopped.
- Verify browser uses **one search field**, IASIP appears as a title result, selected S01–S05 coverage can be read, all other shows remain untouched, candidate rejections appear when saved, and the action counts match the selected episode IDs.
- Verify selected `/api/translation/coverage` and `/api/status` endpoints. No provider request or translation starts automatically on page open.
- Test a single selected episode first. Actual sourcing, timing verification and PLaMo publication are not confirmed until the host reports their real output.
