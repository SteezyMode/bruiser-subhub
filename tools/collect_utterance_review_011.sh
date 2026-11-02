#!/usr/bin/env bash
# Read-only EN+JA pairs from the NEW v011 completed preview. No host file writes.
set -euo pipefail
if [[ $# -ne 1 ]]; then
 echo 'Usage: bash tools/collect_utterance_review_011.sh optiplex@HOST' >&2
 exit 2
fi
HOST="$1"
ROOT="$(cd -- "$(dirname -- "$0")/.." && pwd)"
umask 077
mkdir -p "$HOME/Downloads"
TMP="$(mktemp "$HOME/Downloads/.bruiser-utterance-v011.XXXXXXXX.tar.gz")"
trap 'rm -f -- "$TMP"' EXIT
ssh "$HOST" 'python3 -' < "$ROOT/tools/collect_utterance_review_011.py" > "$TMP"
tar -tzf "$TMP" >/dev/null
DEST="$HOME/Downloads/american-dad-utterance-011-review-$(date -u +%Y%m%dT%H%M%SZ).tar.gz"
if [[ -e "$DEST" ]]; then echo 'Existing archive; refuse overwrite' >&2; exit 1; fi
mv -- "$TMP" "$DEST"
trap - EXIT
printf '\nPRIVATE English/Japanese v011 review archive: %s\n' "$DEST"
echo 'Upload archive to the chat for bilingual quality review; never commit it to public GitHub.'
