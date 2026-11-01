#!/usr/bin/env bash
set -euo pipefail
HOST="${1:?Usage: bash tools/run_model_benchmark.sh optiplex@HOST [challenger-model-name-or-auto]}"
CHALLENGER="${2:-auto}"
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
python3 -m unittest discover -p 'test_*.py' -q
echo "=== STAGE ISOLATED BENCHMARK (live engine untouched) ==="
ssh "$HOST" 'mkdir -p ~/bruiser-pilot/subhub-benchmark ~/bruiser-pilot/subhub1-state/review'
scp -q service.py localization_policy.py tools/benchmark_localization.py tools/model_benchmark.py "$HOST:~/bruiser-pilot/subhub-benchmark/"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
FILE="primate-model-matrix-v1-$STAMP.json"
CMD="python3 ~/bruiser-pilot/subhub-benchmark/model_benchmark.py --challenger-model '$CHALLENGER' --out ~/bruiser-pilot/subhub1-state/review/'$FILE'"
echo "=== PREFLIGHT: installed models, fixed English source hash, frozen cue windows ==="
ssh "$HOST" "$CMD --dry-run"
echo "=== RUN LOCAL MODEL x PROMPT BENCHMARK (holds worker locks; uses Ollama/GPU) ==="
ssh "$HOST" "$CMD"
scp -q "$HOST:~/bruiser-pilot/subhub1-state/review/$FILE" "$HOME/Downloads/$FILE"
echo "PRIVATE RESULTS: $HOME/Downloads/$FILE"
echo "Send that JSON to this chat for a blinded/manual Japanese quality assessment."
echo "No production checkpoint or published subtitle has been edited."
