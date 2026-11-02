#!/usr/bin/env bash
# Real S19E04 readability repair without touching old pilot Japanese or media.
# A transient user systemd service survives MacBook SSH disconnect/shutdown.
# If the OptiPlex powers off, repeat this SAME command to resume checkpoints.
set -euo pipefail
if [[ $# -ne 1 ]]; then
  echo 'Usage: bash tools/run_s19e04_repair.sh optiplex@HOST' >&2
  exit 2
fi
HOST="$1"
ROOT="$(cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT"
echo '=== TEST EXISTING QUALITY RULES AND SHUTDOWN-SAFE CHECKPOINTS ==='
python3 -m unittest -q test_repair_s19e04 test_subtitle_publish_gate \
  test_subtitle_quality_010
echo '=== STAGE ONLY ISOLATED REPAIR CODE ==='
ssh "$HOST" \
 'mkdir -p -m 700 ~/bruiser-pilot/s19e04-repair-code ~/bruiser-pilot/american-dad-s19e04-repair'
scp -q \
  service.py \
  tools/american_dad_intake_009.py \
  tools/american_dad_core_009.py \
  tools/context_engine_008.py \
  tools/subtitle_quality_010.py \
  tools/subtitle_publish_gate.py \
  tools/repair_s19e04.py \
  "$HOST:~/bruiser-pilot/s19e04-repair-code/"
echo '=== READ-ONLY S19E04 SOURCE + ORIGINAL-JA CHECK ==='
ssh "$HOST" \
 'python3 ~/bruiser-pilot/s19e04-repair-code/repair_s19e04.py plan'
echo '=== START RESUMABLE REPAIR UNDER HOST USER SYSTEMD ==='
ssh "$HOST" 'bash -s' <<'REMOTE'
set -eu
UNIT='bruiser-s19e04-repair.service'
if systemctl --user is-active --quiet "$UNIT"; then
  echo 'S19E04_REPAIR_ALREADY_ACTIVE; no duplicate launched'
else
  systemd-run --user --collect \
    --unit='bruiser-s19e04-repair' \
    --property=Nice=15 \
    --property=CPUWeight=10 \
    --property=CPUQuota=250% \
    --property=MemoryMax=5G \
    --property=RuntimeMaxSec=4h \
    -- /usr/bin/python3 -u \
       "$HOME/bruiser-pilot/s19e04-repair-code/repair_s19e04.py" \
       run --max-minutes 180 --publish
  echo 'S19E04_REPAIR_LAUNCH_REQUESTED; original pilot unchanged'
fi
systemctl --user show "$UNIT" -p ActiveState -p SubState --no-pager || true
REMOTE
echo '=== CURRENT REPAIR LOG (NO SPEECH OR TRANSLATION TEXT) ==='
ssh "$HOST" \
  'journalctl --user -u bruiser-s19e04-repair.service -n 12 --no-pager || true'
echo
echo 'The new track appears in Jellyfin only if every repaired cue passes QA.'
echo 'MacBook power-off does not stop the host job. After OptiPlex shutdown,'
echo 'repeat this same command to resume previously verified private cue checkpoints.'
