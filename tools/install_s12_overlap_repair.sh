#!/usr/bin/env bash
# Narrow, source-safe IASIP E04/E05 overlap repair deployment.
# Only updates the verified local ffsubsync module and installs ONE new helper.
# No video, Jellyfin metadata, older subtitles or credentials are replaced.
set -Eeuo pipefail
umask 077

if [[ $# -ne 1 || ! "$1" =~ ^[0-9a-f]{40}$ ]]; then
  echo "Usage: install_s12_overlap_repair.sh <pinned-commit>" >&2
  exit 2
fi
PIN="$1"
REPO=https://raw.githubusercontent.com/SteezyMode/bruiser-subhub
PREVIOUS=6a52b2f8df63f932a13b333c8ad9cc852d491941
CODE="$HOME/bruiser-pilot/subhub-control"
ROOT="$HOME/bruiser-pilot/ja-first-inventory"
TARGET="$CODE/ja_first_ffsubsync.py"
HELPER="$CODE/repair_iasip_s12_overlap.py"
UNIT=bruiser-subhub-s12-overlap-repair
WORK="$(mktemp -d)"
ROLLBACK=0

cleanup() {
  code=$?
  trap - EXIT
  if [[ "$ROLLBACK" == 1 ]]; then
    echo "Installer failed before launch; restoring source module." >&2
    if [[ -f "$WORK/original" ]]; then
      cp -p "$WORK/original" "$TARGET.rollback"
      mv -f "$TARGET.rollback" "$TARGET"
    fi
    # A failed install leaves no media changes; preserve existing helpers.
  fi
  rm -rf "$WORK"
  exit "$code"
}
trap cleanup EXIT

for root in "$CODE" "$ROOT"; do
  if [[ ! -d "$root" || -L "$root" ||
        "$(stat -c %u "$root")" != "$(id -u)" ]]; then
    echo "STOP: required private source folder missing, symlinked or unowned: $root" >&2
    exit 1
  fi
done
if [[ ! -f "$TARGET" || -L "$TARGET" ||
      "$(stat -c %u "$TARGET")" != "$(id -u)" ||
      -L "$HELPER" ]]; then
  echo "STOP: installed source module or target helper unsafe" >&2
  exit 1
fi
if [[ -e "$ROOT/.autofill.lock" &&
     ( ! -f "$ROOT/.autofill.lock" || -L "$ROOT/.autofill.lock" ||
       "$(stat -c %u "$ROOT/.autofill.lock")" != "$(id -u)" ) ]]; then
  echo "STOP: source lock file unsafe" >&2
  exit 1
fi
exec 9>>"$ROOT/.autofill.lock"
flock -n 9 || { echo "STOP: a source job is already running." >&2; exit 1; }

for service in \
  bruiser-subhub-batch.service \
  bruiser-ja-source-autofill.service \
  bruiser-subhub-season-sources.service \
  bruiser-subhub-translation-batch.service \
  bruiser-subhub-s12-recovery.service \
  "$UNIT.service"; do
  state="$(systemctl --user show --property=ActiveState --value "$service")"
  case "$state" in
    inactive|failed) ;;
    *) echo "STOP: $service state=$state; no code installed" >&2; exit 1 ;;
  esac
done

mkdir -p "$WORK/tools"
touch "$WORK/tools/__init__.py"
for name in \
    ja_first_ffsubsync.py \
    ja_first_obvious_quality.py \
    ja_first_publish_staged.py \
    ja_first_publish_shifted.py \
    ja_first_publish_queue.py \
    ja_first_stage_saved_batch.py \
    ja_first_stage_timing_audit.py \
    ja_first_priority.py \
    bruiser_ja_movie_rescue.py \
    ja_first_autofill.py \
    repair_iasip_s12_overlap.py; do
  curl -fsSL --retry 3 --connect-timeout 10 --max-time 90 \
    "$REPO/$PIN/tools/$name" -o "$WORK/tools/$name"
done
for test in test_ja_first_ffsubsync.py test_repair_iasip_s12_overlap.py; do
  curl -fsSL --retry 3 --connect-timeout 10 --max-time 90 \
    "$REPO/$PIN/$test" -o "$WORK/$test"
done
curl -fsSL --retry 3 --connect-timeout 10 --max-time 90 \
  "$REPO/$PREVIOUS/tools/ja_first_ffsubsync.py" -o "$WORK/previous"
curl -fsSL --retry 3 --connect-timeout 10 --max-time 90 \
  "$REPO/$PIN/tools/install_s12_overlap_repair.sh" -o "$WORK/installer.sh"

bash -n "$WORK/installer.sh"
if ! cmp -s "$TARGET" "$WORK/previous" &&
   ! cmp -s "$TARGET" "$WORK/tools/ja_first_ffsubsync.py"; then
  echo "STOP: installed ffsubsync differs from reviewed code; no files modified." >&2
  exit 1
fi
if [[ -e "$HELPER" ]] && ! cmp -s "$HELPER" "$WORK/tools/repair_iasip_s12_overlap.py"; then
  echo "STOP: existing repair helper differs; refusing to overwrite." >&2
  exit 1
fi

echo "=== OFFLINE REPAIR SAFETY TESTS ==="
(
  cd "$WORK"
  PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$WORK" \
    python3 -B -m unittest -v \
      test_ja_first_ffsubsync test_repair_iasip_s12_overlap
)

echo "=== INSTALL ONLY VERIFIED SOURCE MODULE AND TARGETED HELPER ==="
cp -p "$TARGET" "$WORK/original"
install -m 600 "$WORK/tools/ja_first_ffsubsync.py" "$TARGET.new"
install -m 600 "$WORK/tools/repair_iasip_s12_overlap.py" "$HELPER.new"
ROLLBACK=1
mv -f "$TARGET.new" "$TARGET"
mv -f "$HELPER.new" "$HELPER"
# The worker must acquire the same lock itself, after installer releases it.
exec 9>&-

echo "=== LAUNCH E04/E05 RETRY AS DETACHED USER SERVICE ==="
systemctl --user reset-failed "$UNIT.service" >/dev/null 2>&1 || true
systemd-run --user --unit="$UNIT" --collect \
  --property=RuntimeMaxSec=2h \
  --property=KillMode=control-group \
  --property=Nice=10 -- \
  /usr/bin/python3 -B -u "$HELPER" --run
ROLLBACK=0
echo "S12_OVERLAP_REPAIR_LAUNCHED"
echo "Only episodes: S12E04 and S12E05. No provider calls or AI started."
echo "Watch: journalctl --user -fu $UNIT.service -o cat"
echo "Result: journalctl --user -u $UNIT.service -n 50 -o cat --no-pager"
