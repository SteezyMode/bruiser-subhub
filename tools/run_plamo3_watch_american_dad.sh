#!/usr/bin/env bash
# One actual American Dad episode in Jellyfin with selected PLaMo 3 8B.
# Run on the EXISTING OptiPlex. No model download, no Gemma switch,
# no season-wide translation, no source-only timer change.
set -euo pipefail
umask 077

ROOT="$HOME/bruiser-pilot/plamo3-ab"
PIN="819bcd16122c868f25ef7894f220c093e14bb43a"
URL="https://raw.githubusercontent.com/SteezyMode/bruiser-subhub/$PIN/tools/plamo3_watch_american_dad.py"
MODEL="$ROOT/models/plamo-3-translate-8b-Q4_K_M.gguf"
EXE="$ROOT/runtime/llama-server"

for required in python3 curl find sort paste ldd stat; do
  command -v "$required" >/dev/null || {
    echo "Missing executable: $required" >&2; exit 1;
  }
done
if [[ ! -d "$ROOT" || -L "$ROOT" ||
      "$(stat -c %u "$ROOT")" != "$(id -u)" ]]; then
  echo "Existing private PLaMo experiment directory unavailable." >&2
  exit 1
fi
for file in "$ROOT/plamo3_small_ab.py" \
            "$ROOT/plamo3_real_film_ab.py" \
            "$ROOT/plamo3_8b_challenger.py" "$MODEL"; do
  if [[ ! -f "$file" || -L "$file" ]]; then
    echo "Missing trusted installed 8B dependency: $(basename "$file")" >&2
    exit 1
  fi
done
if [[ ! -x "$EXE" ]]; then
  echo "Missing tested llama-server binary." >&2; exit 1
fi

TMP="$(mktemp "$ROOT/.american-dad.XXXXXXXX.py")"
trap 'rm -f "$TMP"' EXIT
curl -fsSL --retry 3 --connect-timeout 15 --max-time 60 "$URL" -o "$TMP"
python3 - "$TMP" <<'PY'
import ast
from pathlib import Path
import sys
ast.parse(Path(sys.argv[1]).read_text(encoding="utf-8"))
print("AMERICAN DAD PLaMo8B: Python syntax OK")
PY
chmod 600 "$TMP"
mv -- "$TMP" "$ROOT/plamo3_watch_american_dad.py"
python3 "$ROOT/plamo3_watch_american_dad.py" --self-test

RUNTIME="$ROOT/runtime"
if [[ ! -d "$RUNTIME/llama" || ! -d "$RUNTIME/cudart" ]]; then
  echo "Missing pinned CUDA libraries." >&2; exit 1
fi
LIBDIRS="$(find "$RUNTIME/llama" "$RUNTIME/cudart" -type f \
  \( -name 'lib*.so' -o -name 'lib*.so.*' \) \
  -printf '%h\n' | sort -u | paste -sd: -)"
export LD_LIBRARY_PATH="$LIBDIRS"
if ldd "$EXE" | grep -q "not found"; then
  echo "Missing CUDA libraries for prior-tested llama.cpp." >&2; exit 1
fi

echo "=== ONE AMERICAN DAD EPISODE — ACTUAL JELLYFIN JAPANESE TRACK ==="
echo "Preferred: S08 (when real English source is available)."
echo "Fallback: fresh S19/S20, other fresh episode, or alternate S19E07."
echo "Official PLaMo 8B Q4, 28 GPU layers, 2 source-translation pairs."
echo "Existing Japanese subtitle tracks never overwritten."
echo "Partial cue-level progress resumes on re-running this command."
python3 -u "$ROOT/plamo3_watch_american_dad.py" --install "$@"
