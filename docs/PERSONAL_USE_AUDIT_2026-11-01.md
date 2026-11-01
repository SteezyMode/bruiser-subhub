# Personal-use architecture audit — 2026-11-01

**Decision:** Optimize for the household's best **free, local English → Japanese subtitles**, not a commercially differentiated product. This audit evaluates alternatives and does not change a running translator.

## Observed pilot (historical, not live)

Last owner-reported status: 3/10 published (Primate, 28 Years Later, Obsession), Heretic 1608/1609, Birth/Rebirth 1130/1131, Hokum 1285/1286 in `needs_review` with one exhausted cue each; The Descent fully translated but `publish_hold`; Strange Darling 510/846 translating; Whistle and A Nightmare on Elm Street queued. The Descent already has separately created editorial Japanese subtitles; never replace or supersede them. Do not infer hold reason from this observation alone. HY 0 everywhere. **These counts are not translation-accuracy measures.**

## What is worth retaining

- SQLite cue-level checkpoints, bounded retries, worker lock, resource guards and source identity checks. The pilot recovered thousands of cues and published several complete films.
- Human/editorial track protection (merged PR #3), but that GitHub code was not yet confirmed deployed.
- A simple local queue and private editorial review export.

## Key code gaps to investigate, not guesses about actual failure cause

1. **No translation quality benchmark:** valid Japanese script is not evidence of correct meaning, natural register, character voice or readable subtitle compression. Real EN/JA examples should remain private.
2. **Context loss:** `service.translation_call` passes 12 source cues through a legacy prompt. Its `single_direct` fallback sees only one English line and approved-memory snippets, which can worsen isolated ambiguous dialogue. Test lookback/lookahead and scene synopsis/glossary without output identity drift.
3. **One-cue stalls:** `acceptable_ja()` requires kana or kanji. Short punctuation, numeric or unchanged-proper-name cues might therefore exhaust retries; verify real `last_error` before changing this. `diagnose_blocked.py` is read-only.
4. **Japanese readability:** `review_sampler.py` currently flags >14 Japanese characters per second, whereas Netflix's Japanese timed text guidance for dialogue uses up to 4 characters/second and 13 full-width characters per line (two lines). Do not automatically impose professional delivery limits on personal SRT, but benchmark appropriate values, line breaking, names and register.
5. **Publishing safety:** the new publisher preserves external Japanese/editorial sidecars. However it opens its final output via O_EXCL and writes directly; a process crash mid-write could leave a partial sidecar. Prefer fully durable temp write plus atomic create-only publication. Investigate existing embedded Japanese and skip translation *before* consuming GPU time, rather than only holding publishing afterward.
6. **Daily-use gap:** hardcoded Ollama model, host media roots and legacy `bruiser_auto.py`/HY imports, legacy Docker import path, limited source acquisition and installation/update lifecycle. `launch.sh` imports+starts jobs and is not an upgrade command.
7. **Dashboard naming:** `main.dashboard()` opens `Store` (which invokes SQLite WAL and CREATE IF NOT EXISTS), so it is not literally read-only at the connection layer. Low priority.

## Relevant 2026 open-source ecosystem

| Tool | Actual useful role for this household | Caveat |
|---|---|---|
| [Subtitle Edit 5.2](https://subtitleedit.github.io/subtitleedit/) | Free cross-platform Linux editor + CLI (`seconv`), OCR, timing, quality checks, batch translation; Ollama/llama.cpp advanced supports synopsis, glossary, context and structured output | Evaluate against current pipeline; do not assume its default Japanese output is better |
| [Sublarr](https://sublarr.de/docs/) | Already installed as a pilot; useful provider search, extraction/health/synchronization and standalone media discovery | Translation is optional and its developers describe it as experimental. Previous integration was unreliable for this host; avoid reverting to it as translation owner without independent test |
| [Lingarr](https://lingarr.com/) | Free automated translation, Ollama, integration with media libraries; proofreading capability added in 2026 | Another full service to operate; no evidence EN→JA performance is superior for this hardware |
| [TranslateGemma](https://blog.google/innovation-and-ai/technology/developers-tools/translategemma/) | Google 4B/12B/27B specialized translation weights released Jan 2026. 4B is an obvious 6GB-VRAM A/B candidate | 12B may require CPU offload; not established better than current Gemma 4 e4b for *these* films |
| [Ollama schema outputs](https://github.com/ollama/ollama/blob/main/docs/capabilities/structured-outputs.mdx) | Structured JSON with cue IDs to reduce malformed SRT response parsing | Validate exact cue set/timing; try on a fixed offline A/B set before changing the adapter |
| [dual-sub-jellyfin](https://github.com/seanmcbroom/dual-sub-jellyfin) / [Subpair](https://github.com/wonjoonSeol/subpair) | Existing browser-based free dual EN/JA subtitle viewing. Separate from translation | Browser extensions, not assured to work in every Jellyfin app or on every projector playback path |

## 2026 research (transfer cautiously to EN → JA)

- [TranslateGemma launch](https://blog.google/innovation-and-ai/technology/developers-tools/translategemma/), 2026-01-15: translation-specialized small model candidates.
- [Alconost EN→JA subtitle benchmark](https://alconost.com/en/blog/ai-subtitle-translation-benchmark), 2026-04-07: TranslateGemma 12B ranked first in their evaluated models but Japanese was hardest; human QA discovered errors invisible to automatic metrics. This is one vendor's evaluation of 1,002 segments across six languages, not proof for our 4B model or household clips.
- [WMT26 subtitle task findings](https://aclanthology.org/2026.wmt-main.58/): context, candidate selection, glossary, semantic validation and revision correlate with stronger outcomes, but its source/target pairs differ from EN→JA.
- [QwenSub-MT WMT26](https://aclanthology.org/2026.wmt-main.202/): contextual blocks, synopsis, previous translation memory, selective revision, timing/format constraints.
- [Netflix Japanese timed text guide](https://partnerhelp.netflixstudios.com/hc/en-us/articles/215767517-Japanese-Timed-Text-Style-Guide): a reference for concise natural subtitle conventions, not a mandatory output specification for private media.

## Priorities: decision gates, not an engineering growth roadmap

**A. Protect today's outputs:** inspect blocked cues, recover three missing cues with an explicit manual/targeted override path (never filler), and do not touch older editorial files. Wait for current worker to be idle before upgrading.

**B. A/B evidence before rebuilding:** choose a private 80–120-cue benchmark spanning horror dialogue, slang, negation, names, interruptions, ambiguous pronouns and very short cues from multiple films. Include previously human-edited subtitles as reference where exact timings align. Compare current SubHub Gemma 4 e4b, Subtitle Edit advanced with same model, and TranslateGemma 4B locally (optionally Qwen3.5 4B). Blind-rate fidelity, natural Japanese, character consistency, reading speed, invalid/missing IDs, throughput and VRAM. Keep approved memory separate; don't auto-learn from unchecked model output.

**C. Choose the simplest winner:** if Subtitle Edit or Lingarr is better, use that and reduce SubHub to a queue/watch/retention wrapper or retire it entirely. If SubHub wins, remove the legacy adapter and add a configurable worker, ingestion from existing tool APIs, and a tested atomic publisher.

**D. Household daily use:** media discovery → prefer existing good Japanese → source selection (embedded/sidecar, provider search, OCR/Whisper only when needed) → local translation → deterministic validation → optional sampled editorial review → create-only sidecar → Jellyfin refresh. Add user-facing diagnostics, tested systemd scheduling, safe install/update/rollback only after A–C.

**HY** stays optional, sampled and advisory. No compulsory back-translation and no arbitrary AI-judged publication gate.

## Audit limitations

Repository static inspection + last owner-reported status, not a fresh live OptiPlex inspection. There has been no newly executed Ollama EN→JA translation comparison or end-to-end correctness test in this audit. Current source is not a self-contained release. A merge to GitHub does not deploy.
