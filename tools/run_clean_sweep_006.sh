#!/usr/bin/env bash
# Real Benchmark 006 — ONE owner-run command; do not change live SubHub.
# Fresh sealed multi-title corpus + ten frozen native model workflows.
set -euo pipefail
HOST="${1:?Usage: bash tools/run_clean_sweep_006.sh optiplex@HOST}"
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "=== LOCAL OFFLINE REGRESSION TESTS ==="
python3 -m unittest discover -p 'test_*.py' -q
echo "=== STAGING REVIEW-ONLY 006 RUNNER (NO LIVE DEPLOY) ==="
ssh "$HOST" 'mkdir -p -m 700 ~/bruiser-pilot/subhub-benchmark ~/bruiser-pilot/subhub-benchmark-006'
scp -q service.py localization_policy.py \
  tools/benchmark_localization.py tools/model_benchmark.py \
  tools/benchmark_native_subtitles.py tools/benchmark_translategemma_004.py \
  tools/analyze_model_benchmark.py tools/model_sweep_005.py \
  tools/clean_sweep_006.py \
  "$HOST:~/bruiser-pilot/subhub-benchmark/"

PY='~/bruiser-pilot/subhub-cat33-venv/bin/python'
SCRIPT='~/bruiser-pilot/subhub-benchmark/clean_sweep_006.py'
DEST="$HOME/Downloads/benchmark006-private"
mkdir -p -m 700 "$DEST"
echo "=== FREEZE UNSEEN SOURCE SCENES AND UNTOUCHED CONFIRMATION TITLE ==="
ssh "$HOST" "$PY $SCRIPT prepare" | tee "$DEST/prepare.log"

# CANDIDATE ROSTER FROZEN: each process is independent, so HF/CUDA memory
# is released before the next candidate. Runtime blocked arms do not erase
# completed model results, and all outputs remain private.
ARMS=(
  cat33 cat7
  tuned_e4b tuned_e2b
  hy7 hy18 index2
  google4 google12 generic_e4b
)
: > "$DEST/STATUS.txt"
for ARM in "${ARMS[@]}"; do
  echo "=== REAL TEST: $ARM, same frozen new English scenes ==="
  if ssh "$HOST" "$PY $SCRIPT arm '$ARM' --max-seconds 7200" \
       2>&1 | tee "$DEST/$ARM.log"; then
    printf '%s\tcomplete\n' "$ARM" >> "$DEST/STATUS.txt"
  else
    printf '%s\tBLOCKED or partial — see private log\n' "$ARM" >> "$DEST/STATUS.txt"
    echo "$ARM recorded as blocked/partial; proceeding to next frozen model."
  fi
done

echo "=== MAKE IDENTITY-BLINDED VIEWER MATERIAL FROM COMPLETE ARMS ==="
if ! ssh "$HOST" "$PY $SCRIPT blind" 2>&1 | tee "$DEST/blind.log"; then
  echo "Blinding incomplete; private per-cue results are preserved."
fi
ssh "$HOST" "$PY $SCRIPT status" | tee "$DEST/COUNTS.json"

echo "=== COPY PRIVATE RESULTS TO MACBOOK, NO GITHUB UPLOAD ==="
scp -qr "$HOST:~/bruiser-pilot/subhub-benchmark-006" "$DEST/" || {
  echo "Result copy failed, but remote checkpointed results remain safe and resumable."
  exit 1
}
echo "PRIVATE MACBOOK COPY: $DEST"
echo "All model output and film dialog are PRIVATE. Never git add these folders."
echo "In blind output, do NOT open IDENTITY_KEY_PRIVATE.json before Japanese viewer scores are frozen."
echo "=== FINAL STATUS ==="
cat "$DEST/STATUS.txt"
