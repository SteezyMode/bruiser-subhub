# Japanese-first SubHub: acquisition, safe synchronization, quality screening, and slow fallback
**Research date: November 5, 2026. STATUS: design/evidence only. NO production configuration, media, model, API keys or timers changed.**

Read first: [STOP decision / repeated-model-test audit](TRANSLATION_RD_STOP_DECISION_2026-11-05.md) and [November 4 native provider gate investigation](JAPANESE_FIRST_ACQUISITION_AND_SYNC.md).

## Product goal and non-negotiable order

**Find verified original Japanese → validate source/release → synchronize safely → check mechanical/content risk → create-only reviewed sidecar → if no acceptable result, leave as 'missing Japanese' or queue clearly labeled slower local draft.**

Never count 'downloaded JA' as 'good human localization'; never convert a low-confidence AI-origin subtitle into 'verified original' by renaming it. Do not translate all 13,199 media entries because one discovery source failed.

No automatic removal/upgrades to existing curated JA. Existing BigDisk archive storage is not a drive to clean up, and read-only inventory is fine. No new translation prompt experimentation on currently installed E4B.

## Existing infrastructure and known blocker

The OptiPlex already has a Sublarr 1.18.0 pilot in standalone mode and four core Movies/TV roots registered but scanning-disabled (as of the 2026-11-04 owner inspection). Two legacy Subliminal OpenSubtitles adapters were initialized/healthy but provider-budget-blocked by `no_pool_key`; native `opensubtitles`, `subdl`, `jimaku` were **not initialized**. No native OpenSubtitles API key detected in active settings. No evidence that a full-Japanese-source yield survey has run on actual titles.

The first pilot should use **native OpenSubtitles** (key required; credentials must stay in Sublarr settings/private secrets), not bypass the provider-budget lock or add fake pool keys. Then test SubDL (free API key), optionally Jimaku (anime-oriented). Do not collect user API secrets in public GitHub or conversation logs.

Sources: https://sublarr.de/docs/user-guide/settings/providers/ and https://sublarr.de/docs/getting-started/onboarding/ and prior [actual host diagnosis](JAPANESE_FIRST_ACQUISITION_AND_SYNC.md).

## Source strategy

| Source | Where useful | Caveat / production status |
| --- | --- | --- |
| **Already embedded Japanese** in actual MKV/MP4, including PGS/ASS, or existing sidecar | Highest-priority, exact media version; often no download or sync needed | Confirm full dialogue vs forced/signs-only; do NOT treat previous Bruiser AI tracks as human originals; PGS may be image-based and Jellyfin client handling varies |
| **OpenSubtitles.com** REST | Main general movie/TV index; many release and language variants | Free developer key + account, limited quota, variable Japanese availability; scoring & exact-file match more important than provider-wide size |
| **SubDL** | Parallel cross-check for general movies/TV, title/IMDb/TMDB and release search | Free key, quotas; catalog includes AI translator product, so *provider presence is not a human-authorship guarantee*. Use existing Sublarr adapter, don't build a separate scraper |
| **Jimaku** | Japanese anime and selected Japanese TV/caption releases | Anime-biased, should NOT be assumed high-yield for US horror movies/American Dad. API token |
| **Kitsunekko** | Niche Japanese-script caption source | Specialized and release matching can be tricky; use only after a confirmed real title match |
| **AnimeTosho / SubsDump** | Optional further provider coverage for anime/fansub subtitles | English fansubs of Japanese audio are not equivalent to Japanese dialogue captions; verify actual JA language, correct season/episode, full text |
| **Owned existing subtitle/caption source, e.g. personally available disc tracks** | May be higher quality; exact-edition sync is best | Cannot assume access; respect copyright/usage rights; OCR PGS only when necessary for delivery |

Other multi-provider packages (Bazarr) share many upstream sources, and Bazarr traditionally expects Sonarr/Radarr; replacing existing Sublarr is NOT justified before measuring retrieval with its native adapters. No site-wide mass scraping, account/rate-limit bypass, or streaming-platform subtitle extraction.

Official docs: https://sublarr.de/docs/user-guide/settings/providers/ ; https://subdl.com/api-doc ; https://wiki.bazarr.media/Additional-Configuration/Settings/Providers/

