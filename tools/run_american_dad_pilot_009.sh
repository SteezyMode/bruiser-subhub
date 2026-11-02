#!/usr/bin/env bash
# Five complete American Dad episodes; no live worker deployment.
set -euo pipefail
if [ "$#" -ne 1 ]; then echo "Usage: bash tools/run_american_dad_pilot_009.sh optiplex@HOST" >&2; exit 2; fi
HOST="$1"
ROOT="$(cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT"
echo "=== OFFLINE REGRESSION TESTS ==="
python3 -m unittest discover -p 'test_*.py' -q
echo "=== STAGE ISOLATED PILOT; EXISTING SUBHUB UNTOUCHED ==="
ssh "$HOST" 'mkdir -p -m 700 ~/bruiser-pilot/american-dad-pilot-009-code/series_profiles ~/bruiser-pilot/american-dad-pilot-009'
scp -q service.py tools/context_engine_008.py tools/american_dad_core_009.py \
  tools/american_dad_intake_009.py tools/american_dad_pilot_009.py \
  "$HOST:~/bruiser-pilot/american-dad-pilot-009-code/"
scp -q tools/series_profiles/american_dad.json \
  "$HOST:~/bruiser-pilot/american-dad-pilot-009-code/series_profiles/"
RUN='python3 ~/bruiser-pilot/american-dad-pilot-009-code/american_dad_pilot_009.py'
echo "=== FREEZE UP TO FIVE ELIGIBLE EPISODES, ENGLISH SOURCE ONLY ==="
ssh "$HOST" "$RUN prepare --episodes 5"
echo "=== PINNED GEMMA E4B: FULL EPISODES, CREATE-ONLY JAPANESE SIDECARS ==="
ssh "$HOST" "$RUN run --episodes 5 --minutes 420 --publish" \
  2>&1 | tee "$HOME/Downloads/american-dad-pilot-009.log"
echo "=== STATUS ==="
ssh "$HOST" "$RUN status"
echo "Log: $HOME/Downloads/american-dad-pilot-009.log"
echo "Re-running resumes existing private cue checkpoints."
