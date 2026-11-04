#!/usr/bin/env bash
# Install the permanent read-only terminal tracker + controller watch command.
# This NEVER modifies service.py, daily_worker.py, job checkpoints or media.
set -euo pipefail
umask 077

PIN="f85ad6a4150cda015bae7f0a76de9e1654f9c486"
BASE="https://raw.githubusercontent.com/SteezyMode/bruiser-subhub/$PIN/tools"
DEST="$HOME/bruiser-pilot/subhub-control"
HOST="$HOME/bruiser-pilot/subhub1"
if [[ ! -d "$DEST" || -L "$DEST" || ! -f "$HOST/service.py" ||
      -L "$HOST/service.py" ]]; then
  echo "BLOCKED: production host/controller paths missing or unsafe" >&2
  exit 1
fi

TEMP="$(mktemp -d)"
trap 'rm -rf "$TEMP"' EXIT
for name in ja_first_cycle.py subhub_live_tracker.py; do
  if [[ -L "$DEST/$name" ]]; then
    echo "BLOCKED: symlinked script $name" >&2
    exit 1
  fi
  curl -fsSL --retry 3 --connect-timeout 10 --max-time 45 \
    "$BASE/$name" -o "$TEMP/$name"
done

echo "=== CHECK CURRENT SUBTITLE PRODUCTION MODEL ==="
PYTHONDONTWRITEBYTECODE=1 python3 - "$HOST" "$DEST" <<'PY'
import sys
from pathlib import Path
host,folder=(Path(s) for s in sys.argv[1:])
sys.path.insert(0,str(host))
import service
expected='hf.co/17slever17/translate-gemma-4-sub-e4b-GGUF:Q4_K_XL'
if service.GEMMA!=expected:
    raise SystemExit('BLOCKED: service.py production model is not pinned E4B')
model=folder/'subtitle_tuned_production.py'
if model.is_symlink() or not model.is_file():
    raise SystemExit('BLOCKED: pinned E4B controller module missing')
if 'MODEL_ID_PREFIX = "9ccfc3b07081"' not in model.read_text('utf-8'):
    raise SystemExit('BLOCKED: installed model identity does not match')
print('INSTALLED PRODUCTION MODEL:',service.GEMMA)
PY

echo "=== OFFLINE TRACKER/CONTROLLER TESTS ==="
PYTHONDONTWRITEBYTECODE=1 python3 - "$TEMP" <<'PY'
import ast,sys
from pathlib import Path
for f in Path(sys.argv[1]).glob('*.py'):
    ast.parse(f.read_text('utf-8'),filename=str(f))
print('Controller/tracker syntax: passed')
PY
PYTHONDONTWRITEBYTECODE=1 python3 "$TEMP/ja_first_cycle.py" --self-test
PYTHONDONTWRITEBYTECODE=1 python3 "$TEMP/subhub_live_tracker.py" --self-test

echo "=== INSTALLING TRACKER (NOT MODEL OR WORKER) ==="
for name in ja_first_cycle.py subhub_live_tracker.py; do
  install -m 600 "$TEMP/$name" "$DEST/.new-$name"
  mv -f "$DEST/.new-$name" "$DEST/$name"
done

echo "TRACKER INSTALLED:"
echo "  python3 $DEST/ja_first_cycle.py watch"
echo "FUTURE START + LIVE TRACKING:"
echo "  python3 $DEST/ja_first_cycle.py start-worker --apply --watch"
echo "NO JOBS STARTED; EXISTING TRANSLATIONS AND MEDIA UNCHANGED."
