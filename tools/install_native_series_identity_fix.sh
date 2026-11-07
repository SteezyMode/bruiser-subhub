#!/usr/bin/env bash
# Pin exact code, test before install, and refresh existing Jellyfin inventory.
# Only source tools + dashboard files change. No videos, torrents or existing
# subtitle sidecars are touched by this installer.
set -Eeuo pipefail
umask 077

if [[ $# -ne 1 || ! "$1" =~ ^[0-9a-f]{40}$ ]]; then
  echo "Usage: install_native_series_identity_fix.sh <pinned-commit>" >&2
  exit 2
fi
PIN="$1"
PREVIOUS="6fd2631c98c21a316d4a2e166cb7798690b911c2"
REPO="https://raw.githubusercontent.com/SteezyMode/bruiser-subhub"
CODE="$HOME/bruiser-pilot/subhub-control"
WORK="$(mktemp -d)"
ROLLBACK=0
SOURCE_FILES=(ja_first_catalog_manifest.py ja_first_stage_saved_batch.py)

cleanup() {
  status=$?
  trap - EXIT
  if [[ "$ROLLBACK" == 1 ]]; then
    echo "Rolling back source module changes after failed validation." >&2
    for name in "${SOURCE_FILES[@]}"; do
      if [[ -f "$WORK/backup/$name" ]]; then
        cp "$WORK/backup/$name" "$CODE/$name.rollback"
        chmod 600 "$CODE/$name.rollback"
        mv -f "$CODE/$name.rollback" "$CODE/$name"
      fi
    done
  fi
  rm -rf "$WORK"
  exit "$status"
}
trap cleanup EXIT

if [[ ! -d "$CODE" || -L "$CODE" ||
      "$(stat -c %u "$CODE")" != "$(id -u)" ]]; then
  echo "Existing private source directory missing, symlinked or unowned." >&2
  exit 1
fi

# Hold the SAME flock file as the scheduled Japanese source worker. This
# prevents a fresh timer firing during module or manifest replacement.
LOCK_ROOT="$HOME/bruiser-pilot/ja-first-inventory"
LOCK="$LOCK_ROOT/.autofill.lock"
if [[ ! -d "$LOCK_ROOT" || -L "$LOCK_ROOT" || -L "$LOCK" ||
      "$(stat -c %u "$LOCK_ROOT")" != "$(id -u)" ]]; then
  echo "Unsafe native sourcing inventory/lock path." >&2
  exit 1
fi
if [[ -e "$LOCK" && ( ! -f "$LOCK" ||
      "$(stat -c %u "$LOCK")" != "$(id -u)" ||
      "$(stat -c %a "$LOCK")" != 600 ) ]]; then
  echo "Unsafe existing source lock." >&2
  exit 1
fi
exec 9>>"$LOCK"
flock -n 9 || { echo "Another Japanese source cycle is running." >&2; exit 1; }

for unit in bruiser-ja-source-autofill.service bruiser-subhub-batch.service \
            bruiser-subhub-season-sources.service bruiser-subhub-translation-batch.service; do
  state="$(systemctl --user show --property=ActiveState --value "$unit")"
  case "$state" in
    inactive|failed) ;;
    *) echo "Cannot update while $unit state=$state" >&2; exit 1 ;;
  esac
done

mkdir -p "$WORK/tools" "$WORK/previous" "$WORK/backup"
touch "$WORK/tools/__init__.py"
for name in "${SOURCE_FILES[@]}"; do
  if [[ ! -f "$CODE/$name" || -L "$CODE/$name" ||
        "$(stat -c %u "$CODE/$name")" != "$(id -u)" ]]; then
    echo "Installed source file missing, symlinked or unowned: $name" >&2
    exit 1
  fi
  curl -fsSL --retry 3 --connect-timeout 10 --max-time 90 \
    "$REPO/$PIN/tools/$name" -o "$WORK/tools/$name"
  curl -fsSL --retry 3 --connect-timeout 10 --max-time 90 \
    "$REPO/$PREVIOUS/tools/$name" -o "$WORK/previous/$name"
  if ! cmp -s "$CODE/$name" "$WORK/previous/$name" &&
     ! cmp -s "$CODE/$name" "$WORK/tools/$name"; then
    echo "STOP: locally installed $name differs from reviewed code." >&2
    echo "No source files, catalogs or services were modified." >&2
    exit 1
  fi
  cp -p "$CODE/$name" "$WORK/backup/$name"
done

for name in ja_first_priority.py ja_first_search_pilot.py; do
  curl -fsSL --retry 3 --connect-timeout 10 --max-time 90 \
    "$REPO/$PIN/tools/$name" -o "$WORK/tools/$name"
done
curl -fsSL --retry 3 --connect-timeout 10 --max-time 90 \
  "$REPO/$PIN/test_ja_first_native_series_identity.py" \
  -o "$WORK/test_ja_first_native_series_identity.py"
curl -fsSL --retry 3 --connect-timeout 10 --max-time 90 \
  "$REPO/$PIN/tools/install_subhub_dashboard.sh" \
  -o "$WORK/install_subhub_dashboard.sh"

echo "=== OFFLINE NEW SERIES IDENTITY TESTS ==="
(
  cd "$WORK"
  PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$WORK" \
    python3 -B -m unittest -v test_ja_first_native_series_identity
)

echo "=== INSTALL REVIEWED SOURCE TOOLS ==="
for name in "${SOURCE_FILES[@]}"; do
  install -m 600 "$WORK/tools/$name" "$CODE/$name.new"
done
ROLLBACK=1
for name in "${SOURCE_FILES[@]}"; do
  mv -f "$CODE/$name.new" "$CODE/$name"
done

echo "=== REFRESH JELLYFIN INTAKE (NO PROVIDER CALLS) ==="
PYTHONDONTWRITEBYTECODE=1 python3 -B -u \
  "$CODE/ja_first_catalog_manifest.py" --save

echo "=== CONFIRM IASIP S12 IS SOURCE ELIGIBLE ==="
python3 - <<'PY'
from collections import Counter
import json
from pathlib import Path
root = Path.home() / "bruiser-pilot/ja-first-inventory"
manifests = sorted(root.glob("ja-intake-*.json"))
if not manifests:
    raise SystemExit("Missing refreshed Japanese intake manifest")
items = json.loads(manifests[-1].read_text(encoding="utf-8"))["items"]
s12 = [x for x in items if x.get("series_title") == "It's Always Sunny in Philadelphia"
       and x.get("season") == 12 and x.get("kind") == "Episode"]
c = Counter(x.get("status") for x in s12)
print("IASIP_S12_SOURCE_ELIGIBILITY",dict(c),"total",len(s12),flush=True)
if len(s12) != 10 or any(x.get("status") not in
   ("ready_ja_search", "existing_japanese_subtitle") for x in s12):
    raise SystemExit("Source identity remains unresolved: no provider search started")
PY

# The refreshed manifest is now consistent with the new source modules.
ROLLBACK=0
echo "=== UPDATE DASHBOARD (INSTALLER RUNS ITS OWN OFFLINE TESTS) ==="
bash "$WORK/install_subhub_dashboard.sh" "$PIN"

echo "IASIP_SEASON_SOURCE_IDENTITY_READY"
echo "No Japanese source searches, PLaMo jobs, torrents or media changes started."
