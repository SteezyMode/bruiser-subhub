#!/usr/bin/env bash
# One-user, one-model PLaMo 3 Translate 8B quality comparison.
# Downloads official PFN GGUF Q4_K_M, reuses tested llama.cpp runtime and
# translates exactly the SAME frozen 100 English cues as the 0.8B/2B tests.
# Does NOT touch Jellyfin, media, service/timer, or original run outputs.
set -euo pipefail
umask 077

ROOT="$HOME/bruiser-pilot/plamo3-ab"
MODEL_DIR="$ROOT/models"
RUNTIME="$ROOT/runtime"
PIN="c84c183048593668f35003a4033981528ab20e8d"
PY_URL="https://raw.githubusercontent.com/SteezyMode/bruiser-subhub/$PIN/tools/plamo3_8b_challenger.py"
MODEL="plamo-3-translate-8b-Q4_K_M.gguf"
MODEL_URL="https://huggingface.co/pfnet/plamo-3-translate-8b-GGUF/resolve/main/$MODEL"

for required in curl python3 nvidia-smi find stat df head ldd; do
  command -v "$required" >/dev/null || { echo "Missing $required" >&2; exit 1; }
done
if [[ ! -d "$ROOT" || -L "$ROOT" || ! -d "$MODEL_DIR" || -L "$MODEL_DIR" ]]; then
  echo "Previous private PLaMo install missing or unsafe." >&2
  exit 1
fi
if [[ ! -x "$RUNTIME/llama-server" ||
      ! -s "$ROOT/plamo3_real_film_ab.py" ||
      ! -s "$ROOT/plamo3_small_ab.py" ]]; then
  echo "Previous llama.cpp/PFML3 runners missing; stop." >&2
  exit 1
fi
if [[ ! -d "$RUNTIME/llama" || ! -d "$RUNTIME/cudart" ]]; then
  echo "Previous pinned CUDA runtime missing; stop." >&2
  exit 1
fi
if [[ "$(stat -c %u "$ROOT")" != "$(id -u)" ]]; then
  echo "Benchmark directory belongs to another user; stop." >&2
  exit 1
fi

echo "=== PLaMo 3 Translate 8B Q4_K_M isolated benchmark ==="
echo "Model: $MODEL (official PFN, approx. 5.28 GB)"
echo "Model choice is the ONLY goal; no GPU-utilization gate."
df -h "$ROOT" | tail -1
WEIGHT="$MODEL_DIR/$MODEL"
if [[ -L "$WEIGHT" ]]; then
  echo "Refusing symlink model destination." >&2; exit 1
fi
if [[ ! -f "$WEIGHT" ]]; then
  AVAILABLE="$(df -Pk "$ROOT" | awk 'NR == 2 {print $4}')"
  if (( AVAILABLE < 7500000 )); then
    echo "Need at least 7.5GB free disk space for model download." >&2
    exit 1
  fi
  PART="$WEIGHT.part"
  if [[ -L "$PART" ]]; then
    echo "Refusing symlink partial download." >&2; exit 1
  fi
  echo "=== Downloading official PFN 8B weights ==="
  curl -fL --retry 5 --retry-delay 3 --retry-all-errors \
    --connect-timeout 20 --continue-at - --output "$PART" "$MODEL_URL"
  mv -- "$PART" "$WEIGHT"
  chmod 600 "$WEIGHT"
else
  echo "Existing 8B file found; Python validates GGUF magic and size."
fi

TMP="$(mktemp "$ROOT/.plamo8b.XXXXXXXX.py")"
trap 'rm -f "$TMP"' EXIT
curl -fsSL --retry 3 --connect-timeout 15 --max-time 60 \
  "$PY_URL" -o "$TMP"
python3 - "$TMP" <<'PY'
import ast,sys
from pathlib import Path
ast.parse(Path(sys.argv[1]).read_text(encoding="utf-8"))
print("PINNED 8B EVALUATOR: syntax OK")
PY
chmod 600 "$TMP"
mv -- "$TMP" "$ROOT/plamo3_8b_challenger.py"
python3 "$ROOT/plamo3_8b_challenger.py" --self-test

LIBDIRS="$(find "$RUNTIME/llama" "$RUNTIME/cudart" -type f \
  \( -name 'lib*.so' -o -name 'lib*.so.*' \) -printf '%h\n' \
  | sort -u | paste -sd: -)"
export LD_LIBRARY_PATH="$LIBDIRS"
if ldd "$RUNTIME/llama-server" | grep -q 'not found'; then
  echo "CUDA runtime libraries missing; no benchmark started." >&2; exit 1
fi

echo "=== ONE 8B TEST: SAME ORIGINAL 100 ENGLISH CUES 153–252 ==="
echo "GPU/CPU placement: 28, 20, 12, 0 layers tried only if loading fails."
python3 -u "$ROOT/plamo3_8b_challenger.py"
echo "=== 8B COMPLETE; original 0.8B/2B results preserved ==="
