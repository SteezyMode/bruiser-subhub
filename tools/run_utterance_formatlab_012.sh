#!/usr/bin/env bash
# Scratch-only 24-utterance same-E4B format lab. No media/subtitle writes.
set -euo pipefail
if [[ $# -ne 1 ]]; then
  echo 'Usage: bash tools/run_utterance_formatlab_012.sh optiplex@HOST' >&2
  exit 2
fi
HOST="$1"
ROOT="$(cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT"
echo '=== ALL OFFLINE REGRESSIONS ==='
python3 -m unittest discover -p 'test_*.py' -q
echo '=== STAGE ONLY NEW LAB MODULE; NEVER RESTAGE ORIGINAL V011 MODULES ==='
ssh "$HOST" 'mkdir -p -m 700 ~/bruiser-pilot/utterance-formatlab-012-code ~/bruiser-pilot/utterance-formatlab-012'
scp -q tools/utterance_formatlab_012.py "$HOST:~/bruiser-pilot/utterance-formatlab-012-code/"
RUN='python3 ~/bruiser-pilot/utterance-formatlab-012-code/utterance_formatlab_012.py'
echo '=== FREEZE 24 REAL PRIVATE ENGLISH UTTERANCES ==='
ssh "$HOST" "$RUN prepare"
echo '=== SAME MODEL, 450 TOKENS PER FORMAT, ONE CALL PER FORMAT PER UTTERANCE ==='
ssh "$HOST" "$RUN run --minutes 180" 2>&1 | tee -a "$HOME/Downloads/american-dad-formatlab-012.log"
echo '=== RESULT COUNTS: success/fail separately for JSON and numbered lines ==='
ssh "$HOST" "$RUN status"
echo 'Log: ~/Downloads/american-dad-formatlab-012.log'
echo 'Rerun this same command to resume any untested format calls without repeating checkpoints.'
