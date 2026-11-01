#!/usr/bin/env bash
set -euo pipefail
HOST="${1:?Usage: bash tools/check_heretic.sh optiplex@HOST}"
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
ssh "$HOST" "python3 - --root /home/optiplex/bruiser-pilot/subhub1-state --service /home/optiplex/bruiser-pilot/subhub1/service.py --job heretic-2024-1080p-10bit-web-84aa6649eb --show-text" < "$ROOT/tools/diagnose_invalid_ja.py"
