#!/usr/bin/env bash
# Read-only diagnostics for Benchmark 005 blocked arms. No inference/downloads.
set -euo pipefail
HOST="${1:?Usage: bash tools/diagnose_model_sweep_005.sh optiplex@HOST}"
ssh "$HOST" 'bash -s' <<'REMOTE'
set -u
ROOT="$HOME/bruiser-pilot/subhub-benchmark"
VENV="$HOME/bruiser-pilot/subhub-cat33-venv"
STATE="$HOME/bruiser-pilot/subhub1-state"
echo '=== 005 DIAGNOSTICS: NO FILE WRITES, MODEL PULLS OR INFERENCE ==='
echo
echo '=== OLLAMA VERSION / RELEVANT MODEL INVENTORY ==='
ollama --version || true
ollama list | grep -E '^NAME|translate-gemma-4-sub|CAT-Translate|Hy-MT2|translategemma' || true
echo
echo '=== ORIGINAL TUNED MODEL PREFLIGHT: SHOW ACTUAL FAILURE ==='
if [ -f "$ROOT/model_sweep_005.py" ]; then
  python3 "$ROOT/model_sweep_005.py" \
    --model tuned \
    --out "$STATE/review/diagnostic-should-not-be-created.json" \
    --dry-run 2>&1 || true
else
  echo "MISSING: $ROOT/model_sweep_005.py"
fi
echo
echo '=== TUNED OLLAMA /api/show: ID, FAMILY, QUANT (NO PROMPT) ==='
python3 - <<'PY'
import json
import urllib.request
tag='hf.co/17slever17/translate-gemma-4-sub-e4b-GGUF:Q4_K_XL'
req=urllib.request.Request('http://127.0.0.1:11434/api/show',
    data=json.dumps({'model':tag}).encode(),
    headers={'Content-Type':'application/json'})
try:
    with urllib.request.urlopen(req,timeout=10) as conn:
        result=json.load(conn)
    detail=result.get('details') or {}
    print('model:',tag)
    print('family:',detail.get('family'))
    print('quantization_level:',detail.get('quantization_level'))
    print('parameter_size:',detail.get('parameter_size'))
except Exception as exc:
    print('SHOW ERROR:',type(exc).__name__,str(exc)[:350])
PY
echo
echo '=== FINAL CAT 3.3B CUDA VENV CHECK (NO MODEL WEIGHTS LOADED) ==='
if [ -x "$VENV/bin/python" ]; then
  "$VENV/bin/python" - <<'PY'
import importlib
for name in ('torch','transformers','accelerate','bitsandbytes','huggingface_hub'):
    try:
        module=importlib.import_module(name)
        print(name,'version',getattr(module,'__version__','?'))
    except Exception as exc:
        print(name,'IMPORT ERROR:',type(exc).__name__,str(exc)[:350])
try:
    import torch
    print('torch CUDA available:',torch.cuda.is_available())
    if torch.cuda.is_available():
        free,total=torch.cuda.mem_get_info()
        print('CUDA memory free/total MiB:',round(free/1024**2),round(total/1024**2))
except Exception as exc:
    print('CUDA ERROR:',type(exc).__name__,str(exc)[:350])
PY
  echo '=== CAT FINAL SAFE SOURCE+ENV PREFLIGHT ==='
  "$VENV/bin/python" "$ROOT/model_sweep_cat33_005.py" \
    --out "$STATE/review/diagnostic-should-not-be-created.json" \
    --dry-run 2>&1 || true
else
  echo "MISSING or broken isolated venv: $VENV/bin/python"
fi
echo
echo '=== FREE DISK / VRAM ==='
df -h "$HOME" | tail -1
nvidia-smi --query-gpu=name,memory.total,memory.free \
  --format=csv,noheader 2>/dev/null || true
echo '=== READ-ONLY DIAGNOSTICS COMPLETE ==='
REMOTE
