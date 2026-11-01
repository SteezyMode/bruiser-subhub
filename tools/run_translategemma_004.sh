#!/usr/bin/env bash
set -euo pipefail
HOST="${1:?Usage: bash tools/run_translategemma_004.sh optiplex@HOST}"
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
python3 -m unittest discover -p 'test_*.py' -q

echo "=== STAGE BENCHMARK ONLY (live service untouched) ==="
ssh "$HOST" 'mkdir -p ~/bruiser-pilot/subhub-benchmark ~/bruiser-pilot/subhub1-state/review'
scp -q service.py localization_policy.py \
  tools/benchmark_localization.py tools/model_benchmark.py \
  tools/benchmark_native_subtitles.py tools/analyze_model_benchmark.py \
  tools/benchmark_translategemma_004.py \
  "$HOST:~/bruiser-pilot/subhub-benchmark/"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
FILE="primate-translategemma-004-$STAMP.json"
CMD="python3 ~/bruiser-pilot/subhub-benchmark/benchmark_translategemma_004.py --out ~/bruiser-pilot/subhub1-state/review/$FILE"

echo "=== VERIFY FROZEN ENGLISH SOURCE BEFORE ANY MODEL DOWNLOAD ==="
ssh "$HOST" "$CMD --source-only"
if ssh "$HOST" 'ollama list | grep -qE "^translategemma:4b[[:space:]]"'; then
  echo "=== GOOGLE TRANSLATEGEMMA ALREADY INSTALLED: no download ==="
else
  echo "=== ONE-TIME DOWNLOAD: official Google TranslateGemma 4B Q4_K_M (~3.3 GB) ==="
  ssh "$HOST" 'ollama pull translategemma:4b'
fi

echo "=== VERIFY OFFICIAL MODEL ID, GEMMA3 FAMILY, Q4_K_M, AND PRIOR TUNED MODEL ==="
ssh "$HOST" "$CMD --dry-run"
echo "=== RUN MODEL-NATIVE ENGLISH->JAPANESE COMPARISON (GPU; read-only) ==="
ssh "$HOST" "$CMD"
scp -q "$HOST:~/bruiser-pilot/subhub1-state/review/$FILE" "$HOME/Downloads/$FILE"
printf "PRIVATE RESULTS: %s\n" "$HOME/Downloads/$FILE"
echo "Attach this JSON here for meaning/tone/readability comparison; do not commit subtitle text to GitHub."
echo "Nothing installed or restarted in live SubHub. Only the explicitly downloaded Ollama model and private benchmark report are new."
