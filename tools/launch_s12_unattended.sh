#!/usr/bin/env bash
# Explicit owner launch of the ONE new unattended S12 recovery tool.
# No media paths or existing source files are modified by installation.
set -euo pipefail
umask 077
if [[ $# -ne 1 || ! "$1" =~ ^[0-9a-f]{40}$ ]]; then
  echo "Usage: launch_s12_unattended.sh <pinned-commit>" >&2
  exit 2
fi
PIN="$1"
DEST="$HOME/bruiser-pilot/subhub-control"
PY="$DEST/subhub_unattended_s12_recovery.py"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
NAME=bruiser-subhub-s12-recovery
if [[ ! -d "$DEST" || -L "$DEST" ||
      "$(stat -c %u "$DEST")" != "$(id -u)" ]]; then
  echo "Existing source directory unsafe or unavailable." >&2
  exit 1
fi
for unit in "$NAME.service" bruiser-ja-source-autofill.service \
            bruiser-subhub-season-sources.service \
            bruiser-subhub-translation-batch.service \
            bruiser-subhub-batch.service; do
  state="$(systemctl --user show --property=ActiveState --value "$unit")"
  case "$state" in
    inactive|failed) ;;
    *) echo "BLOCKED: $unit is $state; no changes made."; exit 1 ;;
  esac
done
curl -fsSL --retry 3 --connect-timeout 10 --max-time 90 \
  "https://raw.githubusercontent.com/SteezyMode/bruiser-subhub/$PIN/tools/subhub_unattended_s12_recovery.py" \
  -o "$WORK/source.py"
python3 -B - "$WORK/source.py" <<'PY'
import ast,sys
from pathlib import Path
path=Path(sys.argv[1])
ast.parse(path.read_text("utf-8"))
print("UNATTENDED_SOURCE_SYNTAX_OK")
PY
if [[ -e "$PY" || -L "$PY" ]]; then
  if [[ ! -f "$PY" || -L "$PY" ||
        "$(stat -c %u "$PY")" != "$(id -u)" ]] ||
     ! cmp -s "$WORK/source.py" "$PY"; then
    echo "Existing unattended source file differs; refusing overwrite." >&2
    exit 1
  fi
else
  # Only add a new helper within the verified existing source tool folder.
  install -m 600 "$WORK/source.py" "$PY"
fi
echo "=== START UNATTENDED RECOVERY ==="
systemd-run --user --unit="$NAME" --collect \
  --property=RuntimeMaxSec=2h \
  --property=KillMode=control-group \
  --property=Nice=10 -- \
  /usr/bin/python3 -B -u "$PY" --run

echo "LAUNCHED: $NAME.service (Season 12 targeted retries)"
echo "FOLLOWED BY: bruiser-ja-source-autofill.service (long source-only pass)"
echo "STATUS: systemctl --user status $NAME.service --no-pager"
echo "LOG: journalctl --user -u $NAME.service -n 80 --no-pager -o cat"
echo "Long-run progress will also appear in the existing SubHub dashboard."
