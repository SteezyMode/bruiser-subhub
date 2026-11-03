# EN → JA subtitle translation: clean baseline (2026-11-03)

## The only objective

Natural, accurate, watchable Japanese subtitles for English films/TV in one household. Aim for about **7.5–8.5/10** quality, **not** professional certification or a bespoke AI product. The larger workflow will eventually find an exact English subtitle match or transcribe accurate English when missing, then translate that English into Japanese. **The current test is only for the EN → JA stage.**

The authoritative requirements are in [GOAL.md](../GOAL.md). The solved Jellyfin dual-subtitle setup is outside this project.

## Hard rule: use the model as documented

Before testing a model, read its **own** developer instructions. Follow its own chat template, recommended generation settings and expected input format. Keep the raw output. Do **not** add our own style prompt, backtranslator, review LLM, glossary, automatic retries, prompt adjustments, semantic QA, or rewriting unless an actual side-by-side comparison demonstrates that it improves home viewing. Mechanical file work (extract, split, preserve timecodes, checkpoint, stop on malformed output) is allowed.

Previous SubHub/Sublarr evaluations confounded model output with bespoke prompt and validation logic. In particular, upstream Sublarr's Japanese-unaware CJK hallucination check generated false-positive retries. **Do not use those older rankings to select a translator.** Never edit a live translation service just to run a model-quality test.

## Current leading candidate — documented Hy-MT2 7B

