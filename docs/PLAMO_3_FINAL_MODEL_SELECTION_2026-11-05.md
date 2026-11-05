# PLaMo 3 Translate — selected single SubHub local model (2026-11-05)

**DECISION: Select `pfnet/plamo-3-translate-8b-GGUF` Q4_K_M as the single preferred local EN→JA **machine-draft** translator among the three PLaMo 3 Translate variants.** The prior 2B was the provisional winner over 0.8B; the new complete 8B test shows meaningful improvements in important semantics and practical runtime on the owner's host. **This is a research/model-selection decision, NOT a claim of independently verified 8/10 viewing quality, NOT automatic authorization to publish to Jellyfin, and NOT a claim that the live E4B fallback has already been replaced.**

## Frozen, matched evidence

Owner ran original media's embedded English subtitles from *Friday the 13th: The Final Chapter* (1984), **100 consecutive original cue IDs 153–252**, all model English strings/timestamps confirmed identical. Frozen English SHA-256: `d4394793c9608ab8935cdba89a6bfb9be41d0e51e1274123966b78939fe1174a`.

| PLaMo official Q4_K_M | 0.8B | 2B | **8B** |
|---|---:|---:|---:|
| Original cues | 100 | 100 | 100 |
| Japanese-script dialogue outputs | 87 | 87 | 87 |
| Untranslated English standalone SDH effects | 13 | 13 | 13 |
| Explicitly held dialogue | 0 | 0 | 0 |
| Generation-request seconds | 9.913 | 32.608 | 133.631 |
| Wall including model startup (s) | 13.431 | 36.240 | **143.526** |
| Median displayed Japanese chars/second (approximately) | 6.00 | 6.33 | 6.17 |
| Dialogue cues above 14 displayed JA chars/second | 0 | 0 | 1 |

