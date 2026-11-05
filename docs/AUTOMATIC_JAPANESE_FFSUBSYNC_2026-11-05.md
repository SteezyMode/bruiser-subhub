# Japanese-first ffsubsync integration — November 5, 2026

## Goal and verified boundaries

For every new Japanese subtitle considered for SubHub publication: inspect timing against its actual video; keep the original subtitle when already aligned; apply correction only after a good mechanical result; hold any uncertain source without modifying a movie or existing Japanese tracks.

The successful real film was You Were Never Really Here (2017): 365 cues, 283 containing Japanese text, 80 punctuation/symbol-only, 2 Latin-only. The proven ffsubsync correction ranged from -19.43 to -24.25 seconds. Real Jellyfin playback timing was confirmed by the owner.

The NEW queue-level integration is implemented and regression-tested in GitHub, but has NOT YET BEEN DEPLOYED or live-verified on the OptiPlex. Do not confuse this with already-active Sublarr daily Wanted scans.

## Reuse rather than rebuild

- Existing ja_first_search_pilot.py and ja_first_stage_saved_batch.py: bounded source discovery and private original-Japanese staging.
- Existing ja_first_publish_queue.py now invokes ja_first_ffsubsync.py for staged Japanese SRTs. It runs ffsubsync inside the currently installed Sublarr container against the actual video through a confirmed Docker host bind mapping. No container media-write permission needed.
- The existing ja_first_publish_staged.py host publisher remains responsible for atomic create-only publication; existing Japanese embedded and sidecar tracks are vetoes.
- The source-only cycle no longer requires embedded English captions, because ffsubsync can compare subtitle speech timing against the video audio.
- Previous trusted embedded-English timing gate remains a conservative fallback if audio matching cannot conclude.

## Safety and efficiency

- Every prospective new subtitle gets an alignment check; no correction when per-cue shifts stay below 400 ms.
- If correction is required, original wording/cue count must be byte-equivalent after SRT parsing. Major structural mismatches, shifts over 30 seconds, variation above 8 seconds, out-of-video timestamps, language/health or coverage holds are refused.
- Record new corrected bytes, original SHA and output SHA in private staging, and check this provenance on future runs.
- Never overwrite the original Japanese provider file or the video. Do not silently upgrade existing human/editorial sidecars.
- No AI translation, prompt work, GPU inference or automatic nightly task is started by installing the code.
- Mechanical QA does not prove translation quality or that provider uploads were human-authored.

## One live pilot

Install the current controller using tools/install_ja_first_controller.sh (pinned to the current integrated tool versions). Installation checks Python syntax and controller dependencies, but does not start media work.

Read-only host status:
  python3 ~/bruiser-pilot/subhub-control/ja_first_cycle.py status

One explicitly authorized, bounded, Japanese-sources-only host pilot:
  python3 ~/bruiser-pilot/subhub-control/ja_first_cycle.py cycle --sources-only --apply --search-budget 4 --stage-budget 1 --publish-limit 1

This does at most 4 provider searches, 1 OpenSubtitles download, 1 new Japanese sidecar. It cannot start or queue a Gemma job. Check the FFSubsync decision or hold, then confirm timing by playback of a NEW title, preferably followed by a TV episode.

## IMPORTANT: next integration boundary

Sublarr 1.18's already-active six-root scheduled Wanted search and this older host-side JA-first controller are NOT YET WIRED AS ONE EVENT PIPELINE. Do not install a duplicate daily timer or claim completely unattended new-title delivery until a live pilot proves the saved inventory is current, and a single authoritative event/job source is chosen. Protect source-download quotas and avoid repeated per-film rescue runs.

Once a newly acquired movie and TV episode pass practical playback, connect the source event stream to this publisher, with bounded concurrency, idempotency, per-title hold codes, and one non-overlapping daily schedule. Test first; automate second.