**Critical unknown:** *What fraction of this specific US-heavy movie/TV library is recoverable as good Japanese originals?* No honest estimate is possible before a real pilot. Japanese providers often focus on Japanese-origin anime/TV, not Hollywood horror. A large general-language catalog is not equivalent to dense Japanese coverage.

## Frozen initial discovery pilot (no publication)

1. **Read-only inventory:** use Jellyfin/Sublarr to locate 50 representative missing-Japanese titles from verified local video paths: for instance 20 horror/live-action films, 20 Western TV episodes including American Dad, and 10 assorted existing genres. Skip titles with real Japanese originals. Record English-audio status, existing JA embedded/sidecar/AI draft, precise release metadata.
2. **Enable only providers needed for pilot:** native OpenSubtitles first, then SubDL; Jimaku only where genre appropriate, Kitsunekko/niche providers where relevant. Confirm per-provider health **and actual downloadable candidate**, not just 'initialized'. Keep existing scanner auto-translate=false, upgrades=false, scheduling=off, source paths immutable.
3. **Search once per title under provider limits, using enriched identity** (movie title + year/IMDb/TMDB; TV series, season, episode; available release group and video hash). Deduplicate results; avoid same filename from multiple scraped mirrors counting as distinct sources.
4. **Download candidate into private scratch only**, not alongside real video. Hash and preserve byte-identical original; scan container/encoding, Japanese script proportion (with short foreign dialogue exceptions), cues, time span, coverage (full dialogue vs signs/forced), language mismatch, density, wrong-title/episode metadata, uploader/credit and known AI-origin marker. Subtitle-file match confidence **is NOT Japanese fluency or 'human translation' confidence**.
5. **Timings:** Prefer already-correct Japanese; otherwise run `ffsubsync` first against audio or a verified well-timed source subtitle, then examine offset/framerate and early/middle/late anchor checks; where warranted use `alass` for multiple breaks. An algorithmic 'success' is not authority to overwrite; original and proposed corrected SRT/ASS stay scratch-only until confidence gate. In particular user reports occasional leading TV intro, not routine ad-splice patterns: prefer conservative constant shifts; hold complex edits.
6. **Quality:** classify `probable-original`, `AI-marked`, `unknown-origin`, `wrong/partial`, `timing-held`, `review-needed`. Do not claim to detect old machine translations reliably by text alone. Favor credible uploader/source records, non-AI labeling, consistency and actual short Japanese review. Optional Sublarr AI quality sample (~30 cues) is **advisory, not auto-publisher or provenance proof**; do not spend another expensive model pass screening a large library by default.
7. **Report counts** split by category and provider, not one 'hit rate': titles searched; any JA result; plausible full-dialogue file; mechanically clean; sync confidently corrected; timing held; AI-marked/suspect; usable after spot review. On ~50 representative items this informs realistic scale, limits, provider account priorities, and whether translating rare missing cases is worthwhile.
8. **Only then** enable conservative nightly bounded searching within provider quotas and read-only-first staged publishing. Retain `missing/needs-review` rather than forcing a bad substitute. No unknown release 'upgrades' of already curated tracks.

Relevant official tools: https://sublarr.de/docs/user-guide/sync-engines/ ; https://ffsubsync.readthedocs.io/en/latest/usage.html ; https://ffsubsync.readthedocs.io/en/latest/advanced.html ; https://github.com/kaegi/alass ; https://sublarr.de/docs/user-guide/subtitle-health/

## Source quality and sync gate details

**Source identity:** file/release hash when available; title/year or series/season/episode metadata must not contradict. 'Hash match' means exact file association for that provider, **not** verified translation. Signs-only/forced, single-scene and mixed-language partial files must not satisfy full-dialogue demand. Downloads should not turn back into repeated queries if clearly no JA source exists.

**Timing:** `ffsubsync` uses language-agnostic audio VAD or reference subtitle on/off timing; can correct shift and frame-rate scaling. Sublarr 1.18 documents ffsubsync bundled, optional alass (the latter is **not installed by default**), sanity-threshold screening and a recorded engine fallback chain. `alass` can also handle multiple offsets. Neither guarantees semantic equivalence or handles alternate cuts and deleted scenes safely. Refuse any path that requires inventing words/new captions to bridge missing content.

