#!/usr/bin/env bash
set -euo pipefail
HOST="${1:?Usage: bash tools/repair_pilot.sh optiplex@HOST /path/to/private-manifest.json}"
MANIFEST="${2:?Provide the private review/repair JSON manifest from the chat}"
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
[[ -f "$MANIFEST" ]] || { echo "Missing private manifest: $MANIFEST" >&2; exit 2; }
python3 -m unittest discover -p 'test_*.py' -q
scp -q service.py "$HOST:~/bruiser-pilot/subhub1/service.candidate.py"
scp -q tools/deploy_validator.py "$HOST:~/bruiser-pilot/deploy_validator.py"
scp -q tools/recover_cues.py "$HOST:~/bruiser-pilot/recover_cues.py"
ssh "$HOST" 'python3 ~/bruiser-pilot/deploy_validator.py'
ssh "$HOST" 'python3 ~/bruiser-pilot/recover_cues.py --manifest -' < "$MANIFEST"
ssh "$HOST" 'python3 ~/bruiser-pilot/recover_cues.py --manifest - --apply --publish' < "$MANIFEST"
