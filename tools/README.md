# Run from the Mac mini checkout

The objective is **watchable Japanese subtitles for existing household media** ([GOAL.md](../GOAL.md)). These tools do not run a new translation campaign or replace media.

From `~/Downloads/bruiser-subhub-repo`, run:

```bash
git pull --ff-only
bash tools/deploy_batch_fix.sh optiplex@YOUR_TAILSCALE_IP
bash tools/collect_review.sh optiplex@YOUR_TAILSCALE_IP
```

## Guarded engine update

`deploy_batch_fix.sh` runs offline unit tests, stages the corrected `service.py` on OptiPlex, and executes `deploy_batch_fix.py`. The latter must acquire **both** new and legacy worker locks; if a worker is active it aborts without swapping code. It refuses an unfamiliar source hash, backs up the existing service.py, runs the installed `bruiser_auto.parse_srt` on a real 12-cue batch (without Ollama) and only then atomically replaces the source file. It does **not** restart a worker, load a model, edit the SQLite cue database, rerun imports, delete editorial subtitles or touch movies. It upgrades only the legacy 1.0 version fingerprint; if user-modified code is present, investigate instead of overriding it.

This is a **code installation**, not a retranslation of already checkpointed Japanese. Previously published tracks stay as they were.

## Get the actual translation sample

`collect_review.sh` reads the live DB in read-only mode to choose the first published film (or pass a specific job ID as the second argument). It copies `review_sampler.py` outside the running source tree and collects 80 representative/problematic EN/JA cues, with a little context. No inference or publishing happens. The private packet is placed in the Mac mini's `~/Downloads` directory.

Upload that local JSON into the private chat for a **real Japanese quality audit**. Do not put it into GitHub; its contents include movie subtitle text.

## Next decision

Evaluate fidelity, naturalness, slang/nuance and Japanese readability on this sample. Compare a new properly batched model response on the *same* private sample after confirming the server is idle. The fixed adapter can then be assessed against existing singleton-heavy output and alternatives. HY remains optional.

## Whole-library metadata inventory (read-only)

Run on the Mac mini:

    bash tools/library_census.sh optiplex@YOUR_TAILSCALE_IP

This streams a Python script over SSH; it does not install it, edit state, queue translations, download subtitles, or use Ollama. It walks `/mnt/BigDisk/Video` and `/mnt/2TB/Plex Expansion`, reading only filenames, file sizes and ffprobe stream headers. Embedded-text English, image-only English, existing Japanese, non-English or unknown audio and missing-source categories are counted separately. The result is **provisional** if language tags or sidecar filenames are missing or inconsistent.

To explicitly save a private per-file candidate inventory on the OptiPlex, run `python3 tools/library_census.py --root ... --root ... --out /path/to/private.json` from a checkout on that server. The file holds personal media filenames and **must not** be committed to GitHub. Use the summary first. No jobs are automatically imported.

## Real Japanese quality comparison: idioms, tone and reading comfort

After the separate library census finishes and **no translation worker is active**, use:

    bash tools/compare_primate_style.sh optiplex@YOUR_TAILSCALE_IP PRIMATE_JOB_ID

The benchmark stages an isolated source copy under `~/bruiser-pilot/subhub-benchmark/`; it never replaces the live engine. It takes up to five nonoverlapping 8-cue windows near review-interest cue IDs `35,71,207,380,465`. The existing Japanese checkpoint is the baseline; the `natural_8` prompt is sent to the existing local Ollama model, using 8 consecutive cues for scene context. The program holds both normal translation worker locks to avoid simultaneous jobs. It will use the RTX 3050 for local model inference; schedule when convenient. This is **not GPU-free**, unlike the library census.

The private comparison JSON is copied to Mac mini `~/Downloads`. Upload it to the private chat for direct EN/JA review and qualitative judgment. It may contain copyrighted subtitle excerpts, so never commit it to the public repository. Erroring batches remain visible as missing candidates; no singleton retry loops or media publishing. Do not turn the new profile on globally until the A/B output is reviewed.

## Frozen two-model quality experiment (Benchmark 001)

See `benchmarks/EXPERIMENT_001.md` and `benchmarks/RUN_LEDGER.md` before proposing another prompt change.

From Mac mini:

    git pull --ff-only
    bash tools/run_model_benchmark.sh optiplex@YOUR_TAILSCALE_IP

