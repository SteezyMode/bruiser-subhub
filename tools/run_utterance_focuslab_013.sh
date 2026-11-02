#!/usr/bin/env bash
# Private v013: 9 coherent prior utterances, 18 individual focus-cue calls.
# All original translation/model/source files are READ ONLY.
set -euo pipefail
if [[ $# -ne 1 ]]; then
  echo 'Usage: bash tools/run_utterance_focuslab_013.sh optiplex@HOST' >&2
  exit 2
fi
HOST="$1"
ROOT="$(cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT"
echo '=== OFFLINE REGRESSION SUITE ==='
python3 -m unittest discover -p 'test_*.py' -q
echo '=== STAGE ONLY NEW, ISOLATED LAB MODULE ==='
ssh "$HOST" 'mkdir -p -m 700 ~/bruiser-pilot/utterance-focuslab-013-code ~/bruiser-pilot/utterance-focuslab-013'
scp -q tools/utterance_focuslab_013.py "$HOST:~/bruiser-pilot/utterance-focuslab-013-code/"
RUN='python3 ~/bruiser-pilot/utterance-focuslab-013-code/utterance_focuslab_013.py'
echo '=== VERIFY ORIGINAL 012 RAW REPLIES; FREEZE NINE COHERENT SENTENCES ==='
ssh "$HOST" "$RUN prepare"
echo '=== ONE MODEL CALL PER ORIGINAL CUE; NO SRT OUTPUTS ==='
ssh "$HOST" "$RUN run --minutes 120" \
 2>&1 | tee -a "$HOME/Downloads/american-dad-focuslab-013.log"
echo '=== RESULTS ==='
ssh "$HOST" "$RUN status"
echo 'Saved log: ~/Downloads/american-dad-focuslab-013.log'
echo 'Rerun the same command to finish remaining focus cues without repeating prior results.'
