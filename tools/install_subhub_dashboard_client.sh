#!/usr/bin/env bash
# Install a one-click Linux desktop shortcut to the remote standalone SubHub.
# Requires an existing SSH key for the requested OptiPlex/Tailscale endpoint.
# Does not change the host, subtitle service, or OptiPlex NOW.
set -euo pipefail
umask 077
if [[ $# -ne 1 || ! "$1" =~ ^([A-Za-z_][A-Za-z0-9_.-]*@)?[A-Za-z0-9_.-]+$ ]]; then
  echo "Usage: install_subhub_dashboard_client.sh ssh-user@tailnet-ip-or-hostname" >&2
  exit 2
fi
HOST="$1"
BIN="$HOME/.local/bin"
APP="$HOME/.local/share/applications"
LAUNCH="$BIN/subhub-dashboard-remote"
DESKTOP="$APP/subhub-dashboard-remote.desktop"
for file in "$BIN" "$APP" "$LAUNCH" "$DESKTOP"; do
  if [[ -L "$file" ]]; then
    echo "Symlink refused: $file" >&2
    exit 1
  fi
done
mkdir -p "$BIN" "$APP"
if [[ "$(stat -c %u "$BIN")" != "$(id -u)" ||
      "$(stat -c %u "$APP")" != "$(id -u)" ]]; then
  echo "Client desktop folders must belong to this user" >&2
  exit 1
fi
cat >"$LAUNCH.new" <<'CLIENT'
#!/usr/bin/env bash
set -euo pipefail
if [[ $# -ne 1 ]]; then
  echo "Usage: subhub-dashboard-remote ssh-user@host" >&2
  exit 2
fi
TARGET="$1"
if ! curl -fsS --max-time 2 http://127.0.0.1:17876/healthz 2>/dev/null |
      grep -Eq '"mode"[[:space:]]*:[[:space:]]*"owner_controls"'; then
  # SSH binds a local-only forward. BatchMode keeps a desktop icon from hanging
  # forever on an invisible password prompt.
  ssh -f -N -o BatchMode=yes -o ExitOnForwardFailure=yes \
      -o ConnectTimeout=12 -o ServerAliveInterval=30 \
      -o ServerAliveCountMax=3 \
      -L 127.0.0.1:17876:127.0.0.1:17876 "$TARGET"
fi
for attempt in {1..15}; do
  if curl -fsS --max-time 2 http://127.0.0.1:17876/healthz 2>/dev/null |
      grep -Eq '"mode"[[:space:]]*:[[:space:]]*"owner_controls"'; then
    exec xdg-open http://127.0.0.1:17876/
  fi
  sleep 0.5
done
echo "Remote SubHub not reachable. Test SSH key and remote service." >&2
exit 1
CLIENT
chmod 700 "$LAUNCH.new"
mv -f "$LAUNCH.new" "$LAUNCH"
{
  printf '[Desktop Entry]\n'
  printf 'Type=Application\nName=SubHub Dashboard (OptiPlex)\n'
  printf 'Comment=Control the standalone subtitle service securely over Tailscale SSH\n'
  printf 'Exec="%s" %s\n' "$LAUNCH" "$HOST"
  printf 'Icon=applications-multimedia\nTerminal=false\n'
  printf 'Categories=AudioVideo;Utility;\nStartupNotify=false\n'
} >"$DESKTOP.new"
chmod 644 "$DESKTOP.new"
mv -f "$DESKTOP.new" "$DESKTOP"
echo "SUBHUB_REMOTE_SHORTCUT_INSTALLED $DESKTOP"
echo "One click opens the remote dashboard via SSH tunnel if SSH keys work."
echo "Troubleshoot in terminal: $LAUNCH $HOST"
