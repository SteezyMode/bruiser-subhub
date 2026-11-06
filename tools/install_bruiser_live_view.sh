#!/usr/bin/env bash
# Install read-only live progress bars over an EXISTING Bruiser batch.
# Does not change the worker, queue, subtitles, timer, or systemd.
set -euo pipefail
umask 077
if [[ $# -lt 1 || $# -gt 2 || ! "$1" =~ ^[0-9a-f]{40}$ ]]; then
  echo "Usage: $0 <pinned-commit> [--watch]" >&2
  exit 2
fi
PIN="$1"
WATCH=""
if [[ $# -eq 2 ]]; then WATCH="$2"; fi
if [[ -n "$WATCH" && "$WATCH" != "--watch" ]]; then
  echo "Second argument must be --watch" >&2
  exit 2
fi
DEST="$HOME/.local/bin/bruiser-live"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
mkdir -m 700 "$WORK/tools"
touch "$WORK/tools/__init__.py"
BASE="https://raw.githubusercontent.com/SteezyMode/bruiser-subhub/$PIN"
curl -fsSL --retry 3 --connect-timeout 10 --max-time 90 \
 "$BASE/tools/bruiser_live_view.py" -o "$WORK/tools/bruiser_live_view.py"
curl -fsSL --retry 3 --connect-timeout 10 --max-time 90 \
 "$BASE/test_bruiser_live_view.py" -o "$WORK/test_bruiser_live_view.py"

python3 - "$WORK/tools/bruiser_live_view.py" <<'PY'
import ast, pathlib, sys
source = pathlib.Path(sys.argv[1]).read_text("utf-8")
ast.parse(source)
for required in ("def terminal_screen(", "def recent_log(",
                 "def published_stage_progress(", "service_running("):
    assert required in source, required
print("LIVE_PROGRESS_VIEW_PREFLIGHT_OK",flush=True)
PY
(cd "$WORK" &&
 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$WORK" \
   python3 -m unittest -v test_bruiser_live_view)

mkdir -p "$HOME/.local/bin"
if [[ -L "$HOME/.local/bin" || -L "$DEST" ||
      "$(stat -c %u "$HOME/.local/bin")" != "$(id -u)" ]]; then
  echo "Unsafe local user bin folder or viewer symlink" >&2
  exit 1
fi
install -m 700 "$WORK/tools/bruiser_live_view.py" "$DEST.new"
mv -f "$DEST.new" "$DEST"
echo "BRUISER_LIVE_PROGRESS_INSTALLED $DEST"
echo "Running subtitle worker has NOT been restarted or modified."
echo "Open anytime: ssh -t optiplex@100.121.156.34 ~/.local/bin/bruiser-live"
if [[ "$WATCH" == "--watch" ]]; then
  echo "Opening live bars; Ctrl+C closes viewer, not the batch."
  exec python3 "$DEST"
fi