- **Official source:** [Tencent Hy-MT2-7B-GGUF model card](https://huggingface.co/tencent/Hy-MT2-7B-GGUF)
- **Model already installed:** `hf.co/tencent/Hy-MT2-7B-GGUF:Q4_K_M`
- **Quantization:** Q4_K_M; model weights about 4.6 GB. Actual full-GPU residency on the RTX 3050 6 GB is *not yet verified*.
- **API:** existing Ollama `/api/chat` with **one user message and no system message**.
- **Prompt:** Tencent's **Structured Data 1** English template, with exactly three variables: format type `SRT`, target language `Japanese`, and the original SRT text. See `official_prompt()` in [the full-episode runner](../tools/hy_mt2_full_srt_test.py). Do not embellish it.
- **Published 7B generation settings:** `temperature=0.7`, `top_p=0.6`, `top_k=20`, `repetition_penalty=1.05` (Ollama `repeat_penalty`), `max_tokens=4096` (Ollama `num_predict`). No different custom sampling or reasoning controls.
- **Context:** 30 consecutive SRT cues per request, the same input length that passed the initial demonstration. Chunking is file handling required for finite context. Tencent does **not** prescribe 30 cues as the optimal batch size; do not present that as a documented model parameter.

The Structured Data 1 template does not mention SRT explicitly; applying it to SRT is our **one format substitution**, already tested. The small demo preserved every timecode and index. This is *not* proof that every longer request or the full episode will preserve structure.

## What is actually verified

Test source: **The Chair Company S01E04**, same 30 consecutive English cues from an embedded `subrip` subtitle stream.

| Clean trial | Observed result | Qualification |
| --- | --- | --- |
| E4B subtitle fine-tune, previous-segment prompt | 30/30 responses, valid SRT | Literal idioms; some awkward context |
| Hy-MT2 7B, Tencent **Default Translation** prompt | Natural Japanese for most difficult idioms; ~51.4 seconds | Output was prose, not aligned SRT |
| TranslateGemma 4B, its documented prompt | ~18.8 seconds | Omissions and awkward passages |
| Hy-MT2 7B, Tencent **Structured Data 1** prompt | **30/30 indexes and timestamps preserved exactly**; no repair | Some overly long lines, including cue 9; only 30 cues evaluated |

These outcomes apply to this one passage. A provisional quality impression is not a validated full-episode score. The **next test** is the complete episode, followed by an actual viewing review.

## Full-episode test: same prompt, no translation enhancements

Run [`tools/hy_mt2_full_srt_test.py`](../tools/hy_mt2_full_srt_test.py) against the same MKV or an English `.srt`. It:

1. Extracts the existing embedded English SRT with ffmpeg (or reads an English sidecar).
2. Sends each consecutive 30-cue SRT section to Hy-MT2 **using the exact same prompt/settings as the successful 30-cue test**.
3. Saves the model's raw response for each section, verifies that indexes/timestamps exactly match (without changing the translation), and saves that section as a draft.
4. Resumes completed sections after a stopped SSH session. If a section is malformed, **stops and preserves the raw response** rather than retrying, fabricating, or rewriting.
5. Assembles `full-episode.draft.ja.srt` only if all sections have intact SRT structure. This is **not** automatic publication or evidence that Japanese viewing quality is sufficient.

Draft path inside `sublarr-pilot` is `/tmp/subhub-hy-mt2-full-chair-test/full-episode.draft.ja.srt`, with the original English source and raw section replies in the same directory. It never edits media, Jellyfin, existing editorial Japanese or the running translation configuration.

**How to evaluate:** Sample meaning, idioms, tone, character voice, omissions, timestamp accuracy, and especially *readability against the actual video*. If some lines are too long, record the issue; do not silently invent a quality fixer. The full Japanese draft is only provisionally usable until watched.

## Start the full-episode trial on the OptiPlex

The following uses the existing Sublarr container **only as an environment with ffmpeg and the configured Ollama URL**. It does not call Sublarr's translation backend. The test runs detached on the host container so the MacBook SSH session can close. Logs are append-only; the Python runner keeps its own completed 30-cue checkpoints.

```bash
ssh optiplex@100.121.156.34 'bash -s' <<'REMOTE'
set -euo pipefail
tmp=$(mktemp)
trap 'rm -f "$tmp"' EXIT
curl -fsSL https://raw.githubusercontent.com/SteezyMode/bruiser-subhub/f586733b756cae30b69f81dafc587ed525986c3e/tools/hy_mt2_full_srt_test.py -o "$tmp"
docker cp "$tmp" sublarr-pilot:/tmp/subhub_hy_mt2_full_srt_test.py

docker exec -d sublarr-pilot sh -c '
  export PYTHONPATH=/app
  exec python3 -u /tmp/subhub_hy_mt2_full_srt_test.py \
    "/media/bigdisk-video/Television/Serials/The Chair Company/The.Chair.Company.S01.1080p.AMZN.WEB-DL.H.264-EniaHD/The.Chair.Company.S01E04.1080p.AMZN.WEB-DL.H.264-EniaHD.mkv" \
    --workdir /tmp/subhub-hy-mt2-full-chair-test \
    >> /tmp/subhub-hy-mt2-full-chair.log 2>&1
'
sleep 3
docker exec sublarr-pilot sh -c 'tail -n 20 /tmp/subhub-hy-mt2-full-chair.log'
REMOTE
```

The command starts the real full-episode job; it does **not** mean that a complete Japanese SRT has already been generated. To check progress later:

```bash
ssh optiplex@100.121.156.34 'docker exec sublarr-pilot tail -n 35 /tmp/subhub-hy-mt2-full-chair.log'
```

The last lines will say `COMPLETE` and give the draft location **only after every part succeeds**. If a part fails, a raw answer is saved and the run stops without repairing/retrying the model output. Running the same pinned script again reuses complete verified segments. A lock prevents simultaneous runs from writing to the same work directory.

When complete, retrieve the separate draft (still **not** a Jellyfin sidecar) from the container with:

```bash
ssh optiplex@100.121.156.34 'docker cp sublarr-pilot:/tmp/subhub-hy-mt2-full-chair-test/full-episode.draft.ja.srt /tmp/subhub-chair-s01e04.ja.srt'
```

No claim of watchability is made until the full draft is reviewed alongside the film or episode.

## Not part of this test

English source acquisition, audio transcription, PGS/OCR, model switching, UI/dashboard work, integration into Bruiser, publishing automation, resource tuning or multi-model grading. Revisit only **after** EN → JA localization is proven acceptable.

## Change control

A future contributor (including an AI assistant) proposing extra translation processing must show:

- The specific observed failure in this **unchanged model-card baseline**.
- The exact departure from the published workflow.
- The same English material translated side by side with and without that change.
- Clear evidence the difference matters to **watchability at home**.

Otherwise **do not make the change**.
