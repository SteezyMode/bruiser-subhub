#!/usr/bin/env bash
set -euo pipefail
HOST="${1:?Usage: bash tools/deploy_batch_fix.sh optiplex@TAILSCALE_IP}"
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
python3 -m unittest discover -p 'test_*.py' -q
scp -q "$ROOT/service.py" "$HOST:~/bruiser-pilot/subhub1/service.candidate.py"
scp -q "$ROOT/tools/deploy_batch_fix.py" "$HOST:~/bruiser-pilot/deploy_batch_fix.py"
ssh "$HOST" 'python3 ~/bruiser-pilot/deploy_batch_fix.py'
