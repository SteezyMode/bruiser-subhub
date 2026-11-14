# Movie Japanese subtitle coverage — current owner priority (November 14, 2026)

**Purpose:** Watch the household's **non-Japanese-language movies** with natural, correctly timed Japanese subtitles. Aim for **100% coverage**; do not pretend every title will be solvable. Work **movie-wide**, not movie by movie. Episodes are outside this pass.

## Baseline: completed live Jellyfin movie census

The November 14 `movies-all` scan counted 679 movies across both movie roots, with 342 already having a Japanese subtitle and 337 without. **30 of those 337 have Japanese audio and are outside the immediate non-Japanese viewing goal**; do not waste sourcing/translation effort on them. The remaining **307 un-subtitled non-Japanese-audio movies are the practical initial backlog** (subject to correcting unknown or mislabelled audio metadata).

The census also recorded 97 missing movies with saved candidate releases, 34 with staged releases, 95 incomplete-provider-search records and 32 never-searched records. **These overlap**: independent search evidence is not an additional missing-movie count. Historical `held` (7) and `held_unchanged` (27) are outcome receipts, not distinct additional missing movies. Recompute counts after each meaningful run rather than hardcoding them.

## Locked work order

1. **Finish movie-wide provider discovery**, first for missing/no evidence and provider-incomplete titles, as provider allowances permit. Preserve the existing successful searches and candidates. Only the agreed movie-only census/sourcer is needed; no new cron/timer, source rules, or extra services. Keep its stop-on-pacing behavior and resume after the real quota window. Track actual provider participation as far as the existing APIs allow; a green provider health indicator is not definitive proof of participation.
2. **Process saved but unstaged Japanese candidates**, across all movie genres in batches. Prefer existing cached releases, then credible alternate releases, validate actual Japanese content, title/edition match and sync before create-only publication.
3. **Process staged but unpublished Japanese candidates** as groups by root cause. Run existing validated correction engines; try alternatives. No one-film patches unless a genuinely general problem is demonstrated. Preserve the original subtitle, no-overwrite policy, and sync QA.
4. **Before PLaMo**, meaningfully exhaust remaining human-sourced Japanese subtitle options, including saved review-grade hits, other provider/alternate-title searches and appropriate cached candidates. A `NONE` search, `REVIEW` metadata or a `HELD` attempt does *not* prove exhaustion.
5. **PLaMo last**, using correctly aligned English/source-language subtitle text, followed by Japanese QA and synchronization. A PLaMo job only counts as covered after the Japanese subtitle is published and actually selectable in Jellyfin. Unsolvable items remain counted as missing with a concrete reason; never relabel them covered to hit a number.

## Non-negotiable operating rules

- **Keep moving**: one difficult release, `HELD`, or inaccessible provider must not block other movies. Save the reason and next action, continue with other eligible films.
- **A hold is an attempt outcome** (e.g., malformed bytes, identity mismatch, unverified sync, quota), never a permanent film status. `held_unchanged` means only that identical evidence/code was not retried.
- **Review means weak candidate metadata**, not a manual task for the user and not proof the subtitle is garbage.
- **Measure outcomes, not attempts**: report total target movies, Japanese tracks actually present, missing, provider-search-evidence status, candidate availability, and real newly published tracks. Count one movie once, and never treat staged/downloaded/translated as published.
- **Avoid more infrastructure**: use the existing `tools/subhub_movie_census.py` `report`/`scan`, existing stored searches, original stage/publisher, and established PLaMo workers. No new timers, competing source services or repeated diagnostic command loops without evidence.
- **Preserve media and playback**. No overwrites, no needlessly repeated provider calls, no premature AI runs. New content remains eligible for its separate automatic processing; this movie backlog is a deliberate owner-run pass.
- **100% is the aspiration, not a deadline or license to cheat QA**. Publish broadly and reliably; accurately explain any residual shortfall.

## Next action

Provider discovery is the active phase. The 2026-11-14 movie census **already ran successfully** and saved a private per-movie CSV/JSON. Do not repeat immediately just to print a different number; the existing search pilot keeps recent incomplete entries for its ~20-hour allowance window. Resume the same bounded movie-only census **after eligible provider reset**, then use the fresh saved per-movie breakdown to select the next whole group. Don't pivot to individual subtitle repair or PLaMo yet. Code merged on GitHub is not automatically installed on the OptiPlex.
