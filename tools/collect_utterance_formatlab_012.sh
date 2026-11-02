#!/usr/bin/env bash
# Read-only SSH export of the completed PRIVATE 24-unit A/B experiment.
set -euo pipefail
if [[ $# -ne 1 ]]; then
  echo 'Usage: bash tools/collect_utterance_formatlab_012.sh optiplex@HOST' >&2
  exit 2
fi
HOST="$1"
umask 077
mkdir -p "$HOME/Downloads"
TMP="$(mktemp "$HOME/Downloads/.utterance-formatlab-012.XXXXXXXX.tar.gz")"
trap 'rm -f -- "$TMP"' EXIT
ssh "$HOST" 'python3 ~/bruiser-pilot/utterance-formatlab-012-code/utterance_formatlab_012.py export' > "$TMP"
tar -tzf "$TMP" >/dev/null
DEST="$HOME/Downloads/american-dad-formatlab-012-review-$(date -u +%Y%m%dT%H%M%SZ).tar.gz"
if [[ -e "$DEST" ]]; then echo 'Archive exists; refuse overwrite' >&2; exit 1; fi
mv -- "$TMP" "$DEST"
trap - EXIT
printf '\nPRIVATE A/B bilingual review: %s\n' "$DEST"
echo 'Upload this archive to chat for paired semantic review; never commit it to public GitHub.'
