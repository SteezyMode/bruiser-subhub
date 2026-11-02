# Context Engine 008 — reusable local subtitle context for any series or movie

**Status 2026-11-02: reusable context extraction and caching code is implemented and offline-tested; NOT yet wired into live SubHub or the still-to-be-built American Dad full-episode canary.** This is the real code at `tools/context_engine_008.py`, not just a roadmap paragraph.

## Why this exists

The user will eventually point Bruiser at a ~6 TB home library and should NOT write a manual show bible for every series. The first priority is producing watchable Japanese subtitle tracks, not building a TV-lore researcher. The primary gain shown by earlier translation experiments was avoiding English cue-by-cue context loss; a reusable series note helps resolve recurrent names/aliases and voice, but is *optional advisory support*.

## Implemented behavior

1. `scan(ROOTS)` finds existing **explicitly English-tagged** `.en.srt`, `.eng.srt`, `.english.srt` files. Infers **SxxEyy** or **NxNN** episode IDs from filenames, or identifies standalone movies. Supports Unicode series titles. Scan does not open movies, Japanese sidecars or modify anything.
2. `cached_context('series', title, first_3_episodes)` deterministically samples **a few short consecutive English subtitle excerpts** spread across up to 3 episodes, generates up to 8 short advisory notes each under `names`, `terms`, `notes`, `caveats` via **local Ollama** (`gemma4:e4b-it-qat`) with JSON output and conservative anti-hallucination instructions. Saves *one* create-only private file under `~/bruiser-pilot/context-cache/series/<series>.json`. A previously cached bible is reused, not regenerated for every episode. Context is explicitly `auto_unverified`; source dialogue always wins.
3. `cached_context('title', title, [english_SRT])` creates a small context note for a **single movie or episode**. Cache filenames include the English source SHA-256 prefix so source changes never reuse stale notes. Standalone films do not require series bibles.
4. `cue_context(rows, i)` provides the preceding 4 English cues, the CURRENT cue and following 4 English cues, **without future Japanese**, permitting models to resolve referents/jokes while emitting only the current translated subtitle.
5. `override_note(profile)` reads separately managed `context-cache/manual/<series>.json` corrections in the same compact schema. The model generator never creates/overwrites these files. Profile support is optional; households need not edit or approve show bibles.

## Direct developer/owner usage (the tool is not a translation launcher)

From the repository checkout on the same machine that can read subtitle files:

```bash
python3 tools/context_engine_008.py scan /path/to/your/series /path/to/your/movies
python3 tools/context_engine_008.py series 'American Dad' /path/to/your/series
python3 tools/context_engine_008.py title --srt '/path/to/Movie.en.srt'
```

Calling `scan` is read-only and does not invoke a model. Calling `series` or `title` requests one **local Ollama context-generation** pass only if the private cache is not already populated. It does NOT translate a title, touch source media, publish SRTs or modify a queue. No external API, web metadata or paid tool required.

## Important not-yet-built integrations

- **English subtitle intake:** many owner videos currently have embedded English text rather than `.en.srt` sidecars, and many have NO English source track. Add source discovery/extraction in a later catalog layer; never assume automatic context covers 6TB today. The engine intentionally handles already available English SRT paths and has no built-in network subtitle downloader.
- **Automatic orchestration:** the live SubHub worker must eventually invoke the correct series + episode/movie cache and pass `cue_context` to a translator. It is NOT integrated today. Do this first in a separate five-episode **American Dad** canary, preserving approved Japanese subtitles and no live database mutation.
- **Context updates:** a bible is cached until explicitly updated. Longer-running library software can periodically propose a new *versioned* bible from newly encountered episodes, keeping manually corrected overrides authoritative. Never silently rewrite an old cache while subtitle jobs are running.
- **Series grouping:** filename SxxEyy and directory heuristics are useful but can be ambiguous. At library scale prefer authoritative Jellyfin series/episode IDs and explicit English subtitle source metadata, falling back to file heuristics only if metadata is missing.
- **Safety:** subtitle text is untrusted data, potential model hallucinations are tagged unverified, and wrong or missing context must never block translating original dialogue. Every context artifact should have source fingerprints/model ID for reproducibility. Existing Japanese/editorial tracks are always out of scope.

## Stop condition

Don't build a franchise-research agent. Once the American Dad pilot produces several watchable episodes, reuse this generic system for another series/movie. Fix recurring context errors only when real viewing warrants it. Prioritize English source intake and reliable create-only publication over advanced lore research.
