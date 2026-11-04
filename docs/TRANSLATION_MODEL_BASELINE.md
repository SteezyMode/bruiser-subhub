# EN → JA subtitle translation: clean baseline (2026-11-03) — HISTORICAL

> **SUPERSEDED FOR PRODUCTION ON 2026-11-04:** The authoritative current model is **17slever17 Translate Gemma 4 Sub E4B** (exact pinned tag hf.co/17slever17/translate-gemma-4-sub-e4b-GGUF:Q4_K_XL; ID 9ccfc3b07081), not the Hy-MT2 7B research model described below. See [the production model decision](PRODUCTION_TRANSLATION_MODEL.md) and the paired [E4B versus Hy7 benchmark](../benchmarks/RESULTS_005_TUNED_HY_PAIRED.md). Preserve this document for historical clean-model tests, NOT as live default guidance.

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

## Full-episode outcome and next clean comparison — 2026-11-03

The detached *The Chair Company* S01E04 Hy-MT2 7B full run **stopped on section 5 of 19**, at source cues 121–150:

- The first four consecutive 30-cue chunks were structurally verified and retained (**120/560**).
- The fifth request returned **29 cues instead of 30**. The runner correctly stopped and preserved `part-0005.raw.txt`. **No complete Japanese episode has been published or produced.**
- This is a **structural-completeness failure** of the current direct structured-data SRT method at the tested chunk size. It is **not by itself evidence that Japanese language quality is poor**.
- The actual missing cue number and possible model generation/truncation cause need inspection; **do not silently retry, pad, retranslate, or mark the episode complete**.

The next comparison intentionally separates **translation merit** from **SRT preservation**. Run `tools/clean_translation_merit_test.py` to compare:

- **Hy-MT2 7B Q4_K_M** — Tencent's exact *Default Translation* English prompt and 7B recommended parameters.
- **Hy-MT2 1.8B Q4_K_M** — same published prompt/parameters as 7B; faster/lighter candidate.
- **CAT-Translate 7B Q4_K_M** — CyberAgent's own exact English→Japanese chat prompt with no invented sampling parameters. The GGUF is a community conversion of the official checkpoint, not an official CyberAgent quantization.

All receive **the same two 30-cue stretches** of dialogue (cues 1–30 and 121–150) with timestamps removed for a fair *language-quality* comparison, and their raw outputs/timing are saved. The script also reports which cue indices the previous structural test omitted. **This evaluation is not an SRT formatting or full-episode test.** If a new model shows better natural Japanese and fewer missing/incorrect meanings, separately verify a real SRT workflow before selecting it.

