# Attachment (2022): fresh E4B subtitle retranslation + tracker

**Current model (never silently substitute):** 17slever17 Translate Gemma 4 Sub E4B, GGUF Q4_K_XL, exact installed Ollama ID `9ccfc3b07081`. Reference: [authoritative production model decision](PRODUCTION_TRANSLATION_MODEL.md).

## One-command run

[tools/start_attachment_e4b.sh](../tools/start_attachment_e4b.sh) installs only the standalone Attachment review runner and read-only tracker. It launches a detached E4B worker and automatically watches its progress. Ctrl+C exits the tracker only. It never loads the generic Gemma model or uses the original Japanese subtitles as translation context.

The runner reads exactly the 1,276 original English cues from the previously published, source-hashed Attachment job, revalidates English-primary audio and media provenance, and uses the *existing installed* E4B native single-cue prompt with the pinned 1344 context and 256 output-token limit.

## Independent checkpoints

State: `~/bruiser-pilot/attachment-e4b-rerun/jobs.sqlite3`

This is deliberately separate from the original SubHub job. It has a source-hashed, model/prompt-pinned checkpoint profile. The live tracker uses its own `--root` and exact job ID so it can never mistake the generic-model Attachment job for this run.

## Separate outputs (never overwrite old subtitles)

- Additional **review track** beside the film: `<video stem>.Bruiser E4B Review Japanese.ja.srt`.
- Private source + full Japanese + provenance archive: `~/bruiser-pilot/attachment-e4b-rerun/review/Attachment-2022-E4B-English-Japanese-review.tar.gz`.
- Private Japanese-only SRT: `~/bruiser-pilot/attachment-e4b-rerun/review/Attachment-2022-E4B.ja.srt`.

All are create-only and resume-safe; an existing different file causes a hold, not overwrite. The original generic-model `.Bruiser Japanese.ja.srt` and all editorial subtitles remain unchanged. The new Jellyfin track is clearly labeled **Review**, not quality approved. Complete translation does not prove semantic fidelity.

## Reattach without restarting

```bash
ssh -t optiplex@100.121.156.34 'python3 ~/bruiser-pilot/subhub-control/retranslate_attachment_e4b.py watch'
```

Job status: `python3 ~/bruiser-pilot/subhub-control/retranslate_attachment_e4b.py status`

Detached worker log: `~/bruiser-pilot/attachment-e4b-rerun/worker.log`.

The proper next step after publication is to review this newly translated Japanese against the original English and the earlier 5.5/10-rated generic track, before expanding library-wide production.