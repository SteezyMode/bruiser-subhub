#!/usr/bin/env bash
# Deploy tested Bruiser-queue ordering into EXISTING JA-only source pipeline.
# No provider calls, timer restart, model or subtitle writes.
set -euo pipefail
umask 077
if [[ $# -ne 1 || ! "$1" =~ ^[0-9a-f]{40}$ ]]; then
  echo "Usage: $0 <pinned_40_character_commit>" >&2
  exit 2
fi
PIN="$1"
CODE="$HOME/bruiser-pilot/subhub-control"
STATE="$HOME/bruiser-pilot/coverage-queue/coverage.sqlite3"
SVC="bruiser-ja-source-autofill.service"
FILES="ja_first_priority.py ja_first_search_pilot.py ja_first_stage_saved_batch.py"

if [[ ! -d "$CODE" || -L "$CODE" ]] ||
   [[ ! -f "$STATE" || -L "$STATE" ]] ||
   [[ $(stat -c %a "$STATE") != "600" ]]; then
  echo "Existing source controller or private initialized coverage queue missing" >&2
  exit 1
fi
if systemctl --user is-active --quiet "$SVC"; then
  echo "Japanese sourcing job is active: refuse to change its running code" >&2
  exit 1
fi
WORK="$(mktemp -d)"
BACK="$(mktemp -d "$CODE/.pre-coverage-sourcing-XXXXXXXX")"
COMMITTED=0
rollback() {
  rc=$?
  if [[ $rc -ne 0 && $COMMITTED -eq 0 ]]; then
    for name in $FILES; do
      if [[ -f "$BACK/$name" ]]; then
        cp -p -- "$BACK/$name" "$CODE/$name"
      fi
    done
    echo "DEPLOYMENT ABORTED; existing source files restored" >&2
  fi
  rm -rf "$WORK"
  if [[ $COMMITTED -eq 1 ]]; then
    echo "Previous controller versions backed up in $BACK"
  elif [[ $rc -eq 0 ]]; then
    rm -rf "$BACK"
  fi
}
trap rollback EXIT
mkdir -p "$WORK/tools"
touch "$WORK/tools/__init__.py"
BASE="https://raw.githubusercontent.com/SteezyMode/bruiser-subhub/$PIN"

for name in $FILES; do
  current="$CODE/$name"
  if [[ ! -f "$current" || -L "$current" ||
        $(stat -c %u "$current") != "$(id -u)" ]]; then
    echo "Unsafe or missing existing controller $current" >&2
    exit 1
  fi
  curl -fsSL --retry 3 --connect-timeout 15 --max-time 90 \
    "$BASE/tools/$name" -o "$WORK/tools/$name"
done
curl -fsSL --retry 3 --connect-timeout 15 --max-time 90 \
  "$BASE/test_ja_first_queue_selection.py" \
  -o "$WORK/test_ja_first_queue_selection.py"

python3 - "$WORK" "$CODE" <<'PY'
import ast, pathlib, sys
root, code = (pathlib.Path(x) for x in sys.argv[1:])
for name in ("ja_first_priority.py","ja_first_search_pilot.py",
             "ja_first_stage_saved_batch.py"):
    old = (code / name).read_text("utf-8")
    fresh = (root / "tools" / name).read_text("utf-8")
    ast.parse(fresh, filename=name)
    if name == "ja_first_priority.py":
        assert "def priority(" in old, "Unexpected existing priority implementation"
        assert "def active_coverage_queue(" in fresh
    else:
        assert "movie_quota = " in old or "queue_position(" in old, \
            "Unexpected existing selection implementation"
        assert "queue_position(" in fresh
        assert "movie_quota = " not in fresh, \
            "Quota ratio was not actually eliminated"
print("SOURCE_SELECTOR_PREFLIGHT_OK",flush=True)
PY

(
  cd "$WORK"
  PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$WORK" \
    python3 -m unittest -v test_ja_first_queue_selection
)
for name in $FILES; do
  cp -p "$CODE/$name" "$BACK/$name"
done
for name in $FILES; do
  install -m 600 "$WORK/tools/$name" "$CODE/$name.deploy-next"
  mv -f "$CODE/$name.deploy-next" "$CODE/$name"
done
COMMITTED=1
echo "QUEUE_DRIVEN_SOURCE_SELECTOR_INSTALLED"
echo "Search/stage use the persistent queue; both movies and shows eligible."
echo "Provider quota, identity, timing and no-overwrite safeguards unchanged."
echo "No service/timer was restarted, no provider calls, no GPU worker."
systemctl --user list-timers --all bruiser-ja-source-autofill.timer --no-pager