**8B model SHA-256:** `6b429549113ce0a61281ac72be195697241f89266f4247efec4893e4f580cf10`. Weights `plamo-3-translate-8b-Q4_K_M.gguf` from [official Preferred Networks GGUF](https://huggingface.co/pfnet/plamo-3-translate-8b-GGUF). It **loaded with 28 GPU layers** of partial offloading on the existing RTX 3050 6GB, pinned llama.cpp b12119 CUDA, with **no GPU utilization gate**. Real result is stored privately in `~/bruiser-pilot/plamo3-ab/real-results/film-100-8b-20261105T095007474812Z/8b.json`. Original private 0.8B/2B JSON remain untouched.

**Exactly the developer-native PLaMo input contract:** PFML3 dataset/translation tags, English inputs, Japanese outputs, **two previous successfully translated source/output pairs**, direct `/v1/completions`, temperature 0, `max_tokens=512`, official stop markers. All three use the same script/interface policy and original timestamps; no invented style prompt or rewrite pass. Different model weights and their corresponding generated prior translations are the intended independent-variable difference.

## Why 8B wins relative to 2B

All 87 spoken/dialogue cues were compared side by side, text-only and unblinded. **Improved meaning on material known failures**, not an arbitrary total score:

- **Original cue 175 (sexual slang):** 0.8B interpreted a sexual-partner idiom as a lie; 2B interpreted it as a bed; **8B recognizes sexual activity**. The 8B rendering remains *imperfect*: it describes bad sex rather than being bad in bed. This is a substantive partial correction, not full joke fidelity.
- **Cue 193 (imitated dog bark):** **8B correctly uses Japanese dog-bark onomatopoeia**, where both smaller sizes mistranslated the animal sound.
- **Cue 247 (one full lap of a lake):** **8B conveys going all the way around once**. Both smaller models incorrectly reduce this to happening once *near* the lake, losing the actual instruction.
- **Cues 234–235 and 237:** 8B uses more suitable female-speaker pronouns and conversational phrasing than 2B's masculine `俺` in a dialogue segment.
- 8B shows somewhat more natural tone in scattered informal exchanges and does not introduce a systematic reading-density problem. However, many lines are identical or close to 2B; the gain is targeted rather than uniformly dramatic.

## Meaningful 8B regressions, unresolved problems

**The larger model is not automatically better.** These are intentionally left visible in the decision:

- **Cue 156:** 8B turns “go easier on her” into `軽く見て` (*look down on/underestimate her*), an important semantic deviation; 2B is better here.
- **Cue 158:** 8B changes an emphatic opinion into a future promise to say something.
- **Cue 179:** 8B uses `いない` for a nonexistent computer, inappropriate for an inanimate object; 2B uses `ない`.
- **Cue 180:** 8B literalizes a profanity-laden idiom while 2B is at least idiomatically natural; neither preserves the sexual joke.
- **Cue 198:** 8B renders an affectionate “honey” as additional child praise, while 2B's version is less intrusive; both are imperfect.
- **Cue 241:** 8B reverts to masculine `僕` for a female speaker, where 2B uses `私`. Its better pronouns at 234–235 are NOT stable throughout the scene.
- **Cues 190–191:** all three mis-handle picking up someone in a vehicle/making room for them, instead rendering physically collecting/placing the person.
- **Cue 206:** **all three** misconstrue a command stopping a person as denying the existence/presence of someone at the door. Meaning changed.
- **Cue 239:** **all three** fail a sexual punchline, with inaccurate masculine pronouns in the female speaker's line.
- Standalone sound descriptions (13) were copied in English intentionally, **not localized**. These do not count as successfully translated Japanese subtitles.
- Some film cues are fragments spanning the previous/following cue; short history alone does not reliably identify speakers and referents. No film-audio/video interpretation was performed, so speaker-gender judgments remain provisional where labels are absent.

These are real quality limits; don't change the original model creator’s interface or optimize known cues in search of green metrics.

## Chosen policy and boundary

1. **Select ONE model for future optional local EN→JA machine drafts: PLaMo 3 Translate 8B Q4_K_M, exact weight SHA above, 28 GPU layers verified on the existing host.** Speed is acceptable in this single-user offline workflow (143.526 sec for this 100-cue segment; do not extrapolate to a precise movie-level ETA).
2. **Don't run another model sweep or repeatedly tweak PFML3 history/prompt/style to patch these same examples.** The research comparison is closed; keep 0.8B, 2B, and all previous model experiment results as immutable evidence.
3. **Keep existing source-first Japanese acquisition working unchanged.** This decision does **not** change running worker/model state, timers, media files, or already published human/subs.
4. **Do not automatically create/release Japanese subtitles from unreviewed 8B outputs as if verified 8/10.** For adoption, use an opt-in draft/review status and, if available, one short actual Japanese-viewer playback to distinguish technical completeness from watchability. That is a viewing decision, not another model architecture search.
5. **Production software integration is a separate future work step**, after the current model selection. The November 4 operational tuned Gemma E4B remains present until explicitly replaced; do not claim 8B has already become the active SubHub production worker.
6. **Don't commit raw movie dialogue, EN/JP subtitles, or full private comparison reports to public GitHub.** This document records only IDs, aggregate metrics, diagnostic observations, model hashes and policy.

## Reproduction links

- [8B challenger launcher](../tools/run_plamo3_8b_challenger.sh), [frozen 8B inference](../tools/plamo3_8b_challenger.py), [CI tests](../test_plamo3_8b_challenger.py)
- [Earlier full 0.8B versus 2B review](PLAMO_0_8B_VS_2B_100_CUE_REVIEW_2026-11-05.md)
- [Official model prompting protocol](PLAMO_3_TRANSLATE_EVALUATION_2026-11-05.md)
- [Current execution roadmap](EXECUTION_ROADMAP_2026-11-05.md)

**Evidence limitation:** A 100-cue, one-film unblinded editorial screen can establish practical relative benefits and visible mistakes but cannot prove general superiority over historical E4B/HY/CAT/Index models trained/evaluated on different sources, nor guarantee native-speaker enjoyment of full episodes. **8B wins within the three directly matched PLaMo configurations**, not all translation systems worldwide.
