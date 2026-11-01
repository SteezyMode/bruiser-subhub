#!/usr/bin/env bash
set -euo pipefail
HOST="${1:?Usage: bash tools/compare_primate_style.sh optiplex@HOST PRIMATE_JOB_ID [cue-ids]}"
JOB="${2:?Provide the Primate job ID shown by SubHub status}"
CUES="${3:-35,71,207,380,465}"
[[ "$JOB" =~ ^[a-z0-9][a-z0-9-]+$ ]] || { echo "Invalid job ID" >&2; exit 2; }
[[ "$CUES" =~ ^[0-9]+(,[0-9]+){0,7}$ ]] || { echo "Invalid cue ID selection" >&2; exit 2; }
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
python3 -m unittest discover -p 'test_*.py' -q
echo "Staging isolated QA tool (NOT upgrading or restarting SubHub)"
ssh "$HOST" 'mkdir -p ~/bruiser-pilot/subhub-benchmark ~/bruiser-pilot/subhub1-state/review'
scp -q service.py localization_policy.py tools/benchmark_localization.py "$HOST:~/bruiser-pilot/subhub-benchmark/"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
FILE="$JOB.natural8-ab-$STAMP.json"
echo "Checking worker locks; run only when no translation is active."
ssh "$HOST" "python3 ~/bruiser-pilot/subhub-benchmark/benchmark_localization.py --job '$JOB' --cue-ids '$CUES' --out ~/bruiser-pilot/subhub1-state/review/'$FILE'"
scp -q "$HOST:~/bruiser-pilot/subhub1-state/review/$FILE" "$HOME/Downloads/$FILE"
printf "\nPRIVATE Japanese A/B sample: %s\nUpload this file to this chat for language-quality comparison. Never commit it to GitHub.\n" "$HOME/Downloads/$FILE"
