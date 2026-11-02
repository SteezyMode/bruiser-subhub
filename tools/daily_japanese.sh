#!/usr/bin/env bash
# Daily household EN->JA: choose ONE video needing Japanese, stage into existing
# SubHub 1.0 queue, then start the existing worker detached. NO code replacement.
set -euo pipefail
if [[ $# -ne 1 ]]; then
  echo 'Usage: bash tools/daily_japanese.sh optiplex@HOST' >&2
  exit 2
fi
HOST="$1"
ROOT="$(cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT"
echo '=== OFFLINE SAFETY REGRESSIONS ==='
python3 -m unittest discover -p 'test_*.py' -q
echo '=== STAGE NEW INTAKE HELPER ONLY; CURRENT SUBHUB WORKER UNTOUCHED ==='
ssh "$HOST" 'mkdir -p -m 700 ~/bruiser-pilot/daily-japanese-code'
scp -q tools/daily_japanese.py tools/daily_worker.py "$HOST:~/bruiser-pilot/daily-japanese-code/"
echo '=== FIND ONE ENGLISH-AUDIO TITLE MISSING JAPANESE AND QUEUE ITS SOURCE ==='
ssh "$HOST" 'python3 ~/bruiser-pilot/daily-japanese-code/daily_japanese.py --apply --start --probe-budget 30'
echo
echo 'Status and progress:'
echo "  ssh $HOST 'python3 ~/bruiser-pilot/subhub1/main.py --root ~/bruiser-pilot/subhub1-state status'"
echo "  ssh $HOST 'tail -50 ~/bruiser-pilot/subhub1-state/worker.log'"
echo 'The existing worker runs detached. A queued job is NOT yet a published or quality-reviewed JA track.'