The run first tests the source code, finds installed Ollama models, verifies the exact Primate source SHA and eight fixed 8-cue windows, then uses local GPU Ollama to generate the four model/prompt arms. It **will NOT download models**; if the subtitle-tuned model isn't installed or more than one matches, the preflight fails and reports available names. To choose manually, pass a second argument with the exact `ollama list` model ID. No changes to old checkpoints, published subtitles, videos, live worker or queue.

The private JSON lands in Mac mini Downloads. **Never put movie dialogue/model output in public GitHub.** Upload it here for assessment using the pre-registered meaning/tone/fluency/readability rubric, then record the aggregated scorecard and final decision in the GitHub run ledger. Historical `natural_8` 40-cue sample is NOT a valid fresh baseline because older checkpoints were generated under broken SRT batching.

## Model-native subtitle-tuned Gemma experiment (Benchmark 002)

After reading `benchmarks/EXPERIMENT_002.md`, run from Mac mini `bash tools/run_native_subtitle_benchmark.sh optiplex@YOUR_TAILSCALE_IP`. The script tests a **single installed pinned model** with its developer's single-segment prompt on the same 64 English cues used in Benchmark 001; no imports, GPU installations or modifications to subtitles/checkpoints. It holds the normal worker locks. A private JSON is copied to Mac mini Downloads for manual EN/JA review. Do not commit it.

## Controlled strict-model-card follow-up (Benchmark 003)

Read the preregistered `benchmarks/EXPERIMENT_003.md` first. Run from Mac mini:

    bash tools/run_model_card_003.sh optiplex@YOUR_TAILSCALE_IP

The two arms use the **same pinned installed subtitle-Gemma, identical model-card-style system and native one-cue format, the same 64 source cues and identical Ollama options**. Only difference: one arm omits previous-context pairs if the gap is greater than eight seconds. All model outputs stay in a private create-only JSON copied to Downloads; no changes to queue, checkpoint, Japanese SRT, videos or live engine. Never commit private dialogue to GitHub. After real native-Japanese review, record the outcome and make a production decision rather than endless prompt tuning.

## Benchmark 004 — Google TranslateGemma native prompt

Read `benchmarks/EXPERIMENT_004.md`. After checkout pull, run **once** on Mac mini:

    bash tools/run_translategemma_004.sh optiplex@YOUR_TAILSCALE_IP

This intentionally installs/downloads **official** `translategemma:4b` Q4_K_M (~3.3 GB) on the OptiPlex if absent, **only after** confirming the private source cue SHA and 64+16 selection. It verifies official model ID/family/quantization, then calls the model under Ollama's own prompt guide, not a Gemma4 batch prompt. Uses existing tuned subtitle model for fresh comparison on 16 held-out cues; everything runs in an isolated directory and holds the usual worker locks. No changes to production code, subtitles, media or SQLite checkpoints. Private EN/JA results copied to Downloads should be attached to the chat and **never committed to public GitHub**.

## Benchmark 005 — all viable November 2026 translation models

See `benchmarks/EXPERIMENT_005.md`. It freezes 64 previously unseen source-hashed Primate cues, runs the currently tuned E4B baseline and three Ollama Q4 alternatives, and runs the actual FINAL CAT 3.3B via isolated CUDA Transformers (NOT old beta GGUF). Run on Mac mini when server GPU is idle:

```bash
cd ~/Downloads/bruiser-subhub-repo
git pull --ff-only
bash tools/run_model_sweep_005.sh optiplex@100.121.156.34 all
```

Optional: `small` omits 12B CPU offload; `tuned`, `cat33`, `cat7`, `hy7`, `google12` individually isolate a problematic arm. This is **an explicit permission to download models** (total disk/downloads easily >25GB) and set up a separate pinned CUDA/PyTorch virtual environment in `~/bruiser-pilot/subhub-cat33-venv`. Does not upgrade live SubHub's Python, overwrite subtitles, modify source SQLite or launch job queue.

