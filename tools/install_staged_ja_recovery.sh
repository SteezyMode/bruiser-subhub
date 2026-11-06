#!/usr/bin/env bash
# Install queue-restricted reuse of ALREADY DOWNLOADED Japanese subtitles.
# This script does NOT run publication. The caller must separately invoke
# --queue-staged-only --apply to create new verified Japanese sidecars.
set -euo pipefail
umask 077

if [[ $# -ne 1 || ! "$1" =~ ^[0-9a-f]{40}$ ]]; then
  echo "Usage: $0 <pinned_40_character_commit>" >&2
  exit 2
fi

PIN="$1"
CODE="$HOME/bruiser-pilot/subhub-control"
QUEUEDB="$HOME/bruiser-pilot/coverage-queue/coverage.sqlite3"
SERVICE="bruiser-ja-source-autofill.service"
NAME="ja_first_publish_queue.py"
TARGET="$CODE/$NAME"
SCRIPT="test_bruiser_publish_queue_staged.py"

if [[ ! -f "$QUEUEDB" || -L "$QUEUEDB" ||
      "$(stat -c %a "$QUEUEDB")" != "600" ]]; then
  echo "Initialized private Bruiser coverage queue not found" >&2
  exit 1
fi
for name in "$NAME" ja_first_ffsubsync.py ja_first_publish_staged.py ja_first_priority.py; do
  if [[ ! -f "$CODE/$name" || -L "$CODE/$name" ]]; then
    echo "Missing or unsafe existing publication module: $name" >&2
    exit 1
  fi
done
if systemctl --user is-active --quiet "$SERVICE"; then
  echo "Source service active; refusing to change source modules while running" >&2
  exit 1
fi

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir "$TMP/tools"
touch "$TMP/tools/__init__.py"
BASE="https://raw.githubusercontent.com/SteezyMode/bruiser-subhub/$PIN"
curl -fsSL --retry 3 --connect-timeout 15 --max-time 90 \
  "$BASE/tools/$NAME" -o "$TMP/tools/$NAME"
curl -fsSL --retry 3 --connect-timeout 15 --max-time 90 \
  "$BASE/$SCRIPT" -o "$TMP/$SCRIPT"

python3 - "$TMP/tools/$NAME" <<'PY'
import ast, pathlib, sys
source=pathlib.Path(sys.argv[1]).read_text("utf-8")
ast.parse(source)
assert "def queued_staged_titles(" in source
assert "--queue-staged-only" in source
assert "FFSUBSYNC" in source and "publish_selected" in source
print("STAGED_JA_RECOVERY_PREFLIGHT_OK",flush=True)
PY

(
  cd "$TMP"
  PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$TMP/tools:$CODE" \
    python3 -m unittest -v test_bruiser_publish_queue_staged
)

BACK="$TARGET.before-queue-staged-$(date -u +%Y%m%dT%H%M%SZ)"
cp -p "$TARGET" "$BACK"
install -m 600 "$TMP/tools/$NAME" "$TARGET.deploy-next"
mv -f "$TARGET.deploy-next" "$TARGET"
echo "STAGED_JA_RECOVERY_INSTALLED"
echo "Publisher uses existing ffsubsync and create-only validation; stage originals retained."
echo "No provider quota consumed, no model/GPU work and no publication started."
echo "Publisher backup: $BACK"
python3 "$HOME/bruiser-pilot/coverage-queue-code/bruiser_coverage_queue.py" \
  next --state "$HOME/bruiser-pilot/coverage-queue" \
  --filter-action align_existing_staged_ja --limit 25
