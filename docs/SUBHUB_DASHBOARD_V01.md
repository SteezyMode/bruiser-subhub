# SubHub Dashboard v0.1 — standalone, read-only release

**Scope:** A tiny optional **web UI**, desktop launchers and a status-only HTTP endpoint for the existing subtitle batch. This is not part of OptiPlex NOW and does not modify the private-alpha application. The source worker remains independent and continues if the UI is closed.

## Installation on the OptiPlex

From any authorized SSH client, download and run the **pinned** `tools/install_subhub_dashboard.sh` against the GitHub commit containing the dashboard. The installer downloads:
- `tools/subhub_dashboard_server.py`
- `tools/subhub_dashboard.html`
- `test_subhub_dashboard.py`

It validates syntax, performs offline status/HTTP tests, and only then installs the files into `~/.local/share/bruiser-subhub-dashboard/`. It registers the **independent** `bruiser-subhub-dashboard.service` as a user service, enables it on login/boot (user linger applies on server), and writes a desktop launcher at `~/.local/share/applications/bruiser-subhub-dashboard.desktop`.

A successful installation reports `SUBHUB_DASHBOARD_INSTALLED` after a live HTTP health check. It must **not** stop, restart, patch, or control `bruiser-subhub-batch.service`, the daily source worker, Sublarr, qBittorrent or any other OptiPlex NOW service.

Open locally on the OptiPlex: `http://127.0.0.1:17876/`.

To view from another computer, start an **authenticated Tailscale SSH tunnel** rather than binding the unauthenticated local HTTP server to the network:

```bash
ssh -N -L 127.0.0.1:17876:127.0.0.1:17876 optiplex@100.121.156.34
```

Then open `http://127.0.0.1:17876/` in the client's browser. The tunnel is intentionally local to both machines; don't port-forward it to your router or expose HTTP publicly.

A one-click Linux remote shortcut can be installed from the separate `tools/install_subhub_dashboard_client.sh`, with the approved SSH endpoint passed as an argument. It runs `ssh -f -N -o BatchMode=yes -L 127.0.0.1:17876:127.0.0.1:17876 ...`, verifies the backend `/healthz`, then opens the browser. **Requires existing SSH key authorization**; it doesn't create an account or store passwords.

## Display correctness update (Nov 6: publication-title regression)

Owner reported the new browser dashboard and terminal viewer were both stuck displaying **Bowfinger (1999)** while the publisher really advanced **8/29 → 14/29** within a few minutes. This is not stalled processing: `bruiser_batch.py` does not update `last_item` for `MEDIA:` publishing events; that field still reflects the last `STAGING:` entry. The dashboard now uses the current phase's bounded log **`MEDIA:` and `RESULT:`** events to display *Verifying subtitle N/total* until a genuine human-readable `RESULT` title is available, then labels it **Last evaluated**, never pretending an old staging title is actively processing. `RESULT` entries also appear in Recent Activity. Added regression coverage for this behavior and phase reset. The older curses terminal monitor remains unmodified for now, and may still show stale `Title:` in publish stages.

The installer now explicitly **restarts only `bruiser-subhub-dashboard.service`** after copying updated UI files. Prior installer used `enable --now`, which would not reload an already-running dashboard process. Re-running the pinned installer now picks up the change without changing the independent `bruiser-subhub-batch.service` or daily sourcing worker. The installer runs 11 offline tests; do not claim host verification until owner supplies successful output.

## v0.1 verified design boundaries

- GET `/`: responsive local HTML/CSS/JS, auto-refreshes every three seconds.
- GET `/api/status`: documented JSON `schema: subhub-dashboard-v1`, reads **only** `~/bruiser-pilot/batch-control/current.json` and safely bounded recent lines of the referenced private log; checks actual batch/daily systemd service state. Displays observed searches, plausible candidates, staged, held and new published separately.
- GET `/healthz`: readonly service health check.
- POST commands: **405**. There are **no working Start, Pause, Resume or Prioritize actions yet**; the browser labels them a future milestone rather than displaying false functional buttons.
- Bound to **127.0.0.1 only**; CSP and other restrictive headers; no JS libraries/CDNs, no listening on Tailnet/public addresses, no provider tokens or filesystem paths in API response, no media file writes.
- Data collection requires no additional provider search or Jellyfin scan.
- Since the dashboard is a **different systemd unit**, shutdown of the dashboard leaves the batch alone; shutdown/reboot of the host still interrupts the current **transient source batch**. Issue #66 tracks true durable automatic recovery.

## Planned v0.2 controller controls and GPU bridge

Dashboard v0.1's status payload already includes `translation: {"state":"not_connected"}` to prevent confusing the source-only batch with GPU translation. This is an intentionally explicit **placeholder**, not an operational translation integration.

Before accepting POST requests, implement separate authenticated owner control API, durable queued/pausing/paused/running tasks, interruption-safe systemd worker recovery, batch lock coordination and idempotent prioritization of Jellyfin item IDs. Read-only and control rights must be distinct; same-origin requests alone are insufficient for writable operations.

For the AI worker, agree on a **versioned, immutable per-job state interface** separate from provider search counters:

- `job_id`, `jellyfin_id`, target language and original audio language
- Source type/quality evidence (embedded EN, sidecar EN, OCR, acquisition, existing JA)
- States: `pending`, `awaiting_english`, `ready_to_translate`, `translating`, `validating`, `published`, `held`, `paused`
- Checkpoint: subtitle cue range, model name/quantization, timestamps, last safe completed block, output hashes and error/retry code
- Resource controls: GPU thermal limits, owner game/stream session preemption, resumable translation with no conflicting GPU worker
- Publication: no overwrite; validate full cue sequence, language and timing before atomic create-only sidecar

The eventual dashboard API can then return a real translation worker snapshot, or distinct `translation: {"state":"not_connected"}` until the worker is ready. Keep **one** durable coverage queue for search/salvage/English recovery/AI, not parallel competing automations.

**Immediate engineering handoff:** deliver dashboard v0.1 on OptiPlex, verify counts match `~/.local/bin/bruiser-live` in the same active batch, then implement v0.2 graceful controller and translation queue adapter. Never hot-patch the active 12-cycle source batch. Auto new-media detection is tracked separately in issue #65.
