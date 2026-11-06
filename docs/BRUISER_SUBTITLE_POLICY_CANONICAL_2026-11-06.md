# Canonical Bruiser subtitle coverage policy
**Owner-confirmed decisions — 2026-11-06. Authoritative for subsequent development and new chat handoffs.**

> **Do not reopen these choices each session or return to arbitrary movie/TV splits and model tournaments.** The target is maximum **usable, correctly timed, properly matched subtitle coverage** across the entire personal Jellyfin library. Performance counts must reflect titles that can actually be watched, not API calls or drafts. This document supersedes conflicting older strategy/model-first statements in `GOAL.md`, old README paragraphs and November 5 roadmap documents as to **coverage workflow**. It does *not* modify the separate working American Dad PLaMo 8B engine or its current safety rules.

## Fixed priority sequence — implement this, not a reinterpretation

1. **Preserve and use good existing subtitles** in the correct language. Count embedded and exact-video named sidecars, including editorial and local machine-generated tracks; do not overwrite, silently supersede or redownload a working track. Actual viewing quality matters. If only a forced/signs-only track exists, this is not complete dialogue coverage.
2. **Timing rescue BEFORE replacement or new translation.** A decent-quality existing **Japanese OR English** subtitle with an adjustable timing offset or drift is worth keeping. Attempt bounded, auditable timing correction against the actual release/audio (e.g., existing ffsubsync pipeline), verify unchanged dialogue and plausibility. Preserve original bytes and publish only a **separate, create-only corrected version** if validated; hold irreconcilable version mismatches, missing dialogue or poor-language tracks. A mere unsynced duration does not prove impossibility. This includes **already downloaded/staged** subtitle files that have not passed publication.
3. **Reuse already discovered and staged provider results, then search OpenSubtitles** (via existing Sublarr integration) for a credible, identity-matched subtitle of the needed language. Searching does not itself constitute publication. Saved strong candidates and already-staged bytes have priority over new quota-consuming downloads. Download at most the best justified result, stage privately, screen for corruption/wrong episode, repair timing when reasonable, publish a new sidecar only after checks. Stop at provider-account quota; don't circumvent account restrictions. Daily JA source timer was confirmed rescheduled to **09:15–09:35 JST** (after approximately 09:00 JST OpenSubtitles daily UTC reset). The fixed 75% movie / 25% episode heuristic in older source scripts is **not an owner-approved priority** and must be replaced by measured per-attempt yield instead of another guessed ratio.
4. **For Japanese still missing after authentic source acquisition/repair, obtain trustworthy English text.** Reuse embedded or existing English subtitle tracks first; repair their timing if needed; recover internal Jellyfin English, then other providers/OCR/ASR when justified. Do not burn OpenSubtitles downloads on another EN copy if an exact video-timed English text source is already available. English text must be structurally parseable and correctly associated with the video prior to GPU translation.
5. **Local GPU translation is the LAST OPTION, but a real expected high-volume production path**, not discouraged, hypothetical, or disabled forever. Use it for titles without acceptable sourced Japanese when valid English text exists or has been recovered; reuse the established PLaMo translation/checkpoint approach, prioritizing fluent, faithful, tone-preserving Japanese. The owner expects to use the GPU a great deal eventually. Record `validate_english_for_ja_fallback` as an actionable queue state, not a terminal failure. Automatic AI jobs remain **off in the current source-only daily timer** until explicitly implemented and validated as a separate supervised queue, preserving Wolf, desktop and power/thermal controls. Do not relaunch the completed American Dad batch while working on general coverage.
6. **Verify real deliverables** in Jellyfin / media-adjacent tracks, and refresh the queue once actual coverage has changed. Record provider outcomes, timing holds, SRT provenance, failure reason, and resumed progress. Do not equate service exit code 0, SRT count or an English codec flag with actual viewing quality.

## Which languages to obtain

| Primary audio | Desired next missing subtitle(s) | Reason |
| --- | --- | --- |
| **English** | **Japanese** | Household watches English audio together; EN is also translation source if JA unavailable |
| **Japanese** | **English** | English-speaking partner follows Japanese audio |
| **Neither English nor Japanese** | **Both Japanese and English** | Household needs both; dual subtitle playback is already solved in Jellyfin |
| **Unknown / unlabeled** | **Verify audio and existing text language first** | Do not spend quota or GPU on an unproven missing-language assumption |

