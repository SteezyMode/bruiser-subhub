# American Dad one-episode Japanese-first real playback (2026-11-05)

**Goal:** Watch one episode of *American Dad!* with the household, not run another model-size benchmark. The selected machine fallback is **PLaMo 3 Translate 8B Q4_K_M**, using Preferred Networks' official PFML3 format and the exact same fixed settings tested on the OptiPlex (28 GPU layers, 2 previous successful English→Japanese pairs, temperature 0, max_tokens 512, official stop markers). Existing sourced-Japanese service, Gemma translator, prior episode subtitles and timers are unchanged.

## Exact precedence

1. **Embedded Japanese or local Japanese sidecar:** finished; do nothing. Check each real episode/copy, do not translate merely because English is present.
2. **Downloadable Japanese:** use existing Sublarr/OpenSubtitles search and cache, verify series + season + episode identity, download **at most one** plausible candidate to private staging, synchronize against actual episode audio with existing ffsubsync and create-only Japanese publication gates. If a credible source is held due insufficient identity/timing, do not present it as verified.
3. **No usable Japanese:** prefer verified same-file embedded English text. If none, prefer a named, verified English sidecar. Otherwise search Jellyfin's installed provider for a **video-file hash-matched** English SRT. Do not treat an arbitrary episode-number match as reliable release timing.
4. **External English:** run existing ffsubsync audio correction. Reject dialogue mutation or excessive shifts; preserve the corrected English timecodes through the model and Jellyfin output.
5. **PLaMo 8B:** translate one real episode sequentially, checkpoint each cue in private SQLite; preserve timing, skip sound-only English SDH descriptions in the Japanese viewing track, never edit the English or movie files, and install one new `.ja.PLaMo8B.srt` external track atomically **only** after all spoken cues are translated. This is an unreviewed machine-generated subtitle track, not a certified native-speaker-quality localization.
6. **No Japanese and no verifiable English source:** stop and report that English speech-to-text sourcing is future work. Do not hallucinate captions.

## Execute from Mac mini

```bash
ssh optiplex@100.121.156.34 'bash -s' <<'REMOTE'
set -euo pipefail
PIN="6f3e7becd5384f27195e6c8f7497d5afe6671952"
SCRIPT="$(mktemp)"
trap 'rm -f "$SCRIPT"' EXIT
curl -fsSL --retry 3 \
  "https://raw.githubusercontent.com/SteezyMode/bruiser-subhub/$PIN/tools/run_plamo3_source_first_american_dad.sh" \
  -o "$SCRIPT"
bash -n "$SCRIPT"
bash "$SCRIPT"
REMOTE
```

The wrapper stages **only private source-first helpers** at `~/bruiser-pilot/plamo3-ab/source-first-code` and two isolated model-facing files at `~/bruiser-pilot/plamo3-ab`. It does not overwrite installed SubHub production components. It uses existing private Jellyfin credentials. Source manifests older than 72 hours are refreshed against local Jellyfin. Existing Japanese searches are reused inside their recorded cooldown. One episode is selected based on verified playable source availability, preferring Season 8 if comparable sources exist, and S19/S20 otherwise. Re-run the command to resume an interrupted cue-level job.

**What the terminal will say:**
- `DONE: Requested episode already has Japanese subtitles` — no model needed.
- `JA READY: downloaded Japanese was synchronized and published` — select the Japanese track in Jellyfin.
- `EN SOURCE READY` then `MODEL: PLaMo 8B Q4` — source acquisition failed to find usable Japanese; translating English.
- `READY TO WATCH IN JELLYFIN` — full episode track installed. If it is not visible immediately, refresh/rescan the episode.
- `JAPANESE-FIRST HOLD`, `EN SOURCE HELD`, or `NO USABLE EPISODE READY` — cannot safely finish; diagnose source evidence rather than switching to a random release.
- `NO SUBS` — no verified English source; audio speech recognition is not yet in this path.

**Do not claim a working Jellyfin track until the owner runs the host command and the terminal reports actual success.** No source-only daily service changes. Do not commit any private subtitle text or model output to the public GitHub repo.

## Limitations

The existing Japanese acquisition stage can hold candidates if the OpenSubtitles provider is unavailable, the identity is ambiguous, the download quota is exhausted, or audio alignment is unverified. The English provider has an intentionally strict exact-video-hash acceptance condition. These conservative gates can mean no result despite an internet listing; avoid silently taking an unreliable subtitle.

**Completion and correct timing do not certify translation quality.** The user and Natsuyo's normal playback impression is the meaningful quality gate; avoid imposing another multi-model tournament.
