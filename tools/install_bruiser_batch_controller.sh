#!/usr/bin/env bash
# One-shot installer for Bruiser batch start/status/logs/stop.
# Checks code/tests and backs up existing local queue/publisher before changing.
# Does NOT launch searches, publications or GPU work until operator calls start.
set -euo pipefail
umask 077

if [[ $# -ne 1 || ! "$1" =~ ^[0-9a-f]{40}$ ]]; then
  echo "Usage: $0 <40-character pinned GitHub commit>" >&2
  exit 2
fi
PIN="$1"
ROOT="$HOME/bruiser-pilot"
CODE="$ROOT/subhub-control"
QUEUE="$ROOT/coverage-queue-code"
STATE="$ROOT/coverage-queue/coverage.sqlite3"
BIN="$HOME/.local/bin"
SVC="bruiser-ja-source-autofill.service"
NAMES="bruiser_batch.py bruiser_coverage_queue.py"
PUBLISH="ja_first_publish_queue.py"

if [[ ! -d "$CODE" || -L "$CODE" ||
      ! -d "$QUEUE" || -L "$QUEUE" ||
      ! -f "$STATE" || -L "$STATE" ||
      "$(stat -c %a "$STATE")" != 600 ]]; then
  echo "Existing source system and private coverage queue required" >&2
  exit 1
fi
if systemctl --user is-active --quiet "$SVC" ||
   systemctl --user is-active --quiet "bruiser-subhub-batch.service"; then
  echo "A source/batch service is already running; refusing hot code replacement" >&2
  exit 1
fi
if [[ -L "$BIN" || -L "$BIN/bruiser-subs" ||
      -L "$CODE/$PUBLISH" ||
      -L "$QUEUE/bruiser_coverage_queue.py" ||
      -L "$QUEUE/bruiser_batch.py" ]]; then
  echo "Symlinked target directory or controller refused" >&2
  exit 1
fi

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$WORK/tools"
touch "$WORK/tools/__init__.py"
BASE="https://raw.githubusercontent.com/SteezyMode/bruiser-subhub/$PIN"
for name in $NAMES; do
  curl -fsSL --retry 3 --connect-timeout 15 --max-time 90 \
    "$BASE/tools/$name" -o "$WORK/tools/$name"
done
curl -fsSL --retry 3 --connect-timeout 15 --max-time 90 \
  "$BASE/tools/$PUBLISH" -o "$WORK/tools/$PUBLISH"
for test in test_bruiser_batch.py test_bruiser_coverage_queue.py test_bruiser_publish_queue_staged.py; do
  curl -fsSL --retry 3 --connect-timeout 15 --max-time 90 \
    "$BASE/$test" -o "$WORK/$test"
done

python3 - "$WORK" "$QUEUE" "$CODE" <<'PY'
import ast, pathlib, sys
root, local_queue, local_code = (pathlib.Path(x) for x in sys.argv[1:])
for name in ("bruiser_batch.py","bruiser_coverage_queue.py",
             "ja_first_publish_queue.py"):
    src=(root/"tools"/name).read_text("utf-8")
    ast.parse(src, filename=name)
    if name=="bruiser_batch.py":
        for required in ("def start(","def status(","def logs(","def stop(",
                         "lock_cycle(","provider quota","queue-staged-only"):
            assert required in src, required
    if name=="ja_first_publish_queue.py":
        assert "BRUISER_PUBLISH_ITEM:" in src
        assert "--queue-staged-only" in src
    if name=="bruiser_coverage_queue.py":
        assert "def read_published_staged(" in src
for existing in (local_queue/"bruiser_coverage_queue.py",
                 local_code/"ja_first_publish_queue.py"):
    if not existing.is_file() or existing.is_symlink():
        raise SystemExit("Expected existing module not safely installed: "+existing.name)
print("BATCH_CONTROLLER_PREFLIGHT_OK", flush=True)
PY

(
 cd "$WORK"
 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$WORK/tools:$CODE" \
   python3 -m unittest -v \
     test_bruiser_batch test_bruiser_coverage_queue \
     test_bruiser_publish_queue_staged
)

mkdir -p -m 700 "$BIN"
if [[ "$(stat -c %u "$BIN")" != "$(id -u)" ||
      "$(stat -c %u "$QUEUE")" != "$(id -u)" ||
      "$(stat -c %u "$CODE")" != "$(id -u)" ]]; then
  echo "Target directories not owned by current user" >&2
  exit 1
fi
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
for name in $NAMES; do
  target="$QUEUE/$name"
  if [[ -e "$target" ]]; then
    cp -p -- "$target" "$target.before-batch-$stamp"
  fi
done
cp -p -- "$CODE/$PUBLISH" "$CODE/$PUBLISH.before-batch-$stamp"
if [[ -e "$BIN/bruiser-subs" ]]; then
  cp -p -- "$BIN/bruiser-subs" "$BIN/bruiser-subs.before-batch-$stamp"
fi

for name in $NAMES; do
  install -m 600 "$WORK/tools/$name" "$QUEUE/$name.new"
  mv -f -- "$QUEUE/$name.new" "$QUEUE/$name"
done
install -m 600 "$WORK/tools/$PUBLISH" "$CODE/$PUBLISH.new"
mv -f -- "$CODE/$PUBLISH.new" "$CODE/$PUBLISH"

cat > "$BIN/bruiser-subs.new" <<'WRAPPER'
#!/bin/sh
exec /usr/bin/python3 "$HOME/bruiser-pilot/coverage-queue-code/bruiser_batch.py" "$@"
WRAPPER
chmod 700 "$BIN/bruiser-subs.new"
mv -f -- "$BIN/bruiser-subs.new" "$BIN/bruiser-subs"

echo "BRUISER_BATCH_CONTROLLER_INSTALLED"
echo "To start NOW: $BIN/bruiser-subs start --cycles 5"
echo "Any time:     $BIN/bruiser-subs status"
echo "Logs:         $BIN/bruiser-subs logs --lines 50"
echo "Live log:     $BIN/bruiser-subs logs --follow"
echo "Stop safely:  $BIN/bruiser-subs stop"
echo "NOTE: Installation made no provider requests, GPU calls or subtitle writes."
"$BIN/bruiser-subs" status
