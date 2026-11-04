# SubHub v2: minimum unattended pipeline (2026-11-04)

## What counts as success

Existing English-language films and episodes in Jellyfin receive a good, readable Japanese track without manual requests. Local and free; target household quality ~8/10. Existing Japanese subtitles and media are never deleted, replaced or suppressed.

## Keep only four functions

1. Existing Sublarr 1.18 for discovery, release/hash scoring, language profiles, embedded extraction, optional hearing-impaired cleanup, sync, scheduling and Jellyfin refresh. Configure HI preference to prefer-not, not require-not, to allow SDH fallback.
2. Frozen Hy-MT2 7B structured-data translator with 30-cue batches, full-GPU offload and mechanical small-batch structural recovery. It produced 731/731 cue-aligned output in the actual Descent 2 test. Do not substitute Sublarr's line-oriented generic Ollama prompt without a controlled benchmark.
3. Minimal deterministic validation: timestamps, nonempty cues, obvious foreign-script contamination, gross overlength and no accidental JA overwrite. No model-generated second-pass rewrites.
4. A narrow durable handoff between Sublarr's chosen English subtitle and the existing translator, with checkpoints on a host-mounted persistent volume. Use the existing scheduler if possible; avoid adding a parallel dashboard or database.

## Findings informing this decision

The bad 377-cue English source was much worse than the 731-cue release-matching English source. Source selection is a high-leverage quality improvement. The complete Hy-MT2 Japanese translation of the better source remains around 6.5–7/10 in text-only editorial review, below our 8/10 aspiration. Its self-reviewer proposed 17 fixes but did not reliably correct important mistakes and introduced regressions. It must not be in the automated production path.

The verified GPU layout used 5134/6144 MiB and translated 30-cue batches roughly 2.6x faster than partial offload. Keep this setup, with thermal monitoring.

Sublarr's normal post-download shell hook is bounded to 60 seconds; the curated shell operation to 30 seconds. Neither should synchronously run a lengthy translation. If a native internal job API cannot coordinate the exact existing translator, the only new component should be a small queue handoff that exits quickly.

## What may be deleted AFTER the replacement works

Old Gemma workers, HY backtranslation, speculative quality evaluators, model-voting experiments, American Dad-specific repair orchestration, duplicate scanners, arbitrary line-width repair gates, and stale timers. We can remove code, images and dead services freely after identifying real live dependencies. Retain all existing user media, Japanese translations, English sources, progress checkpoints, account secrets and backups.

## Deployment in order

A. Run tools/minimal_automation_audit.sh against the actual host. It starts existing Sublarr if stopped, reports health, non-secret configuration and available tools. It neither changes settings nor translates.

B. Configure only one pilot title. Choose English subtitle with provider scoring and prefer-not SDH; compare alignment, and clean descriptions safely. Confirm existing JA veto.

C. Implement and test the one handoff using the frozen runner with a host-mounted checkpoint folder, then deliver a separate complete JA sidecar and verify ordinary Jellyfin playback.

D. Test after overnight power-off and on one NEW title. Only then enable larger unattended queue and disable old conflicting timers/services.

## Current sources, checked 2026-11-04

- https://sublarr.de/docs/
- https://sublarr.de/docs/user-guide/translation-llm/
- https://sublarr.de/docs/user-guide/post-processing/
- https://sublarr.de/docs/user-guide/settings/subtitles-languages/
- https://sublarr.de/docs/development/architecture/

Do not imply a successful local host deployment from a GitHub commit alone.