**Health:** Sublarr's existing Subtitle Health reports format, encoding, leaked escape sequences, language mismatch, overlapping/broken timing, excessive CPS, and optional advisory AI text-quality check. Its optional default sampled-cue limit is 30 and is off by default: **no model can reliably prove a caption is old machine translation or good human Japanese by reading 30 unrelated lines**. Screener can flag implausible script, verbatim ASCII, repeating placeholders, wildly wrong density and obvious nonsense, but not certify idioms/plot dialogue.

**Machine-translation score:** Sublarr has a disabled-by-default machine-translation penalty for results flagged MT confidence ≥80. That flag helps triage but does not establish how the candidate was made; never assume all unflagged sources are human.

**Provisional system:** Sublarr already has an opt-in "Keep seeking the original" state for its own machine translations, daily `mt_reseek` (no repeated inference), and **Notify me** vs **Replace automatically** behavior. Choose **Notify me**, not auto-replace, especially for previously polished/existing tracks. This is optional; existing dedicated Bruiser drafts and old outputs are not necessarily registered as Sublarr provisional items. Don't silently migrate them.

Official sources:
- https://sublarr.de/docs/user-guide/settings/subtitles-scoring/
- https://sublarr.de/docs/user-guide/subtitle-health/
- https://sublarr.de/docs/user-guide/provisional-translation/
- https://sublarr.de/docs/user-guide/sync-engines/

## Slower local translation fallback: worthwhile ONLY after acquisition yield established

If the discovery+sync pilot shows many titles acquired without translation, slower inference is commercially/personal-use practical for the remainder. **This changes acceptable throughput, NOT the evidence needed to claim quality.**

- Current **E4B** installed/pinned `9ccfc3b07081` stays as a clearly marked rough draft fallback; no new prompt/quantization/context microtuning.
- **PLaMo 3 Translate** released by Preferred Networks **today 2026-11-05**, official model-native English→Japanese options at 2B, 8B, 31B and Japanese context/terminology. Evaluate 2B and potentially 8B in a *single* prespecified short real-scene comparison only if needed, with vendor-native prompt, no publication and Japanese-speaker quality decision. 2B Q4_K_M ~1.81GB; 8B Q4_K_M ~5.28GB on a 6GB RTX3050 leaves insufficient margin for guaranteed full residency with KV/cache/concurrent services; CPU offload on 32GB system RAM is reasonable to try but slow. Do NOT claim 8B will fit on GPU. 31B Q4 uses substantial system RAM and competes with Jellyfin, Wolf and other server services; don't default to 31B or background launch it. No assurance that any PLaMo version makes an 8/10 movie track; author benchmarks on general Japanese translation are not native horror-comedy watchability tests.
- Other CAT/Index/Google/HY candidates were already thoroughly technically tried in 006; do not call them 'new' or rebenchmark without finishing existing viewer evidence.
- Prefer `one selected title overnight` if running a bigger model; lower scheduling priority, temp/power and memory limits, resumable checkpoint, no interruptions to interactive games/music/Jellyfin. If it isn't better in blinded review, **STOP** rather than tune it endlessly.

Official release/license: https://www.preferred.jp/ja/news/pr20261105 and https://huggingface.co/pfnet/plamo-3-translate-2b . PLaMo Community License permits eligible personal/small business use; product distribution must check exact license. **No model was downloaded or configured from this document.**

## Architecture worth keeping

Sublarr = managed provider, matching, sync, health, review UI; Jellyfin = existing media/metadata; Bruiser SubHub = optional independent metadata/cache/queuing and fallback source-to-JA machine drafts only. Do not recreate Bazarr or overhaul service before the 50-title pilot.

A useful eventual UI has explicit per-title states: `existing-good-JA`, `found-review`, `sync-review`, `provider-miss`, `AI-draft`, `source-missing`, `human-approved`. No fake '95% quality' indicator. All originals and editorial sidecars protected by create-only versioning; metadata-only counts distinguish source access, timings and linguistic review.

**GO/NO-GO:** If native JA source yield is thin on this actual US-heavy library, say so and shift to selected slower translation/editing; do not promise 'great swathes' without counts. If provider yield is high with acceptable syncing and quality, then prioritize ongoing source search and use slow translation only for misses. Either outcome should reduce wasted cycles.
