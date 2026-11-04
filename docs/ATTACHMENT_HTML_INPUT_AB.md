# Attachment E4B — one-variable HTML presentation-markup A/B (2026-11-04)

**Status:** Small offline-tested, scratch-only experiment. **Actual OptiPlex inference has NOT run yet.** No change to live production, and no new published subtitles.

## Why this is a genuinely different test

The source-hashed *Attachment (2022)* English SRT has **1,276/1,276 cues** wrapped in HTML `<font ...>` tags. Some also include `<i>` tags. The currently installed E4B translation implementation sends `row["english"]` from SQLite directly as `[CURRENT_SOURCE]` without normalizing SRT presentation tags. The prior Attachment translation therefore received formatting markup alongside actual spoken English.

This is **not** another context-count, temperature, max-token, prompt, glossary or model change. The model author documents *subtitle content* in [CURRENT_SOURCE], with previous English/Japanese for context, and uses temperature 0, 1344 context and a 256-token output limit. See [production model](PRODUCTION_TRANSLATION_MODEL.md) and [official E4B GGUF model card](https://huggingface.co/17slever17/translate-gemma-4-sub-e4b-GGUF).

**Hypothesis:** Removing font/italic presentation tags from the English input could reduce distraction and improve meaning. It may also have no measurable effect. There is NO proven gain until returned real outputs are graded. Not a guarantee of 8/10.

## Why NOT simply add more previous/future context

- [Benchmark 002](../benchmarks/RESULTS_002.md) tried two previous pairs, but altered style, 4096 context and 320 output tokens.
- [Benchmark 003](../benchmarks/RESULTS_003.md) compared one previous pair with and without an 8-second gap rule at model-card settings; **no consistent quality improvement**, and specifically warned against more 2-versus-1 history or token microtuning.
- [FormatLab 012](UTTERANCE_FORMATLAB_012.md) tested grouped timed-cue outputs; many calls exceeded length limits or failed cue mapping.
- [FocusLab 013](UTTERANCE_FOCUSLAB_013.md) proposed one-cue output with broader utterance context, but its own document records no completed real host inference or editorial grade.

More previous lines are therefore **not** an established new fix. Future English, guessed speaker roles and generated glossary entries are not part of the author's simple native baseline. Do not ship them as a supposed quality improvement.

## Frozen comparison

[tools/attachment_html_input_ab.py](../tools/attachment_html_input_ab.py), with [offline tests](../test_attachment_html_input_ab.py), reads the existing source and fully completed E4B English/Japanese pairs **read-only** from the isolated Attachment review database. It refuses mismatched model ID, source SHA/profile, incomplete original results, or other active SubHub workers.

**24 fixed cues** span known errors and normal controls: 25, 65, 87, 95, 126, 140, 180, 280, 367, 420, 502, 530, 620, 733, 738, 750, 780, 930, 1027, 1074, 1082, 1138, 1265, 1275.

For each cue, compare:
- **Raw:** the same author-native CURRENT_SOURCE containing its original font markup, plus exactly one previous raw English/current-model Japanese cue pair.
- **Clean:** exactly the same request except remove known presentational font/italic/bold/underline tags from current and previous **English only**. The previous Japanese is IDENTICAL between arms. Whitespace, dialogue wording, timestamps, translation model, prompt and generation options are unchanged.

Both arms call the **same pinned E4B** `tuned.translation()` with **temperature 0, n_ctx 1344, num_predict 256, one previous pair, unchanged system message**. Two calls per cue, up to 48 calls, checkpointed privately. No second AI model, output repair, auto-review, source-file rewrite, model downloads, or publication.

Private scratch output:

`~/bruiser-pilot/attachment-e4b-rerun/markup-ab/report.json`

Only code/experiment metadata and **non-copyrighted summary findings** belong in GitHub. Keep English and Japanese dialogue outputs in the private host folder and private ChatGPT upload.

## Decision criterion

Compare meaning, idioms, sentence fragments, dialogue register, character names, correct supernatural terminology, and serious regressions **against the same English source**. A meaningful win would correct several known consequential errors **without adding material new ones** across normal controls, not just produce prettier line breaks or fewer tags in output. If results are mixed or identical, **discard the idea and move on**. Do not automatically retranslate 1,276 cues or change live production code based on input cleanup theory alone. Preserve the existing published original and E4B review subtitles.

This is data hygiene, not a rescue loop for an incapable model.