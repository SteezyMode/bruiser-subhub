#!/usr/bin/env bash
# Safe, pinned, one-time repair/resume of an already-started American Dad batch.
# Refuses a live batch. Preserves the 48-episode queue, per-cue SQLite DBs,
# existing subtitles, original model, source timer, and LACT GPU power cap.
set -euo pipefail
umask 077

PIN="${1:-}"
if [[ ! "$PIN" =~ ^[0-9a-f]{40}$ ]]; then
  echo "Usage: $0 <tested-commit-sha>" >&2
  exit 2
fi

ROOT="$HOME/bruiser-pilot/plamo3-ab"
STATE="$ROOT/american-dad-existing-english-batch"
TARGET="$ROOT/plamo8b_american_dad_existing_en_batch.py"
PROGRESS="$ROOT/american_dad_batch_progress.py"
LOG="$STATE/batch.log"
BASE="https://raw.githubusercontent.com/SteezyMode/bruiser-subhub/$PIN/tools"

# Fail closed before downloading or writing when the existing worker is alive.
python3 - <<'PY'
from pathlib import Path
import os, sys
for entry in Path("/proc").iterdir():
    if not entry.name.isdigit():
        continue
    try:
        raw = (entry / "cmdline").read_bytes()
        args = raw.split(b"\0")
        if (any(b"plamo8b_american_dad_existing_en_batch.py" in arg
                for arg in args) and b"--apply" in args):
            print("BATCH_ALREADY_RUNNING pid=" + entry.name + "; no change made.")
            sys.exit(55)
    except (OSError, PermissionError):
        continue
PY

if [[ ! -d "$ROOT" || -L "$ROOT" || -L "$STATE" ||
      ! -f "$STATE/queue.json" || -L "$STATE/queue.json" ||
      ! -f "$TARGET" || -L "$TARGET" ]]; then
  echo "Existing installed batch/queue is missing or unsafe. Refusing to start a new queue." >&2
  exit 1
fi
if [[ "$(stat -c %u "$ROOT")" != "$(id -u)" ||
      "$(stat -c %u "$STATE")" != "$(id -u)" ]]; then
  echo "Private runtime/state ownership mismatch." >&2
  exit 1
fi
if [[ -f "$STATE/batch.pid" ]]; then
  oldpid="$(cat "$STATE/batch.pid")"
  if [[ "$oldpid" =~ ^[0-9]+$ ]] && kill -0 "$oldpid" 2>/dev/null; then
    echo "Saved PID $oldpid is still alive; investigate before repair." >&2
    exit 1
  fi
fi
if command -v ss >/dev/null 2>&1 &&
   ss -ltn '( sport = :18886 )' 2>/dev/null | grep -q '127.0.0.1:18886'; then
  echo "Batch llama.cpp port 18886 is in use; refusing to interfere." >&2
  exit 1
fi

BATCH_NEW="$(mktemp "$ROOT/.plamo8b-overnight-XXXXXXXX.py")"
PROGRESS_NEW="$(mktemp "$ROOT/.plamo8b-progress-XXXXXXXX.py")"
trap 'rm -f "$BATCH_NEW" "$PROGRESS_NEW"' EXIT

curl -fsSL --retry 3 --connect-timeout 15 --max-time 90 \
  "$BASE/plamo8b_american_dad_existing_en_batch.py" -o "$BATCH_NEW"
curl -fsSL --retry 3 --connect-timeout 15 --max-time 90 \
  "$BASE/american_dad_batch_progress.py" -o "$PROGRESS_NEW"

python3 - "$BATCH_NEW" "$PROGRESS_NEW" <<'PY'
import ast, pathlib, sys
for name in sys.argv[1:]:
    ast.parse(pathlib.Path(name).read_text("utf-8"), filename=name)
print("Offline Python syntax: OK")
PY

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
cp -p -- "$TARGET" "$TARGET.before-overnight-$STAMP"
if [[ -f "$PROGRESS" && ! -L "$PROGRESS" ]]; then
  cp -p -- "$PROGRESS" "$PROGRESS.before-overnight-$STAMP"
elif [[ -L "$PROGRESS" ]]; then
  echo "Progress reader is a symlink. Refusing to replace." >&2
  exit 1
fi

chmod 600 "$BATCH_NEW" "$PROGRESS_NEW"
mv -f -- "$BATCH_NEW" "$TARGET"
mv -f -- "$PROGRESS_NEW" "$PROGRESS"
python3 -B "$TARGET" --self-test

echo "RESUMING saved American Dad batch (no cue/checkpoint reset)."
echo "Untranslated cue: one identical replay, then hold episode and proceed."
echo "Cooling: 5-second checks; unchanged thermal and LACT limits."
echo "Log is append-only: $LOG"
nohup python3 -u "$TARGET" --apply >> "$LOG" 2>&1 < /dev/null &
pid=$!
pidtmp="$(mktemp "$STATE/.batchpid-XXXXXXXX")"
printf '%s\n' "$pid" > "$pidtmp"
mv -f -- "$pidtmp" "$STATE/batch.pid"
sleep 2
if ! kill -0 "$pid" 2>/dev/null; then
  echo "Batch exited during startup; recent log:" >&2
  tail -n 35 "$LOG" >&2
  exit 1
fi
echo "RESUMED background pid=$pid"
python3 -B "$PROGRESS"
