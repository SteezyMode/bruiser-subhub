#!/usr/bin/env bash
# Build an EN subtitle source shelf for the whole Jellyfin library.
# Unlike the American Dad launcher, does not start Japanese translation.
# S08 is prioritized for acquisition, not made a library-wide translation task.
set -euo pipefail
if [[ $# -ne 1 ]]; then
  echo 'Usage: bash tools/stock_english_sources.sh optiplex@HOST' >&2
  exit 2
fi
HOST="$1"
ROOT="$(cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT"
echo '=== TEST SUBTITLE SOURCE SAFETY OFFLINE ==='
python3 -m unittest discover -p 'test_*.py' -q
echo '=== STAGE ISOLATED EN INVENTORY HELPERS (NO SERVICE REINSTALLS) ==='
ssh "$HOST" 'mkdir -p -m 700 ~/bruiser-pilot/english-source-code'
scp -q tools/library_english_sources.py tools/enable_english_source_timer.py \
  tools/jellyfin_english_sources.py tools/american_dad_seasons.py \
  tools/daily_japanese.py tools/daily_worker.py \
  "$HOST:~/bruiser-pilot/english-source-code/"
echo '=== INDEX ALL JELLYFIN MOVIES AND EPISODES; REQUEST UP TO 18 PERFECT EN MATCHES ==='
echo 'One-time native Jellyfin admin login may be required; enter password only at hidden SSH prompt.'
ssh -tt "$HOST" 'python3 ~/bruiser-pilot/english-source-code/library_english_sources.py run --budget 18'
echo '=== ENABLE THROTTLED DAILY SOURCE MAINTENANCE (5 PROVIDER SEARCHES PER DAY) ==='
if ssh "$HOST" 'python3 ~/bruiser-pilot/english-source-code/enable_english_source_timer.py'; then
  echo 'Nightly maintenance user timer is enabled.'
else
  echo 'Daily timer could not be activated in this SSH user session.'
  echo 'The inventory and downloads remain intact; repeat this command manually when needed.'
fi
echo '=== SUMMARY, NO ADDITIONAL PROVIDER CALLS ==='
ssh "$HOST" 'python3 ~/bruiser-pilot/english-source-code/library_english_sources.py status'
echo
echo 'English source acquisition is separate from Japanese translation.'
echo 'American Dad Season 8 remains the translation priority; re-run its existing season command once it has English sources.'
