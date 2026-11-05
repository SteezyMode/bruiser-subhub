#!/usr/bin/env bash
# Isolated PLaMo 3 0.8B+2B GGUF setup for user's OptiPlex.
# No change to Jellyfin, Ollama, source-only systemd, or other GPU processes.
set -euo pipefail
umask 077

BASE="$HOME/bruiser-pilot/plamo3-ab"
RUNTIME="$BASE/runtime"
MODELS="$BASE/models"
VERSION="b12119"
COMMIT="f10686b1fa1c365e3d871c657600738a8a6cc7d6"
RELEASE="https://github.com/ggml-org/llama.cpp/releases/download/$VERSION"
if [[ "$(uname -m)" != "x86_64" ]]; then echo "Requires x86_64" >&2; exit 1; fi
for app in curl tar python3 nvidia-smi ldd; do
  command -v "$app" >/dev/null || { echo "Missing $app" >&2; exit 1; }
done
mkdir -p -m 700 "$BASE" "$RUNTIME" "$MODELS"
for dir in "$BASE" "$RUNTIME" "$MODELS"; do
  if [[ -L "$dir" ]] || [[ "$(stat -c %u "$dir")" != "$(id -u)" ]]; then
    echo "Unsafe directory $dir" >&2; exit 1
  fi
  chmod 700 "$dir"
done
download() {
  local url="$1" dest="$2" temp
  if [[ -s "$dest" && ! -L "$dest" ]]; then
    echo "Already downloaded: $dest"; return
  fi
  if [[ -L "$dest" ]]; then echo "Unsafe download destination: $dest" >&2; exit 1; fi
  temp="$dest.part"
  if [[ -L "$temp" ]]; then echo "Unsafe partial download: $temp" >&2; exit 1; fi
  echo "Downloading: $dest"
  curl -fL --retry 5 --retry-delay 3 --connect-timeout 20 --retry-all-errors \
    -C - --output "$temp" "$url"
  test -s "$temp"
  mv "$temp" "$dest"
  chmod 600 "$dest"
}

echo "=== PRIVATE PLaMo model test setup ==="
df -h "$BASE" | tail -1
avail_kib="$(df -Pk "$BASE" | awk 'NR==2 {print $4}')"
if (( avail_kib < 6000000 )); then
  echo "Need 6 GB free for a first-time setup" >&2; exit 1
fi

download "https://raw.githubusercontent.com/SteezyMode/bruiser-subhub/$COMMIT/tools/plamo3_small_ab.py" \
  "$BASE/plamo3_small_ab.py"
python3 "$BASE/plamo3_small_ab.py" --self-test

SERVER_ARCHIVE="$RUNTIME/llama-server-$VERSION.tar.gz"
CUDA_ARCHIVE="$RUNTIME/cudart-$VERSION.tar.gz"
download "$RELEASE/llama-$VERSION-bin-ubuntu-cuda-12.8-x64.tar.gz" "$SERVER_ARCHIVE"
download "$RELEASE/cudart-llama-$VERSION-bin-ubuntu-cuda-12.8-x64.tar.gz" "$CUDA_ARCHIVE"

if [[ ! -e "$RUNTIME/llama-server" ]]; then
  mkdir -p -m 700 "$RUNTIME/llama" "$RUNTIME/cudart"
  tar -xf "$SERVER_ARCHIVE" -C "$RUNTIME/llama"
  tar -xf "$CUDA_ARCHIVE" -C "$RUNTIME/cudart"
  SERVER_BIN="$(find "$RUNTIME/llama" -type f -name llama-server -print -quit)"
  if [[ -z "$SERVER_BIN" ]]; then echo "No llama-server in pinned archive" >&2; exit 1; fi
  chmod u+x "$SERVER_BIN"
  ln -s "$SERVER_BIN" "$RUNTIME/llama-server"
fi

for size in 0.8b 2b; do
  name="plamo-3-translate-$size-Q4_K_M.gguf"
  download "https://huggingface.co/pfnet/plamo-3-translate-$size-GGUF/resolve/main/$name" \
    "$MODELS/$name"
done

LIBDIRS="$(find "$RUNTIME/llama" "$RUNTIME/cudart" -type f \
  \( -name 'lib*.so' -o -name 'lib*.so.*' \) -printf '%h\n' | sort -u | paste -sd: -)"
export LD_LIBRARY_PATH="$LIBDIRS:$LD_LIBRARY_PATH"
if ldd "$RUNTIME/llama-server" | grep "not found"; then
  echo "Missing CUDA runtime libraries; no model inference attempted" >&2; exit 1
fi
echo "=== GPU STATUS ==="
nvidia-smi --query-gpu=name,memory.free,utilization.gpu --format=csv,noheader
echo "=== 16-CUE IDENTICAL EN->JA COMPARISON ==="
python3 -u "$BASE/plamo3_small_ab.py" \
  --binary "$RUNTIME/llama-server" \
  --models "$MODELS" --output-root "$BASE/results" \
  --gpu-layers 99 --limit 16

echo "Results in $BASE/results/"
echo "No Japanese sidecars published; source-only timer untouched."
