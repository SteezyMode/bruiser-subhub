# American Dad S08 — use native Jellyfin to acquire English subtitles

**Confirmed blocker on the host, 2026-11-02:** native jellyfin.service and caddy.service run; Jellyfin listens on port 8096; all 18 American Dad S08 files have English audio but lack embedded EN text and external EN SRT. The old Sublarr pilot is stopped. Do not restart Sublarr or modify Gemma to fix missing English source material.

## One command from MacBook

    cd ~/Downloads/bruiser-subhub-repo
    git pull --ff-only
    bash tools/fetch_american_dad_english.sh optiplex@100.121.156.34 8

Append 9 only if a second season is desired.

The launcher runs all offline unit tests, stages only the previously safe American Dad season runner, the existing daily intake/worker helpers, and a small Jellyfin source acquisition script. The existing SubHub/Jellyfin install is not modified, and no service is restarted.

One-time sign-in **in the MacBook SSH terminal** using your EXISTING Jellyfin ADMIN username/password may be necessary. The password is hidden in terminal and is **never stored**, logged or sent to ChatGPT. The resulting access token is stored privately with 0600 permissions on OptiPlex in ~/.config/bruiser/jellyfin-english-source-auth.json for later runs. It can be revoked in Jellyfin. The Jellyfin login is sent only to the native loopback server (127.0.0.1:8096), not to the public Internet.

The helper uses Jellyfin's existing provider interface, including Subbuzz when already enabled, to search EN subtitles **per real episode**. No full-library scheduled task or extra downloader. It maps actual video paths to Jellyfin item IDs, checks the supplied season numbering against Jellyfin's own metadata, refuses wrong-episode or ambiguous provider releases, skips any existing Japanese track, and accepts only matching English SRTs. It confirms the downloaded EN SRT exists beside the video and parses it with existing SubHub intake rules. A generic Jellyfin success message is not treated as proof of a usable file.

Only after at least one real EN SRT has been found does the script start the established American Dad season campaign, which sequentially translates with the same Gemma E4B, unchanged prompts/locks/checkpoints/publisher. Other media queue titles remain excluded.

**Boundaries:** The tests are synthetic; the first host run determines whether installed Jellyfin subtitle plugins find appropriate English releases and have permission to write an SRT beside the media. If not, the tool gives one per-episode result and makes no destructive changes. Speech-to-text is the fallback for unavailable sources, not another Japanese prompt experiment.

After SEASON_LAUNCHED check:

    ssh optiplex@100.121.156.34 \
      'tail -60 ~/bruiser-pilot/subhub1-state/american-dad-seasons.log'
