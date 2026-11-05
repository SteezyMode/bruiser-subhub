#!/usr/bin/env bash
# Run real-film PLaMo 3 0.8B vs 2B benchmark from the EXISTING private
# standalone install. This is not a production subtitle worker.
set -euo pipefail
umask 077
ROOT="$HOME/bruiser-pilot/plamo3-ab"
PIN="2a382556a30001b1535138de2ff4e50c7ea0065c"
URL="https://raw.githubusercontent.com/SteezyMode/bruiser-subhub/$PIN/tools/plamo3_real_film_ab.py"
mkdir -p -m 700 "$ROOT"
if [[ -L "$ROOT" ]] || [[ "$(stat -c %u "$ROOT")" != "$(id -u)" ]]; then
  echo "Unsafe PLaMo benchmark directory" >&2; exit 1
fi
if [[ ! -f "$ROOT/plamo3_small_ab.py" ]]; then
  echo "Missing first successful PLaMo installation; run install_plamo3_small_ab.sh first" >&2
  exit 1
fi
if [[ ! -x "$ROOT/runtime/llama-server" ]]; then
  echo "Missing existing pinned llama.cpp runtime" >&2; exit 1
fi
for model in plamo-3-translate-0.8b-Q4_K_M.gguf plamo-3-translate-2b-Q4_K_M.gguf; do
  if [[ ! -s "$ROOT/models/$model" ]]; then
    echo "Missing existing official GGUF model: $model" >&2; exit 1
  fi
done

TMP="$(mktemp "$ROOT/.real-film-ab.XXXXXXXX.py")"
trap 'rm -f "$TMP"' EXIT
curl -fsSL --retry 3 --connect-timeout 15 --max-time 60 "$URL" -o "$TMP"
python3 - "$TMP" <<'PY'
import ast, sys
ast.parse(open(sys.argv[1], encoding="utf-8").read(), filename=sys.argv[1])
print("REAL-FILM SOURCE: Python syntax OK")
PY
chmod 600 "$TMP"
mv -f -- "$TMP" "$ROOT/plamo3_real_film_ab.py"
python3 "$ROOT/plamo3_real_film_ab.py" --self-test

# Original isolated CUDA archive from the successful 16-cue test. No driver
# or system package modifications.
LIBDIRS="$(find "$ROOT/runtime/llama" "$ROOT/runtime/cudart" -type f \
  \( -name 'lib*.so' -o -name 'lib*.so.*' \) -printf '%h\n' \
  | sort -u | paste -sd: -)"
export LD_LIBRARY_PATH="$LIBDIRS"
if ldd "$ROOT/runtime/llama-server" | grep -q "not found"; then
  echo "Missing previously pinned CUDA libraries; refusing model run" >&2
  exit 1
fi
echo "=== VERIFY SOURCE-ONLY TIMER IS UNCHANGED ==="
systemctl --user list-timers --all bruiser-ja-source-autofill.timer --no-pager || true
echo "=== BEGIN READ-ONLY REAL FILM 100-CUE PLaMo 0.8B/2B A/B ==="
python3 -u "$ROOT/plamo3_real_film_ab.py" \
  --frozen-run "$ROOT/real-results/film-100-20261105T085111561829Z"
echo "=== TEST FINISHED: PRIVATE OUTPUTS ONLY ==="
