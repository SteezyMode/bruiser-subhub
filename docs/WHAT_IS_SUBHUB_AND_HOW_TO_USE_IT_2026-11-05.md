# What SubHub actually is — November 5, 2026

## Identity and product boundary

**Bruiser SubHub is a standalone server-side utility, not a Jellyfin plugin, a desktop application, or a flagship Bruiser/OptiPlex NOW feature.** It is currently a collection of tested Python controllers, inventory/search/QA/publishing tools, and a host-side \`systemd --user\` service. It uses **Sublarr** as a separate installed subtitle search/download service, and **ffsubsync** to synchronize third-party Japanese SRTs to the media on the user's home server.

Jellyfin is the media player and sees ordinary media-adjacent \`.ja.srt\` files. Plex can likewise consume properly named external SRTs on shared media paths. Neither player needs a bespoke SubHub plugin for that. **No Bruiser app integration is required or planned for the primary workflow.** The user specifically wants this functionality independent and unobtrusive.

There is **no one-click installer or consumer-facing app yet**. The existing guarded installer is for the *already configured OptiPlex*; it relies on the owner's Jellyfin/Sublarr credentials, media mappings, systemd user session, and ffsubsync. A new user's installation is not yet turnkey. Do not describe it as a downloadable universal \`.deb\`.

## Current architecture

\`\`\`text
Media files / Jellyfin catalog
           │
   detect existing JA/EN tracks
           │
           ▼
Source-only SubHub scheduler (Python, OptiPlex user systemd)
           │
           ├─ Sublarr + configured OpenSubtitles credentials
           │  └─ search, rank and stage actual JA subtitle files
           │
           ├─ check media identity, source provenance and obvious garbage
           ├─ ffsubsync against the *actual video/audio*; validate result
           ├─ do not overwrite pre-existing Japanese/editors' files
           └─ create-only sidecar .ja.srt
                      │
                      ▼
                Jellyfin / Plex
\`\`\`

English-to-Japanese **DIY model translation is a separate, currently non-automatic fallback**. It is not part of the source-only daily service and must not be switched on implicitly by installing a new model.

## Where to find and control the existing deployment

- Public repository: https://github.com/SteezyMode/bruiser-subhub
- Host controller directory: \`~/bruiser-pilot/subhub-control/\`
- Daily host timer: \`bruiser-ja-source-autofill.timer\` (05:15 host local + 0–20 minutes jitter)
- Host source service: \`bruiser-ja-source-autofill.service\` (bounded, native provider limits enforced)
- Real source-job monitor: \`python3 -u ~/bruiser-pilot/subhub-control/ja_first_source_tracker.py --watch\` on OptiPlex
- Read-only journal: \`journalctl --user -u bruiser-ja-source-autofill.service -n 80 --no-pager\`
- Read-only schedule: \`systemctl --user list-timers --all bruiser-ja-source-autofill.timer --no-pager\`
- Check scheduling persistence with \`loginctl show-user "$USER" -p Linger\`; user-systemd timer may not run after all logins end if linger is not enabled.

Open the monitor from another machine over SSH (\`ssh -t HOST 'python3 -u ~/bruiser-pilot/subhub-control/ja_first_source_tracker.py --watch'\`). The monitor performs **no acquisition, translation or publication** and can be closed with Ctrl+C; the independently running systemd service continues. The user can minimize the terminal.

Installation/update: see [source-only controller](SOURCED_JAPANESE_AUTOFILL_2026-11-05.md), [installer](../tools/install_ja_first_controller.sh), [model decision](TRANSLATION_RD_STOP_DECISION_2026-11-05.md). A GitHub commit does *not* deploy code to the host. A live process should not be disrupted merely to update docs.

## Verified as of November 5 (owner-provided host monitor snapshots)

- First small source cycle: 8 searches, 2 staging downloads, 3 new sidecars, including Fargo (1996) and Twin Peaks S02E13.
- Later test: interrupted 600-search exploration after dozens of saved searches, then a one-time 100-search cycle. The owner's **interim** monitor snapshot recorded 100/100 new searches, 50/51 staged downloads, and **18 newly published Japanese sidecars at 28/56 publication titles examined**. This is **not** a final cycle summary, not 18 native-viewer-certified translations, and not proof all 50 stage files will pass publication.
- A real *You Were Never Really Here* corrected Japanese track was independently confirmed to play properly for the household; this demonstrates a practical win over a poorly timed sourced track.
- The 100-search test budget is a one-time setting. The routine ceiling is **600 searches, 200 staging attempts, 200 publications** per source-only cycle, bounded further by actual provider allowances and an eight-hour service timeout.

Older instructions stating the source-only service is "not deployed" or that tiny limits remain in place are historical and superseded by this verified dated snapshot.

## Design direction

Keep a self-sufficient server daemon with a read-only terminal UI. Consider a small local web status page *only* if real unattended use justifies it; not a replacement for the source service. A hypothetical standalone consumer installer is a later packaging milestone, not present functionality. Avoid making SubHub an OptiPlex NOW sales feature or mandatory service.

**Primary user-facing success metric:** pick a film in Jellyfin and find usable, correctly timed Japanese already available. Machine learning model output, filenames, commits and aggregate cue counts alone do not establish success.