If the target language already has a usable track, **do not create a second acquisition task**. An existing track with a known timing problem gets a **repair task instead of a replacement task**. The policy extends across movies and episodes alike.

## Proven baseline; do not rescan out of habit

Owner ran complete EN/JA matrix on **2026-11-06**. Private source:
`~/bruiser-pilot/coverage-audits/subtitle-matrix-20261106T015513Z.json`

**12,386** media entries: **522 both EN+JA**, **2,563 EN-only**, **41 JA-only**, **8,336 neither**, **924 uncertain**. Independent detected totals **3,112 English**, **572 Japanese**, with some uncertain-category overlap. Previous verification found **2,270** true embedded EN streams, **265** stale Jellyfin claims, **15** unresolved external Jellyfin EN tracks, **675** unlabeled sidecars. These are the authoritative baseline until new files/sidecars are actually added. Treat the EN-only category as the immediate *potential* translation-source pool, not automatically 2,563 ready-to-run GPU jobs.

## Priority among eligible titles and service boundaries

- **Maximize successful new coverage per scarce download**, not fixed 75/25 category quotas. Existing staged/recoverable candidates first, then strong saved OpenSubtitles matches, then newly searched credible candidates. Preserve the provider account's actual allowance and reset.
- Horror/drama movies and *The X-Files* / *It's Always Sunny in Philadelphia* are **soft household preferences** only; they do **not** exclude American Dad, other shows or films. The earlier special American Dad S08 English-provider preference is obsolete, and the ongoing/finished PLaMo batch is separate. Do not accidentally redo accepted Japanese translations.
- Source **Japanese** first for English-speaking media. When source Japanese cannot be found and clean English exists, schedule actual **GPU translation fallback** when the dedicated GPU queue is enabled. For Japanese-language media, source English; for other languages, acquire both. Don't let EN-only media exhaust the download quota if a cached JA candidate can cheaply increase coverage.
- Existing Japanese source service, OpenSubtitles quota and FFsubsync publication logic remain **independent** from the queue until a deliberate, tested integration. The new queue's priorities do **not** silently replace the old deployed 75/25 nightly scheduler. This gap is a **specific implementation task**, not reason to re-debate priorities.

## Implementation and handoff — as of Nov 6

- Code: `tools/bruiser_coverage_queue.py`. Private SQLite state: `~/bruiser-pilot/coverage-queue/coverage.sqlite3`. It imports the existing private matrix (no scan), uses read-only cached Japanese searches/staging, creates per-language actions and retains held/pending progress across reimport. A new source snapshot retires tasks when a subtitle is actually present.
- Timing rescue: `flag-timing --jellyfin-id ID --language en|ja --reason TEXT` creates a highest-priority **`repair_existing_timing`** task without changing subtitle media. The FFsubsync code supports bounded adjustment and provenance, but the queue itself does not yet autonomously detect or perform repair.
- GPU: `validate_english_for_ja_fallback` and `recover_english_for_ja_fallback` are **planning/handoff actions**, not operational model dispatch. Local PLaMo 8B is already validated on American Dad by household viewing; extending to arbitrary titles requires proper source/input guards, not a new model competition.
- Completion: a `pending` / `held` / `candidate_found` / `ready_for_translation` queue state is trackable; **only a real new subtitle in a later verified matrix can retire a completed acquisition task**. Never allow a status string to count as coverage.
- Next explicit development step: **connect the coverage queue to OpenSubtitles acquisition ordering**, replacing arbitrary category quotas safely while retaining provider result caching, identity validation, sync repair, quotas, no-overwrite safeguards and one daily job. Test with a small bounded provider window, measure *published new distinct titles*. Then develop the opt-in GPU fallback dispatch from verified English sources, with temperature/power/load safeguards and resumable checkpoints.

## Permanent development rule

Do not repeat a full library audit or expensive 40-title extraction sample just to restart a conversation. Read this policy, the verified inventory documentation and existing private queue status. Only collect a narrow diagnostic for an actual known blocker, without asking the owner to repeat decisions already codified here. If an implementation is merely committed to GitHub, say **NOT DEPLOYED** until the host output confirms it.
