#!/usr/bin/env bash
# NEW scratch-only, versioned v011 three-episode pilot on the OptiPlex.
# No production service/SQLite/worker changes; untouched previous Japanese SRTs.
set -euo pipefail
if [[ "$#" -ne 1 ]]; then
  echo "Usage: bash tools/run_utterance_pilot_011.sh optiplex@HOST" >&2
  exit 2
fi
HOST="$1"
ROOT="$(cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT"
echo "=== LOCAL OFFLINE REGRESSION ==="
python3 -m unittest discover -p 'test_*.py' -q
echo "=== STAGE ONLY SCRATCH v011 CODE ==="
ssh "$HOST" 'mkdir -p -m 700 ~/bruiser-pilot/utterance-011-code/series_profiles ~/bruiser-pilot/american-dad-utterance-011'
scp -q service.py \
 tools/context_engine_008.py \
 tools/american_dad_intake_009.py \
 tools/american_dad_core_009.py \
 tools/american_dad_pilot_009.py \
 tools/subtitle_quality_010.py \
 tools/semantic_groups_011.py \
 tools/american_dad_utterance_011.py \
 "$HOST:~/bruiser-pilot/utterance-011-code/"
scp -q tools/series_profiles/american_dad.json \
 "$HOST:~/bruiser-pilot/utterance-011-code/series_profiles/"
RUN='python3 ~/bruiser-pilot/utterance-011-code/american_dad_utterance_011.py'
echo "=== FREEZE THREE FRESH ENGLISH-SOURCE EPISODES ==="
ssh "$HOST" "$RUN prepare --episodes 3"
echo "=== TRANSLATE GROUPED SENTENCES / QA / CREATE-ONLY JAPANESE ==="
ssh "$HOST" "$RUN run --episodes 3 --minutes 420 --publish" \
 2>&1 | tee -a "$HOME/Downloads/american-dad-utterance-011.log"
echo "=== READ-ONLY PROGRESS ==="
ssh "$HOST" "$RUN status"
echo "Log saved: $HOME/Downloads/american-dad-utterance-011.log"
echo "Re-running this command resumes the same frozen unit checkpoints."