Each successful arm writes a private JSON in `~/Downloads/model-sweep-005-<timestamp>/`. After two or more compatible complete outputs, the wrapper automatically produces `BLIND_REVIEW.json` with shuffled A–E labels per cue and a separate `BLIND_IDENTITY_KEY.json`. Review actual dialogue without viewing the key first; score semantic 4, tone 2, fluency 2 and readability 2; log critical errors, then reveal. Keep both and every raw model JSON PRIVATE, never commit movie dialogue to GitHub. Known external limitations: Hy7 GGUF may require newer STQ support; CAT3.3 final bitsandbytes CUDA may be unavailable; Google12 Q4 requires CPU/RAM offload. Mark those arm runs blocked rather than silently substituting a different model.

## Benchmark 005: diagnosing blocked controls and preserving logs

Owner-run real status on 2026-11-02: Hy7, CAT7 and Google12 generated private JSON; **tuned was blocked in preflight**, **FINAL CAT3.3 was blocked/incomplete**. Before re-running models, use from MacBook checkout:

    bash tools/diagnose_model_sweep_005.sh optiplex@100.121.156.34

Read-only inspection prints actual tuned `ollama list` ID, `/api/show` model family/quantization, the model-sweep tuned preflight error, and the isolated CAT3.3 venv import/CUDA checks. Does NOT pull weights, send inference, change services or write subtitles/DB. Share full terminal diagnostic to investigate exact blockers. On later runs the runner now saves per-arm stderr/stdout into PRIVATE `*-preflight.log`, `*-model-run.log`, `cat33-run.log` while still streaming to terminal. Never commit private dialogue or logs to GitHub.

Partial public findings and structural contamination caveat in `benchmarks/RESULTS_005_PARTIAL.md`. The original CAT7 final model specifically requires its own chat template; current GGUF via Ollama leaked `assistant` into 16/64 cues despite only two format warnings. Do not trust the general publisher validator.

## Benchmark 005 recovery after owner read-only diagnostics (2026-11-02)

The tuned model is present and correct: `hf.co/...Q4_K_XL` is the tag; Ollama `quantization_level` is `Q4_K_M`. The false-negative model metadata check was fixed with the exact pinned ID and gemma4 family retained. CAT 3.3B **source/environment/CUDA preflight works**; its failure is later, exact traceback unobserved. After updating the MacBook checkout, run only the two missing arms with `bash tools/run_model_sweep_005.sh optiplex@100.121.156.34 missing`. This downloads NO new tuned model and does not rerun Hy7, CAT7 or Google12; CAT 3.3B may still download official HF weights through isolated venv. `cat33-run.log` saves actual stderr if it fails. Share the two new private model JSONs and/or redacted CAT log; then compare tuned vs HY7 on identical 64 cue IDs.

## Benchmark 005 — paired tuned/HY results, final CAT memory-only retry

Tuned subtitle-Gemma E4B now completed successfully (64/64, Q4_K_M reported quant despite Q4_K_XL tag). With HY7 on identical English/timecodes it is faster, less dense and preferred by the assistant's provisional cue-masked review in 26 versus 15 cues (23 ties), but both have real meaning errors. See `benchmarks/RESULTS_005_TUNED_HY_PAIRED.md`. **Only final CAT3.3 remains unfinished.** Its logs show `Under 3GB free VRAM` during preflight after tuned benchmark kept Ollama model resident; cannot assume exact GPU consumer without measuring.

The updated CAT runner prints current Ollama-loaded models (`ollama ps`) and NVIDIA free VRAM before Python model loading. It does NOT terminate any other Ollama model, worker or desktop service. With no active translation/AI/game workloads and sufficient VRAM, run from MacBook:

    bash tools/run_model_sweep_005.sh optiplex@100.121.156.34 cat33

Mode `missing` is now also cat33-only, so none of the four successful arms are rerun. CAT3.3 Python packages remain isolated in its original venv. If its preflight fails, share private `cat33-run.log` and the current `ollama ps`; do not disable ongoing services just to get the benchmark through. Preserve all private model JSONs. No production source, SQLite, media, human Japanese or queued jobs changed.

## CAT3.3 tokenizer-dependency recovery (2026-11-02)
Owner's last private log confirmed that CUDA/VRAM and frozen source checks PASSED, but the HF tokenizer required `sentencepiece` and `protobuf`; both were absent in the CAT venv. The pinned `tools/cat33_requirements_005.txt` now installs both in isolation and source preflight checks them. No global Python changes, no live worker deployment, no model re-download by default. The final candidate can be retried alone from MacBook after `git pull --ff-only`:
    bash tools/run_model_sweep_005.sh optiplex@100.121.156.34 cat33
