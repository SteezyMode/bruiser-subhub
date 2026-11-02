#!/usr/bin/env bash
# Resume frozen v011 from original accepted unit checkpoints, with bounded
# recovery-specific fallback. Never restage or mutate frozen v011 source code.
set -euo pipefail
if [[ $# -ne 1 ]]; then
  echo 'Usage: bash tools/run_utterance_rescue_011.sh optiplex@HOST' >&2
  exit 2
fi
HOST="$1"
ROOT="$(cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT"
echo '=== OFFLINE REGRESSIONS (NO GPU) ==='
python3 -m unittest discover -p 'test_*.py' -q
echo '=== STAGE ONLY NEW RESCUE ADAPTER; FROZEN v011 CODE UNCHANGED ==='
ssh "$HOST" 'mkdir -p -m 700 ~/bruiser-pilot/utterance-011-recovery-code ~/bruiser-pilot/american-dad-utterance-011-recovery'
scp -q tools/rescue_utterance_011.py "$HOST:~/bruiser-pilot/utterance-011-recovery-code/"
RUN='python3 ~/bruiser-pilot/utterance-011-recovery-code/rescue_utterance_011.py'
echo '=== RESUME CACHED ORIGINAL GROUPS; BOUNDED SOLO FALLBACK IF REQUIRED ==='
ssh "$HOST" "$RUN run --minutes 420 --publish" \
  2>&1 | tee -a "$HOME/Downloads/american-dad-utterance-011-recovery.log"
echo '=== READ-ONLY RESULT SUMMARY ==='
ssh "$HOST" "$RUN status"
echo 'Log: ~/Downloads/american-dad-utterance-011-recovery.log'
echo 'Inspect RECOVERY_SUMMARY: only published_new_recovery or already_published_identical means published.'
echo 'Repeat this command to resume unchanged recovered units if incomplete/held.'
