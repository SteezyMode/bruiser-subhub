#!/usr/bin/env bash
# ONE COMMAND: use existing Jellyfin/Subbuzz providers to find English subtitles
# for actual American Dad S08 media, then let existing SubHub translator work.
# Usage: bash tools/fetch_american_dad_english.sh optiplex@HOST 8 [9]
set -euo pipefail
if [[ $# -lt 2 || $# -gt 3 ]]; then
  echo 'Usage: bash tools/fetch_american_dad_english.sh optiplex@HOST 8 [9]' >&2
  exit 2
fi
HOST="$1"
shift
for season in "$@"; do
  if ! [[ "$season" =~ ^[0-9]{1,2}$ ]] || (( 10#$season < 1 || 10#$season > 40 )); then
    echo 'Choose one or two season numbers (1..40)' >&2
    exit 2
  fi
done
if [[ $# -eq 2 && "$1" == "$2" ]]; then
  echo 'Duplicate season selection not permitted' >&2
  exit 2
fi
ROOT="$(cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT"
echo '=== OFFLINE TESTS; NO MODEL OR MEDIA CHANGES ==='
python3 -m unittest discover -p 'test_*.py' -q
echo '=== STAGE ISOLATED HELPERS ONLY; NO JELLYFIN OR SUBHUB REINSTALL ==='
ssh "$HOST" 'mkdir -p -m 700 ~/bruiser-pilot/american-dad-season-code'
scp -q \
  tools/american_dad_seasons.py \
  tools/daily_japanese.py \
  tools/daily_worker.py \
  tools/jellyfin_english_sources.py \
  "$HOST:~/bruiser-pilot/american-dad-season-code/"
echo '=== ACQUIRE ENGLISH SUBTITLES USING EXISTING JELLYFIN PROVIDERS ==='
echo 'A one-time Jellyfin ADMIN sign-in may appear. Password is hidden, never saved or sent to ChatGPT.'
echo 'Existing Japanese is never replaced. Only requested episodes are searched.'
# Force PTY for terminal password prompt even if SSH is launched via a script.
ssh -tt "$HOST" "python3 ~/bruiser-pilot/american-dad-season-code/jellyfin_english_sources.py --apply --start --seasons $*"
echo
echo "Translation log: ssh $HOST 'tail -50 ~/bruiser-pilot/subhub1-state/american-dad-seasons.log'"
echo 'If providers have no strongly matched English files, the tool reports each SxxExx as needing a source; no unrelated movies are touched.'
