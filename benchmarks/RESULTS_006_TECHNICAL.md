# Benchmark 006 — real owner-run technical outcome (2026-11-02)

**STATUS: 9/10 MODEL ARMS COMPLETE on the 006 FROZEN NEW-DATA SET. NO Japanese-language quality winner has been graded.** This report is based on the owner's actual uploaded `COUNTS.json`, `prepare.log`, `blind.log`, `STATUS(5).txt` and all ten arm console logs. Logs contain model download status and start/end counts; they are NOT the private cue translations or human viewing scores. The film texts and private model mappings remain off GitHub.

## Corpus identity verified from owner prepare log

- PRIVATE manifest SHA-256: `6900fb27123acaab4ce6f1277efccc11c0b6c504372b0b07640c4c34f07ae3ab`. Do not change this manifest or regenerate scenes to rescue failing model.
- **4 continuous 5-minute scenes** from **3 distinct titles**. **273 source cues** in total: scene counts **77, 86, 48, 62**. A **fourth completely unused title** remains reserved for later confirmation.
- Old *Primate* source excluded by the runner. Prior exploratory 005 same-dialogue assistant comparisons must NOT be used to choose 006 quality winner.
- Validation checks run before inference; actual source text, source hashes, scene movie paths and model-generated Japanese are all PRIVATE and not present in this repository.

## Recorded completed model calls (exact owner COUNTS.json values)

| Arm | Records | Broad JA accepted | Format-flagged | >14 JA char/s | Generation-call seconds | Failure? |
|---|---:|---:|---:|---:|---:|---|
| CAT-Translate FINAL 3.3B HF NF4 | 273/273 | **269/273** | 0 | 9 | **124.54** | none |
| Index-Translate 2B | 273/273 | **271/273** | 0 | 6 | **130.16** | none |
| 17slever17 tuned Gemma E2B | 273/273 | **272/273** | 0 | 2 | **187.30** | none |
| CAT-Translate FINAL 7B HF NF4 | 273/273 | **272/273** | 0 | 8 | **193.64** | none |
| 17slever17 tuned Gemma E4B | 273/273 | **271/273** | 0 | 6 | **227.59** | none |
| untuned Gemma E4B control | 273/273 | **273/273** | 0 | 4 | **234.67** | none |
| Google TranslateGemma 4B | 273/273 | **272/273** | 0 | 26 | **238.27** | none |
| Tencent Hy-MT2 7B | 273/273 | **273/273** | 0 | 7 | **328.78** | none |
| Google TranslateGemma 12B (CPU offload) | 273/273 | **273/273** | 0 | 40 | **964.59** | none |
| Tencent Hy-MT2 1.8B GGUF | **4/273** | **0/273** | 3 | 1 | **12.16** | **BLOCKED after 3 failed model calls; not scored** |

**Interpretation warning:** All 9 successful arms returned 273 cue records and zero API-level errors; 'accepted Japanese' only validates a broad language/format heuristic, not meaning, naturalness, or dialogue fidelity. This heuristic accepted earlier wrong translations. A model with 269/273 accepted is not necessarily worse for a Japanese viewer than 273/273. Excluded cold-model load/download time, runtime/VRAM residency and backend differences make wall-time values OPERATIONAL comparisons, not isolated architecture performance or energy estimates.

## Newly tested models — direct answer to owner's earlier question

- **Index-Translate 2B:** complete 273/273; 130.16s of generation calls, 271 broad JA accepts. It is a serious speed candidate, quality not assessed.
- **Subtitle-tuned Gemma E2B:** complete 273/273; 187.3s, 272 accepts, just two >14 JA char/s. Directly comparable operationally with tuned E4B on the same text; quality not assessed.
- **Untuned Gemma E4B:** complete 273/273; 234.67s, 273 accepts. Can now assess whether subtitle tuning offers a **viewing** benefit on identical scenes.
- **Hy-MT2 1.8B:** the model weights downloaded successfully (approximately 1.1 GB), but the runner stopped after 3 failed inference calls in its first 4 recorded cues. Its shell log shows only summary error, **not individual Python/API error causes**. Do **not** label 1.8B 'bad Japanese' or infer that quantization/prompt is definitely at fault. Exact error is inside PRIVATE `arms/hy18/s01/<cue_id>.json`, not uploaded in the current log set; retrieval should print only error TYPE/REASON and avoid printing film dialogue.
- **CAT-Translate FINAL 7B:** the correct HF final 7B workflow completed all 273 without role-label format flags; this is **not** the earlier broken GGUF-Ollama wrapper. Do not carry previous GGUF result forward as a CAT7 language score.

## Independent blinded review ALREADY GENERATED

Owner's `blind.log`: **`BLIND PACK READY`, 9 completed models**. Source folder on MacBook after successful result copy: `~/Downloads/benchmark006-private/subhub-benchmark-006/blind/`; inside, for each `s01` through `s04`, `option_A.srt` etc plus `SCENE_PRIVATE.json` containing title/job ID and original scene start/end seconds. Reviewer score sheet: `blind/REVIEW_SCORES_PRIVATE.csv`. **MODEL IDENTITY KEY IS OUTSIDE THIS FOLDER**: `~/Downloads/benchmark006-private/subhub-benchmark-006/IDENTITY_KEY_PRIVATE.json`. Do not open/share the key with the viewer before scores are recorded.

**Manageable staged review rather than 36 full viewings:** Have a Japanese-speaking viewer rate a common scene from ALL nine blinded models, then longer playback for ~2–3 finalists on all other frozen scenes; consistently use original English audio and source timing. The viewer may safely regard intelligent condensation/idiomatic shifts as good localization. Score 1–5 for watchability, naturalness, plot comprehension and readability, plus major context misunderstandings (not one-to-one word equivalence). Ratings are a household one-viewer result, not formal independent multi-reviewer statistical validation. Don't unblind on assistant opinion.

**Next actual action:** Conduct first blinded scene playback and record independent Japanese ratings from the existing completed outputs, rather than creating additional models, new prompts or new scenes. Decide whether to repair/rerun Hy1.8 **separately** after obtaining its exact 3 errors; any recovered results must be clearly labeled post-compatibility repair and NEVER substitute silently into sealed 006 data. Preserve all 9 successful arms unmodified. Fourth title stays sealed until a finalist passes staged review.

**No production deployment, destructive SQLite change, media mutation or approved human Japanese SRT replacement was authorized or made by this benchmark harness.**
