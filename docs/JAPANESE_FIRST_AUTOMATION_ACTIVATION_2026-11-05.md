# Bruiser Japanese-first activation — November 5, 2026

## Objective

**Provide usable Japanese subtitles for English-language media without translating every title.** This is the first working automatic native-source track: it uses the already installed Sublarr 1.18.0, not a seventh account or a replacement Bazarr server. Earlier repeated E4B context/prompt research is stopped: see [STOP decision](TRANSLATION_RD_STOP_DECISION_2026-11-05.md).

This is an **operational activation** of source search/sync and a **one-film spoiler-free rescue**, NOT a claim that every downloadable Japanese subtitle was translated well. Automatic semantic fidelity guarantees do not exist. A track can be full-length, correctly synchronized, and still be a bad machine translation. Do not claim that \`machine_translated=false\` means human. A human Japanese viewer/stronger model can later triage ambiguous cases; do not block straightforward natural paraphrases like "take point" → "take the lead" if situational intent is preserved.

## Committed tools

- [\`tools/bruiser_ja_sublarr_rollout.py\`](../tools/bruiser_ja_sublarr_rollout.py) — activates built-in Sublarr searching/scanning/synchronization for all six existing library mounts, without installing another app. The four main movie/TV folders are enabled only when exact ID/path/readability match pre-verified host inventory; their existing Japanese sidecars are protected. Scan jobs are triggered via the documented standalone endpoint and proceed in the server, not in the command.
- [\`tools/bruiser_ja_movie_rescue.py\`](../tools/bruiser_ja_movie_rescue.py) — spoiler-free direct search and autonomous Japanese subtitle screening/correction for *You Were Never Really Here*. **If a Japanese sidecar is already saved locally**, the tool instead tries ffsubsync on that exact track and creates a separate `*.BruiserSynced.ja.srt` or `*.BruiserSynced.ja.ass` only when a meaningful (>=400 ms), safe offset is found; it never overwrites the original. If Plex only streams a remote subtitle and nothing is saved on disk, it cannot align Plex's inaccessible bytes directly and will instead search native OpenSubtitles for a local candidate. It discovers only a matching real media filename under existing movie roots, refuses ambiguous video matches, checks preexisting Japanese sidecars/embedded Japanese, uses the already-working native OpenSubtitles credentials, downloads at most three Japanese full-dialogue results and attempts \`ffsubsync\` against the actual video. It screens for Japanese text, plausible cue coverage, timestamp errors, repeated garbage and gross reading-speed problems. A qualifying corrected candidate is published **create-only**, with a private metadata audit. No model is called and no movie dialogue or plot is printed. If nothing qualifies, it holds rather than fabricating an original or replacing existing files.

Both scripts are Python and can run from stdin inside the existing \`sublarr-pilot\` container with \`PYTHONPATH=/app\`. They have offline regression tests in CI for exact API contracts, settings safety, provider identity and create-only publication.

## Production safety configuration

The activation script programs Sublarr's **actual v1.18.0 HTTP endpoints**:
- \`PUT /api/v1/config\` with \`wanted_scan_interval_hours=24\`, \`standalone_scan_interval_hours=24\`, \`wanted_search_interval_hours=24\`, **up to 40 Wanted items/search cycle** (not a promise to search 13,199 items immediately), provider budgets ON, and one concurrent provider search.
- \`wanted_auto_translate=false\`, \`translation_enabled=false\`, \`webhook_auto_translate=false\`, \`jellyfin_play_translate_enabled=false\`, \`subtitle_automation_enabled=false\`, \`upgrade_enabled=false\`, \`upgrade_scan_interval_hours=0\`. No hidden model fallback or silent upgrades.
- \`auto_sync_after_download=true\`, engine \`ffsubsync\`, shift sanity cutoff 30 seconds; this can improve simple several-second drift, but does **not** prove that alignment is correct for a different cut or detect semantic MT errors.
- \`wanted_skip_srt_on_no_ass=false\` (important: OpenSubtitles reported an UNKNOWN result as ASS during the previous dry-run but actually delivered an SRT), \`subtitle_health_enabled=true\`, quality auto-fixes OFF, no automatic deletes or overwrites.
- \`score_threshold_per_language\` is set to JA 80 as a conservative preference, **but candidate score is a metadata matching score, not a measured linguistic-quality score**. Do not claim this config alone rejects stale fluent-but-inaccurate MT. The existing source search pipeline may fetch unverified uploads. Existing JA upgrades are disabled; downloaded new originals are provisional until viewed.
- Four main movie/TV roots already mounted/readable are enabled via \`PUT /api/v1/standalone/folders/{3..6}\` only when their exact identities still match. Finally \`POST /api/v1/standalone/scan\` starts a background catalog pass. There is **no mass translation run**.

## Copy-and-run command on Mac mini

The commit below should be pinned to the HEAD SHA including both scripts and their passing regression tests when this page is updated. The example uses GitHub main for maintainability; for a production deployment replace \`main\` with a tested SHA.

\`\`\`bash
ssh optiplex@100.121.156.34 'bash -s' <<'REMOTE'
set -euo pipefail
DEST="$HOME/bruiser-pilot/subhub-control"
mkdir -p "$DEST"
BASE='https://raw.githubusercontent.com/SteezyMode/bruiser-subhub/main/tools'
curl -fsSL --retry 3 "$BASE/bruiser_ja_sublarr_rollout.py" -o "$DEST/bruiser_ja_sublarr_rollout.py"
curl -fsSL --retry 3 "$BASE/bruiser_ja_movie_rescue.py" -o "$DEST/bruiser_ja_movie_rescue.py"

echo '=== ACTIVATE JAPANESE-SOURCE AUTOMATION (no AI translation) ==='
docker exec -i -e PYTHONPATH=/app sublarr-pilot python3 - --apply \
  < "$DEST/bruiser_ja_sublarr_rollout.py"

echo '=== RESCUE REQUESTED MOVIE (status only, no spoilers) ==='
docker exec -i -e PYTHONPATH=/app sublarr-pilot python3 - \
  --title 'You Were Never Really Here' --apply \
  < "$DEST/bruiser_ja_movie_rescue.py"
REMOTE
\`\`\`

The second command is allowed to publish one original Japanese sidecar only after source/coverage/sync checks. It does not identify bad fluent translation with certainty, and it will not overwrite manually curated files. A "source miss" or "held" verdict means the explicit current film is NOT solved yet; don't call it done or bury the failure under a "100% automation" claim. If OpenSubtitles returns no viable Japanese file, move this exact film to the slower local translation fallback shortlist, without reverting to endless E4B prompt tuning.

## Linguistic quality / spoiler policy

Accept natural Japanese paraphrasing, modest condensation and alternate idioms preserving speaker, action, tone and meaning. "Take point" vs "take the lead" is not a defect absent contextual change. Reject only meaningful reversals, nonsensical idioms, wrong subjects, invented events, and material loss of meaning. Technical quality screens are **not** able to guarantee this judgment on all films.

**Movie-specific review must never reveal spoilers for *You Were Never Really Here*.** Status reports display only title, matched release, provider, cue counts, shift, and clear pass/held reason. No story explanation, finale, twists, or scene summaries. Only minimal dialogue excerpts if the owner requests examples.

## Larger translation-focused fallback

After measuring source coverage, reconsider **PLaMo 3 Translate 8B** under a single native-format, real-scene Japanese viewer test. This is a new 2026-11-05 translation-focused family; 8B Q4 ~5.3 GB is tight on the RTX 3050 6GB, so partial CPU offload may be required. Bigger is not automatically better, and the previous Google TranslateGemma 12B was already in Benchmark 006. If PLaMo fails practical Japanese comprehension, stop—do not add more micro prompt settings or unbounded retries.

No bigger model is installed or run by the activation above. The slower fallback remains separate; no fresh movies get machine-translated automatically while a viable original Japanese provider source exists.
