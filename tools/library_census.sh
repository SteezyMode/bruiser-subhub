#!/usr/bin/env bash
set -euo pipefail
HOST="${1:?Usage: bash tools/library_census.sh optiplex@HOST}"
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
# Streaming Python over SSH; no installer, source replacement or running worker touched.
ssh "$HOST" 'python3 - --root "/mnt/BigDisk/Video" --root "/mnt/2TB/Plex Expansion"' < "$ROOT/tools/library_census.py"
