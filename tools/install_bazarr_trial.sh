#!/usr/bin/env bash
# Trial only: independent video copies, isolated Sonarr/Bazarr, no production media mounts.
set -euo pipefail
umask 077
ROOT="$HOME/bruiser-pilot/bazarr-trial"
SRC="/mnt/2TB/Plex Expansion/Television/Episodic/It's Always Sunny in Philadelphia"
IP="100.121.156.34"
fail() { printf 'TRIAL BLOCKED: %s\n' "$*" >&2; exit 1; }
command -v docker >/dev/null || fail 'Docker is missing'
command -v tailscale >/dev/null || fail 'Tailscale is missing'
command -v ss >/dev/null || fail 'ss is missing'
docker info >/dev/null 2>&1 || fail 'Current account cannot use Docker'
docker compose version >/dev/null 2>&1 || fail 'Docker Compose plugin missing'
[[ -d "$SRC" && ! -L "$SRC" ]] || fail 'Actual Sunny series folder is missing'
[[ -d "$HOME/bruiser-pilot" && ! -L "$HOME/bruiser-pilot" ]] || fail 'Existing private trial parent missing'
[[ ! -e "$ROOT" && ! -L "$ROOT" ]] || fail 'Trial folder already exists: inspect instead of overwriting'
tailscale ip -4 | grep -Fxq "$IP" || fail 'Expected Tailscale IP changed; avoid LAN exposure'
for name in bruiser-sonarr-trial bruiser-bazarr-trial; do
  if docker container inspect "$name" >/dev/null 2>&1; then
    fail "Container name in use: $name"
  fi
done
for port in 18989 16767; do
  if ss -H -ltn | awk '{print $4}' | grep -Eq ":$port$"; then
    fail "TCP port in use: $port"
  fi
done
files=()
tags=()
bytes=0
for tag in S02E01 S03E03 S04E03 S05E13 S06E07; do
  season="${tag:1:2}"
  folder="$SRC/Season $season"
  [[ -d "$folder" && ! -L "$folder" ]] || fail "Expected existing Season $season missing"
  mapfile -d '' -t found < <(find "$folder" -maxdepth 1 -type f \
    \( -iname "*$tag*.mkv" -o -iname "*$tag*.mp4" -o -iname "*$tag*.avi" \
       -o -iname "*$tag*.m4v" -o -iname "*$tag*.webm" \) -print0)
  if [[ "${#found[@]}" -ne 1 ]]; then
    printf 'Candidate video files in %s:\n' "$folder" >&2
    find "$folder" -maxdepth 1 -type f -iname "*$tag*" -printf '  %f\n' >&2
    fail "Expected one video for $tag; found ${#found[@]}"
  fi
  [[ ! -L "${found[0]}" ]] || fail "Source for $tag is a symlink"
  files+=("${found[0]}")
  tags+=("$tag")
  bytes=$(( bytes + $(stat -c '%s' "${found[0]}") ))
done
free=$(df -B1 --output=avail "$HOME" | tail -1 | tr -d '[:space:]')
[[ "$free" =~ ^[0-9]+$ ]] || fail 'Cannot measure free space'
(( free > bytes + 1073741824 )) || fail 'Insufficient disk space for independent copies plus 1 GiB reserve'

mkdir -p "$ROOT/config/bazarr" "$ROOT/config/sonarr" "$ROOT/media/tv"
for i in "${!files[@]}"; do
  tag="${tags[$i]}"
  folder="$ROOT/media/tv/It's Always Sunny in Philadelphia/Season ${tag:1:2}"
  mkdir -p "$folder"
  # Only video copies. No existing sidecars are copied or changed;
  # S04E03's original PLaMo subtitle remains safe in the real library.
  cp --reflink=auto -- "${files[$i]}" "$folder/"
  [[ "$(stat -c%s "${files[$i]}")" == "$(stat -c%s "$folder/$(basename "${files[$i]}")")" ]] || fail "Copy size differs: $tag"
  printf 'STAGED VIDEO COPY: %s\n' "$tag"
done
PUID=$(id -u)
PGID=$(id -g)
cat > "$ROOT/compose.yaml" <<YAML
name: bruiser-bazarr-trial
services:
  sonarr:
    image: lscr.io/linuxserver/sonarr:4.0.20
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
    ports:
      - "$IP:16767:6767"
YAML

docker compose -f "$ROOT/compose.yaml" config --quiet
docker compose -f "$ROOT/compose.yaml" up -d
docker compose -f "$ROOT/compose.yaml" ps
printf '\nSonarr: http://%s:18989\nBazarr: http://%s:16767\n' "$IP" "$IP"
printf 'Test media is ONLY under %s/media/tv; production library is not mounted.\n' "$ROOT"
