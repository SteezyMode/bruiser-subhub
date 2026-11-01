#!/usr/bin/env bash
set -euo pipefail
HOST="${1:?Usage: bash tools/run_native_subtitle_benchmark.sh optiplex@HOST}"
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
python3 -m unittest discover -p 'test_*.py' -q
echo "=== STAGE NATIVE PROMPT TEST (live SubHub unchanged) ==="
ssh "$HOST" 'mkdir -p ~/bruiser-pilot/subhub-benchmark ~/bruiser-pilot/subhub1-state/review'
scp -q service.py localization_policy.py \
  tools/benchmark_localization.py tools/model_benchmark.py \
  tools/analyze_model_benchmark.py tools/benchmark_native_subtitles.py \
  "$HOST:~/bruiser-pilot/subhub-benchmark/"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
FILE="primate-native-sub-e4b-v1-$STAMP.json"
CMD="python3 ~/bruiser-pilot/subhub-benchmark/benchmark_native_subtitles.py --out ~/bruiser-pilot/subhub1-state/review/$FILE"
echo "=== PREFLIGHT: exact installed model ID, frozen English source and 64 cues ==="
ssh "$HOST" "$CMD --dry-run"
echo "=== MODEL-NATIVE SINGLE-CUE BENCHMARK (GPU; read-only; worker locks) ==="
ssh "$HOST" "$CMD"
scp -q "$HOST:~/bruiser-pilot/subhub1-state/review/$FILE" "$HOME/Downloads/$FILE"
echo "PRIVATE RESULTS: $HOME/Downloads/$FILE"
echo "Upload that JSON for an actual translation quality comparison."
echo "No existing subtitles or checkpoints were modified."
