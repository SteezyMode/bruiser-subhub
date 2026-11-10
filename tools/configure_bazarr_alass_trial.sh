#!/usr/bin/env bash
# Install an existing Bazarr/alass postprocessor in the isolated Sunny trial.
# No custom subtitle algorithms, no provider access, no production media.
set -euo pipefail
umask 077
ROOT="$HOME/bruiser-pilot/bazarr-trial"
APP="bruiser-bazarr-trial"
URL="https://github.com/friedrich-de/bazarr-sync-my-subs/releases/download/v0.1.9/bazarr-subsync-linux-x86_64-musl"
BIN="$ROOT/config/bazarr/scripts/bazarr-subsync"
fail() { printf 'TRIAL BLOCKED: %s\n' "$*" >&2; exit 1; }

[[ -d "$ROOT/config/bazarr/config" && -f "$ROOT/config/bazarr/config/config.yaml" ]] || fail "Missing Bazarr trial config"
[[ -d "$ROOT/media/tv/It's Always Sunny in Philadelphia" ]] || fail "Missing isolated Sunny media"
[[ "$(uname -m)" == "x86_64" ]] || fail "Release binary requires x86_64"
command -v docker >/dev/null || fail "Docker missing"
command -v curl >/dev/null || fail "curl missing"
if ! docker inspect "$APP" >/dev/null 2>&1; then fail "Trial container missing"; fi
mounts=$(docker inspect --format '{{json .Mounts}}' "$APP")
python3 - "$ROOT" "$mounts" <<'PY'
import json, pathlib, sys
root=pathlib.Path(sys.argv[1]).resolve()
mounts=json.loads(sys.argv[2])
if not mounts or any(not pathlib.Path(m.get("Source","/")).resolve().is_relative_to(root)
                     for m in mounts):
    raise SystemExit("TRIAL BLOCKED: unexpected Bazarr container mount")
expected=str(root / "config/bazarr")
if not any(m["Destination"] == "/config" and m["Source"] == expected for m in mounts):
    raise SystemExit("TRIAL BLOCKED: expected /config mount missing")
PY

mkdir -p "$(dirname "$BIN")"
if [[ ! -f "$BIN" ]]; then
    tmp=$(mktemp "$(dirname "$BIN")/.bazarr-subsync.XXXXXX")
    trap 'rm -f "$tmp"' EXIT
    curl -fsSL --retry 3 "$URL" -o "$tmp"
    chmod 755 "$tmp"
    mv "$tmp" "$BIN"
    trap - EXIT
fi
chmod 755 "$BIN"
echo "=== VERIFY OFF-THE-SHELF BINARY IN BAZARR ==="
docker exec "$APP" sh -c 'command -v ffmpeg >/dev/null && command -v ffprobe >/dev/null' \
    || fail "Bazarr container missing ffmpeg/ffprobe"
docker exec "$APP" /config/scripts/bazarr-subsync --help >/dev/null \
    || fail "Bazarr postprocessor did not run (possible ABI mismatch)"

echo "=== SET DOCUMENTED BAZARR POSTPROCESSING HOOK ==="
python3 - "$ROOT/config/bazarr/config/config.yaml" <<'PY'
import json, re, sys, urllib.parse, urllib.request
from pathlib import Path
config=Path(sys.argv[1]).read_text("utf-8")
match=re.search(r"(?m)^auth:\s*\n(?:[ \t]+[^\n]+\n)*?[ \t]+apikey:[ \t]*['\"]?([a-fA-F0-9]{32,128})",config)
if not match:
    raise SystemExit("TRIAL BLOCKED: Bazarr API key unavailable")
key=match.group(1)
base="http://100.121.156.34:16767"
def api(method,path,fields=None):
    headers={"X-Api-Key":key}
    payload=None
    if fields is not None:
        payload=urllib.parse.urlencode(fields).encode("utf-8")
        headers["Content-Type"]="application/x-www-form-urlencoded"
    req=urllib.request.Request(base+path,data=payload,headers=headers,method=method)
    with urllib.request.urlopen(req,timeout=30) as response:
        body=response.read()
        return json.loads(body) if body else None
current=api("GET","/api/system/settings")
if current.get("general",{}).get("enabled_providers"):
    raise SystemExit("TRIAL BLOCKED: providers are already configured; inspect first")
if current.get("general",{}).get("use_radarr"):
    raise SystemExit("TRIAL BLOCKED: unexpected Radarr enabled")
cmd="/config/scripts/bazarr-subsync --episode {{episode}} --subtitles {{subtitles}}"
api("POST","/api/system/settings",{
    "settings-general-use_postprocessing":"true",
    "settings-general-postprocessing_cmd":cmd,
    "settings-general-use_postprocessing_threshold":"false",
    "settings-subsync-use_subsync":"false",
    "settings-sonarr-defer_search_signalr":"true",
    "settings-general-upgrade_subs":"false",
})
after=api("GET","/api/system/settings")
if (after.get("general",{}).get("postprocessing_cmd") != cmd
    or not after.get("general",{}).get("use_postprocessing")
    or after.get("subsync",{}).get("use_subsync")):
    raise SystemExit("TRIAL BLOCKED: Bazarr post-processing configuration did not persist")
print("BAZARR: external alass sync hook ENABLED; Bazarr native ffsubsync DISABLED")
print("BAZARR: postprocess uses Bazarr's actual video/subtitle arguments")
print("PROVIDERS: still disabled; no quotas consumed")
print("OUTPUT: original download + .alass1/.alass2 candidates (not automatically promoted)")
PY
echo "Trial configuration complete. Production media remains unmounted."
