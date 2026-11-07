#!/usr/bin/env bash
# Install ONE standalone S12E04/E05 source-exhausted PLaMo dispatcher.
# No global queue modifications and NO overwriting production model scripts.
set -Eeuo pipefail
umask 077
if [[ $# -ne 1 || ! "$1" =~ ^[0-9a-f]{40}$ ]]; then
  echo "Usage: launch_iasip_s12_held_fallback.sh <pinned-commit>" >&2
  exit 2
fi
PIN="$1"
BASE="https://raw.githubusercontent.com/SteezyMode/bruiser-subhub/$PIN"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
SOURCE="$HOME/bruiser-pilot/subhub-control"
PLAMO="$HOME/bruiser-pilot/plamo3-ab"
DEST="$SOURCE/translate_iasip_s12_held.py"
UNIT="bruiser-subhub-iasip-s12-fallback"
PUBLISH_SOURCE="$SOURCE/ja_first_ffsubsync.py"
MODEL_SOURCE="$PLAMO/subhub_plamo_handoff.py"
for dir in "$SOURCE" "$PLAMO" "$HOME/bruiser-pilot/subhub-translation"; do
  if [[ ! -d "$dir" || -L "$dir" || "$(stat -c %u "$dir")" != "$(id -u)" ]]; then
    echo "STOP: existing private folder missing or unsafe: $dir" >&2
    exit 1
  fi
done
for file in "$PUBLISH_SOURCE" "$MODEL_SOURCE" "$HOME/.local/bin/subhub-ai"; do
  if [[ ! -f "$file" || -L "$file" || "$(stat -c %u "$file")" != "$(id -u)" ]]; then
    echo "STOP: required existing model/source component missing or unsafe." >&2
    exit 1
  fi
done
if [[ -L "$DEST" ]]; then
  echo "STOP: existing helper path is symlink." >&2
  exit 1
fi

for unit in \
  "$UNIT.service" \
  bruiser-subhub-batch.service \
  bruiser-ja-source-autofill.service \
  bruiser-subhub-season-sources.service \
  bruiser-subhub-translation-batch.service \
  bruiser-subhub-s12-recovery.service \
  bruiser-subhub-s12-overlap-repair.service; do
  state="$(systemctl --user show --property=ActiveState --value "$unit")"
  case "$state" in
    inactive|failed) ;;
    *) echo "STOP: $unit active/unknown ($state); no work started" >&2; exit 1 ;;
  esac
done
mkdir -p "$WORK/tools"
touch "$WORK/tools/__init__.py"
for file in translate_iasip_s12_held.py ja_first_ffsubsync.py; do
  curl -fsSL --retry 3 --max-time 90 \
    "$BASE/tools/$file" -o "$WORK/tools/$file"
done
curl -fsSL --retry 3 --max-time 90 \
  "$BASE/test_translate_iasip_s12_held.py" -o "$WORK/test_translate_iasip_s12_held.py"
if ! cmp -s "$PUBLISH_SOURCE" "$WORK/tools/ja_first_ffsubsync.py"; then
  echo "STOP: installed ffsubsync is not the reviewed overlap-repair version." >&2
  echo "No model/source files modified." >&2
  exit 1
fi

if [[ -e "$DEST" ]] && ! cmp -s "$DEST" "$WORK/tools/translate_iasip_s12_held.py"; then
  echo "STOP: existing targeted helper differs; refusing overwrite." >&2
  exit 1
fi

echo "=== OFFLINE TWO-EPISODE FALLBACK TESTS ==="
(
  cd "$WORK"
  PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$WORK" \
    python3 -B -m unittest -v test_translate_iasip_s12_held
)
python3 -B - "$MODEL_SOURCE" <<'PY'
import ast,sys
from pathlib import Path
root=ast.parse(Path(sys.argv[1]).read_text("utf-8"))
functions={n.name for n in root.body if isinstance(n,ast.FunctionDef)}
required={"translate","prepared_source","modules","private_folder","safe_db"}
if not required.issubset(functions):
    raise SystemExit("installed_model_source_missing_required_verified_handoff")
print("PRESERVE_INSTALLED_HANDOFF code unchanged")
PY

if [[ ! -e "$DEST" ]]; then
  install -m 600 "$WORK/tools/translate_iasip_s12_held.py" "$DEST"
fi

# Same bundled GPU libraries as the original installed subhub-ai launcher.
LIBS="$(find "$PLAMO/runtime/llama" "$PLAMO/runtime/cudart" -type f \
  \( -name 'lib*.so' -o -name 'lib*.so.*' \) \
  -printf '%h\n' | sort -u | paste -sd: -)"
if [[ -z "$LIBS" || ! -x "$PLAMO/runtime/llama-server" ]]; then
  echo "GPU runtime missing; no translation started." >&2
  exit 1
fi
echo "=== START E04/E05 SOURCE-VERIFIED TRANSLATION ==="
systemctl --user reset-failed "$UNIT.service" >/dev/null 2>&1 || true
systemd-run --user --unit="$UNIT" --collect \
  --property=KillMode=control-group \
  --property=RuntimeMaxSec=12h \
  --property=Nice=10 \
  --setenv="LD_LIBRARY_PATH=$LIBS" -- \
  /usr/bin/python3 -B -u "$DEST" --run

echo "S12_FALLBACK_LAUNCHED"
echo "Only IASIP S12E04/E05; source-first re-verified per episode."
echo "Existing source tools, model, global queue and subtitles were not replaced."
echo "PROGRESS: journalctl --user -u $UNIT.service -n 80 --no-pager -o cat"
