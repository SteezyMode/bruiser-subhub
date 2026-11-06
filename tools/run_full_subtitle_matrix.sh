#!/usr/bin/env bash
# One-shot bilingual inventory for all Jellyfin movies and episodes.
# Does not launch ffprobe, ffmpeg, provider searches, models or timers.
set -euo pipefail
umask 077

if [[ $# -ne 1 || ! "$1" =~ ^[0-9a-f]{40}$ ]]; then
    echo "Usage: $0 <pinned-github-commit-sha>" >&2
    exit 2
fi

PIN="$1"
CODE="$HOME/bruiser-pilot/english-source-code"
REPORT="$HOME/bruiser-pilot/coverage-audits"
TARGET="$CODE/audit_full_subtitle_matrix.py"

if [[ ! -d "$CODE" || -L "$CODE" ||
      ! -f "$CODE/library_english_sources.py" ||
      ! -f "$CODE/jellyfin_english_sources.py" ||
      ! -f "$CODE/daily_japanese.py" ]]; then
    echo "Existing English source installation missing or unsafe" >&2
    exit 1
fi
if [[ -L "$TARGET" || -L "$REPORT" ]]; then
    echo "Refusing symlinked script or private report directory" >&2
    exit 1
fi
TMP="$(mktemp "$CODE/.matrix-XXXXXXXX.py")"
trap 'rm -f "$TMP"' EXIT

curl -fsSL --retry 3 --connect-timeout 15 --max-time 90 \
 "https://raw.githubusercontent.com/SteezyMode/bruiser-subhub/$PIN/tools/audit_full_subtitle_matrix.py" \
 -o "$TMP"

python3 - "$TMP" <<'PY'
import ast, pathlib, sys
source = pathlib.Path(sys.argv[1]).read_text("utf-8")
ast.parse(source)
assert "SUBTITLE_MATRIX_SUMMARY" in source
assert "japanese_subtitles" in source and "english_subtitles" in source
print("BILINGUAL_MATRIX_PREFLIGHT_OK", flush=True)
PY

if [[ -e "$TARGET" ]]; then
    cp -p "$TARGET" "$TARGET.backup-$(date -u +%Y%m%dT%H%M%SZ)"
fi
chmod 600 "$TMP"
mv -f "$TMP" "$TARGET"

echo "Scanning existing English and Japanese subtitle tracks for EVERY Jellyfin file"
echo "No subtitle extraction, provider downloads, GPU or media writes"
PYTHONDONTWRITEBYTECODE=1 python3 -u "$TARGET" --folder "$REPORT"
