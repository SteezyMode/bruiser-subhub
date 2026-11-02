#!/usr/bin/env bash
# Run a NEW three-episode American Dad context-safe trial on the OptiPlex.
# Versioned scratch state; previous five Japanese tracks are left untouched.
set -euo pipefail
if [ "$#" -ne 1 ]; then
  echo "Usage: bash tools/run_contextsafe_pilot_010.sh optiplex@HOST" >&2
  exit 2
fi
HOST="$1"
ROOT="$(cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT"

echo "=== OFFLINE REGRESSION TESTS ==="
python3 -m unittest discover -p 'test_*.py' -q

echo "=== STAGING ISOLATED v010 PIPELINE ON HOST ==="
ssh "$HOST" 'mkdir -p -m 700 ~/bruiser-pilot/contextsafe-010-code/series_profiles ~/bruiser-pilot/american-dad-contextsafe-010'
scp -q service.py \
  tools/context_engine_008.py \
  tools/american_dad_intake_009.py \
  tools/american_dad_core_009.py \
  tools/american_dad_pilot_009.py \
  tools/subtitle_quality_010.py \
  tools/american_dad_contextsafe_010.py \
  "$HOST:~/bruiser-pilot/contextsafe-010-code/"
scp -q tools/series_profiles/american_dad.json \
  "$HOST:~/bruiser-pilot/contextsafe-010-code/series_profiles/"

RUN='python3 ~/bruiser-pilot/contextsafe-010-code/american_dad_contextsafe_010.py'
echo "=== FREEZE THREE PREVIOUSLY UNTRANSLATED EPISODES ==="
ssh "$HOST" "$RUN prepare --episodes 3"
echo "=== TRANSLATE, QUALITY GATE, CREATE-ONLY v2 SUBTITLES ==="
ssh "$HOST" "$RUN run --episodes 3 --minutes 420 --publish" \
  2>&1 | tee -a "$HOME/Downloads/american-dad-contextsafe-010.log"
echo "=== PRIVATE PROGRESS SUMMARY ==="
ssh "$HOST" "$RUN status"
echo "Log: $HOME/Downloads/american-dad-contextsafe-010.log"
echo "Re-run the same command to resume existing private cue checkpoints."
