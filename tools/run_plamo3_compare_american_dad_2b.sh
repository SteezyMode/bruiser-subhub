#!/usr/bin/env bash
# Single real household test: PLaMo 3 Translate 2B vs APPROVED 8B,
# frozen American Dad S19E13 392 original English cues.
# Does NOT source subtitles, edit accepted 8B, change LACT power cap,
# start any production worker, or add another episode pipeline.
set -euo pipefail
umask 077

ROOT="$HOME/bruiser-pilot/plamo3-ab"
PIN="1f2cf4353be21c4949a866f482c3cf73bc51502c"
URL="https://raw.githubusercontent.com/SteezyMode/bruiser-subhub/$PIN/tools/plamo3_compare_american_dad_2b.py"
TARGET="$ROOT/plamo3_compare_american_dad_2b.py"
MODEL="$ROOT/models/plamo-3-translate-2b-Q4_K_M.gguf"

for executable in python3 curl stat find sort paste ldd; do
  command -v "$executable" >/dev/null || {
    echo "Missing $executable" >&2; exit 1;
  }
done
if [[ ! -d "$ROOT" || -L "$ROOT" ||
      "$(stat -c %u "$ROOT")" != "$(id -u)" ]]; then
  echo "Original private PLaMo install unavailable." >&2; exit 1
fi
if [[ ! -x "$ROOT/runtime/llama-server" || ! -f "$MODEL" || -L "$MODEL" ]]; then
  echo "Previously tested 2B model or llama-server missing." >&2; exit 1
fi
for file in "$ROOT/plamo3_small_ab.py" \
            "$ROOT/plamo3_real_film_ab.py" \
            "$ROOT/plamo3_8b_challenger.py" \
            "$ROOT/plamo3_watch_american_dad.py" \
            "$ROOT/american-dad-one-episode/episode.json" \
            "$ROOT/american-dad-one-episode/source.en.srt" \
            "$ROOT/american-dad-one-episode/progress.sqlite3"; do
  if [[ ! -f "$file" || -L "$file" ]]; then
    echo "Missing the successful 8B episode/source: $file" >&2; exit 1
  fi
done
if [[ ! -d "$ROOT/runtime/llama" || ! -d "$ROOT/runtime/cudart" ]]; then
  echo "Missing previously pinned CUDA libraries." >&2; exit 1
fi
echo "=== ISOLATED SAME-EPISODE 2B COMPARISON ==="
echo "S19E13: exact 392 English cues and accepted 8B reference."
echo "2B: full GPU offload, two CPU threads. Existing GPU 32W cap untouched."
echo "Output: separate optional Japanese (PLaMo2B) Jellyfin track."
echo "This is resumable; original 8B track and data are READ ONLY."

TMP="$(mktemp "$ROOT/.plamo-2b-XXXXXXXX.py")"
trap 'rm -f "$TMP"' EXIT
curl -fsSL --retry 3 --connect-timeout 15 --max-time 60 \
  "$URL" -o "$TMP"
python3 - "$TMP" <<'PY'
import ast,sys
from pathlib import Path
ast.parse(Path(sys.argv[1]).read_text(encoding="utf-8"))
print("2B controller syntax verified")
PY
chmod 600 "$TMP"
if [[ -L "$TARGET" ]]; then
  echo "Unsafe existing comparison controller symlink." >&2; exit 1
fi
mv -- "$TMP" "$TARGET"
python3 "$TARGET" --self-test

LIBDIRS="$(find "$ROOT/runtime/llama" "$ROOT/runtime/cudart" -type f \
  \( -name 'lib*.so' -o -name 'lib*.so.*' \) -printf '%h\n' \
  | sort -u | paste -sd: -)"
export LD_LIBRARY_PATH="$LIBDIRS"
if ldd "$ROOT/runtime/llama-server" | grep -q "not found"; then
  echo "Pinned CUDA runtime dependencies unavailable." >&2; exit 1
fi

python3 -u "$TARGET" --install
echo "=== FINISHED: PRIVATE 392-CUE SIDE-BY-SIDE FILE READY ==="