Save and share either the private CAT result JSON or `cat33-run.log` on any new failure. Do not restart other 4 completed arms. Decision and method stop rules: `benchmarks/DECISION_RECORD_2026-11-02.md`.


## Benchmark 005 CLOSED, 006 fresh source discovery (2026-11-02)

Final CAT3.3 HF NF4 output was COMPLETE: 64/64, median 6.8 chars/sec, 1 >14, 28.27 seconds generation calls excluding one-time model download/load; all five 005 arms now have REAL results but no native-viewer grade. `benchmarks/RESULTS_005_COMPLETE.md` contains immutable IDs/technical metrics. Do not rerun *Primate* lines or choose a winner from assistant subjective rankings. Address CAT3.3's recorded `attention_mask` warning in the future frozen 006 runner.

Read-only new-source inventory on MacBook:

```bash
cd ~/Downloads/bruiser-subhub-repo
git pull --ff-only
bash tools/inventory_sources_006.sh optiplex@100.121.156.34
```

This sends the inventory script through SSH stdin (no remote script staging), opens OptiPlex SQLite `mode=ro`, and prints job IDs/source hashes, English cue count/timeline span only. Primate's already-reviewed English SHA is excluded from eligibility. It does NOT read/view any subtitles, movie paths, Japanese contents, download/load models or modify source DB/media. Inventory alone does not establish title diversity or purity. Need three unrelated NEW EN sources and one untouched confirmation title, then freeze the corpus and run the native Japanese-blind review per `benchmarks/PROTOCOL_006_INDEPENDENT_HOLDOUT.md`.


## Run FULL clean Benchmark 006 in one command (no additional setup diagnostics)

From MacBook, after pulling merged PR #30:
```bash
cd ~/Downloads/bruiser-subhub-repo
git pull --ff-only
bash tools/run_clean_sweep_006.sh optiplex@100.121.156.34
```
It stages scripts only in the OptiPlex scratch benchmark folder; never installs/restarts the production SubHub worker. Uses the EXISTING isolated CAT3.3 CUDA venv with sentencepiece/protobuf already installed. It auto-downloads missing authorized Ollama candidate weights, chooses and freezes 3 new private sources and one confirmation holdout, translates same >=200 English cues with each of TEN model-native workflows, and safely resumes existing private per-cue results if restarted. Experimental output is copied to MacBook `~/Downloads/benchmark006-private/subhub-benchmark-006`. Share `COUNTS.json` + `STATUS.txt` for technical progress; keep source/JA and `IDENTITY_KEY_PRIVATE.json` private. Send ONLY `blind/` option SRT and blind score CSV to Japanese reviewer; do not show model identities until scores are submitted. Untranslated/failed arms are marked blocked, not ranked poorly. Real source selection and model inference require owner's explicit command: GitHub CI tests alone verify no GPU quality.

## Benchmark 006 completed technical runs — viewer stage (2026-11-02)

Real owner logs: frozen new private manifest (4 scenes, 273 cues, 3 films, 1 holdout), 9/10 candidate arms finished. Full counts in `benchmarks/RESULTS_006_TECHNICAL.md`; only Hy-MT2 1.8B blocked after four cues (3 call errors, exact per-cue error strings not included in uploaded shell log). No rerun of the other nine. The run generated **actual anonymous .srt subtitle variants** under MacBook `~/Downloads/benchmark006-private/subhub-benchmark-006/blind/` and an editable `blind/REVIEW_SCORES_PRIVATE.csv`. Open scene metadata `blind/s01/SCENE_PRIVATE.json` to identify original film job ID and seek position; play scene on original English-audio film while loading one `option_A.srt` file, repeat for matched options without showing model identity, then write blind review scores (1–5 watchability, naturalness, plot understanding, reading comfort). Start with the one scene across 9 options (45 minutes) and reserve other frozen scenes for 2–3 finalists. Japanese localization may rephrase/condense; reject only consequential mistakes, awkwardness or unreadability, not changes in word count. Do NOT share the private `IDENTITY_KEY_PRIVATE.json` with reviewer until blind scores are locked. No active queue/published subtitles/movie files changed by this experiment.
