#!/usr/bin/env bash
# Repair ONLY the American Dad scheduled worker lifecycle (2026-11-02).
# The old one-shot maintenance service spawned a detached season child, then
# systemd killed that child when the one-shot service completed.
# This deploys the supervised-foreground fix and safely upgrades that exact
# known unit. Does not restart Jellyfin, Ollama, Caddy, Sublarr or Docker.
set -euo pipefail
if [[ $# -ne 1 ]]; then
  echo 'Usage: bash tools/repair_american_dad_worker.sh optiplex@HOST' >&2
  exit 2
fi
HOST="$1"
ROOT="$(cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT"

echo '=== REGRESSION TESTS FOR SERVICE LIFECYCLE ==='
python3 -m unittest -q test_american_dad_maintenance \
  test_enable_american_dad_timer test_american_dad_autopilot
echo '=== ENSURE AN EXISTING SUPERVISED RUN IS NOT INTERRUPTED ==='
if ssh "$HOST" \
  'systemctl --user is-active --quiet bruiser-american-dad-maintenance.service'; then
  echo 'The maintenance service is already active; refusing an in-place repair during work.'
  echo 'Review its journal and re-run this command after it finishes.'
  exit 0
fi
echo '=== STAGE ONLY FIXED OWNER-SIDE AUTOMATION HELPERS ==='
ssh "$HOST" 'mkdir -p -m 700 ~/bruiser-pilot/american-dad-auto-code'
scp -q tools/american_dad_maintenance.py tools/enable_american_dad_timer.py \
  "$HOST:~/bruiser-pilot/american-dad-auto-code/"

echo '=== UPGRADE THE EXACT KNOWN OLD USER UNIT, PRESERVING BACKUP ==='
ssh "$HOST" 'bash -s' <<'REMOTE'
set -eu
SCRIPT="$HOME/bruiser-pilot/american-dad-auto-code/enable_american_dad_timer.py"
python3 "$SCRIPT"
UNIT="$HOME/.config/systemd/user/bruiser-american-dad-maintenance.service"
if ! grep -Fq 'ExecStart=/usr/bin/python3 -u %h/' "$UNIT"; then
  echo 'REPAIR_BLOCKED: supervised ExecStart not installed' >&2
  exit 1
fi
if ! grep -Fq 'Type=exec' "$UNIT"; then
  echo 'REPAIR_BLOCKED: long-running systemd Type=exec not installed' >&2
  exit 1
fi
if ! grep -Fq 'RuntimeMaxSec=11h' "$UNIT"; then
  echo 'REPAIR_BLOCKED: long-running systemd service timeout not installed' >&2
  exit 1
fi
if systemctl --user is-active --quiet bruiser-american-dad-maintenance.service; then
  echo 'WORKER_ALREADY_RUNNING; no restart attempted'
else
  systemctl --user start --no-block bruiser-american-dad-maintenance.service
  echo 'WORKER_LAUNCH_REQUESTED: selected season, supervised foreground'
fi
systemctl --user show bruiser-american-dad-maintenance.service \
  -p ActiveState -p SubState --no-pager
REMOTE

echo '=== READ-ONLY CHECK AFTER WORKER REQUEST ==='
ssh "$HOST" \
  'journalctl --user -u bruiser-american-dad-maintenance.service -n 9 --no-pager'
echo
echo 'Track worker with:'
echo "ssh $HOST 'journalctl --user -u bruiser-american-dad-maintenance.service -n 40 --no-pager; tail -40 ~/bruiser-pilot/subhub1-state/american-dad-seasons.log'"
echo 'No generic restart/kill command was issued.'
