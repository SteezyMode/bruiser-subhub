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

## Proven provider gate root cause and preferred setup (2026-11-04)

The actual running Sublarr \`/api/v1/providers/health\` reports both
\`opensubtitlescom_subliminal\` and \`opensubtitles_subliminal\` as
initialized/healthy **but blocked with \`no_pool_key\`**. The native
\`opensubtitles\`, \`subdl\`, and \`jimaku\` providers are not initialized.
\`subf2m\` has gate \`ok\` but scored only a Smile 2 title-only match.

A read-only check of \`config_entries\` and the alternate adapter's pool
reported no stored OpenSubtitles key, username, password, or pool rows. No
credentials were created and no settings were modified.

### Native provider is the recommended route

- Use Sublarr's **native** \`opensubtitles\` provider, not the two
  Subliminal wrappers, for the first real production acquisition pilot.
- Its implementation (Sublarr 1.18.0,
  \`backend/providers/opensubtitles.py\`) requires **only**
  \`opensubtitles_api_key\` to initialize. Username/password are optional.
- The production budget gate explicitly allows a provider with no pool rows
  when its required credential is present in the active Settings object
  (\`_provider_credentials_configured\`). Thus, saving a genuine API key
  through Sublarr Settings -> Providers / API Keys should be enough for
  normal searches; **no fake pool row is needed**.
- A personal OpenSubtitles developer API key generally requires an
  OpenSubtitles.com account to issue it. This is one optional third-party
  account, not a demand for separate accounts for the underlying libraries.
- The existing \`subhub_v2_pool_repair.py\` is only a cautious helper for the
  **alternate** \`opensubtitlescom_subliminal\` adapter, which requires
  API key, username, and password. Do not use it as the normal onboarding
  route or interpret its three missing fields as requirements for native.
- Keep \`provider_budget_enabled=True\`, scan scheduling off,
  \`wanted_auto_translate=False\`, and publication create-only.
  Consider disabling subtitle upgrades before any automatic operation.

### Accountless evaluation only

OpenSubtitles currently documents limited anonymous REST downloads (a
client application still needs a valid application API key). A third-party
CLI, \`opensubs-cli\`, embeds its own app key and offers approximately
five unauthenticated downloads, but this would add another runtime tool and
is **not** approved as a production SubHub dependency. Use only as an
isolated scratch pilot if needed; never install it over the working host
stack or let it write next to source media. Do not circumvent provider quotas.

Next verification once the native API key is saved: health gate must be
\`ok\`; search the exact Smile 2 video and a real Sunny video through
Sublarr's own enriched Wanted query builder, then fetch at most one
reasonable JA candidate into isolated scratch storage for provenance,
coverage and constant-offset sync review. Nothing should auto-publish.
