#!/usr/bin/env bash
# Pinned one-time update of the EXISTING American Dad batch, with checkpoint reuse.
# Does not install a daemon, touch model weights, change GPU limits or restart sourcing.
set -euo pipefail
umask 077

if [[ ${#} -ne 1 || ! "$1" =~ ^[a-f0-9]{40}$ ]]; then
  echo "Usage: install_american_dad_held_recovery.sh <pinned-commit>" >&2
  exit 2
fi
PIN="$1"
ROOT="$HOME/bruiser-pilot/plamo3-ab"
STATE="$ROOT/american-dad-existing-english-batch"
BASE="https://raw.githubusercontent.com/SteezyMode/bruiser-subhub/$PIN/tools"

test -d "$ROOT" && test ! -L "$ROOT"
test -f "$ROOT/plamo3_real_film_ab.py"
test -x "$ROOT/runtime/llama-server"
test -f "$ROOT/models/plamo-3-translate-8b-Q4_K_M.gguf"
for name in plamo3_watch_american_dad.py plamo8b_american_dad_existing_en_batch.py; do
  target="$ROOT/$name"
  if [[ ! -f "$target" || -L "$target" || "$(stat -c %u "$target")" != "$(id -u)" ]]; then
    echo "Existing worker missing, foreign-owned or symlink: $name" >&2
    exit 1
  fi
done

# Updating an active Python worker could create a split-version run.
if pgrep -f '[p]ython3.*plamo8b_american_dad_existing_en_batch.py|[p]ython3.*subhub_plamo_handoff.py|[l]lama-server.*plamo' >/dev/null; then
  echo "An inference worker is already running; files unchanged." >&2
  exit 1
fi

WORK="$(mktemp -d "$ROOT/.ad-recovery-XXXXXXXX")"
trap 'rm -rf "$WORK"' EXIT
for name in plamo3_watch_american_dad.py plamo8b_american_dad_existing_en_batch.py; do
  curl -fsSL --retry 3 --connect-timeout 10 --max-time 60 "$BASE/$name" -o "$WORK/$name"
  chmod 600 "$WORK/$name"
done

python3 - "$WORK" <<'PY'
import ast, pathlib, sys
root=pathlib.Path(sys.argv[1])
a=(root/"plamo3_watch_american_dad.py").read_text("utf-8")
b=(root/"plamo8b_american_dad_existing_en_batch.py").read_text("utf-8")
ast.parse(a); ast.parse(b)
assert 'HELD = "held_translation"' in a
assert "allow_held=True" in b
assert "episode_held_limit_exceeded_" in a
assert "CUE_RETRY no_history_after" in b
print("AMERICAN_DAD_RECOVERY_PREFLIGHT_OK",flush=True)
PY

mkdir -p -m 700 "$STATE"
if [[ -L "$STATE" || "$(stat -c %u "$STATE")" != "$(id -u)" ]]; then
  echo "Unsafe batch state directory" >&2
  exit 1
fi

# Two tested files only; preserve previous versions for explicit rollback.
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
for name in plamo3_watch_american_dad.py plamo8b_american_dad_existing_en_batch.py; do
  cp -p -- "$ROOT/$name" "$STATE/$name.before-$STAMP"
  mv -f -- "$WORK/$name" "$ROOT/$name"
done
python3 "$ROOT/plamo8b_american_dad_existing_en_batch.py" --self-test

LIBDIRS="$(find "$ROOT/runtime/llama" "$ROOT/runtime/cudart" -type f \
  \( -name 'lib*.so' -o -name 'lib*.so.*' \) -printf '%h\n' | sort -u | paste -sd: -)"
export LD_LIBRARY_PATH="$LIBDIRS"

LOG="$STATE/batch.log"
echo "=== RECOVERY BATCH RESTART $STAMP pinned=$PIN ===" >> "$LOG"
nohup python3 -u "$ROOT/plamo8b_american_dad_existing_en_batch.py" --apply >> "$LOG" 2>&1 < /dev/null &
PID=$!
printf '%s\n' "$PID" > "$STATE/batch.pid"
sleep 2
if kill -0 "$PID" 2>/dev/null; then
  echo "AMERICAN_DAD_RECOVERY_RUNNING PID=$PID"
  echo "Progress: ~/bruiser-pilot/plamo3-ab/american_dad_batch_progress.py"
  echo "Existing translated cues and media preserved."
else
  echo "Batch stopped during startup; recent log:" >&2
  tail -30 "$LOG" >&2
  exit 1
fi
