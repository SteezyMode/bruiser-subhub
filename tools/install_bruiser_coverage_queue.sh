#!/usr/bin/env bash
# Import the EXISTING private bilingual matrix into a persistent Bruiser queue.
# Does NOT scan media, contact providers, change running services or run GPU.
set -euo pipefail
umask 077

if [[ $# -ne 1 || ! "$1" =~ ^[0-9a-f]{40}$ ]]; then
    echo "Usage: $0 <pinned-GitHub-commit-sha>" >&2
    exit 2
fi
PIN="$1"
ROOT="$HOME/bruiser-pilot"
REPORT="$ROOT/coverage-audits"
CODE="$ROOT/coverage-queue-code"
STATE="$ROOT/coverage-queue"
TARGET="$CODE/bruiser_coverage_queue.py"

if [[ ! -d "$REPORT" || -L "$REPORT" ||
      "$(stat -c %a "$REPORT")" != 700 ]]; then
    echo "Private full-library inventory is not installed at $REPORT" >&2
    exit 1
fi
if [[ -L "$CODE" || -L "$STATE" || -L "$TARGET" ]]; then
    echo "Symlinked queue location or controller refused" >&2
    exit 1
fi
mkdir -p -m 700 "$CODE" "$STATE"
if [[ "$(stat -c %a "$CODE")" != 700 ||
      "$(stat -c %a "$STATE")" != 700 ]]; then
    echo "Private queue directories must be 0700" >&2
    exit 1
fi
TMP="$(mktemp "$CODE/.coverage-queue-XXXXXXXX.py")"
trap 'rm -f "$TMP"' EXIT
curl -fsSL --retry 3 --connect-timeout 15 --max-time 90 \
 "https://raw.githubusercontent.com/SteezyMode/bruiser-subhub/$PIN/tools/bruiser_coverage_queue.py" \
 -o "$TMP"
python3 - "$TMP" <<'PY'
import ast,pathlib,sys
body=pathlib.Path(sys.argv[1]).read_text("utf-8")
ast.parse(body)
for required in ("COVERAGE_QUEUE_INIT","timing_flags","source_ja",
                 "repair_existing_timing","validate_english_for_ja_fallback"):
    assert required in body, required
print("COVERAGE_QUEUE_PREFLIGHT_OK",flush=True)
PY

if [[ -e "$TARGET" ]]; then
    cp -p -- "$TARGET" "$TARGET.backup-$(date -u +%Y%m%dT%H%M%SZ)"
fi
chmod 600 "$TMP"
mv -f -- "$TMP" "$TARGET"
echo "IMPORTING existing complete EN/JA library matrix (no fresh scan)"
PYTHONDONTWRITEBYTECODE=1 python3 -u "$TARGET" init --reports "$REPORT" --state "$STATE"
echo "TOP OF THE PERSISTENT QUEUE (PLAN ONLY):"
PYTHONDONTWRITEBYTECODE=1 python3 -u "$TARGET" next --state "$STATE" --limit 8
echo "QUEUE READY: $STATE/coverage.sqlite3"
echo "No subtitle searches/downloads, model/GPU work, media writes or service changes."
