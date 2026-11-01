#!/usr/bin/env bash
set -euo pipefail
HOST="${1:?Usage: bash tools/repair_heretic_hold.sh optiplex@HOST /path/to/private-manifest.json}"
MANIFEST="${2:?Provide the private single-cue repair manifest}"
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
[[ -f "$MANIFEST" ]] || { echo "Private manifest not found: $MANIFEST" >&2; exit 2; }
python3 -m unittest discover -p 'test_*.py' -q
# Copy auxiliary tooling only; do not overwrite service.py or start a worker.
scp -q tools/recover_cues.py tools/scan_checkpoint_contamination.py tools/diagnose_invalid_ja.py "$HOST:~/bruiser-pilot/"
echo "=== Existing checkpoints: read-only audit ==="
ssh "$HOST" 'python3 ~/bruiser-pilot/scan_checkpoint_contamination.py --root ~/bruiser-pilot/subhub1-state --service ~/bruiser-pilot/subhub1/service.py'
echo "=== Source-verified DRY RUN ==="
ssh "$HOST" 'python3 ~/bruiser-pilot/recover_cues.py --manifest -' < "$MANIFEST"
echo "=== Apply one verified correction, back up DB and try safe publication ==="
ssh "$HOST" 'python3 ~/bruiser-pilot/recover_cues.py --manifest - --apply --publish' < "$MANIFEST"
echo "=== Updated checkpoints: read-only audit ==="
ssh "$HOST" 'python3 ~/bruiser-pilot/scan_checkpoint_contamination.py --root ~/bruiser-pilot/subhub1-state --service ~/bruiser-pilot/subhub1/service.py'
