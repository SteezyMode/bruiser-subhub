#!/usr/bin/env bash
set -euo pipefail
HOST="${1:?Usage: bash tools/collect_review.sh optiplex@TAILSCALE_IP [job-id]}"
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
JOB="${2:-}"
if [[ -z "$JOB" ]]; then
  JOB="$(ssh "$HOST" 'python3 -' <<'PY_REMOTE'
from pathlib import Path
import sqlite3
path = Path.home() / 'bruiser-pilot/subhub1-state/jobs.sqlite3'
with sqlite3.connect(path.resolve(strict=True).as_uri() + '?mode=ro', uri=True) as db:
    row = db.execute('SELECT id FROM jobs WHERE status=? ORDER BY created LIMIT 1', ('published',)).fetchone()
    print(row[0] if row else '')
PY_REMOTE
)"
fi
if [[ ! "$JOB" =~ ^[a-z0-9][a-z0-9-]+$ ]]; then
  echo "No published film found or invalid job ID. Provide job ID explicitly." >&2
  exit 2
fi
STAMP="$(date -u '+%Y%m%dT%H%M%SZ')"
NAME="$JOB.editorial-$STAMP.json"
scp -q "$ROOT/review_sampler.py" "$HOST:~/bruiser-pilot/subhub1-review-sampler.py"
ssh "$HOST" "python3 ~/bruiser-pilot/subhub1-review-sampler.py --root ~/bruiser-pilot/subhub1-state --job '$JOB' --count 80 --out ~/bruiser-pilot/subhub1-state/review/'$NAME'"
scp -q "$HOST:~/bruiser-pilot/subhub1-state/review/$NAME" "$HOME/Downloads/$NAME"
printf '\nPRIVATE EN/JA review packet: %s\nUpload the JSON to this chat for actual linguistic assessment. Do NOT commit it to GitHub.\n' "$HOME/Downloads/$NAME"
