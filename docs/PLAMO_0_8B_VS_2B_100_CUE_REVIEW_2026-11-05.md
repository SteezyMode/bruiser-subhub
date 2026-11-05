# PLaMo 3 Translate 0.8B versus 2B — real film editorial evaluation (2026-11-05)

**Result: 2B is the provisional winner among the two small models. Neither is yet qualified as the sole final SubHub translation model. The next quality challenger should be 8B on the same frozen English cues, if practical on this host.**

## Scope and reproducibility

- Source: *Friday the 13th: The Final Chapter* (1984), embedded English SRT from actual Jellyfin media; **original cue IDs 153–252** (100 consecutive cues).
- Frozen English SHA-256: `d4394793c9608ab8935cdba89a6bfb9be41d0e51e1274123966b78939fe1174a`. The two submitted result files were independently verified to have identical IDs, timestamps and source English.
- 0.8B: `plamo-3-translate-0.8b-Q4_K_M.gguf`, model SHA-256 `3dbb09295bfd3350231ba0dba92bc72cb14111ef1b034e37dad39d581bd86b9c`. Private output: `~/bruiser-pilot/plamo3-ab/real-results/film-100-20261105T091004064058Z/0.8b.json`.
- 2B: `plamo-3-translate-2b-Q4_K_M.gguf`, model SHA-256 `2c288ecc7ebfe60c3561726580da3583767f3c41ca3ef5c6825bf6c4cc060787`. Private output: `~/bruiser-pilot/plamo3-ab/real-results/film-100-20261105T091839645501Z/2b.json`.
- Both: **native PFN PFML3** translation grammar, direct llama.cpp Completions endpoint, two previous source/output translation pairs, temperature 0, 512 maximum tokens, official stopping tokens. Output Japanese SRT uses original English timestamps. Do not change the creator's prompting method merely to increase scores.
- **No model texts, cue-by-cue dialogue, or film scripts are committed to this public repo.** Raw inputs/outputs and the full private editorial table remain in owner-controlled working files/chat.

## Measured mechanical outcome

| Metric | 0.8B Q4_K_M | 2B Q4_K_M |
|---|---:|---:|
| Original subtitle cues examined | 100 | 100 |
| Marked Japanese-script dialogue translations | 87 | 87 |
| Non-dialogue English SDH captions intentionally preserved | 13 | 13 |
| Marked held dialogue | 0 | 0 |
| Sum of translation-request durations | 9.913 seconds | 32.608 seconds |
| Wall time including server/model startup | 13.431 seconds | 36.240 seconds |
| Median approximate visible Japanese chars/sec on dialogue cues | 6.54 | 6.38 |

Timings and counts are from the **uploaded model JSON results**, not extrapolated. These completion checks do **not** establish translation accuracy. Readability statistics strip font tags but do not replace native viewing.

## Full 87-dialogue-cue editorial pass (text only; not blind or native-viewer certified)

Human-language plausibility was assessed for every one of the 87 spoken/dialogue cues, including idioms, colloquial Japanese, tone, semantic reversals, speaker register and readability. The classification is **one assistant's subjective pass**, not a benchmark score. Grouping: 2B had a visible advantage on **26** cues; 0.8B on **11**; **10** had a meaningful problem in both; **40** were approximately similar or inconclusive. The 13 separately held SDH labels were not graded as translated Japanese. Numbers are only useful as a navigation summary; **severity matters more than count**.

### Strengths of 2B

- Cues **160–166**: consistently more natural spoken Japanese for relationship dialogue and better previous-tense narration; 0.8B repeatedly translates the concept of treating someone well with stiff literal language.
- Cues **178, 180, 226, 235, 242**: better interpretation of negation, an idiomatic assertion of being in trouble, an incomplete exchange, an interrupted noun phrase, and permission/purpose language.
- Cues **186, 224, 225, 241, 249**: better handling of some female speakers and domestic register; notably 0.8B uses masculine-associated first-person pronouns for a named female character.
- Both models are remarkably fast in absolute terms on the owner's RTX 3050; the ~2.7x wall-time difference does not outweigh language quality in this model-selection trial.

### Strengths of 0.8B

- Cues **156, 170, 179, 184–185, 198, 202, 232–233, 237, 240**: occasional better idiomatic brevity, adult speech register or fewer unwarranted masculine pronouns. The smaller model is **not** uniformly worse.

### Important shortcomings in BOTH models

- **173–176, 180, 239 — sexual idioms and connected comedy:** both fail a prolonged sexually explicit insult/punchline exchange, including a clear erroneous interpretation of sexual-partner slang in cue 175. A natural-sounding Japanese sentence may be fundamentally *wrong* in context. The 2B's idiomatic rendering at 180 partially helps but does not repair the joke.
- **206 — incorrect conversational action:** both turn an interruption/refusal of an action into a denial that somebody is at the door, changing what the scene communicates.
- **190–191 — ride/space context:** both handle picking up someone and making room in a vehicle too literally or with the wrong situational action.
- **193 — sound imitation:** both mishandle a dog bark, with 2B's imitation especially off.
- **247 — lost concrete action:** both miss that the plan is one full lap around a lake.
- **Voice continuity:** 2B fixes certain female-speaker pronouns, but elsewhere can assign an apparently male first-person register to women (notably in the later reputation/sex dialogue). Text-only labels are insufficient to certify all voices without actual movie audio.
- **Profanity and satire:** in cue 167, both tone down an explicit expletive. Both can lose sexual innuendo even when their SRT syntax is entirely valid.
- **SDH localization:** 13 bracketed English sound descriptions are intentionally copied rather than localized. They must not be counted as translated JP; do not accidentally publish them as finished Japanese SDH.

## Model-selection decision

**Two-small-model result: 2B wins, tentatively.** However, given the household's emphasis on conversational fidelity, adult humor and horror, 2B cannot be endorsed as an automatically published high-quality translator based on this sample. It is a strong fast baseline/draft model.

**Next and only next model test:** challenge the current leading 2B against **official PLaMo 3 Translate 8B** on **the same original 100 cue IDs and unchanged native PFML3 translation scheme**, rather than tweaking the prompt or building new infrastructure. Compare especially **173–176, 190–193, 206, 224, 239, 241, 247**, plus full set for unexpected regressions. Use partial CPU offload if required because 8B Q4_K_M weights alone are ~5.28 GB and the owner's RTX 3050 has 6 GB VRAM; verify runtime rather than assume full GPU fit. No need for a simultaneous gaming safeguard in this dedicated owner-led benchmark. Stop after a genuine A/B or decide 2B is the best practical local model if 8B brings insufficient benefit.

**Final quality gate:** at least one small native-Japanese film playback check before treating model-generated subtitles as production ready. The entire existing source-acquisition and synced-human-Japanese service remains independent and untouched.
