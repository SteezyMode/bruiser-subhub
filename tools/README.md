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
