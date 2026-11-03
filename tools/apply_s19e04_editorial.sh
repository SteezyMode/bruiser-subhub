#!/usr/bin/env bash
# Transfer privately reviewed S19E04 corrections from Mac to OptiPlex.
# DO NOT commit/private-upload the payload to GitHub. Originals untouched.
set -euo pipefail
if [[ $# -ne 2 ]]; then
  echo 'Usage: bash tools/apply_s19e04_editorial.sh optiplex@HOST ~/Downloads/s19e04_private_editorial_27.json' >&2
  exit 2
fi
HOST="$1"
PAYLOAD="$2"
if [[ ! -f "$PAYLOAD" || -L "$PAYLOAD" ]]; then
  echo 'EDITORIAL_PAYLOAD_MISSING: download the private 27-cue file to your Mac first' >&2
  exit 2
fi
ROOT="$(cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT"

echo '=== OFFLINE REAL-SRT AND ORIGINAL-PRESERVATION REGRESSION TESTS ==='
python3 -m unittest -q \
  test_s19e04_apply_private_editorial \
  test_repair_s19e04 test_s19e04_recovery_v2 \
  test_subtitle_publish_gate

echo '=== VERIFY NO ORIGINAL S19E04 OR SELECTED-SEASON JOB IS ACTIVE ==='
if ssh "$HOST" 'systemctl --user is-active --quiet bruiser-s19e04-repair.service || systemctl --user is-active --quiet bruiser-american-dad-maintenance.service'; then
  echo 'A real subtitle service is still active; no concurrent editorial publication attempted.'
  exit 2
fi

echo '=== STAGE PRIVATE EDITORIAL OVERLAY; NOTHING SAVED TO GITHUB ==='
ssh "$HOST" 'mkdir -p -m 700 ~/bruiser-pilot/s19e04-editorial-code'
scp -q service.py \
  tools/american_dad_intake_009.py \
  tools/american_dad_core_009.py \
  tools/context_engine_008.py \
  tools/subtitle_quality_010.py \
  tools/subtitle_publish_gate.py \
  tools/s19e04_recovery_v2.py \
  tools/repair_s19e04.py \
  tools/s19e04_apply_private_editorial.py \
  "$HOST:~/bruiser-pilot/s19e04-editorial-code/"
scp -q "$PAYLOAD" \
  "$HOST:~/bruiser-pilot/s19e04-editorial-code/private-editorial.json"
ssh "$HOST" 'chmod 600 ~/bruiser-pilot/s19e04-editorial-code/private-editorial.json'

echo '=== RECONSTRUCT AND AUDIT ALL 392 REAL CUES; PRIVATE PREVIEW ONLY ==='
ssh "$HOST" \
  'python3 ~/bruiser-pilot/s19e04-editorial-code/s19e04_apply_private_editorial.py ~/bruiser-pilot/s19e04-editorial-code/private-editorial.json'

echo '=== CREATE NEW VERSIONED JAPANESE SRT ONLY IF WHOLE EPISODE PASSES ==='
ssh "$HOST" \
  'python3 ~/bruiser-pilot/s19e04-editorial-code/s19e04_apply_private_editorial.py ~/bruiser-pilot/s19e04-editorial-code/private-editorial.json --publish'

echo '=== DONE: CHECK FOR S19E04_EDITORIAL_PUBLISHED (not merely exit code 0) ==='
echo 'Existing Bruiser Pilot Japanese v009 and every private v1/v2 checkpoint remain intact.'
echo 'If held, report the exact quality reasons; do not run more model loops.'
