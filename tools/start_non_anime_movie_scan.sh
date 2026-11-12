#!/usr/bin/env bash
# Launch ONE full non-anime movie source pass after other SubHub workers are idle.
# Uses the existing daily source unit so the dashboard shows genuine progress.
set -euo pipefail
umask 077
if [[ ${1-} != "" && ! "$1" =~ ^[0-9a-f]{40}$ ]]; then
  echo "Usage: start_non_anime_movie_scan.sh <pinned-40-hex-commit>" >&2
  exit 2
fi
if [[ $# -ne 1 ]]; then
  echo "Usage: start_non_anime_movie_scan.sh <pinned-40-hex-commit>" >&2
  exit 2
fi
PIN="$1"
LAUNCH_UNIT="bruiser-subhub-movies-launch.service"
active_state() {
  systemctl --user show -p ActiveState --value "$1"
}
case "$(active_state "$LAUNCH_UNIT")" in
  active|activating|reloading|deactivating)
    echo "MOVIE_SCAN_LAUNCH_ALREADY_QUEUED: $LAUNCH_UNIT"
    exit 0 ;;
esac

TASK="$(mktemp /tmp/bruiser-movie-scan.XXXXXX.sh)"
cat > "$TASK" <<'TASKBODY'
#!/usr/bin/env bash
set -euo pipefail
umask 077
PIN="$1"
INSTALLER=""
trap 'rm -f -- "$0"; if [[ -n "$INSTALLER" ]]; then rm -f -- "$INSTALLER"; fi' EXIT

# Do not replace working code or trigger another source run during any known
# source/owner job. Exit on unknown service states rather than guessing.
BUSY_UNITS=(
  bruiser-ja-source-autofill.service
  bruiser-subhub-season-sources.service
  bruiser-subhub-batch.service
  bruiser-subhub-translation-batch.service
  bruiser-subhub-movie-ja.service
  bruiser-subhub-jellyfin-source.service
  bruiser-subhub-finish-scope.service
)
idle=0
for attempt in {1..540}; do
  idle=1
  for unit in "${BUSY_UNITS[@]}"; do
    state="$(systemctl --user show -p ActiveState --value "$unit")"
    case "$state" in
      active|activating|deactivating|reloading)
        idle=0
        echo "MOVIE_SCAN_WAITING: $unit is $state"
        break ;;
      inactive|failed) ;;
      *) echo "MOVIE_SCAN_HELD: unknown $unit state $state" >&2; exit 1 ;;
    esac
  done
  if (( idle )); then break; fi
  sleep 60
done
if (( ! idle )); then
  echo "MOVIE_SCAN_HELD: workers still busy after 9 hours" >&2
  exit 1
fi

INSTALLER="$(mktemp /tmp/bruiser-installer.XXXXXX.py)"
curl -fsSL --retry 3 --connect-timeout 10 --max-time 90 \
  "https://raw.githubusercontent.com/SteezyMode/bruiser-subhub/$PIN/tools/install_global_ja_sourcing.py" \
  -o "$INSTALLER"
python3 -B "$INSTALLER" --commit "$PIN" --install-only

# Generate a fresh saved manifest. No subtitle-provider credit is consumed.
python3 -B "$HOME/bruiser-pilot/subhub-control/ja_first_catalog_manifest.py" --save

# This selection persists for future daily runs until changed by the owner.
python3 -B "$HOME/bruiser-pilot/subhub-control/ja_first_autofill.py" \
  scope --scope movies-no-anime --apply

# Start the same audited service the dashboard already monitors. Its search,
# staging, publishing, file safety and provider budgets remain unchanged.
systemctl --user start --no-block bruiser-ja-source-autofill.service
echo "MOVIE_SCAN_LAUNCHED: non-anime movies, no TV or PLaMo"
echo "DASHBOARD: Active work > Automatic Japanese sourcing"
echo "LOG: journalctl --user -u bruiser-ja-source-autofill.service -f"
TASKBODY
chmod 700 "$TASK"

state="$(active_state bruiser-ja-source-autofill.service)"
case "$state" in
  active|activating|reloading|deactivating)
    if ! systemd-run --user --unit=bruiser-subhub-movies-launch \
       --description="Install and launch all non-anime movie Japanese sourcing after current SubHub job" \
       --property=RuntimeMaxSec=9h \
       /usr/bin/bash "$TASK" "$PIN"; then
      rm -f -- "$TASK"
      exit 1
    fi
    echo "MOVIE_SCAN_QUEUED: waits for current SubHub job, then installs and starts scan"
    echo "CHECK_QUEUE: journalctl --user -u $LAUNCH_UNIT -n 15 --no-pager" ;;
  inactive|failed)
    /usr/bin/bash "$TASK" "$PIN" ;;
  *)
    rm -f -- "$TASK"
    echo "MOVIE_SCAN_HELD: unknown source service state $state" >&2
    exit 1 ;;
esac
