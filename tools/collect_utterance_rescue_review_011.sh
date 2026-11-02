#!/usr/bin/env bash
# Read-only private bilingual export of COMPLETED rescue tracks.
set -euo pipefail
if [[ $# -ne 1 ]]; then
  echo 'Usage: bash tools/collect_utterance_rescue_review_011.sh optiplex@HOST' >&2
  exit 2
fi
HOST="$1"
ROOT="$(cd -- "$(dirname -- "$0")/.." && pwd)"
umask 077
mkdir -p "$HOME/Downloads"
TMP="$(mktemp "$HOME/Downloads/.subhub-rescue-review.XXXXXXXX.tar.gz")"
trap 'rm -f -- "$TMP"' EXIT
ssh "$HOST" 'python3 -' < "$ROOT/tools/collect_utterance_rescue_review_011.py" > "$TMP"
tar -tzf "$TMP" >/dev/null
DEST="$HOME/Downloads/american-dad-utterance-011-recovery-review-$(date -u +%Y%m%dT%H%M%SZ).tar.gz"
if [[ -e "$DEST" ]]; then
  echo 'Review archive already exists; no overwrite.' >&2
  exit 1
fi
mv -- "$TMP" "$DEST"
trap - EXIT
printf '\nPRIVATE recovered EN/JA review: %s\n' "$DEST"
echo 'Upload this archive to chat for bilingual review; do NOT commit to GitHub.'
