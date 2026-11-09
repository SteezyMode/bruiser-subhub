#!/usr/bin/env bash
# SubHub Dashboard: one title search, source-first selectable seasons, PLaMo fallback.
# Installs only the dashboard. Owner controls require explicit in-browser action.
set -euo pipefail
umask 077

if [[ $# -ne 1 || ! "$1" =~ ^[0-9a-f]{40}$ ]]; then
  echo "Usage: install_subhub_dashboard.sh <pinned-40-character-git-commit>" >&2
  exit 2
fi
PIN="$1"
BASE="https://raw.githubusercontent.com/SteezyMode/bruiser-subhub/$PIN"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$WORK/tools"
touch "$WORK/tools/__init__.py"

for name in subhub_dashboard_server.py subhub_dashboard.html ja_first_source_tracker.py subhub_translation_batch.py subhub_season_sources.py bruiser_coverage_queue.py; do
  curl -fsSL --retry 3 --connect-timeout 10 --max-time 90 \
    "$BASE/tools/$name" -o "$WORK/tools/$name"
done
curl -fsSL --retry 3 --connect-timeout 10 --max-time 90 \
  "$BASE/test_subhub_dashboard.py" -o "$WORK/test_subhub_dashboard.py"
curl -fsSL --retry 3 --connect-timeout 10 --max-time 90 \
  "$BASE/test_subhub_translation_batch.py" -o "$WORK/test_subhub_translation_batch.py"
curl -fsSL --retry 3 --connect-timeout 10 --max-time 90 \
  "$BASE/test_subhub_season_sources.py" -o "$WORK/test_subhub_season_sources.py"

python3 - "$WORK/tools/subhub_dashboard_server.py" "$WORK/tools/subhub_dashboard.html" <<'PY'
import ast, pathlib, sys
server = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")
html = pathlib.Path(sys.argv[2]).read_text(encoding="utf-8")
ast.parse(server)
ast.parse(pathlib.Path(sys.argv[1]).with_name('ja_first_source_tracker.py').read_text(encoding='utf-8'))
ast.parse(pathlib.Path(sys.argv[1]).with_name('subhub_translation_batch.py').read_text(encoding='utf-8'))
ast.parse(pathlib.Path(sys.argv[1]).with_name('subhub_season_sources.py').read_text(encoding='utf-8'))
ast.parse(pathlib.Path(sys.argv[1]).with_name('bruiser_coverage_queue.py').read_text(encoding='utf-8'))
assert '("127.0.0.1", args.port)' in server, "loopback-only policy missing"
assert '/api/control/start-auto' in server and 'owner_control_access_denied' in server, "owner control safeguards missing"
assert "/api/status" in server and "textContent" in html
assert 'id="title-search"' in html and html.count('type="text"') == 1, "single title search missing"
assert 'id="episode-details"' in html and 'Review remaining episodes' in html, "compact episode review missing"
assert '/api/translation/start' in server and 'selected_multi_plan' in server
assert '/api/source-season/start' in server and 'selected_scope' in server
assert 'id="source-selected"' in html and 'id="translate-selected"' in html
assert 'library_wide_sourcing_disabled_use_selected_season' in server
print("SUBHUB_DASHBOARD_PREFLIGHT_OK", flush=True)
PY
(
  cd "$WORK"
  PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$WORK" \
    python3 -m unittest -v test_subhub_dashboard test_subhub_translation_batch test_subhub_season_sources
)

DEST="$HOME/.local/share/bruiser-subhub-dashboard"
BIN="$HOME/.local/share/applications"
UNITDIR="$HOME/.config/systemd/user"
UNIT="$UNITDIR/bruiser-subhub-dashboard.service"
SHORTCUT="$BIN/bruiser-subhub-dashboard.desktop"
for item in "$DEST" "$DEST/subhub_dashboard_server.py" "$DEST/subhub_dashboard.html" "$DEST/ja_first_source_tracker.py" "$DEST/subhub_translation_batch.py" "$DEST/subhub_season_sources.py" "$DEST/bruiser_coverage_queue.py" \
            "$UNITDIR" "$UNIT" "$BIN" "$SHORTCUT"; do
  if [[ -L "$item" ]]; then
    echo "Unsafe symlink at $item" >&2
    exit 1
  fi
done
mkdir -p "$DEST" "$BIN" "$UNITDIR"
if [[ "$(stat -c %u "$DEST")" != "$(id -u)" ||
      "$(stat -c %u "$UNITDIR")" != "$(id -u)" ||
      "$(stat -c %u "$BIN")" != "$(id -u)" ]]; then
  echo "Dashboard folders are not owned by the current user" >&2
  exit 1
fi
chmod 700 "$DEST"
install -m 600 "$WORK/tools/subhub_dashboard_server.py" "$DEST/subhub_dashboard_server.py.new"
install -m 600 "$WORK/tools/subhub_dashboard.html" "$DEST/subhub_dashboard.html.new"
install -m 600 "$WORK/tools/ja_first_source_tracker.py" "$DEST/ja_first_source_tracker.py.new"
install -m 600 "$WORK/tools/subhub_translation_batch.py" "$DEST/subhub_translation_batch.py.new"
install -m 600 "$WORK/tools/subhub_season_sources.py" "$DEST/subhub_season_sources.py.new"
install -m 600 "$WORK/tools/bruiser_coverage_queue.py" "$DEST/bruiser_coverage_queue.py.new"
mv -f "$DEST/subhub_dashboard_server.py.new" "$DEST/subhub_dashboard_server.py"
mv -f "$DEST/subhub_dashboard.html.new" "$DEST/subhub_dashboard.html"
mv -f "$DEST/ja_first_source_tracker.py.new" "$DEST/ja_first_source_tracker.py"
mv -f "$DEST/subhub_translation_batch.py.new" "$DEST/subhub_translation_batch.py"
mv -f "$DEST/subhub_season_sources.py.new" "$DEST/subhub_season_sources.py"
mv -f "$DEST/bruiser_coverage_queue.py.new" "$DEST/bruiser_coverage_queue.py"

cat > "$UNIT.new" <<'UNITFILE'
[Unit]
Description=Standalone SubHub subtitle dashboard (owner controls, loopback)
After=network.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 -B -u %h/.local/share/bruiser-subhub-dashboard/subhub_dashboard_server.py --port 17876
Environment=PYTHONDONTWRITEBYTECODE=1
Restart=on-failure
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=read-only
UMask=0077

[Install]
WantedBy=default.target
UNITFILE
chmod 600 "$UNIT.new"
mv -f "$UNIT.new" "$UNIT"

cat > "$SHORTCUT.new" <<'DESKTOP'
[Desktop Entry]
Type=Application
Name=SubHub Dashboard
GenericName=Subtitle Automation
Comment=Open standalone SubHub owner dashboard
Exec=xdg-open http://127.0.0.1:17876/
Icon=applications-multimedia
Terminal=false
Categories=AudioVideo;Utility;
StartupNotify=false
DESKTOP
chmod 644 "$SHORTCUT.new"
mv -f "$SHORTCUT.new" "$SHORTCUT"

systemctl --user daemon-reload
systemctl --user enable bruiser-subhub-dashboard.service
# Updated dashboard code requires a restart of the DASHBOARD service only.
# The independent subtitle sourcing worker remains untouched.
systemctl --user restart bruiser-subhub-dashboard.service
# Server may need a moment to bind, but the installer must not claim it is
# running just because systemd accepted the unit configuration.
healthy=0
for attempt in {1..16}; do
  if curl -fsS --max-time 2 http://127.0.0.1:17876/healthz |
     grep -Eq '"mode"[[:space:]]*:[[:space:]]*"owner_controls"'; then
    healthy=1
    break
  fi
  sleep 0.5
done
if [[ "$healthy" != 1 ]]; then
  echo "Dashboard did not pass HTTP health check." >&2
  systemctl --user status bruiser-subhub-dashboard.service --no-pager >&2 || true
  exit 1
fi
echo "SUBHUB_DASHBOARD_INSTALLED"
echo "Mode: owner controls | Listener: 127.0.0.1:17876 | Service: active"
echo "Desktop launcher: $SHORTCUT"
echo "Open on OptiPlex: http://127.0.0.1:17876/"
echo "Running source batch and OptiPlex NOW were NOT modified."
echo "Remote access requires an SSH tunnel; do not expose this HTTP port to the Internet."
