# SubHub v2 — Japanese-first acquisition and intro-offset safety

## Observations (November 4, 2026)

- Japanese profile already exists; the four main movie/TV folders are registered but scanning-disabled.
- Two Subliminal OpenSubtitles adapters are initialized/healthy. Native OpenSubtitles, SubDL, and Jimaku are not initialized.
- Provider-test catalog searches returned abundant weak or unrelated records, and a promising but unverified `Its.Always.Sunny.in.Philadelphia.S01E01.WEB-DL.DSNP.ja.srt` label.
- The production `POST /api/v1/providers/search` returned one `subf2m` Smile 2 result (title match only, score 60), and no Sunny S01E01 results. That route creates a sparse `VideoQuery` that does not fill year, release metadata or file hash. It is not a reliable exact-file matching benchmark.

## Policy: source, quality and timing are separate gates

1. Verify correct film/year or series/season/episode and prefer strongly matched releases. A score or matching title is not proof of a human-quality Japanese translation.
2. Evaluate provenance and completeness. Forced/signs-only tracks do not replace full dialogue. Keep existing Japanese and English subtitle files intact.
3. For this household library, a few TV rips have a leading station intro, but **no known in-episode commercial breaks**. Focus on **constant-offset** synchronization first; do not construct a complex ad-break or multi-cut correction engine.
4. Use an actual-local-video audio/speech alignment tool (e.g. `ffsubsync`) to propose a constant offset. Check the resulting alignment at early, middle and late points. Only apply a highly confident correction; never guess a 15-second or 30-second standard intro length.
5. If a candidate is still mistimed or uncertain, hold rather than publish. Keep a verified English source timed to the actual file as authority for Hy-MT2 fallback; that translation must preserve cue IDs/timestamps.
6. Do **create-only** publication. No upgrading/replacing existing Japanese subtitles and no unattended library-wide searches until a narrow pilot works.

## Diagnostic

`tools/japanese_first_candidate_probe.py` runs inside sublarr-pilot and directly checks the two OpenSubtitles adapters, using a richer Smile 2 release query and separate Sunny S01E01 metadata-only query. It performs no downloads, file writes or configuration changes. It may spend provider-search quota. Hash usage is reported if supported; the probe does not claim a hash match unless the adapter provides that evidence.

The intended next stage is an isolated scratch-download comparison of one or two credible candidates, with constant-offset synchronization proposals and manual content spot checks before any automated acceptance logic is enabled.
