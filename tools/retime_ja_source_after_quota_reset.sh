#!/usr/bin/env bash
# Guarded OptiPlex deployment: move Japanese-source schedule after the
# OpenSubtitles daily quota reset (23:59:59 UTC == 08:59:59 JST).
# Does not call any provider or restart translation.
set -euo pipefail
umask 077

if [[ "$#" -ne 1 || ! "$1" =~ ^[0-9a-f]{40}$ ]]; then
  echo "Usage: $0 <pinned-repo-commit-sha>" >&2
  exit 2
fi
PIN="$1"
CODE="$HOME/bruiser-pilot/subhub-control"
WORKER="$CODE/ja_first_autofill.py"
UNIT_DIR="$HOME/.config/systemd/user"
TIMER_FILE="$UNIT_DIR/bruiser-ja-source-autofill.timer"
SERVICE="bruiser-ja-source-autofill.service"
TIMER="bruiser-ja-source-autofill.timer"

for FILE in "$WORKER" "$TIMER_FILE"; do
  if [[ ! -f "$FILE" || -L "$FILE" || "$(stat -c %u "$FILE")" != "$(id -u)" ]]; then
    echo "Unexpected source-controller or timer file: $FILE" >&2
    exit 1
  fi
done
if systemctl --user is-active --quiet "$SERVICE"; then
  echo "Japanese source service is currently active; not replacing running controller" >&2
  exit 1
fi
if ! systemctl --user is-enabled --quiet "$TIMER"; then
  echo "Japanese source timer is disabled; refusing schedule migration" >&2
  exit 1
fi

TMP="$(mktemp "$CODE/.ja-after-reset-XXXXXXXX.py")"
trap 'rm -f "$TMP"' EXIT
curl -fsSL --retry 3 --connect-timeout 15 --max-time 90 \
  "https://raw.githubusercontent.com/SteezyMode/bruiser-subhub/$PIN/tools/ja_first_autofill.py" \
  -o "$TMP"

python3 - "$TMP" "$TIMER_FILE" "$WORKER" <<'PY'
import ast, pathlib, re, sys
incoming = pathlib.Path(sys.argv[1]).read_text("utf-8")
current_timer = pathlib.Path(sys.argv[2]).read_text("utf-8")
current_worker = pathlib.Path(sys.argv[3]).read_text("utf-8")
ast.parse(incoming, filename=sys.argv[1])
target_match = re.search(r'^TIMER = """(.*?)"""', incoming, re.M | re.S)
assert target_match is not None, 'new timer template missing'
target = target_match.group(1)
assert 'OnCalendar=*-*-* 09:15:00' in target
assert 'RandomizedDelaySec=20min' in target
assert 'Persistent=false' in target
old = target.replace('OnCalendar=*-*-* 09:15:00',
                     'OnCalendar=*-*-* 05:15:00')
assert current_timer in (old,target), 'installed timer differs from known Bruiser version'
assert ('OnCalendar=*-*-* 05:15:00' in current_worker or
        'OnCalendar=*-*-* 09:15:00' in current_worker), \
        'installed controller is not recognized'
print('GUARDED TIMER MIGRATION: validated existing Bruiser unit and Python')
PY

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
cp -p "$TIMER_FILE" "$TIMER_FILE.before-0915-$STAMP"
cp -p "$WORKER" "$WORKER.before-0915-$STAMP"
python3 - "$TMP" "$TIMER_FILE" <<'PY'
import pathlib, re, sys
s=pathlib.Path(sys.argv[1]).read_text("utf-8")
target=re.search(r'^TIMER = """(.*?)"""',s,re.M|re.S).group(1)
out=pathlib.Path(sys.argv[2])
tmp=out.parent / ('.'+out.name+'.quota-reset-tmp')
with tmp.open("x",encoding="utf-8") as f:
    f.write(target)
tmp.chmod(0o600)
tmp.replace(out)
PY
chmod 600 "$TMP"
mv -f "$TMP" "$WORKER"
systemctl --user daemon-reload
systemctl --user restart "$TIMER"
echo "SOURCE SCHEDULE UPDATED: 09:15 JST + up to 20 min random delay"
echo "No provider requests or AI jobs started; current PLaMo batch unchanged."
systemctl --user list-timers --all "$TIMER" --no-pager
