#!/usr/bin/env bash
# Start the existing-English American Dad 8B batch as a detached, resumable job.
# Does not touch GPU power limits or any existing translation service.
set -euo pipefail
umask 077

ROOT="$HOME/bruiser-pilot/plamo3-ab"
STATE="$ROOT/american-dad-existing-english-batch"
TARGET="$ROOT/plamo8b_american_dad_existing_en_batch.py"
PIN="bc9be0710519df9fb6e3852b68f200869d1d5307"
BASE="https://raw.githubusercontent.com/SteezyMode/bruiser-subhub/$PIN/tools"
URL="$BASE/plamo8b_american_dad_existing_en_batch.py"
LOG="$STATE/batch.log"
PROGRESS="$ROOT/american_dad_batch_progress.py"
PROGRESS_URL="$BASE/american_dad_batch_progress.py"

for util in python3 curl find sort paste ldd stat nohup; do
  command -v "$util" >/dev/null || { echo "Missing $util" >&2; exit 1; }
done

if [[ ! -d "$ROOT" || -L "$ROOT" ||
      "$(stat -c %u "$ROOT")" != "$(id -u)" ]]; then
  echo "Original private PLaMo install missing/unsafe." >&2; exit 1
fi
if [[ ! -x "$ROOT/runtime/llama-server" ]]; then
  echo "Original tested llama-server missing." >&2; exit 1
fi
for file in "$ROOT/plamo3_small_ab.py" \
            "$ROOT/plamo3_real_film_ab.py" \
            "$ROOT/plamo3_8b_challenger.py" \
            "$ROOT/plamo3_watch_american_dad.py" \
            "$ROOT/plamo3_source_first_american_dad.py" \
            "$ROOT/models/plamo-3-translate-8b-Q4_K_M.gguf" \
            "$ROOT/source-first-code/ja_first_ffsubsync.py"; do
  if [[ ! -f "$file" || -L "$file" ]]; then
    echo "Missing previously installed tested dependency: $(basename "$file")" >&2
    exit 1
  fi
done
if [[ ! -d "$ROOT/runtime/llama" || ! -d "$ROOT/runtime/cudart" ]]; then
  echo "Pinned CUDA runtime libraries unavailable." >&2; exit 1
fi

TMP="$(mktemp "$ROOT/.american-dad-batch-XXXXXXXX.py")"
trap 'rm -f "$TMP"' EXIT
curl -fsSL --retry 3 --connect-timeout 15 --max-time 60 "$URL" -o "$TMP"
python3 - "$TMP" <<'PY'
from pathlib import Path
import ast,sys
ast.parse(Path(sys.argv[1]).read_text("utf-8"))
print("American Dad batch syntax verified")
PY
chmod 600 "$TMP"
if [[ -L "$TARGET" ]]; then
  echo "Refusing symlink controller target." >&2; exit 1
fi
mv -f -- "$TMP" "$TARGET"
python3 "$TARGET" --self-test

TMPPROGRESS="$(mktemp "$ROOT/.american-dad-progress-XXXXXXXX.py")"
trap 'rm -f "$TMP" "$TMPPROGRESS"' EXIT
curl -fsSL --retry 3 --connect-timeout 15 --max-time 60 \
  "$PROGRESS_URL" -o "$TMPPROGRESS"
python3 - "$TMPPROGRESS" <<'PY'
from pathlib import Path
import ast,sys
ast.parse(Path(sys.argv[1]).read_text("utf-8"))
print("Live progress display syntax verified")
PY
chmod 600 "$TMPPROGRESS"
if [[ -L "$PROGRESS" ]]; then
  echo "Refusing progress controller symlink." >&2; exit 1
fi
mv -f -- "$TMPPROGRESS" "$PROGRESS"

LIBDIRS="$(find "$ROOT/runtime/llama" "$ROOT/runtime/cudart" -type f \
  \( -name 'lib*.so' -o -name 'lib*.so.*' \) -printf '%h\n' \
  | sort -u | paste -sd: -)"
export LD_LIBRARY_PATH="$LIBDIRS"
if ldd "$ROOT/runtime/llama-server" | grep -q "not found"; then
  echo "Pinned CUDA libraries missing." >&2; exit 1
fi
if [[ -L "$STATE" ]]; then
  echo "Unsafe batch state directory symlink." >&2; exit 1
fi
mkdir -p -m 700 "$STATE"

echo "=== AMERICAN DAD: ALL EXISTING ENGLISH SUBTITLES AFTER SEASON 2 ==="
echo "Queue priority: S20, S21, S19, other English-ready episodes."
echo "Skip any episode with existing Japanese. Missing English sources later."
echo "PLaMo8B Q4, two CPU threads, 28 GPU layers, automatic thermal pauses."
echo "Original 32W GPU cap unchanged. Every episode resumes from saved cues."
echo "No provider searches or additional account setup in this pass."

if [[ $# -gt 0 && "$1" == "--status" ]]; then
  exec python3 -u "$PROGRESS"
fi
if [[ $# -gt 0 && "$1" == "--watch" ]]; then
  exec python3 -u "$PROGRESS" --watch
fi
if [[ $# -gt 0 && "$1" == "--preview" ]]; then
  exec python3 -u "$TARGET"
fi
if [[ $# -gt 0 && "$1" == "--foreground" ]]; then
  shift
  exec python3 -u "$TARGET" --apply "$@"
fi
if [[ $# -ne 0 ]]; then
  echo "Usage: no args (start), --watch, --status, --preview, or --foreground" >&2
  exit 2
fi
if [[ -f "$STATE/batch.pid" ]]; then
  PID="$(cat "$STATE/batch.pid" || true)"
  if [[ "$PID" =~ ^[0-9]+$ ]] && kill -0 "$PID" 2>/dev/null; then
    echo "Batch may already be running (PID $PID); inspect existing log."
    echo "LOG: $LOG"
    exit 0
  fi
fi
nohup python3 -u "$TARGET" --apply > "$LOG" 2>&1 < /dev/null &
PID=$!
printf '%s\n' "$PID" > "$STATE/batch.pid"
sleep 1
if ! kill -0 "$PID" 2>/dev/null; then
  echo "Batch exited during startup; last log messages:" >&2
  tail -30 "$LOG" >&2
  exit 1
fi
echo "STARTED background PID $PID"
echo "LOG: $LOG"
echo "Status: tail -f \"$LOG\""
echo "Live progress: python3 -u \"$PROGRESS\" --watch"
python3 -u "$PROGRESS"
echo "Stop safely: kill -INT $PID (completed cues remain saved)"
