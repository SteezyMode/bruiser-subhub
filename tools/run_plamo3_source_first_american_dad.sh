#!/usr/bin/env bash
# User-requested one-episode American Dad source-first real use.
# 1. Existing Japanese -> DONE. 2. Verified Japanese provider -> sync/use.
# 3. Existing/downloaded English -> audio sync -> PLaMo 8B -> Jellyfin.
# No source at all -> report audio transcription as LATER, no fabrication.
set -euo pipefail
umask 077

ROOT="$HOME/bruiser-pilot/plamo3-ab"
SOURCE_CODE="$ROOT/source-first-code"
CONTROL="$HOME/bruiser-pilot/subhub-control"
PIN="2d27542296c615b542e4fbe3136d52c40026a199"
BASE="https://raw.githubusercontent.com/SteezyMode/bruiser-subhub/$PIN/tools"

for util in python3 curl find sort paste ldd stat; do
  command -v "$util" >/dev/null || { echo "Missing $util" >&2; exit 1; }
done
if [[ ! -d "$ROOT" || -L "$ROOT" ||
      "$(stat -c %u "$ROOT")" != "$(id -u)" ]]; then
  echo "Existing tested PLaMo private install missing or unsafe." >&2; exit 1
fi
for file in "$ROOT/plamo3_small_ab.py" \
            "$ROOT/plamo3_real_film_ab.py" \
            "$ROOT/plamo3_8b_challenger.py" \
            "$ROOT/models/plamo-3-translate-8b-Q4_K_M.gguf" \
            "$CONTROL/daily_japanese.py"; do
  if [[ ! -f "$file" || -L "$file" ]]; then
    echo "Previously installed required dependency missing: $(basename "$file")" >&2
    exit 1
  fi
done
if [[ ! -x "$ROOT/runtime/llama-server" ]]; then
  echo "Existing tested llama-server runtime missing." >&2; exit 1
fi
if [[ ! -d "$ROOT/runtime/llama" || ! -d "$ROOT/runtime/cudart" ]]; then
  echo "Pinned CUDA libraries missing." >&2; exit 1
fi
if [[ -L "$SOURCE_CODE" ]]; then
  echo "Unsafe helper destination." >&2; exit 1
fi
mkdir -p -m 700 "$SOURCE_CODE"
if [[ "$(stat -c %u "$SOURCE_CODE")" != "$(id -u)" ||
      "$(stat -c %a "$SOURCE_CODE")" != 700 ]]; then
  echo "Helper directory should be user-owned 0700." >&2; exit 1
fi

get_file() {
  local name="$1" dest="$2" tmp
  if [[ -L "$dest" ]]; then
    echo "Refusing symlink code target: $dest" >&2; exit 1
  fi
  tmp="$(mktemp "$SOURCE_CODE/.staging.XXXXXXXX")"
  curl -fsSL --retry 3 --connect-timeout 15 --max-time 60 \
    "$BASE/$name" -o "$tmp"
  python3 - "$tmp" <<'PY'
import ast,sys
from pathlib import Path
ast.parse(Path(sys.argv[1]).read_text(encoding="utf-8"))
PY
  chmod 600 "$tmp"
  mv -f -- "$tmp" "$dest"
}

echo "=== PINNED SOURCE-FIRST MODULES ==="
# Keep these all at ONE Git commit. Never modify installed production code.
for name in \
  ja_first_catalog_manifest.py \
  ja_first_search_pilot.py \
  ja_first_priority.py \
  ja_first_stage_saved_batch.py \
  ja_first_stage_timing_audit.py \
  ja_first_publish_staged.py \
  ja_first_publish_shifted.py \
  ja_first_publish_queue.py \
  ja_first_ffsubsync.py \
  ja_first_obvious_quality.py \
  bruiser_ja_movie_rescue.py; do
  get_file "$name" "$SOURCE_CODE/$name"
done
get_file "plamo3_watch_american_dad.py" "$ROOT/plamo3_watch_american_dad.py"
get_file "plamo3_source_first_american_dad.py" "$ROOT/plamo3_source_first_american_dad.py"

python3 "$ROOT/plamo3_watch_american_dad.py" --self-test
python3 "$ROOT/plamo3_source_first_american_dad.py" --self-test

LIBDIRS="$(find "$ROOT/runtime/llama" "$ROOT/runtime/cudart" -type f \
  \( -name 'lib*.so' -o -name 'lib*.so.*' \) \
  -printf '%h\n' | sort -u | paste -sd: -)"
export LD_LIBRARY_PATH="$LIBDIRS"
if ldd "$ROOT/runtime/llama-server" | grep -q "not found"; then
  echo "Missing original tested CUDA libraries." >&2; exit 1
fi

echo "=== SOURCE-FIRST: ONE REAL AMERICAN DAD EPISODE ==="
echo "Japanese embedded/local > verified Japanese search/download+sync"
echo " > embedded English > English sidecar/download+audio-sync > PLaMo 8B"
echo "No subtitles at all: hold for future English speech transcription."
echo "Japanese files never overwritten; one episode only; 8B 28 GPU layers."
echo "Re-running this command resumes per-cue progress on selected episode."
python3 -u "$ROOT/plamo3_source_first_american_dad.py" --install "$@"
