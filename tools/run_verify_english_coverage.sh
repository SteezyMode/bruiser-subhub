#!/usr/bin/env bash
# Bruiser: read-only on-media verification of English-text tracks.
# The only files created are private audit code and private CSV/JSON reports.
set -euo pipefail
umask 077

if [[ "$#" -ne 1 || ! "$1" =~ ^[0-9a-f]{40}$ ]]; then
  echo "Usage: $0 <pinned-commit>" >&2
  exit 2
fi
PIN="$1"
CODE="$HOME/bruiser-pilot/english-source-code"
REPORT="$HOME/bruiser-pilot/coverage-audits"
TARGET="$CODE/verify_english_coverage.py"

if [[ ! -d "$CODE" || -L "$CODE" || -L "$REPORT" ||
      ! -f "$CODE/daily_japanese.py" || -L "$CODE/daily_japanese.py" ]]; then
  echo "Missing or unsafe existing English source installation" >&2
  exit 1
fi
if [[ ! -d "$REPORT" || "$(stat -c %a "$REPORT")" != 700 ]]; then
  echo "Expected previously created private 0700 report directory absent" >&2
  exit 1
fi
if [[ -L "$TARGET" ]]; then
  echo "Refusing controller symlink" >&2
  exit 1
fi
TMP="$(mktemp "$CODE/.verify-english-XXXXXXXX.py")"
trap 'rm -f "$TMP"' EXIT
curl -fsSL --retry 3 --connect-timeout 15 --max-time 90 \
  "https://raw.githubusercontent.com/SteezyMode/bruiser-subhub/$PIN/tools/verify_english_coverage.py" \
  -o "$TMP"
python3 - "$TMP" <<'PY'
import ast,pathlib,sys
source=pathlib.Path(sys.argv[1]).read_text("utf-8")
ast.parse(source)
assert "def probe_media(" in source and "def extract_sample(" in source
assert "ENGLISH_MEDIA_STREAM_VERIFICATION" in source
print("VERIFY_ENGLISH_SOURCE_SYNTAX_OK",flush=True)
PY
if [[ -e "$TARGET" ]]; then
  cp -p "$TARGET" "$TARGET.before-verify-$(date -u +%Y%m%dT%H%M%SZ)"
fi
chmod 600 "$TMP"
mv -f "$TMP" "$TARGET"
echo "VERIFYING English subtitle streams in existing private full-library inventory"
echo "No downloads, provider searches, translation, video writes or subtitle changes"
PYTHONDONTWRITEBYTECODE=1 python3 -u "$TARGET" --folder "$REPORT" --sample-extract 40
