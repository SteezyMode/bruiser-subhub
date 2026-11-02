# SubHub v011r1 — REAL owner recovery, QA and bilingual verdict

**Observed November 2, 2026. Real archive:** completed private English/Japanese SRTs for **American Dad S19E10, S19E11, S19E12**. Private subtitles and editorial flag CSV are **not** committed; this document contains aggregate metrics and category summaries only.

## Operational success (verified, not projected)

| Episode | Preserved original v011 Japanese cues | Completed cue pairs | >18 visible Japanese chars/sec | Unresolved mechanical QA | Recovery newly grouped units | Recovery singleton-fallback units | Post-QA repairs |
|---|---:|---:|---:|---:|---:|---:|---:|
| S19E10 | 219 | 372 | 1 | 0 | 1 | 127 | 0 |
| S19E11 | 192 | 409 | 1 | 0 | 5 | 186 | 1 |
| S19E12 | 346 | 408 | 2 | 0 | 2 | 49 | 0 |
| **Total** | **757** | **1,189** | **4** | **0** | **8** | **362** | **1** |

The private archive exporter verified original English source hashes, exact 1,189 cue IDs/timing pairs and byte equality of the published recovery sidecars with their private drafts. All 45 clearly multi-speaker English cues are now visually separated into Japanese lines (26, 8, 11, respectively), a structural improvement from v010 where 24/51 were not clearly separated.

## Central discovery: grouped translation is mostly NOT working

The original v011 pass had **711 accepted units containing 757 cues**, so most of its successes were already singletons. Its recovery processed **370 remaining units**, of which **only 8 (2.2%)** succeeded as new grouped Japanese outputs; **362 (97.8%)** required current-cue-only fallbacks.

Consequently this recovered collection **cannot establish that v011's utterance-aware model interface improves semantics**. It primarily establishes that independent immutable checkpoints and bounded singleton fallback rescue the operation. The previously identified original v011 failure categories were 51 generation length caps vs 6 invalid Japanese/speaker attempts across 18 exhausted units.

## Human text-only bilingual editorial assessment

Private inspection covered opening, middle, end, high-risk scenes and a reproducible sample of 40 other cues per episode. **Provisional quality range: ~5.5–6/10**, not native-speaker viewing certification and not a controlled head-to-head test against v010 (~6/10, different episodes). The owner's practical target remains 7.5–8.5/10 for personal watching, **not yet reached**. Forty-one selected high-confidence examples are documented in a PRIVATE CSV; **they are not an error percentage for all 1,189 cues**.

Recurring **major** categories: cross-cue semantic anticipation and duplicated meaning despite zero overlap flags; proper-name drift (one recurring character's established Japanese name appears consistently in only 5 of 19 English references); wrong senses of polysemous English terms causing serious joke/plot errors; idioms and slang translated literally; logical polarity/agent reversals; occasional unreadable over-literalness and stray quote punctuation. One recurring pivotal snack/food motif was turned into a sexual meaning in three consecutive lines; injury described as musculature; a contraception-related term became an organ. Mechanical success alone did not catch any of these.

Some longer expository and emotional passages are reasonably intelligible. Most ordinary short conversational lines are fine. Still too many central jokes or key narrative facts are altered to claim high-quality localized subtitle output.

## Next engineering direction: reduce scope, no model tournament

1. **Do not deploy this as the whole-library production translator.** Keep the stable original 010 current-cue prompt, frozen v009/v010/v011 tracks and operational rescue.
2. Perform a tiny **read-only 15–30 utterance formatting test with the SAME pinned tuned Gemma E4B**, comparing a minimal plain cue-ID-delimited output to v011's current multi-cue JSON and observing exact completion/length-cap behavior. No media writes, no new model sweep, no retranslation of completed TV seasons.
3. Track episode-local **proper-name consistency** using English source references, with curated/reviewable Japanese mappings for real names. Do not auto-translate ambiguous common nouns such as `Can` as proper names without context.
4. Add targeted bilingual checks for pragmatic meaning, time-displaced information, negation, humor, slang and polysemy; simple Japanese density/overlap checks cannot warrant an 8/10 quality claim. Record when human review remains necessary.
5. Only promote after a controlled small EN/JA quality comparison plus actual household Jellyfin watching. Preserve source/approved SRT integrity and create-only publication.

**Privacy:** Do not place the source or localized cue text, user archive, private quality report, or selected bilingual example CSV in this public repo. The private review is retained only in the user conversation.
