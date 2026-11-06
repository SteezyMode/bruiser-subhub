#!/usr/bin/env bash
# Guarded host-only library audit. No provider search, translation or media writes.
set -euo pipefail
umask 077

if [[ "$#" -ne 1 || ! "$1" =~ ^[0-9a-f]{40}$ ]]; then
  echo "Usage: $0 <pinned-repo-commit-sha>" >&2
  exit 2
fi
PIN="$1"
CODE="$HOME/bruiser-pilot/english-source-code"
SCRIPT="$CODE/audit_english_without_japanese.py"
REPORT="$HOME/bruiser-pilot/coverage-audits"

if [[ ! -d "$CODE" || -L "$CODE" || "$(stat -c %u "$CODE")" != "$(id -u)" ]]; then
  echo "Existing private English source controller not installed or unsafe" >&2
  exit 1
fi
for dep in library_english_sources.py jellyfin_english_sources.py daily_japanese.py american_dad_seasons.py; do
  if [[ ! -f "$CODE/$dep" || -L "$CODE/$dep" ]]; then
    echo "Missing dependency $CODE/$dep; nothing changed" >&2
    exit 1
  fi
done
if [[ -L "$SCRIPT" || -L "$REPORT" ]]; then
  echo "Symlinked controller/report destination refused" >&2
  exit 1
fi
TMP="$(mktemp "$CODE/.coverage-audit-XXXXXXXX.py")"
trap 'rm -f "$TMP"' EXIT
curl -fsSL --retry 3 --connect-timeout 15 --max-time 90 \
  "https://raw.githubusercontent.com/SteezyMode/bruiser-subhub/$PIN/tools/audit_english_without_japanese.py" \
  -o "$TMP"
python3 - "$TMP" <<'PY'
import ast,pathlib,sys
s=pathlib.Path(sys.argv[1]).read_text("utf-8")
ast.parse(s)
assert "prior_jellyfin_only" in s and "source_text_ready" in s
assert "COVERAGE_AUDIT_SUMMARY" in s
print("COVERAGE_AUDIT_SYNTAX_OK",flush=True)
PY
if [[ -e "$SCRIPT" ]]; then
  cp -p -- "$SCRIPT" "$SCRIPT.before-coverage-audit-$(date -u +%Y%m%dT%H%M%SZ)"
fi
chmod 600 "$TMP"
mv -f -- "$TMP" "$SCRIPT"
echo "COVERAGE AUDIT STARTING: Jellyfin catalog, sidecars, stream metadata"
echo "No subtitle provider API calls. No GPU/AI. No media file writes."
PYTHONDONTWRITEBYTECODE=1 python3 -u "$SCRIPT" --save
echo "COVERAGE AUDIT DONE; private CSV/JSON reports: $REPORT"
