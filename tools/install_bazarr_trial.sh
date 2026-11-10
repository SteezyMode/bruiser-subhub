#!/usr/bin/env bash
# Isolated Bazarr/Sonarr/Radarr experiment. Does not write into real media mounts.
set -euo pipefail
umask 077

ROOT="$HOME/bruiser-pilot/bazarr-trial"
SRC="/mnt/2TB/Plex Expansion/Television/Episodic/It's Always Sunny in Philadelphia/Season 01"
IP="100.121.156.34"

fail() { echo "BAZARR_TRIAL_BLOCKED: $*" >&2; exit 1; }
command -v docker >/dev/null || fail "Docker missing"
command -v tailscale >/dev/null || fail "Tailscale missing"
command -v ss >/dev/null || fail "ss missing"
docker info >/dev/null 2>&1 || fail "Cannot access Docker daemon"
docker compose version >/dev/null 2>&1 || fail "docker compose plugin unavailable"
[[ -d "$SRC" && ! -L "$SRC" ]] || fail "Expected existing TV source folder missing"
[[ -d "$HOME/bruiser-pilot" && ! -L "$HOME/bruiser-pilot" ]] || fail "Existing private bruiser-pilot root missing or symlinked"
[[ "$(tailscale ip -4 | head -n 1)" == "$IP" ]] || fail "OptiPlex Tailscale IP changed; stop rather than expose to LAN"

if [[ -f "$ROOT/compose.yaml" ]]; then
  echo "Existing trial found; leaving config and media unchanged."
  docker compose -f "$ROOT/compose.yaml" ps
  exit 0
fi

for name in bruiser-bazarr-trial bruiser-sonarr-trial bruiser-radarr-trial; do
  if docker container inspect "$name" >/dev/null 2>&1; then
    fail "Existing container $name found without this trial's compose.yaml"
  fi
done
for port in 16767 18989 17878; do
  if ss -H -ltn | awk '{print $4}' | grep -Eq ":$port$"; then
    fail "Host TCP port $port already in use"
  fi
done

E04=""
E05=""
for ep in S01E04 S01E05; do
  mapfile -d '' found < <(find "$SRC" -maxdepth 1 -type f \( -iname "*$ep*.mkv" -o -iname "*$ep*.mp4" \) -print0)
  [[ "${#found[@]}" -eq 1 ]] || fail "Expected exactly one existing video for $ep; found ${#found[@]}"
  if [[ "$ep" == S01E04 ]]; then E04="${found[0]}"; else E05="${found[0]}"; fi
done

NEED=$(( $(stat -c %s "$E04") + $(stat -c %s "$E05") + 536870912 ))
FREE=$(df -B1 --output=avail "$HOME" | tail -n 1 | tr -d '[:space:]')
[[ "$FREE" =~ ^[0-9]+$ && "$FREE" -gt "$NEED" ]] ||
  fail "Not enough space on home volume for independent test copies"

DST="$ROOT/media/tv/It's Always Sunny in Philadelphia/Season 01"
mkdir -p "$DST" "$ROOT/media/movies" "$ROOT/config/bazarr" "$ROOT/config/sonarr" "$ROOT/config/radarr"

for file in "$E04" "$E05"; do
  cp --reflink=auto --no-clobber "$file" "$DST/"
done
# E04 retains the original Japanese track for a timing-repair comparison.
# E05 has no JA sidecar in scratch, allowing a genuine provider search.
for suffix in ja.srt jpn.srt en.srt eng.srt; do
  sidecar="${E04%.*}.$suffix"
  if [[ -f "$sidecar" && ! -L "$sidecar" ]]; then
    cp --reflink=auto --no-clobber "$sidecar" "$DST/"
  fi
done

PUID=$(id -u)
PGID=$(id -g)
cat > "$ROOT/compose.yaml" <<YAML
name: bruiser-bazarr-trial
services:
  sonarr:
    image: lscr.io/linuxserver/sonarr:latest
    container_name: bruiser-sonarr-trial
    restart: "no"
    environment:
      PUID: "$PUID"
      PGID: "$PGID"
      TZ: Asia/Tokyo
    volumes:
      - "$ROOT/config/sonarr:/config"
      - "$ROOT/media/tv:/tv"
    ports:
      - "$IP:18989:8989"
  radarr:
    image: lscr.io/linuxserver/radarr:latest
    container_name: bruiser-radarr-trial
    restart: "no"
    environment:
      PUID: "$PUID"
      PGID: "$PGID"
      TZ: Asia/Tokyo
    volumes:
      - "$ROOT/config/radarr:/config"
      - "$ROOT/media/movies:/movies"
    ports:
      - "$IP:17878:7878"
  bazarr:
    image: lscr.io/linuxserver/bazarr:latest
    container_name: bruiser-bazarr-trial
    restart: "no"
    environment:
      PUID: "$PUID"
      PGID: "$PGID"
      TZ: Asia/Tokyo
    volumes:
      - "$ROOT/config/bazarr:/config"
      - "$ROOT/media/tv:/tv"
      - "$ROOT/media/movies:/movies"
    ports:
      - "$IP:16767:6767"
YAML

docker compose -f "$ROOT/compose.yaml" config --quiet
docker compose -f "$ROOT/compose.yaml" pull
docker compose -f "$ROOT/compose.yaml" up -d
echo "=== BAZARR TRIAL CONTAINERS ==="
docker compose -f "$ROOT/compose.yaml" ps
echo
echo "BAZARR: http://$IP:16767"
echo "SONARR: http://$IP:18989"
echo "RADARR: http://$IP:17878"
echo "Sonarr library root: /tv (scratch E04 + E05; E04 JA only)"
echo "Radarr library root: /movies (intentionally empty pending exact-cut selection)"
echo "All media copies/config are under $ROOT; originals and existing containers untouched."
