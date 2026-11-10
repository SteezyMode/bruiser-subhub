# Bruiser SubHub

**The entire purpose:** give one household good, natural, correctly timed Japanese subtitles for the movies and TV it already watches in Jellyfin. This is not a startup, a software product, a showcase, or a competition to invent a subtitle manager. A subtitle that actually plays well is success. A commit, benchmark, downloaded candidate or attractive dashboard is not.

## Read these, in this order

1. [GOAL.md](GOAL.md) — what the owner actually needs.
2. [docs/CURRENT_STATE.md](docs/CURRENT_STATE.md) — the current evidence, decision, and next real test.
3. [docs/SUBHUB_CORRECTION_FIRST_POLICY_2026-11-10.md](docs/SUBHUB_CORRECTION_FIRST_POLICY_2026-11-10.md) — sourcing/reference/repair/publication rules.
4. [AGENTS.md](AGENTS.md) — rules for the next development session.

Other date-stamped documents, experiments, project handoffs, and GitHub issues are **historical evidence**, not competing current instructions. Do not infer live host state from this repository. Git history retains older versions of this README and instructions.

## Operating approach

- **Reuse existing software first.** We have Jellyfin, Sublarr, ffsubsync and working custom utilities. Inspect configuration and capabilities, then test on real files before duplicating them in code. Evaluate Bazarr or another tool if its actual prerequisites and outcomes justify the change.
- **The custom dashboard is presently the owner's most useful interface, but still inadequate.** That is an observation, **not** a mandate to keep it or replace it. Determine which tool or small combination best handles the library. Do not build or migrate by ideology.
- Search, retain, identify and repair **human-authored Japanese subtitles** before local AI translation. Never treat a search miss or failed automatic sync as proof that Japanese is unavailable.
- Inspect existing embedded/sidecar **native-language text** early; proactively obtain and cache a matching reference when useful. That can help release matching, timing and eventual translation. **Missing native/English subtitles never block Japanese search, reuse or repair.** Do not waste daily provider downloads sourcing references for the entire library before targeting Japanese.
- Prefer existing sync/repair engines; test **beginning, middle and end against dialogue**. Different-language cue starts are not a reliable automatic judge. Preserve original subtitle bytes and preview corrections before reversible promotion.
- Use existing PLaMo translation as a **last resort**, after meaningful sourcing/recovery and only with verified source dialogue. Do not run new model tournaments or add an AI critic by default.
- Preserve existing media folders, working subtitle sidecars, credentials, staging, checkpoints, thermal protections and live services. **No automatic overwrite.** Never conflate committed GitHub code with host deployment or Jellyfin playback acceptance.

## Current immediate work

Fix the observable cold-open timing problem in *It's Always Sunny in Philadelphia* S01E04 using a **non-destructive preview** and actual dialogue checks; compare S01E05 as control. Both episodes already have embedded English references. Our November 10 timestamp-only regional audits were inconclusive, so stop creating more statistical gates. See [current state](docs/CURRENT_STATE.md) for next steps and backlog.

Keep dashboard changes subordinate to an actual subtitle workflow failure. The default question is: **what will get us the next verified, watchable Japanese subtitle with the least maintenance?**
