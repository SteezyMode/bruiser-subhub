#!/usr/bin/env bash
# Isolated official FINAL CyberAgent CAT-Translate 3.3B benchmark.
# This is a separate Transformers+CUDA lane because no final-model GGUF is verified.
set -euo pipefail
HOST="${1:?Usage: bash tools/run_cat33_005.sh optiplex@HOST [PRIVATE_DEST_DIR]}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
DEST="${2:-$HOME/Downloads/cat33-final-005-$STAMP}"
mkdir -p -m 700 "$DEST"
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

python3 -m unittest discover -p 'test_*.py' -q
ssh "$HOST" 'mkdir -p ~/bruiser-pilot/subhub-benchmark ~/bruiser-pilot/subhub1-state/review'
scp -q service.py localization_policy.py \
  tools/benchmark_localization.py tools/model_benchmark.py \
  tools/benchmark_native_subtitles.py tools/benchmark_translategemma_004.py \
  tools/analyze_model_benchmark.py tools/model_sweep_005.py \
  tools/model_sweep_cat33_005.py \
  "$HOST:~/bruiser-pilot/subhub-benchmark/"

FILE="model-sweep-005-cat33-final-$STAMP.json"
CHECK="python3 ~/bruiser-pilot/subhub-benchmark/model_sweep_005.py --model tuned --out ~/bruiser-pilot/subhub1-state/review/$FILE --source-only"
ssh "$HOST" "$CHECK"
echo "CAT 3.3B uses official cyberagent/CAT-Translate-3.3b final safetensors."
echo "An isolated CUDA PyTorch virtual environment and Hugging Face cache will require additional disk space."
ssh "$HOST" 'df -h ~ | tail -1'

VENV='~/bruiser-pilot/subhub-cat33-venv'
ssh "$HOST" 'python3 -m venv ~/bruiser-pilot/subhub-cat33-venv'
echo "=== Installing pinned inference packages IN ISOLATED venv only ==="
ssh "$HOST" '~/bruiser-pilot/subhub-cat33-venv/bin/python -m pip install --disable-pip-version-check --no-input "torch==2.9.0" "transformers==4.57.3" "accelerate==1.12.0" "bitsandbytes==0.48.2" "huggingface-hub==0.36.0"'

CMD="~/bruiser-pilot/subhub-cat33-venv/bin/python ~/bruiser-pilot/subhub-benchmark/model_sweep_cat33_005.py --out ~/bruiser-pilot/subhub1-state/review/$FILE --max-seconds 3600"
echo "=== Preflight: exact English SHA, real CUDA and >=3GB free VRAM ==="
ssh "$HOST" "$CMD --dry-run"
echo "=== Load pinned FINAL model revision and run 64 cue translations ==="
STATUS='complete'
if ! ssh "$HOST" "$CMD"; then STATUS='failed-or-partial'; fi
if scp -q "$HOST:~/bruiser-pilot/subhub1-state/review/$FILE" "$DEST/$FILE"; then
  echo "PRIVATE FILE: $DEST/$FILE"
else
  echo "No output; official final-model compatibility/loading may require investigation." >&2
  exit 1
fi
echo "CAT FINAL benchmark status: $STATUS"
echo "All Transformers dependencies and weights remain isolated from the live SubHub worker."
[ "$STATUS" = complete ]
