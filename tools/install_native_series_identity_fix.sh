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
  cp -p "$CODE/$name" "$WORK/backup/$name"
done

# Never discard a local source policy to satisfy a GitHub version check.
# One known local variant of the intake removes the unknown-audio gate.
# Reconstruct and verify that variant BYTE FOR BYTE from the reviewed old
# version, then preserve that exact policy in the new intake. Unexpected
# changes remain a hard stop.
python3 - "$WORK/previous/ja_first_catalog_manifest.py" \
          "$CODE/ja_first_catalog_manifest.py" \
          "$WORK/tools/ja_first_catalog_manifest.py" \
          "$WORK/previous/ja_first_stage_saved_batch.py" \
          "$CODE/ja_first_stage_saved_batch.py" \
          "$WORK/tools/ja_first_stage_saved_batch.py" \
          "$WORK/guardless-source-policy" <<'PY'
from pathlib import Path
import sys
old_manifest, installed_manifest, new_manifest, old_stage, installed_stage, new_stage, marker = [
    Path(p) for p in sys.argv[1:]
]

def omit_unknown_audio_gate(content):
    substitutions = (
        (
            'UNKNOWN_AUDIO = {"", "und", "unknown", "mul", "zxx", "none"}\n',
            ''
        ),
        (
            '          "review_audio_language_unverified", "review_no_movie_imdb", "review_missing_series_identity",',
            '          "review_no_movie_imdb", "review_missing_series_identity",'
        ),
        (
            '    elif audio_lang in UNKNOWN_AUDIO:\n'
            '        # A present audio stream with no language tag is NOT evidence of EN\n'
            '        # audio. Never spend JA search quota on a potentially Japanese show.\n'
            '        data["status"] = "review_audio_language_unverified"\n',
            ''
        ),
        (
            '    assert lang("und") in UNKNOWN_AUDIO and lang("jpn") not in UNKNOWN_AUDIO\n',
            ''
        ),
    )
    for original, replacement in substitutions:
        if content.count(original) != 1:
            raise RuntimeError("reviewed_unknown_audio_gate_layout_changed")
        content = content.replace(original, replacement)
    return content

old = old_manifest.read_text(encoding="utf-8")
installed = installed_manifest.read_text(encoding="utf-8")
proposed = new_manifest.read_text(encoding="utf-8")
if installed == old:
    print("LOCAL_SOURCE_POLICY: stock GitHub version", flush=True)
elif installed == omit_unknown_audio_gate(old):
    proposed = omit_unknown_audio_gate(proposed)
    marker.write_text("known_audio_policy_override", encoding="utf-8")
    print("LOCAL_SOURCE_POLICY: verified existing audio override preserved", flush=True)
elif installed == proposed:
    print("LOCAL_SOURCE_POLICY: already updated", flush=True)
elif installed == omit_unknown_audio_gate(proposed):
    proposed = installed
    marker.write_text("known_audio_policy_override", encoding="utf-8")
    print("LOCAL_SOURCE_POLICY: already updated with audio override", flush=True)
else:
    raise SystemExit("STOP: unexpected local catalog changes; no files modified")
if installed_stage.read_bytes() not in (
    old_stage.read_bytes(), new_stage.read_bytes()
):
    raise SystemExit("STOP: unexpected local stage changes; no files modified")
print("LOCAL_STAGE_POLICY: reviewed version", flush=True)
new_manifest.write_text(proposed, encoding="utf-8")
PY

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

if [[ -f "$WORK/guardless-source-policy" ]]; then
  echo "=== TEST ACTUAL INSTALLED AUDIO POLICY (known override) ==="
  (
    cd "$WORK"
    PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$WORK" python3 -B - <<'PY'
from pathlib import Path
import unittest
import test_ja_first_native_series_identity as tests
from tools import ja_first_catalog_manifest as catalog

suite = unittest.defaultTestLoader.loadTestsFromTestCase(tests.NativeSeriesIdentityTests)
# Preserving the installed override intentionally retains different behavior
# for und/unknown audio from standard GitHub policy.
selected = unittest.TestSuite(
    test for test in suite
    if test._testMethodName != "test_no_audio_language_does_not_use_native_identity_to_bypass_review"
)
result = unittest.TextTestRunner(verbosity=2).run(selected)
if not result.wasSuccessful():
    raise SystemExit(1)
test = tests.NativeSeriesIdentityTests()
test.setUp()
try:
    test.item["MediaStreams"] = [{"Type":"Audio","Language":"und"}]
    if test.inspect()["status"] != "ready_ja_search":
        raise SystemExit("Existing unknown-audio override was not preserved")
    print("KNOWN_OVERRIDE_PRESERVED verified unchanged unknown-audio behavior")
finally:
    test.tearDown()
PY
  )
fi

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
