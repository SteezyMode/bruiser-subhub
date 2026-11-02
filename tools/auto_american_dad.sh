#!/usr/bin/env bash
# Choose a REAL American Dad season with available EN; fill source gaps locally.
# The full-library English inventory timer stays independent, and the original
# Gemma engine is not changed. No manual season selection or subtitles needed.
set -euo pipefail
if [[ $# -ne 1 ]]; then
  echo "Usage: bash tools/auto_american_dad.sh optiplex@HOST" >&2
  exit 2
fi
HOST="$1"
ROOT="$(cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT"
echo '=== OFFLINE SAFETY TESTS ==='
python3 -m unittest discover -p 'test_*.py' -q
echo '=== STAGE ISOLATED SEASON + ENGLISH SOURCE CODE ==='
ssh "$HOST" 'mkdir -p -m 700 ~/bruiser-pilot/american-dad-auto-code'
scp -q \
  tools/american_dad_autopilot.py \
  tools/american_dad_maintenance.py \
  tools/english_asr_fallback.py \
  tools/enable_american_dad_timer.py \
  tools/american_dad_seasons.py \
  tools/daily_japanese.py \
  tools/daily_worker.py \
  "$HOST:~/bruiser-pilot/american-dad-auto-code/"
echo '=== AUTOMATICALLY SCORE EVERY REAL AMERICAN DAD SEASON ==='
ssh "$HOST" 'python3 ~/bruiser-pilot/american-dad-auto-code/american_dad_autopilot.py'
echo '=== PREPARE ISOLATED LOCAL ENGLISH TRANSCRIPTION; CPU ONLY ==='
if ssh "$HOST" 'bash -s' <<'REMOTE'
set -eu
VENV="$HOME/bruiser-pilot/american-dad-asr-venv"
if [ ! -x "$VENV/bin/python" ]; then
  python3 -m venv "$VENV"
fi
if ! "$VENV/bin/python" -c 'import faster_whisper' >/dev/null 2>&1; then
  "$VENV/bin/python" -m pip install --disable-pip-version-check --no-input \
    'faster-whisper==1.2.1'
fi
"$VENV/bin/python" -c 'from faster_whisper import WhisperModel; print("LOCAL_ASR_READY cpu_int8")'
REMOTE
then
  echo 'Local Whisper engine installed in private venv; no system Python or GPU change.'
else
  echo 'LOCAL_ASR_NOT_READY: dependency setup failed; alternative seasons with existing EN can still translate.'
fi
echo '=== ENABLE CONSERVATIVE ONE-EPISODE-PER-NIGHT MAINTENANCE ==='
if ssh "$HOST" 'python3 ~/bruiser-pilot/american-dad-auto-code/enable_american_dad_timer.py'; then
  echo 'Nightly selected-season maintenance timer active.'
  echo '=== LAUNCH FIRST MAINTENANCE RUN WITHOUT BLOCKING SSH ==='
  if ssh "$HOST" \
      'systemctl --user start --no-block bruiser-american-dad-maintenance.service'; then
    echo 'FIRST_RUN_LAUNCHED user-systemd'
  else
    echo 'FIRST_RUN_USER_SERVICE_FAILED; using detached host process.'
    ssh "$HOST" 'python3 -' <<'PY'
import subprocess
from pathlib import Path
root=Path.home()/'bruiser-pilot'
path=root/'subhub1-state'/'american-dad-maintenance.log'
path.parent.mkdir(parents=True,exist_ok=True)
cmd=['python3',str(root/'american-dad-auto-code/american_dad_maintenance.py')]
with path.open('a') as f:
    child=subprocess.Popen(cmd,stdin=subprocess.DEVNULL,stdout=f,
                           stderr=subprocess.STDOUT,start_new_session=True)
print('FIRST_RUN_LAUNCHED',child.pid)
PY
  fi
else
  echo 'Nightly timer unavailable in this user session; launching initial maintenance once.'
  ssh "$HOST" 'python3 -' <<'PY'
import subprocess
from pathlib import Path
root=Path.home()/'bruiser-pilot'
path=root/'subhub1-state'/'american-dad-maintenance.log'
path.parent.mkdir(parents=True,exist_ok=True)
cmd=['python3',str(root/'american-dad-auto-code/american_dad_maintenance.py')]
with path.open('a') as f:
    child=subprocess.Popen(cmd,stdin=subprocess.DEVNULL,stdout=f,
                           stderr=subprocess.STDOUT,start_new_session=True)
print('FIRST_RUN_LAUNCHED',child.pid)
PY
fi
echo '=== MONITOR ON HOST ==='
echo "ssh $HOST 'journalctl --user -u bruiser-american-dad-maintenance.service -n 60 --no-pager'"
echo "ssh $HOST 'tail -60 ~/bruiser-pilot/subhub1-state/american-dad-seasons.log'"
echo 'ASR is a draft English source, never claimed to be editorial transcription.'
