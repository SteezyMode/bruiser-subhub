# Benchmark 006 — private archive inspected; preliminary assistant screen (2026-11-02)

**Status: 2,457 completed Japanese outputs programmatically inspected, 38 selected context/idiom-sensitive source cues spot-checked by ONE assistant. NO independent native-speaker quality score or final model winner.** Owner provided `subhub-006-review.tar.gz`: private `manifest.json`, all candidate raw source/JA cue records, and blind SRT pack; source manifest SHA `6900fb27123acaab4ce6f1277efccc11c0b6c504372b0b07640c4c34f07ae3ab` verified. Four frozen source scenes across three titles, 273 cues. Fourth film is still sealed for confirmation.

## What was actually checked

- All nine completed 273-cue candidate arms were enumerated: no empty returned `candidate_japanese` strings, all 2,457 output records available. Broad JA acceptance and reading-speed figures are in [RESULTS_006_TECHNICAL.md](RESULTS_006_TECHNICAL.md); **these are not quality grades**.
- Programmatic flags included: broad JA acceptance failures; Japanese reading density >14 chars/sec; high ratio of untranslated ASCII/roman text; model replies offering alternate versions. Private deterministic flags file recorded locally; does **not** classify every flag as an actual translation error.
- One assistant manually compared **38 selected cues across all four scenes** with the original EN and other generated Japanese. This is **purposefully selected risk material**, not a blinded, representative natural-Japanese error-rate estimate. Preserve native viewer as independent judge, do not feed findings into new prompts on 006 data.

## One definitive operational blocker: Hy-MT2 1.8B

- The private per-cue JSON resolves the unknown 3 failed call reasons. On the initial four source cues, **three calls threw `RuntimeError: Ollama output length cap`**; the fourth returned a malformed **JSON-like fragment instead of Japanese**. Therefore **0/4** passed broad JA structural checks and the automatic stop triggered.
- Exact downloaded model: `hf.co/tencent/Hy-MT2-1.8B-GGUF:Q4_K_M`, Ollama ID `33a3a4ab0f4e`, reported quant `Q4_K_M`, family `hunyuan-dense`, template SHA `0d08dbd520acace905df280dc5475557b060ab618fd4d31d9b961e152250cccf`.
- This is an **observed output-format / length-cap compatibility problem**, NOT evidence that the genuine 1.8B model weights produce low-quality translation. Fixing its native template/runtime should be a **separate later compatibility experiment** if needed; do NOT silently rerun, resample or unblind existing nine completed 006 arms.

## Meaningful exploratory findings, not a model preference score

- Across several models, the broad JA validator accepted semantically wrong but grammatical Japanese, including errors involving biological tissue, ambiguous profanity, medical/action terms and dramatic dialogue. Natural shortening/condensation was expressly **not** penalized.
- **Shared context failure in ALL nine completed arms:** in a plot-relevant dialogue, a speaker highlights a WORD from the earlier sentence, but every individual-cue translation turns it into a reference to uttering something once. Very short previous-context windows did not include the needed antecedent. Also a religious phrase was rendered as literal physical blood by every model, missing preceding faith/atonement context. These issues are **system-level scene/fragment context weaknesses**, not evidence that bigger weights inherently win.
- **Model-specific consequential errors occurred in multiple families:** Index2B confuses a medical blood term, tuned E2B reverses an urgent rescue plea, some model variants take coarse profanity as literal feces, some mistranslate a physical connection to a room, and one Google4 rendering plausibly reverses a character's outrage. This is qualitative single-assistant inspection on SELECTED CUES, not a measured per-model error-rate table.
- TranslateGemma 12B produced **18/273** outputs with the Japanese conjunction `または` (*or*), sometimes presenting alternative interpretations instead of one film-ready subtitle; it also had 40/273 lines over 14 JA chars/sec, compared with 2 for tuned Gemma E2B. Mechanical flag, not independent viewer disqualification.
- There is NO proof that subtitle-tuned E4B is better than untuned E4B, or that a multi-tier model review is better than one native pass. Shorter models Index2B and tuned E2B remain serious candidates on speed, but both have potential substantive errors. Only Japanese speaker playback can decide.

## Next user-facing deliverables (kept PRIVATE, never committed)

- `subhub006_quality_audit_PRIVATE.md`: comprehensive technical + manual contextual screen, limitations and cited cue IDs.
- `subhub006_all_models_PRIVATE.csv`: full **273 × ten-arm** side-by-side source and outputs (HY1.8 incomplete).
- `subhub006_mechanical_review_flags_PRIVATE.csv`: 133 deterministic flagged records; each flag is a review prompt, not an adjudicated mistranslation.
- `subhub006_blind_quick_view_Hokum.zip`: **9 anonymous A–I SRTs covering the SAME first 90 sec of scene s02**, original movie playback at **35:00–36:30**, score CSV and simple directions. The model identity key was **never included**. This is only a short stage-1 screen; later longer natural viewing across finalists and held-out fourth film remain necessary.

**Do not rerun 006, change prompt settings against these already-read outputs, choose an alleged 8/10 winner, overwrite live Japanese tracks or bother a household reviewer with 9 × 5 minute scenes before the short blind stage.** Model switch remains UNDECIDED.
