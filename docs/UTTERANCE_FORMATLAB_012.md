# SubHub format lab v012 — small, paired, same-model output-format experiment

**Scope:** 24 frozen real American Dad utterances from S19E10, S19E11 and S19E12. This is a SCRATCH EXPERIMENT, not a new subtitle release, production feature, or model tournament. Actual completion and Japanese quality have **not** yet been measured on the user's host.

## Why

The real v011r1 recovery archive contains 1,189 verified, aligned cues, but bilingual quality remains approximately 5.5–6/10 and mixed-script/grouped translation was very unreliable. Out of 370 newly handled units in that recovery, only 8 generated a usable multi-cue result; the other 362 fell back to isolated cues. The previous v011 diagnostic recorded 51 model length caps and six JA/speaker failures in 57 failed attempts. It does NOT establish whether verbose prompting, forced JSON format, or the underlying model's ability to track multiple cue IDs causes the cap.

## Fair and deliberately small comparison

A deterministic, immutable source selection chooses **8 utterances per episode** (4 original v011 multi-cue groups with saved failed attempts, 4 that were never attempted). Twelve examples stress the original failure mode; twelve test previously untouched groups. All source text remains on the private OptiPlex until deliberately exported for review. This is not a representative sample of the whole library.

For EVERY utterance, compare these two formats, using the **same tuned Gemma E4B digest**:

- JSON arm: small, identical semantic prompt + exact JSON cue-ID mapping, Ollama format=json.
- Numbered-line arm: identical semantic prompt + exact one-line ID | Japanese mapping, no JSON mode.

Both arms use temperature 0, 4096 context, think false, **450 completion tokens**, same source cues, same series name hints, no later source cues outside the utterance. The ordering alternates across utterances to reduce order effects. One call per mode per utterance, **48 total bounded model calls**. No model sweep or additional 1,189-cue experiment.

The lab records per-call validation success/failure, length cap, output token counts, and exact returned Japanese ONLY in private scratch files. Strict validators demand matching cue IDs, valid Japanese, no severe density, no obvious future-Japanese copying or substantial adjacent duplication. No heuristic can certify intended meaning. No retries are made for a completed attempt; rerunning skips completed successful and failed attempts. Interrupted runs resume only missing format calls.

The lab's scratch state is under ~/bruiser-pilot/utterance-formatlab-012 and its code under ~/bruiser-pilot/utterance-formatlab-012-code. It verifies the frozen original v011 pipeline/model/profile hashes and English source SHA before selecting or calling the model. It uses existing model-residency preflight and subtitle locks. It NEVER stages original frozen v011 modules, alters existing translations, publishes any JA media sidecars, restarts services, writes to live worker/SQLite, or changes source videos.

## On MacBook, after merge

    cd ~/Downloads/bruiser-subhub-repo
    git pull --ff-only
    bash tools/run_utterance_formatlab_012.sh optiplex@100.121.156.34

This runs the full synthetic offline regression suite, stages ONLY new format-lab code, freezes 24 private source utterances on the host, runs at most 48 calls with equal budgets and prints separate summary counts for formerly failed and never-attempted groups. Log appends to ~/Downloads/american-dad-formatlab-012.log.

**Important:** If fewer than 48 calls are logged, rerunning the **identical command** safely resumes the remaining attempts. A zero exit code is not a semantic-quality pass. No episode is translated or published by this lab.

## Private paired quality comparison after exactly 48 attempted responses

    cd ~/Downloads/bruiser-subhub-repo
    bash tools/collect_utterance_formatlab_012.sh optiplex@100.121.156.34

This read-only SSH export creates a private tar.gz in Mac Downloads containing 24 EN utterances, the existing published JA baseline for those exact cue IDs, both experimental Japanese outputs when valid, format error reasons and inference token counts. The export checks frozen English and original recovery JA timecode alignment. Upload privately to ChatGPT. No English/Japanese dialogue is committed to public GitHub.

The next decision is based on **paired** counts of successful formatting and human bilingual semantic review for the same 24 utterances. Even if numbered output has superior reliability, it should not be deployed until it also demonstrates a useful semantic quality gain. If both formats fail similarly, investigate the compact multi-cue prompt/model behavior rather than rewriting the whole library. Avoid promising Hulu-level localization from a mechanical format result.
