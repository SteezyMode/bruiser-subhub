#!/usr/bin/env bash
# Copy private ContextSafe v010 EN+JA pairs to the Mac for editorial review.
# Read-only SSH: no host deployment, no GPU calls, no retranslation.
set -euo pipefail
if [[ $# -ne 1 ]]; then
  echo 'Usage: bash tools/collect_contextsafe_review_010.sh optiplex@HOST' >&2
  exit 2
fi
HOST="$1"
ROOT="$(cd -- "$(dirname -- "$0")/.." && pwd)"
umask 077
mkdir -p "$HOME/Downloads"
TMP="$(mktemp "$HOME/Downloads/.subhub-contextsafe-review.XXXXXXXX.tar.gz")"
trap 'rm -f -- "$TMP"' EXIT
ssh "$HOST" 'python3 -' < "$ROOT/tools/collect_contextsafe_review_010.py" > "$TMP"
tar -tzf "$TMP" >/dev/null
DEST="$HOME/Downloads/american-dad-contextsafe-010-review-$(date -u +%Y%m%dT%H%M%SZ).tar.gz"
if [[ -e "$DEST" ]]; then
  echo 'Output name already exists; not replacing.' >&2
  exit 1
fi
mv -- "$TMP" "$DEST"
trap - EXIT
printf '\nPRIVATE ContextSafe EN+JA review archive: %s\n' "$DEST"
echo 'Upload this tar.gz to the chat. It contains copyrighted dialogue; do not commit it to GitHub.'
