#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
if [[ ! -f "$HOME/bruiser-pilot/bruiser_auto.py" || ! -f "$HOME/bruiser-pilot/bruiser_hy_backtranslate_compare.py" ]]; then
    echo 'MISSING: existing Bruiser translator modules; legacy installation has not been changed.' >&2
    exit 2
fi
if [[ ! -f "$HOME/bruiser-pilot/subhub-household/jobs.json" ]]; then
    echo 'MISSING: legacy jobs.json; no jobs were imported or launched.' >&2
    exit 2
fi
python3 -m compileall -q "$ROOT"
python3 main.py self-test
python3 main.py import-legacy --prioritize heretic,primate --limit 10
python3 main.py status
python3 main.py start --mode all --publish --max-minutes 90 --max-titles 10 --hy-sample 48 --max-gpu-c 82 --max-cpu-c 85
printf '\nStarted independently of legacy timers. Progress: python3 %s/main.py status\n' "$ROOT"
