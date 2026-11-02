# SubHub v012 — REAL pinned E4B paired format experiment: neither grouped format passes

**Date:** 2026-11-02. **Evidence:** owner's PRIVATE complete 24-utterance archive american-dad-formatlab-012-review-20261102T101809Z.tar.gz. It contains 48 completed calls, English source, baseline Japanese and experimental Japanese accepted under the strict validator. No copyrighted dialogue or raw model responses are stored in this public document.

## Full real mechanical result (same 450 output-token cap per format)

| Category | Forced JSON | Plain numbered lines |
|---|---:|---:|
| Total attempted | 24 | 24 |
| Strictly accepted | **6 (25%)** | **10 (42%)** |
| Capped at 450 output tokens | **18** | **0** |
| Wrong cue-ID mapping or count | 0 | **11** |
| Invalid numbered-line format | 0 | **1** |
| Repeated adjacent Japanese | 0 | **2** |
| Completion tokens summed | 8,619 | 740 |
| Mean completion tokens per call | 359.1 | 30.8 |

Previously failed selection: JSON 4/12 valid, numbered 5/12. Previously unattempted selection: JSON 2/12 valid, numbered 5/12. Paired 24-group breakdown: **5 passed both**, **1 JSON-only**, **5 numbered-only**, **13 neither**. More numbered outputs pass, but this small deliberately failure-enriched set does not establish production reliability or statistically convincing superiority (exact paired sign p=0.219 for six discordant pairs).

The JSON arm uses Ollama JSON enforcement and response-format instructions, while numbered output is unconstrained with a different response-format instruction. Model, English cue set, semantic prompt, context, temperature and output-token budget were held constant. This is a format-bundle comparison, not an isolated test of one variable.

**Major evidence:** forced JSON consumed 8,619 tokens vs 740 for numbered lines; all 18 JSON failures exhausted the 450-token output cap. Constrained JSON is particularly unstable with tuned E4B on these groups. Plain numbered lines avoid the cap but often fail strict ID/cue mapping. Crucially, the existing uploaded archive omits raw unsuccessful outputs, so the actual cause of the 11 mapping/count failures is still unobserved. Do not invent a root cause until examining their preserved raw records.

## Semantic verdict: formatting alone did NOT fix translation quality

Even accepted outputs introduce high-impact issues:
- A named product is rendered as literal hardware terminology in the numbered output, worse than the baseline transliteration.
- One two-cue answer puts the following cue's audition explanation too early, leaving later text redundant.
- A dog-parade answer anticipates/repeats the parade across two cues and mistransliterates its location.
- Both accepted formats frontload the following cue's historical building reference, leaving a vague second caption.
- The context-dependent compliment "striking" is rendered as conspicuous, not attractive/impressive in the likely context.

Some simple narration and a few emotional exchanges are passable; there is no demonstrated material gain from these formatting variants over the already published recovered Japanese. The earlier full collection's approximate 5.5–6/10 text-only bilingual assessment is not revised (not a native-speaker viewing score).

**Do not deploy either grouped format into the live subtitle worker or replace the 1,189 already published Japanese cues.** Mechanical acceptance does not certify meaning or timing.

## Next precise evidence step — ZERO new inference

New read-only collector tools/collect_formatlab_failures_012.py retrieves the 48 existing private format-lab result records, verifies original source/code/model/selection identities, and exports **only failed raw model replies** and paired English context to a PRIVATE archive. Records include observed output line count, numbered IDs, JSON syntax and original category. It never calls Ollama, stages code on the host, alters checkpoints, publishes SRT sidecars, restarts services, or writes production SQLite.

MacBook command after merge:

    cd ~/Downloads/bruiser-subhub-repo
    git pull --ff-only
    bash tools/collect_formatlab_failures_012.sh optiplex@100.121.156.34

Upload that PRIVATE archive for analysis of actual malformed outputs. Determine whether lines collapse two cues, drop IDs, hallucinate formatting or are rejected by a too-strict parser. Only then implement the smallest justified corrective experiment; no other model tournament or full-episode pilot.
