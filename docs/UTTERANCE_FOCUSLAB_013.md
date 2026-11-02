# SubHub FocusLab 013 — Contextual meaning, one timed cue per model call

**November 2, 2026. Experiment coded and offline-tested; NO actual v013 host inference or editorial quality result yet.** Uses the SAME pinned tuned Gemma E4B on OptiPlex, not a model tournament.

## Grounded v012 failure evidence

The owner provided a private read-only forensic archive of all 32 failed v012 calls (18 JSON + 14 numbered). JSON: **18/18 hit the 450 output-token cap**, mostly returning no visible text. Numbered: 11 mapping/count errors, two duplicated-adjacent-meaning outputs, one invalid numbered format.

**Critical root-cause observation:** Of 11 numbered mapping/count failures, **10 were a single Japanese sentence for an English multi-cue utterance** (the remaining three-cue result contained only two numbered lines). Nine of the ten single-sentence responses correspond to **exactly two English cues**; the last had three cues. This is not just a parser refusing good numbers: the translation model tends to translate the *whole thought* without respecting the timed English cue boundaries. It would be unsafe to split its generated Japanese on punctuation/length as if semantic time alignment were preserved.

The v012 model itself could produce coherent whole-utterance Japanese under these conditions, so the next small test is **meaning context, not grouped output formatting**.

## v013 experiment — deliberately bounded

Deterministically select precisely those **9 previously failed two-cue groups** with a single coherent non-numbered Japanese sentence saved in v012 private scratch. Reuse each original **whole-utterance Japanese output verbatim as ADVISORY CONTEXT**. For each of its 2 original English cues, call the pinned E4B model **once** to translate that *single focus cue*, while showing the other English cue and whole utterance as context. Explicitly prohibit information introduced only in the other cue. English stays authoritative; model is instructed to preserve idioms, joke, pragmatics, speaker intent and negation. Two independent results per utterance, **18 model calls maximum** with the existing single-cue default 320-token cap. No new whole-utterance inference.

Original source SRT IDs/timings and accepted Japanese are frozen and never written. Old v011/v012 experiment checkpoints, source videos, live Subtitle worker, Jellyfin and production SQLite remain untouched. v013 writes only **a separately versioned scratch manifest and 18 create-only one-cue response records** under ~/bruiser-pilot/utterance-focuslab-013, with its own code fingerprint. It validates original v011/v012 frozen model, code, source hashes and 1,189-cue recovered JA baseline hash. Real model calls are protected by existing two subtitle worker locks and the E4B resident-model preflight. Failed response records also persist, and reruns do not redo already attempted calls.

No output can publish a media sidecar or modify any previous Japanese. Mechanical per-cue validators guard against malformed Japanese/speaker and excessive density. The collector additionally reports within-utterance duplicate/leakage flags, but **no automatic QA can certify semantic correctness**.

## One MacBook command after PR merge

    cd ~/Downloads/bruiser-subhub-repo
    git pull --ff-only
    bash tools/run_utterance_focuslab_013.sh optiplex@100.121.156.34

The script runs all synthetic offline tests, stages ONLY the new v013 lab module in its own host folder, freezes 9 known private historical v012 responses, and makes up to 18 calls. Log: ~/Downloads/american-dad-focuslab-013.log. A repeat of the same command resumes missing attempts; it will not retranslate a checkpointed cue. Check FOCUSLAB_SUMMARY for completed_calls=18 (not a semantic pass).

Then privately export an EN/JA paired comparison, without new inference:

    cd ~/Downloads/bruiser-subhub-repo
    bash tools/collect_utterance_focuslab_013.sh optiplex@100.121.156.34

Upload the resulting PRIVATE .tar.gz here. It contains each original 2-cue English context, *existing published JA baseline*, the historical one-line v012 whole-utterance Japanese, two new focus-cue outputs and mechanical risk indicators. Compare the THREE choices on meaning accuracy, original cue time boundaries, repetition, recurring names and readability. If one-cue-with-utterance-context improves paired semantic fidelity, develop a production-quality context strategy; if it doesn't, stop format experimentation and focus on better semantic review/translation methods.

No copyrighted subtitle dialogue, user media path, or private raw Japanese outputs may go to the public repository.
