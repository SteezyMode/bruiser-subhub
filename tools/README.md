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
