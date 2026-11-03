#!/usr/bin/env bash
# Download and test official FINAL CAT-Translate-3.3b, without modifying SubHub.
# Run on the OptiPlex host. Shows progress and ends with a finished/failed report.
set -Eeuo pipefail

ROOT="$HOME/bruiser-pilot/cat33-official-final"
PY="$ROOT/.venv/bin/python"
SRT="$ROOT/english.en.srt"
RUN="$ROOT/cat33_official_final_test.py"
LOG="$ROOT/cat33-test.log"
mkdir -p "$ROOT"
# One log for downloading, setup, and all raw translations.
exec > >(tee -a "$LOG") 2>&1

on_exit() {
    status=$?
    if [ "$status" -eq 0 ]; then
        printf '\nCAT33 OFFICIAL FINAL TEST FINISHED SUCCESSFULLY\n'
        printf 'Log: %s\nResults: %s\n' "$LOG" "$ROOT/cat33-final-results.json"
    else
        printf '\nCAT33 TEST FAILED (exit %s). Saved log: %s\n' "$status" "$LOG" >&2
    fi
}
trap on_exit EXIT

if [ -e "$ROOT/cat33-final-results.json" ]; then
    echo "Existing successful CAT33 report: $ROOT/cat33-final-results.json"
    echo "No repeated inference or overwriting required."
    exit 0
fi

command -v python3 >/dev/null || { echo "Missing python3" >&2; exit 1; }
command -v docker >/dev/null || { echo "Missing docker" >&2; exit 1; }
command -v nvidia-smi >/dev/null || { echo "Missing NVIDIA CUDA device" >&2; exit 1; }
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader
available_kb=$(df -Pk "$ROOT" | awk 'NR==2 {print $4}')
if (( available_kb < 20971520 )); then
    echo "Need at least 20 GiB free to install model, Python/CUDA dependencies and cache." >&2
    exit 1
fi

if [ ! -f "$SRT" ]; then
    # Use the EXACT already-extracted English track from The Chair Company.
    # Does not change container, media or installed translation services.
    docker cp \
      "sublarr-pilot:/tmp/subhub-hy-mt2-full-chair-test/original.en.srt" \
      "$SRT"
fi

if [ ! -x "$PY" ]; then
    echo "Creating isolated Python environment: $ROOT/.venv"
    python3 -m venv "$ROOT/.venv"
fi

# Keep Python/CUDA/Transformers dependencies isolated from the working server.
# The official model uses Transformers. Bitsandbytes 4-bit is solely for 6GB VRAM.
echo "Installing standard PyTorch / Transformers CUDA dependencies in isolated venv"
"$PY" -m pip install --disable-pip-version-check --no-input --progress-bar off \
  'torch>=2.5,<3' \
  'transformers>=4.57,<5' \
  'accelerate>=1,<2' \
  'bitsandbytes>=0.46,<1' \
  'huggingface_hub>=0.35,<2' \
  'sentencepiece>=0.2' \
  'protobuf>=4.25,<7'

if [ ! -f "$RUN" ]; then
    echo "Missing official test file: $RUN" >&2
    exit 1
fi
"$PY" -m py_compile "$RUN"

echo
echo "STARTING ACTUAL FINAL CAT-TRANSLATE 3.3B TEST"
echo "English: $SRT"
echo "Progress: model download / GPU load / four documented-prompt translations"
echo
export PYTHONUNBUFFERED=1
export HF_HUB_DOWNLOAD_TIMEOUT=90
export HF_HUB_ETAG_TIMEOUT=30
export OMP_NUM_THREADS=4
"$PY" -u "$RUN" --source "$SRT" --workdir "$ROOT"
