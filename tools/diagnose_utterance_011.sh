#!/usr/bin/env bash
# Diagnose the REAL saved v011 state without changing any host files.
set -euo pipefail
if [[ $# -ne 1 ]]; then
  echo 'Usage: bash tools/diagnose_utterance_011.sh optiplex@HOST' >&2
  exit 2
fi
HOST="$1"
ROOT="$(cd -- "$(dirname -- "$0")/.." && pwd)"
umask 077
mkdir -p "$HOME/Downloads"
TMP="$(mktemp "$HOME/Downloads/.utterance-011-diagnostic.XXXXXXXX.json")"
trap 'rm -f -- "$TMP"' EXIT
ssh "$HOST" 'python3 -' < "$ROOT/tools/diagnose_utterance_011.py" > "$TMP"
python3 -m json.tool "$TMP" >/dev/null
DEST="$HOME/Downloads/utterance-011-diagnostic-$(date -u +%Y%m%dT%H%M%SZ).json"
if [[ -e "$DEST" ]]; then
 echo 'Output collision, refuse overwrite' >&2
 exit 1
fi
mv -- "$TMP" "$DEST"
trap - EXIT
cat -- "$DEST"
printf '\nREAD-ONLY DIAGNOSTIC: %s\n' "$DEST"
echo 'Upload this JSON to the chat. No new model inference, file staging or checkpoint replacement.'
