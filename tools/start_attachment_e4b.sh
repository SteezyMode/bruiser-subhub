#!/usr/bin/env bash
# One-time setup AND launch: Attachment (2022), full 1276-cue tuned E4B review.
# Run on OptiPlex; use SSH -t to watch and Ctrl+C to detach the tracker.
# Does not replace original Attachment Japanese subtitle or touch old job DB.
set -euo pipefail
umask 077

PIN="ea67522aba9e693be4f71d68ea4b81a4c4888423"
URL="https://raw.githubusercontent.com/SteezyMode/bruiser-subhub/$PIN/tools"
DEST="$HOME/bruiser-pilot/subhub-control"
HOST="$HOME/bruiser-pilot/subhub1"
if [[ ! -d "$DEST" || -L "$DEST" ||
      ! -f "$HOST/service.py" || -L "$HOST/service.py" ]]; then
    echo "BLOCKED: expected production host/controller not installed" >&2
    exit 1
fi
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "=== VERIFY INSTALLED TUNED MODEL CODE ==="
PYTHONDONTWRITEBYTECODE=1 python3 - "$HOST" "$DEST" <<'PY'
import sys
sys.path.insert(0,sys.argv[1])
sys.path.insert(0,sys.argv[2])
import service,subtitle_tuned_production as tuned
assert service.GEMMA == tuned.MODEL, "Production model mismatch"
assert tuned.MODEL_ID_PREFIX == "9ccfc3b07081", "Model ID mismatch"
assert tuned.NUM_CTX == 1344 and tuned.NUM_PREDICT == 256
print("MODEL:",tuned.MODEL)
print("DIGEST:",tuned.MODEL_ID_PREFIX)
print("CONTEXT:",tuned.NUM_CTX)
PY

echo "=== FETCH VERIFIED REVIEW WORKER AND TRACKER ==="
for f in retranslate_attachment_e4b.py subhub_live_tracker.py; do
    curl -fsSL --retry 3 --connect-timeout 10 --max-time 50 \
      "$URL/$f" -o "$TMP/$f"
done
PYTHONDONTWRITEBYTECODE=1 python3 - "$TMP" <<'PY'
import ast,sys
from pathlib import Path
root=Path(sys.argv[1])
for f in sorted(root.glob('*.py')):
    ast.parse(f.read_text(encoding='utf-8'),filename=str(f))
print("SOURCE SYNTAX: checked 2 files")
PY

BACKUPS="$DEST/attachment-e4b-tool-backups"
if [[ -L "$BACKUPS" ]]; then
    echo "BLOCKED: tool backup folder is symlink" >&2
    exit 1
fi
mkdir -p -m 700 "$BACKUPS"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
for f in retranslate_attachment_e4b.py subhub_live_tracker.py; do
    if [[ -L "$DEST/$f" ]]; then
        echo "BLOCKED: existing script path is symlink: $f" >&2
        exit 1
    fi
    if [[ -f "$DEST/$f" ]]; then
        cp -p "$DEST/$f" "$BACKUPS/$f.$STAMP"
    fi
done
for f in retranslate_attachment_e4b.py subhub_live_tracker.py; do
    target="$(mktemp "$DEST/.e4b-new-$f.XXXXXXXX")"
    cp "$TMP/$f" "$target"
    chmod 600 "$target"
    mv -f "$target" "$DEST/$f"
done

echo "=== OFFLINE REVIEW-RUNNER SELF-TEST ==="
PYTHONDONTWRITEBYTECODE=1 python3 \
  "$DEST/retranslate_attachment_e4b.py" self-test

echo "=== START ATTACHMENT WITH LIVE TRACKER ==="
echo "This creates a SEPARATE E4B review track; original Japanese stays untouched."
echo "Ctrl+C detaches the display, NOT the translation worker."
exec python3 -u "$DEST/retranslate_attachment_e4b.py" start
