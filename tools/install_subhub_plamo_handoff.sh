#!/usr/bin/env bash
# Install opt-in source-first PLaMo handoff WITHOUT starting model inference.
# Never replaces the proven American Dad PLaMo scripts, existing source services,
# dashboard, video files or subtitles.
set -euo pipefail
umask 077
if [[ $# -ne 1 || ! "$1" =~ ^[0-9a-f]{40}$ ]]; then
  echo "Usage: install_subhub_plamo_handoff.sh <pinned-commit-sha>" >&2
  exit 2
fi

PIN="$1"
BASE="https://raw.githubusercontent.com/SteezyMode/bruiser-subhub/$PIN"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$WORK/tools"
touch "$WORK/tools/__init__.py"

curl -fsSL --retry 3 --connect-timeout 10 --max-time 90 \
  "$BASE/tools/subhub_plamo_handoff.py" \
  -o "$WORK/tools/subhub_plamo_handoff.py"
curl -fsSL --retry 3 --connect-timeout 10 --max-time 90 \
  "$BASE/test_subhub_plamo_handoff.py" \
  -o "$WORK/test_subhub_plamo_handoff.py"

python3 - "$WORK/tools/subhub_plamo_handoff.py" <<'PY'
import ast,pathlib,sys
s=pathlib.Path(sys.argv[1]).read_text("utf-8")
ast.parse(s)
assert "def translate(" in s
assert "japanese_sourcing_not_exhausted" in s
assert "source_batch_still_running" in s
assert "engine.write_new_sidecar" in s
print("SUBHUB_PLAMO_HANDOFF_PREFLIGHT_OK",flush=True)
PY

(cd "$WORK" &&
 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$WORK" \
 python3 -m unittest -v test_subhub_plamo_handoff)

ROOT="$HOME/bruiser-pilot/plamo3-ab"
TARGET="$ROOT/subhub_plamo_handoff.py"
BIN="$HOME/.local/bin"
COMMAND="$BIN/subhub-ai"

if [[ ! -d "$ROOT" || -L "$ROOT" ||
      "$(stat -c %u "$ROOT")" != "$(id -u)" ||
      ! -d "$ROOT/runtime/llama" ||
      ! -d "$ROOT/runtime/cudart" ||
      ! -x "$ROOT/runtime/llama-server" ||
      ! -f "$ROOT/models/plamo-3-translate-8b-Q4_K_M.gguf" ||
      ! -f "$ROOT/plamo8b_american_dad_existing_en_batch.py" ||
      ! -f "$ROOT/plamo3_watch_american_dad.py" ||
      ! -f "$ROOT/plamo3_source_first_american_dad.py" ]]; then
  echo "Tested PLaMo 8B runtime missing; refusing to install a broken handoff." >&2
  exit 1
fi
mkdir -p "$BIN"
if [[ -L "$BIN" || -L "$TARGET" || -L "$COMMAND" ||
      "$(stat -c %u "$BIN")" != "$(id -u)" ]]; then
  echo "Unsafe client script destination" >&2
  exit 1
fi
install -m 600 "$WORK/tools/subhub_plamo_handoff.py" "$TARGET.new"
mv -f "$TARGET.new" "$TARGET"

cat > "$COMMAND.new" <<'WRAPPER'
#!/usr/bin/env bash
set -euo pipefail
umask 077
ROOT="$HOME/bruiser-pilot/plamo3-ab"
LIBDIRS="$(find "$ROOT/runtime/llama" "$ROOT/runtime/cudart" -type f \
  \( -name 'lib*.so' -o -name 'lib*.so.*' \) -printf '%h\n' \
  | sort -u | paste -sd: -)"
if [[ -z "$LIBDIRS" ]]; then
  echo "Bundled CUDA libraries not found; refusing CPU fallback" >&2
  exit 1
fi
export LD_LIBRARY_PATH="$LIBDIRS"
exec python3 -B -u "$ROOT/subhub_plamo_handoff.py" "$@"
WRAPPER
chmod 700 "$COMMAND.new"
mv -f "$COMMAND.new" "$COMMAND"

echo "SUBHUB_AI_HANDOFF_INSTALLED"
echo "Read-only readiness: $COMMAND"
echo "One-title EN checkpoint: $COMMAND --prepare --jellyfin-id <exact-id>"
echo "One-title GPU pilot (AFTER sourcing job ends): $COMMAND --apply --jellyfin-id <exact-id>"
echo "Newly added movie opt-in (no queue refresh): $COMMAND --prepare --explicit-movie-pilot --jellyfin-id <exact-id> --movie-path <absolute-host-path>"
echo "After PREPARED, use same flags with --apply to translate"
echo "No GPU process started. No existing source job or PLaMo/American Dad batch changed."
