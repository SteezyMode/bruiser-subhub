#!/usr/bin/env bash
# Install/refresh the bounded Japanese-first controller on the OptiPlex host.
# Does NOT enable a timer or start translation. Uses a fixed source commit.
set -euo pipefail

PIN="e533801ea514b9c9a40e5ca798f252cdaef943b6"
BASE="https://raw.githubusercontent.com/SteezyMode/bruiser-subhub/$PIN/tools"
DEST="$HOME/bruiser-pilot/subhub-control"

mkdir -p -m 700 "$DEST"
if [[ -L "$DEST" ]]; then
  printf 'Unsafe symlink controller directory\n' >&2
  exit 1
fi
chmod 700 "$DEST"
umask 077

NAMES=(
  ja_first_cycle.py
  ja_first_search_pilot.py
  ja_first_stage_saved_batch.py
  ja_first_stage_timing_audit.py
  ja_first_publish_staged.py
  ja_first_publish_shifted.py
  ja_first_publish_queue.py
  ja_first_ffsubsync.py
  ja_first_obvious_quality.py
  bruiser_ja_movie_rescue.py
  ja_first_gemma_fallback.py
  daily_japanese.py
  daily_worker.py
  subtitle_publish_gate.py
  subtitle_quality_010.py
  subtitle_tuned_production.py
  subhub_live_tracker.py
)
for name in "${NAMES[@]}"; do
  target="$DEST/$name"
  if [[ -L "$target" ]]; then
    printf 'Unsafe symlink target: %s\n' "$name" >&2
    exit 1
  fi
  tmp="$(mktemp "$DEST/.staging-${name}.XXXXXXXX")"
  if ! curl -fsSL --retry 3 --connect-timeout 10 --max-time 40 \
    "$BASE/$name" -o "$tmp"; then
    rm -f "$tmp"
    exit 1
  fi
  chmod 600 "$tmp"
  mv -f -- "$tmp" "$target"
done

PYTHONDONTWRITEBYTECODE=1 python3 - "$DEST" <<'PY'
import ast
from pathlib import Path
import sys
path = Path(sys.argv[1])
files = sorted(path.glob("*.py"))
for source in files:
    ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
print("PYTHON SYNTAX: checked", len(files), "files")
PY

PYTHONDONTWRITEBYTECODE=1 python3 "$DEST/ja_first_cycle.py" --self-test
PYTHONDONTWRITEBYTECODE=1 python3 "$DEST/subhub_live_tracker.py" --self-test
printf '\nCONTROLLER: %s\n' "$DEST/ja_first_cycle.py"
printf 'STATUS: python3 %s/ja_first_cycle.py status\n' "$DEST"
printf 'START PINNED E4B JOB (only after model preflight): python3 %s/ja_first_cycle.py start-worker --apply\n' "$DEST"
printf 'READ-ONLY SOURCED QA: python3 %s/ja_first_obvious_quality.py --audit-staged\n' "$DEST"
printf 'JA SOURCES ONLY (no AI queue): python3 %s/ja_first_cycle.py cycle --sources-only --apply\n' "$DEST"
printf 'ONE BOUNDED JA-FIRST CYCLE: python3 %s/ja_first_cycle.py cycle --apply\n' "$DEST"
printf 'READ-ONLY LIVE TRACKER: python3 %s/ja_first_cycle.py watch\n' "$DEST"
printf 'START AND FOLLOW: python3 %s/ja_first_cycle.py start-worker --apply --watch\n' "$DEST"
