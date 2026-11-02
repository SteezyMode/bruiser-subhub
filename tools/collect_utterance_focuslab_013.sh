#!/usr/bin/env bash
# Private EN/JA baseline vs whole-sentence context vs per-cue focused output.
# READ ONLY on host. No further Ollama calls.
set -euo pipefail
if [[ $# -ne 1 ]]; then
 echo 'Usage: bash tools/collect_utterance_focuslab_013.sh optiplex@HOST' >&2
 exit 2
fi
HOST="$1"
ROOT="$(cd -- "$(dirname -- "$0")/.." && pwd)"
umask 077
mkdir -p "$HOME/Downloads"
TMP="$(mktemp "$HOME/Downloads/.focuslab-013-private.XXXXXXXX.tar.gz")"
trap 'rm -f -- "$TMP"' EXIT
ssh "$HOST" 'python3 -' < "$ROOT/tools/utterance_focuslab_013.py" > /dev/null 2>&1 && {
 echo 'Unexpected side effect prevention: do not run generic script without export' >&2
 exit 1
}
ssh "$HOST" 'python3 ~/bruiser-pilot/utterance-focuslab-013-code/utterance_focuslab_013.py export' > "$TMP"
tar -tzf "$TMP" >/dev/null
DEST="$HOME/Downloads/american-dad-focuslab-013-review-$(date -u +%Y%m%dT%H%M%SZ).tar.gz"
if [[ -e "$DEST" ]]; then
 echo 'Destination collision, refusing overwrite' >&2
 exit 1
fi
mv -- "$TMP" "$DEST"
trap - EXIT
printf '\nPRIVATE focused bilingual comparison: %s\n' "$DEST"
echo 'Upload the archive to chat. No source/Japanese dialogue enters public GitHub.'