Official documentation:
- [Tencent Hy-MT2-1.8B](https://huggingface.co/tencent/Hy-MT2-1.8B-GGUF) and [Hy-MT2-7B](https://huggingface.co/tencent/Hy-MT2-7B-GGUF)
- [CyberAgent CAT-Translate-7B](https://huggingface.co/cyberagent/CAT-Translate-7b) and [the community Q4_K_M GGUF](https://huggingface.co/mmnga-o/CAT-Translate-7b-gguf)

Do **not** decide the winner based on a single sample, or accept a prose quality winner as a complete subtitle solution without checking SRT completeness, readability and sustained execution.

## Important correction — 2026-11-03 model-merit results

A later 3-model / 2-passage comparison was run using developer-published **text instructions**, but **the actual Ollama chat templates were not independently verified** for all three installed GGUFs. Therefore it is not a valid final ranking of *underlying model capability*. Record the observations without claiming all three models ran in their intended runtime format.

| Installed GGUF | Passages | Raw observation | Interpretation |
| --- | --- | --- | --- |
| Tencent Hy-MT2 7B Q4_K_M | 2/2 | Coherent Japanese, 42.8s + 37.5s | **Best working configuration tested**, with some meaning and readability mistakes |
| Tencent Hy-MT2 1.8B Q4_K_M | 0/2 | Unrelated Chinese mathematics (6.2s) and unrelated Python code (49.7s, generation cut off by token limit) | Installed configuration broken or unsuitable; **do not attribute this automatically to model weights** |
| CyberAgent CAT-Translate 7B community Q4_K_M | 0/2 | Unrelated stock phrases (9.2s) and severe omissions (3.1s) | Installed configuration broken or unsuitable; **official model requires its distinct 7B chat template** |

The first full Hy-MT2 7B SRT attempt stopped with **29 parsable cues in section 5**, but a subsequent crude ID-only scan found *30 numeric labels*. Exact malformed block/timing cause remains **unconfirmed**. Do not state that a cue was definitely missing.

**New non-negotiable prerequisite:** Before declaring a model test clean, check BOTH (a) the model card's text prompt and sampling instructions and (b) the actual inference runtime's applied **chat template and stop tokens**. Ollama `ollama show --modelfile MODEL` shows the installed template; compare it to the official model's tokenizer/chat-template documentation. If they disagree, fix the inference configuration faithfully, not with invented translation instructions. Do not claim a model is intrinsically poor based on an unverified community GGUF wrapper.

Official model documentation:
- https://huggingface.co/cyberagent/CAT-Translate-7b — explicitly requires its specific 7B chat template
- https://huggingface.co/tencent/Hy-MT2-1.8B-GGUF — official GGUF
- https://ollama.com/kaelri/hy-mt2 — an existing, third-party Ollama packaging that implements Tencent control tokens; an option, not yet tested on this user's host.

**Current decision:** Hy-MT2 7B remains the best proven working configuration, but full-episode SRT reliability and screen readability are unproven. No other model has been fairly disqualified until runtime-template verification.

## CAT-Translate 3.3B FINAL: official-native clean test (2026-11-03)

**Do not substitute the available 3.3B-beta GGUF or an unverified CAT-7B chat template.**

- Official final checkpoint: https://huggingface.co/cyberagent/CAT-Translate-3.3b
- Official usage: Transformers, native `chat_template.jinja`, one user turn with `Translate the following English text into Japanese.\n\n{source}`, `max_new_tokens=512`. No system prompt, prompt rewriting, evaluation LLM, or alternate temperature.
- On the OptiPlex 6GB GPU the sole deviation from full-precision author inference is **standard bitsandbytes NF4 4-bit loading**, applied to the official final model weights. This is **not the developer's baseline precision**, so results must be labeled accordingly.
- Use `tools/run_cat33_official_final.sh` and `tools/cat33_official_final_test.py`. They run on the **host**, outside Sublarr/Ollama; extract the same English source from the existing container via `docker cp`; create a separate local Python virtualenv; download original final checkpoint via Hugging Face; require the tokenizer template to start with `<|user|>` and end with `<|assistant|>`; force GPU execution; translate four consecutive 15-cue passages from the previously tested episode (1–15, 16–30, 121–135, 136–150); and save raw output with wall times.
- Scripts do not produce subtitles, rewrite any Japanese, modify the media library, replace a worker, or configure an auto-publisher.
- This code was reviewed and committed but **has not yet been executed on the OptiPlex**. Neither installation nor quality can be claimed until the host returns logs/results.
- If quality wins, **separately** test SRT alignment/continuity. Do not bolt a new SRT prompting framework onto this result before establishing model merit.

## CAT-Translate 3.3B FINAL native test — actual result (2026-11-03)

The host completed the official FINAL `cyberagent/CAT-Translate-3.3b` test using its published English→Japanese user instruction, tokenizer-provided chat template, and `max_new_tokens=512`. Installed separately in `~/bruiser-pilot/cat33-official-final`, without touching Ollama/Sublarr/Jellyfin. **The model ran in bitsandbytes NF4 4-bit with float16 compute, rather than original BF16.** Results are from `cat33-final-results.json` supplied by the user.

- Cues **1–15**: 9.1 seconds, 228 output tokens; Japanese completed but mistranslated idioms such as *jump through hoops* into literal physical hoop-jumping and used stilted dialogue.
- Cues **16–30**: 5.6 seconds, 153 tokens; translated *people are killing me* literally as **人々が私を殺しているんだ**, unlike the previously tested Hy-MT2 7B which correctly conveyed the unbearable coworkers.
- Cues **121–135**: 8.8 seconds, 241 tokens; **entire response was unchanged English** (no Japanese characters). This is a semantic failure despite successful API completion and no generation token-cap.
- Cues **136–150**: 7.3 seconds, 199 tokens; Japanese mostly present but stilted, including a literal/awkward phrasing of *go crazy on your lawn*.
- All four invocations completed with no 512-token cap. Total inference time 30.8s. Splitting the CAT input into 15-cue calls vs the earlier Hy7 30-cue calls makes timings **not strictly apples-to-apples**.
- **Verdict: CAT-Translate 3.3B final, in this verified native 4-bit deployment, fails the required semantic completeness and idiom-fidelity checks.** Do not select it as the household subtitle model on the basis of developer BLEU benchmarks. This is a statement about *the tested model/configuration*, not every possible precision, decoding or context length.

**Best demonstrated working model remains Tencent Hy-MT2 7B Q4_K_M**, which translated both full 30-cue plain-text passages coherently but whose structured-SRT full-episode run failed structural verification at chunk 5 after 120 correct cues. Next objective should be exact diagnosis of `part-0005.raw.txt` and reliable, non-publishing SRT completeness—not new model proliferation.

## Not part of this test

English source acquisition, audio transcription, PGS/OCR, model switching, UI/dashboard work, integration into Bruiser, publishing automation, resource tuning or multi-model grading. Revisit only **after** EN → JA localization is proven acceptable.

## Change control

A future contributor (including an AI assistant) proposing extra translation processing must show:

- The specific observed failure in this **unchanged model-card baseline**.
- The exact departure from the published workflow.
- The same English material translated side by side with and without that change.
- Clear evidence the difference matters to **watchability at home**.

Otherwise **do not make the change**.
