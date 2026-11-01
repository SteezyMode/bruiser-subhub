#!/usr/bin/env bash
set -euo pipefail
HOST="${1:?Usage: bash tools/run_model_card_003.sh optiplex@HOST}"
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
python3 -m unittest discover -p 'test_*.py' -q
echo "=== STAGING BENCHMARK ONLY; live translator unchanged ==="
ssh "$HOST" 'mkdir -p ~/bruiser-pilot/subhub-benchmark ~/bruiser-pilot/subhub1-state/review'
scp -q service.py localization_policy.py \
  tools/benchmark_localization.py tools/model_benchmark.py \
  tools/benchmark_native_subtitles.py tools/analyze_model_benchmark.py \
  tools/benchmark_model_card_003.py \
  "$HOST:~/bruiser-pilot/subhub-benchmark/"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
FILE="primate-model-card-003-$STAMP.json"
CMD="python3 ~/bruiser-pilot/subhub-benchmark/benchmark_model_card_003.py --out ~/bruiser-pilot/subhub1-state/review/$FILE"
echo "=== PREFLIGHT: fixed source, installed model ID, two controlled arms ==="
ssh "$HOST" "$CMD --dry-run"
echo "=== REAL CONTROLLED A/B: same model, with vs without >8s stale context ==="
ssh "$HOST" "$CMD"
scp -q "$HOST:~/bruiser-pilot/subhub1-state/review/$FILE" "$HOME/Downloads/$FILE"
echo "PRIVATE COMPARISON: $HOME/Downloads/$FILE"
echo "Upload the file here for EN/JA review; never commit the private output."
echo "No published subtitles, model installations, database checkpoint or active worker were modified."
