#!/usr/bin/env bash
# Controlled multi-model sweep. Downloads only specific documented model tags.
# Safe per-arm independent private outputs; failures never erase other results.
set -euo pipefail
HOST="${1:?Usage: bash tools/run_model_sweep_005.sh optiplex@HOST [small|all|cat33|tuned|cat7|hy7|google12]}"
MODE="${2:-all}"
case "$MODE" in
  all) ARMS=(cat33 tuned cat7 hy7 google12) ;;
  small) ARMS=(cat33 tuned cat7 hy7) ;;
  cat33|tuned|cat7|hy7|google12) ARMS=("$MODE") ;;
  *) echo "Unknown model arm: $MODE" >&2; exit 2 ;;
esac
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
python3 -m unittest discover -p 'test_*.py' -q
echo "STAGING isolated model benchmark; live translator untouched"
ssh "$HOST" 'mkdir -p ~/bruiser-pilot/subhub-benchmark ~/bruiser-pilot/subhub1-state/review'
scp -q service.py localization_policy.py \
  tools/benchmark_localization.py tools/model_benchmark.py \
  tools/benchmark_native_subtitles.py tools/benchmark_translategemma_004.py \
  tools/analyze_model_benchmark.py tools/model_sweep_005.py \
  "$HOST:~/bruiser-pilot/subhub-benchmark/"
echo "=== SOURCE PREFLIGHT BEFORE ANY MODEL DOWNLOAD ==="
ssh "$HOST" "python3 ~/bruiser-pilot/subhub-benchmark/model_sweep_005.py --model tuned --out ~/bruiser-pilot/subhub1-state/review/never-created-source-only.json --source-only"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
DEST="$HOME/Downloads/model-sweep-005-$STAMP"
mkdir -p -m 700 "$DEST"
printf 'Model sweep 005; UTC %s\n' "$STAMP" > "$DEST/STATUS.txt"
echo "PRIVATE RESULTS DIR: $DEST"
echo "HOST STORAGE: "
ssh "$HOST" 'df -h ~ | tail -1'
echo "OTHER OLLAMA MODELS CURRENTLY LOADED:"
ssh "$HOST" 'ollama ps || true'

for ARM in "${ARMS[@]}"; do
  if [ "$ARM" = cat33 ]; then
    echo "=== CAT 3.3B FINAL — separate CUDA Transformers environment ==="
    if bash tools/run_cat33_005.sh "$HOST" "$DEST" 2>&1 | tee "$DEST/cat33-run.log"; then
      printf 'cat33\tcomplete\n' >> "$DEST/STATUS.txt"
    else
      echo "CAT 3.3B failed or is blocked; continuing other models"
      printf 'cat33\tBLOCKED or incomplete — see separate output\n' >> "$DEST/STATUS.txt"
    fi
    continue
  fi
  case "$ARM" in
    tuned) MODEL='hf.co/17slever17/translate-gemma-4-sub-e4b-GGUF:Q4_K_XL' ;;
    cat7) MODEL='hf.co/mradermacher/CAT-Translate-7b-GGUF:Q4_K_M' ;;
    hy7) MODEL='hf.co/tencent/Hy-MT2-7B-GGUF:Q4_K_M' ;;
    google12) MODEL='translategemma:12b' ;;
  esac
  FILE="model-sweep-005-$ARM-$STAMP.json"
  CMD="python3 ~/bruiser-pilot/subhub-benchmark/model_sweep_005.py --model $ARM --out ~/bruiser-pilot/subhub1-state/review/$FILE --max-seconds 3600"
  echo
  echo "=== $ARM | pinned tag $MODEL ==="
  echo "This test can use local GPU and CPU offload; worker locks will prevent a concurrent SubHub runner."
  if ! ssh "$HOST" 'ollama list' | grep -Fq "$MODEL"; then
    if [ "$ARM" = tuned ]; then
      echo "BLOCKED: original tuned model not installed; refusing to replace baseline"
      printf '%s\tBLOCKED tuned baseline missing\n' "$ARM" >> "$DEST/STATUS.txt"
      continue
    fi
    echo "Installing documented Q4 model tag $MODEL"
    if ! ssh "$HOST" "ollama pull '$MODEL'"; then
      echo "BLOCKED: model download failed; continuing other candidates"
      printf '%s\tBLOCKED download\n' "$ARM" >> "$DEST/STATUS.txt"
      continue
    fi
  fi
  if ! ssh "$HOST" "$CMD --dry-run" 2>&1 | tee "$DEST/$ARM-preflight.log"; then
    echo "BLOCKED: model metadata/source preflight; continuing"
    printf '%s\tBLOCKED preflight\n' "$ARM" >> "$DEST/STATUS.txt"
    continue
  fi
  STATUS='complete'
  if ! ssh "$HOST" "$CMD" 2>&1 | tee "$DEST/$ARM-model-run.log"; then
    STATUS='failed-or-partial'
    echo "Model arm stopped or failed. Attempting to retrieve private partial result."
  fi
  if scp -q "$HOST:~/bruiser-pilot/subhub1-state/review/$FILE" "$DEST/$FILE"; then
    echo "Saved private result $DEST/$FILE"
    printf '%s\t%s\t%s\n' "$ARM" "$STATUS" "$FILE" >> "$DEST/STATUS.txt"
  else
    echo "No result file; model may be runtime-incompatible"
    printf '%s\tBLOCKED no output\n' "$ARM" >> "$DEST/STATUS.txt"
  fi
done
echo
echo "=== MODEL SWEEP REPORT ==="
cat "$DEST/STATUS.txt"
echo
echo "=== TRYING A BLINDED REVIEW PACK (only complete, matching arms) ==="
shopt -s nullglob
RESULTS=("$DEST"/model-sweep-005-*.json)
if [ "${#RESULTS[@]}" -ge 2 ]; then
  if python3 tools/blind_model_sweep_005.py "${RESULTS[@]}" \
    --out "$DEST/BLIND_REVIEW.json" --key "$DEST/BLIND_IDENTITY_KEY.json"; then
    echo "Blind review is ready; keep the identity key hidden during language scoring."
  else
    echo "Blinding skipped; one arm may be incomplete/mismatched. Individual model results are retained."
  fi
fi
echo "Files in $DEST contain PRIVATE English and Japanese film dialogue. Do not commit to GitHub."
