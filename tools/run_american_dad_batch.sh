#!/usr/bin/env bash
# Thin launcher for the EXISTING resumable American Dad PLaMo 8B worker.
# Runs only when the owner starts bruiser-plamo-american-dad.service.
set -euo pipefail
umask 077

ROOT="$HOME/bruiser-pilot/plamo3-ab"
STATE="$ROOT/american-dad-existing-english-batch"
SCRIPT="$ROOT/plamo8b_american_dad_existing_en_batch.py"
RUNTIME="$ROOT/runtime"

for path in "$ROOT" "$STATE" "$SCRIPT" "$RUNTIME/llama" "$RUNTIME/cudart"; do
    if [[ -L "$path" || ! -e "$path" ]]; then
        echo "PLaMo launch held: missing or symlinked $path" >&2
        exit 1
    fi
done
if [[ ! -d "$STATE" || "$(stat -c %u "$STATE")" != "$(id -u)" ]]; then
    echo "PLaMo launch held: unsafe checkpoint directory" >&2
    exit 1
fi
if [[ ! -x "$RUNTIME/llama-server" ]]; then
    echo "PLaMo launch held: existing llama-server missing" >&2
    exit 1
fi

LIBDIRS="$(find "$RUNTIME/llama" "$RUNTIME/cudart" -type f \
    \( -name 'lib*.so' -o -name 'lib*.so.*' \) -printf '%h\n' |
    sort -u | paste -sd: -)"
if [[ -z "$LIBDIRS" ]]; then
    echo "PLaMo launch held: existing CUDA libraries not found" >&2
    exit 1
fi
export LD_LIBRARY_PATH="$LIBDIRS"

# exec retains this service's PID for the existing dashboard process monitor.
printf '%s\n' "$$" > "$STATE/batch.pid"
echo "=== SUBHUB OWNER RESUME AMERICAN DAD ==="
exec /usr/bin/python3 -u "$SCRIPT" --apply
