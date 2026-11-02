#!/usr/bin/env bash
# Export existing 012 failed replies. No model calls, no SSH writes.
set -euo pipefail
if [[ $# -ne 1 ]]; then
 echo 'Usage: bash tools/collect_formatlab_failures_012.sh optiplex@HOST' >&2
 exit 2
fi
HOST="$1"
ROOT="$(cd -- "$(dirname -- "$0")/.." && pwd)"
umask 077
mkdir -p "$HOME/Downloads"
TMP="$(mktemp "$HOME/Downloads/.formatlab-failed.XXXXXXXX.tar.gz")"
trap 'rm -f -- "$TMP"' EXIT
ssh "$HOST" 'python3 -' < "$ROOT/tools/collect_formatlab_failures_012.py" > "$TMP"
tar -tzf "$TMP" >/dev/null
DEST="$HOME/Downloads/american-dad-formatlab-012-failure-forensics-$(date -u +%Y%m%dT%H%M%SZ).tar.gz"
if [[ -e "$DEST" ]]; then
 echo 'Destination collision; refusing overwrite' >&2
 exit 1
fi
mv -- "$TMP" "$DEST"
trap - EXIT
printf '\nPRIVATE failed-response archive: %s\n' "$DEST"
echo 'Upload this to chat. No Ollama inference, host staging, media writes, or service changes.'
