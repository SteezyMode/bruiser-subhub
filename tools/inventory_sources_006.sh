#!/usr/bin/env bash
# Read-only query of the existing remote jobs.sqlite3; NO files copied to host.
set -euo pipefail
HOST="${1:?Usage: bash tools/inventory_sources_006.sh optiplex@HOST}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
echo "=== Benchmark 006 fresh-source inventory (metadata only; read-only SQLite) ==="
echo "This prints private job IDs and source hashes; do not commit terminal output to GitHub."
ssh "$HOST" 'python3 - --root "$HOME/bruiser-pilot/subhub1-state"' \
  < tools/inventory_sources_006.py
