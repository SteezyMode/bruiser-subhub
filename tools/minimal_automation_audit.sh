#!/usr/bin/env bash
# Read-only live information about existing Sublarr + Hy-MT2 assets.
# Starts the already-installed Sublarr container if it is stopped.
# Does not change settings, queue, originals, translations or subtitles.
set -euo pipefail
NAME=sublarr-pilot
echo "=== CURRENT SUBLARR CONTAINER ==="
if ! docker inspect "$NAME" >/dev/null 2>&1; then
  echo "ERROR: Sublarr pilot container not installed. No changes made."
  exit 1
fi
if [ "$(docker inspect -f '{{.State.Running}}' "$NAME")" != true ]; then
  echo "Starting the existing stopped Sublarr container..."
  docker start "$NAME" >/dev/null
fi
docker inspect -f 'Image={{.Config.Image}} Restart={{.HostConfig.RestartPolicy.Name}}' "$NAME"
echo "Media mounts (container destination and writable flag only):"
docker inspect -f '{{range .Mounts}}{{println .Destination .RW}}{{end}}' "$NAME"
echo
echo "=== API + CONFIGURATION (NON-SECRET FIELDS ONLY) ==="
docker exec -i -e PYTHONPATH=/app "$NAME" python3 - <<'PY'
import json, time
import urllib.request

from config import get_settings
cfg = get_settings()
headers = {"X-Api-Key": cfg.api_key} if cfg.api_key else {}
base = "http://127.0.0.1:5765"
for i in range(30):
    try:
        with urllib.request.urlopen(base + "/api/v1/health", timeout=3) as r:
            print("Health:", r.status)
        break
    except Exception:
        if i == 29:
            print("Health not ready")
        time.sleep(2)

def read(path):
    req = urllib.request.Request(base + path, headers=headers)
    with urllib.request.urlopen(req, timeout=12) as r:
        return json.load(r)

try:
    spec = read("/api/v1/openapi.json")
    paths = sorted(spec.get("paths", {}))
    print("Useful exposed API paths:")
    for p in paths:
        if any(word in p.lower() for word in (
            "config", "settings", "translation", "provider",
            "wanted", "post-processing", "subtitle",
        )):
            print(" ", p)
except Exception as e:
    print("API discovery unavailable:", type(e).__name__)

try:
    values = read("/api/v1/config")
except Exception as e:
    print("Config API unavailable:", type(e).__name__)
else:
    include = (
        "translation_enabled", "translation_backend", "translation_model",
        "wanted_", "scan_interval", "hearing_impaired", "hi_remov",
        "sdh", "auto_extract", "auto_sync", "post_processing",
        "sync_engine", "translation_batch",
    )
    exclude = (
        "password", "secret", "token", "credential", "api_key",
        "apikey", "auth", "cookie", "url", "header", "prompt",
        "private", "keypool", "login",
    )
    collected = []
    def walk(v, key="", depth=0):
        if depth > 3 or len(collected) > 100:
            return
        if isinstance(v, dict):
            for k, item in v.items():
                walk(item, key + "." + str(k), depth + 1)
        elif isinstance(v, (bool, int, float, str)):
            low = key.lower()
            if (any(k in low for k in include)
                    and not any(k in low for k in exclude)
                    and len(str(v)) < 100):
                collected.append((key.lstrip("."), v))
    walk(values)
    print("Selected non-secret settings:")
    for key, value in sorted(collected):
        print(" ", key, "=", value)
    if not collected:
        print("  No matching settings in this API response")
PY

echo
echo "=== EXISTING UTILITIES ==="
for name in ffmpeg ffprobe ffsubsync alass ollama; do
  if command -v "$name" >/dev/null 2>&1; then
    printf "Host: %-12s %s\n" "$name" "$(command -v "$name")"
  fi
done
docker exec "$NAME" sh -c '
  for name in ffmpeg ffprobe ffsubsync alass; do
    if command -v "$name" >/dev/null 2>&1; then
      printf "Sublarr: %-12s %s\n" "$name" "$(command -v "$name")"
    fi
  done
'
echo
echo "=== TESTED HY-MT2 REFERENCE INPUTS ==="
python3 - <<'PY'
import re
from pathlib import Path
root = Path.home() / "bruiser-pilot/descent2"
for name in ("Descent2-YIFY-clean.en.srt", "Descent2-YIFY-draft.ja.srt"):
    path = root / name
    if path.exists():
        blocks = re.split(r"\n[ \t]*\n", path.read_text(encoding="utf-8-sig").strip())
        print(name, "cues:", len(blocks), "bytes:", path.stat().st_size)
    else:
        print(name, "missing")
PY
echo
echo "DONE: existing Sublarr started if necessary; no settings or media changed."
