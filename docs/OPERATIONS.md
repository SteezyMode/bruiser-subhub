# Local operation, inspection, and rollout

> **Current operations are split.** For the live source-only subtitle acquisition service, use [What SubHub is](WHAT_IS_SUBHUB_AND_HOW_TO_USE_IT_2026-11-05.md) and [source-only autofill](SOURCED_JAPANESE_AUTOFILL_2026-11-05.md): \`python3 -u ~/bruiser-pilot/subhub-control/ja_first_source_tracker.py --watch\` is the read-only search/download/publish dashboard. The E4B worker and cue tracker documented below are a **separate legacy translation pipeline**; do not start them to manage source-only jobs. The [PLaMo experiments](PLAMO_3_TRANSLATE_EVALUATION_2026-11-05.md) are documentation only, not a live deployment.


**CURRENT TRANSLATOR (2026-11-04): pinned subtitle-tuned 17slever17 E4B, model ID 9ccfc3b07081.** Read [the production model decision](PRODUCTION_TRANSLATION_MODEL.md) before touching any legacy commands. Hy7 and generic Gemma are not current production choices.

The known OptiPlex deployment is **not yet a portable install**. Commands below are for the owner on the server. Never put the media paths, logs, or exported subtitle content into Git.

## Safe read-only checks

```bash
python3 ~/bruiser-pilot/subhub1/main.py --root ~/bruiser-pilot/subhub1-state status
pgrep -af 'bruiser-pilot/subhub1/main.py' || true
ollama ps
```

`status` opens the existing runtime database using the 1.0 Store class; use a read-only DB snapshot or the independent review tool if strict no-mutation access is required. A visible model or HTTP 200 only proves a process is present, not that a film has completed or was translated correctly.

## Read-only editorial QA

From a checkout that includes `review_sampler.py` (run on the server or against a safe copy of the SQLite state):

```bash
python3 review_sampler.py --root ~/bruiser-pilot/subhub1-state --job JOB_ID
```

This prints **only counts and mechanical flags**. Export an EN/JA/context sample explicitly:

```bash
python3 review_sampler.py --root ~/bruiser-pilot/subhub1-state \
  --job JOB_ID --count 60 --out ~/bruiser-pilot/subhub1-state/review/JOB_ID.editorial.json
```

For every cue use `--all`. This tool opens SQLite in read-only mode, makes no model calls, does not publish, and refuses to overwrite existing output. JSON includes user-owned/private subtitle text and must never be committed or uploaded publicly. `number_review`/`negation_review`/`reading_speed_review` are **editorial prompts only**, not verified errors.

## Deployment safety contract

1. Verify no active worker and record current process state; do not kill an active translation for a code update.
2. Record deployed source hashes and current commit; back up source, deployment config, and SQLite state consistently (include WAL/SHM only via a proper SQLite backup API or while fully stopped).
3. Run the offline tests against the candidate checkout. Complete one test translation/quality comparison before swapping the Gemma adapter.
4. Replace only necessary source files atomically. **Do not** use `launch.sh` to upgrade. Do not reset/import jobs during upgrades.
5. Verify `status`, sample review, and publishing protection, then document success and rollback instructions in `docs/CURRENT_STATE.md`.

## Runtime boundaries

- `main.py` runs the queue, checkpointing, model calls, and optional advisory HY pass.
- `service.py` owns DB, validation, prompt adapter, publisher and review CSV.
- `review_sampler.py` reads the DB separately in SQLite read-only mode, exports no information unless `--out` is explicitly supplied.
- Host has been observed running Gemma translation and desktop usage concurrently; always respect resource limits rather than assuming GPU availability.

## Read-only blocked-title diagnostics (GitHub code only)

The GitHub checkout contains a diagnostic that opens the existing SQLite database
in read-only mode, including the live WAL snapshot. It does not load models or
change jobs. Run on the OptiPlex against the **checkout's** script, never by
overwriting a running worker:

```bash
python3 diagnose_blocked.py --root ~/bruiser-pilot/subhub1-state
python3 diagnose_blocked.py --root ~/bruiser-pilot/subhub1-state --show-text
```

The default command prints exhausted cue IDs and stored error messages, plus
job hold reasons (especially The Descent). The optional text mode includes
private English/Japanese dialogue excerpts and should not be published to GitHub.
A hold is not proof an editorial track caused it until the job's last_error
is inspected. Existing human-authored subtitles must stay untouched.
