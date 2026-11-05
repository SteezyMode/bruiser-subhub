#!/usr/bin/env bash
# JP sources first: chain bounded English-source maintenance only after the
# existing daily Japanese-source service has completed successfully.
# Does NOT touch the concurrent American Dad translation batch.
set -euo pipefail
umask 077

if [[ "$#" -ne 1 || ! "$1" =~ ^[0-9a-f]{40}$ ]]; then
  echo "Usage: $0 <pinned-repo-commit-sha>" >&2
  exit 2
fi
PIN="$1"
CODE="$HOME/bruiser-pilot/english-source-code"
WORKER="$CODE/library_english_sources.py"
BASE="$HOME/.config/systemd/user"
JA_UNIT="$BASE/bruiser-ja-source-autofill.service"
EN_UNIT="$BASE/bruiser-english-source.service"
JA_TIMER="bruiser-ja-source-autofill.timer"
EN_TIMER="bruiser-english-source.timer"
DROP_DIR="$BASE/bruiser-ja-source-autofill.service.d"
DROP="$DROP_DIR/40-english-after-japanese.conf"

# Validate the exact existing services and currently deployed English worker.
for FILE in "$WORKER" "$JA_UNIT" "$EN_UNIT"; do
  if [[ ! -f "$FILE" || -L "$FILE" || "$(stat -c %u "$FILE")" != "$(id -u)" ]]; then
    echo "Missing, unsafe or non-owned existing file: $FILE" >&2
    exit 1
  fi
done
grep -Fxq 'Type=oneshot' "$JA_UNIT"
grep -Fxq 'ExecStart=/usr/bin/python3 %h/bruiser-pilot/subhub-control/ja_first_autofill.py once --apply' "$JA_UNIT"
grep -Fxq 'Type=oneshot' "$EN_UNIT"
if ! grep -Fxq 'ExecStart=/usr/bin/python3 %h/bruiser-pilot/english-source-code/library_english_sources.py run --budget 5' "$EN_UNIT" &&
   ! grep -Fxq 'ExecStart=/usr/bin/python3 %h/bruiser-pilot/english-source-code/library_english_sources.py run --budget 300 --provider-delay 1' "$EN_UNIT"; then
  echo "Unexpected English source service command; refusing rewrite." >&2
  exit 1
fi
if ! grep -Eq '^TimeoutStartSec=(90min|6h)$' "$EN_UNIT"; then
  echo "Unexpected English service timeout; refusing rewrite." >&2
  exit 1
fi
if systemctl --user is-active --quiet bruiser-english-source.service; then
  echo "English acquisition is currently active; not updating its running worker." >&2
  exit 1
fi
if ! systemctl --user is-enabled --quiet "$JA_TIMER"; then
  echo "Japanese-first timer isn't enabled; refusing to chain." >&2
  exit 1
fi
if [[ -L "$DROP_DIR" || -L "$DROP" ]]; then
  echo "Unsafe systemd drop-in symlink" >&2
  exit 1
fi
if [[ -e "$DROP" ]]; then
  EXPECTED='[Service]
ExecStartPost=-/usr/bin/systemctl --user start --no-block bruiser-english-source.service'
  if [[ "$(cat "$DROP")" != "$EXPECTED" ]]; then
    echo "Conflicting service drop-in; refusing overwrite" >&2
    exit 1
  fi
fi

TMP="$(mktemp "$CODE/.english-japanese-first-XXXXXXXX.py")"
trap 'rm -f "$TMP"' EXIT
curl -fsSL --retry 3 --connect-timeout 15 --max-time 90 \
  "https://raw.githubusercontent.com/SteezyMode/bruiser-subhub/$PIN/tools/library_english_sources.py" \
  -o "$TMP"
python3 - "$TMP" <<'PY'
import ast, pathlib, sys
t=pathlib.Path(sys.argv[1]).read_text('utf8')
ast.parse(t,filename=sys.argv[1])
assert "japanese_present" in t and "intake.already_ja(video)" in t
assert "search_budget<=300" in t and "provider_delay_s" in t
print("Japanese-first English worker Python syntax: OK")
PY

# Disable only the *early* English timer; keep the English service and
# Japanese-source timer untouched. No work is launched now.
systemctl --user disable --now "$EN_TIMER"

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
cp -p -- "$WORKER" "$WORKER.before-japanese-first-$STAMP"
# Preserve the previously configured English service, but use the newly
# supported high-volume budget. Reject arbitrary service definitions above.
cp -p -- "$EN_UNIT" "$EN_UNIT.before-heavy-english-$STAMP"
NEW_EN="$(mktemp "$BASE/.bruiser-en-service-XXXXXXXX")"
sed -e 's@^ExecStart=/usr/bin/python3 %h/bruiser-pilot/english-source-code/library_english_sources.py run --budget 5$@ExecStart=/usr/bin/python3 %h/bruiser-pilot/english-source-code/library_english_sources.py run --budget 300 --provider-delay 1@' \
    -e 's@^TimeoutStartSec=90min$@TimeoutStartSec=6h@' \
    "$EN_UNIT" > "$NEW_EN"
chmod 600 "$NEW_EN"
mv -f -- "$NEW_EN" "$EN_UNIT"
chmod 600 "$TMP"
mv -f -- "$TMP" "$WORKER"
mkdir -p -m 700 "$DROP_DIR"
if [[ ! -e "$DROP" ]]; then
  cat > "$DROP" <<'CONF'
[Service]
ExecStartPost=-/usr/bin/systemctl --user start --no-block bruiser-english-source.service
CONF
  chmod 600 "$DROP"
fi
systemctl --user daemon-reload
echo "CHAIN INSTALLED: successful Japanese source job -> English fallback (up to 300 searches, 1 sec pacing)"
echo "English timer disabled: no more 03:30 English-before-Japanese starts"
echo "Japanese source timer remains enabled; PLaMo batch untouched."
echo "=== NEXT SOURCE TIMER ==="
systemctl --user list-timers --all "$JA_TIMER" "$EN_TIMER" --no-pager
echo "=== ENGLISH SOURCE SHELF ==="
python3 "$WORKER" status
