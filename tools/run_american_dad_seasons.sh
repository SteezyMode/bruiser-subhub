#!/usr/bin/env bash
# Finish the requested American Dad season(s), not unrelated videos.
# Usage: bash tools/run_american_dad_seasons.sh optiplex@HOST 8 [9]
set -euo pipefail
if [[ $# -lt 2 || $# -gt 3 ]]; then
  echo 'Usage: bash tools/run_american_dad_seasons.sh optiplex@HOST 8 [9]' >&2
  exit 2
fi
HOST="$1"
shift
for SEASON in "$@"; do
  if ! [[ "$SEASON" =~ ^[0-9]{1,2}$ ]] || (( 10#$SEASON < 1 || 10#$SEASON > 40 )); then
    echo 'Season must be a number from 1 to 40' >&2
    exit 2
  fi
done
if [[ $# -eq 2 && "$1" == "$2" ]]; then
  echo 'Two requested seasons must differ' >&2
  exit 2
fi
ROOT="$(cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT"
echo '=== VERIFY EXISTING REPO REGRESSIONS, NO GPU ==='
python3 -m unittest discover -p 'test_*.py' -q
echo '=== STAGE ONLY ISOLATED SEASON HELPERS, NEVER REPLACE SUBHUB ==='
ssh "$HOST" 'mkdir -p -m 700 ~/bruiser-pilot/american-dad-season-code'
scp -q tools/american_dad_seasons.py tools/daily_japanese.py \
  tools/subtitle_publish_gate.py tools/subtitle_quality_010.py tools/daily_worker.py \
  "$HOST:~/bruiser-pilot/american-dad-season-code/"
REMOTE='python3 ~/bruiser-pilot/american-dad-season-code/american_dad_seasons.py'
echo '=== ACTUAL FILES/EPISODES FOUND; EXISTING JA AND ENGLISH SOURCES ==='
ssh "$HOST" "$REMOTE plan --seasons $*"
echo '=== START DETACHED, SEQUENTIAL, REQUESTED SEASONS ONLY ==='
ssh "$HOST" "$REMOTE start --seasons $* --max-episodes 50 --max-minutes 480"
echo
echo "Progress: ssh $HOST 'tail -50 ~/bruiser-pilot/subhub1-state/american-dad-seasons.log'"
echo "Job status: ssh $HOST 'python3 ~/bruiser-pilot/subhub1/main.py --root ~/bruiser-pilot/subhub1-state status'"
echo 'One failed episode is reported and skipped; accepted existing Japanese is never overwritten.'
echo 'A STARTED campaign does not imply that all episodes have been published.'
