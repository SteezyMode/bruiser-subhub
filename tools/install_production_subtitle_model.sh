#!/usr/bin/env bash
# Guarded production E4B deployment. Run on OptiPlex as regular user.
# No translation jobs, model downloads, provider calls or media writes.
set -euo pipefail
umask 077
PIN="6bee7700a234df219fa3073b45f19fe7a73ecf39"
BASE="https://raw.githubusercontent.com/SteezyMode/bruiser-subhub/$PIN"
HOST="$HOME/bruiser-pilot/subhub1"
CONTROL="$HOME/bruiser-pilot/subhub-control"
STATE="$HOME/bruiser-pilot/subhub1-state"
OLD_SERVICE="2dc325e728ef1eb9fdbb709bb0d27dd1e8532cad"
OLD_MAIN="e523d1809fa96836314146ccb88f7405a8de6c42"

if [[ ! -d "$HOST" || ! -d "$CONTROL" || ! -d "$STATE" ||
      -L "$HOST" || -L "$CONTROL" || -L "$STATE" ||
      ! -f "$HOST/service.py" || ! -f "$HOST/main.py" ||
      -L "$HOST/service.py" || -L "$HOST/main.py" ]]; then
  echo "BLOCKED: host paths missing or unsafe" >&2
  exit 1
fi
if pgrep -af '[d]aily_worker.py|[s]ubhub1/main.py' >/dev/null; then
  echo "BLOCKED: SubHub worker or main process active" >&2
  pgrep -af '[d]aily_worker.py|[s]ubhub1/main.py' || true
  exit 1
fi

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
mkdir -m 700 "$WORK/tools"
for name in service.py main.py tools/subtitle_tuned_production.py \
  tools/daily_worker.py tools/subtitle_publish_gate.py \
  tools/subtitle_quality_010.py test_subtitle_tuned_production.py \
  test_daily_worker.py test_subhub1.py
do
  curl -fsSL --retry 3 --connect-timeout 10 --max-time 50 \
    "$BASE/$name" -o "$WORK/$name"
done

echo "=== SYNTAX ==="
PYTHONDONTWRITEBYTECODE=1 python3 - "$WORK" <<'PY'
import ast,sys
from pathlib import Path
root=Path(sys.argv[1])
files=list(root.rglob('*.py'))
for f in files: ast.parse(f.read_text('utf-8'),filename=str(f))
print('Syntax OK:',len(files),'Python files')
PY
echo "=== OFFLINE TESTS (MUST ALL PASS) ==="
(cd "$WORK" && PYTHONPATH="$WORK" PYTHONDONTWRITEBYTECODE=1 \
 python3 -m unittest test_subtitle_tuned_production test_subhub1 test_daily_worker -v)

echo "=== CANONICAL HOST CODE CHECK ==="
PYTHONDONTWRITEBYTECODE=1 python3 - "$HOST/service.py" "$HOST/main.py" \
 "$WORK/service.py" "$WORK/main.py" "$OLD_SERVICE" "$OLD_MAIN" <<'PY'
import hashlib,sys
from pathlib import Path
def blob(path):
    data=Path(path).read_bytes()
    return hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
live_service,live_main,new_service,new_main,old_service,old_main=sys.argv[1:]
for label,old,new,expected in (
    ('service.py',live_service,new_service,old_service),
    ('main.py',live_main,new_main,old_main),
):
    actual,desired=blob(old),blob(new)
    print(label,'installed:',actual,'proposed:',desired)
    if actual not in (expected,desired):
        raise SystemExit('BLOCKED: unrecognized local '+label+
                         '; no files replaced')
print('Host matches a known safe version')
PY

BACKUPS="$HOME/bruiser-pilot/subhub-model-backups"
if [[ -L "$BACKUPS" ]]; then
  echo "BLOCKED: symlinked backups" >&2; exit 1
fi
mkdir -p -m 700 "$BACKUPS"
chmod 700 "$BACKUPS"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
for name in service.py main.py; do
  cp -p "$HOST/$name" "$BACKUPS/$name.$STAMP.pre-e4b"
done
if [[ -f "$CONTROL/daily_worker.py" ]]; then
  cp -p "$CONTROL/daily_worker.py" \
    "$BACKUPS/daily_worker.py.$STAMP.pre-e4b"
fi

atomic_copy() {
  local src="$1" dst="$2" tmp
  if [[ -L "$dst" ]]; then
    echo "BLOCKED: symlinked destination $dst" >&2; exit 1
  fi
  tmp="$(mktemp "$(dirname "$dst")/.e4b-stage.XXXXXXXX")"
  cp "$src" "$tmp"
  chmod 600 "$tmp"
  mv -f "$tmp" "$dst"
}
atomic_copy "$WORK/tools/subtitle_tuned_production.py" \
 "$HOST/subtitle_tuned_production.py"
atomic_copy "$WORK/tools/subtitle_tuned_production.py" \
 "$CONTROL/subtitle_tuned_production.py"
atomic_copy "$WORK/service.py" "$HOST/service.py"
atomic_copy "$WORK/main.py" "$HOST/main.py"
atomic_copy "$WORK/tools/daily_worker.py" "$CONTROL/daily_worker.py"

echo "=== INSTALLED MODEL IDENTITY ==="
PYTHONDONTWRITEBYTECODE=1 python3 - "$HOST" "$CONTROL" <<'PY'
import sys
sys.path.insert(0,sys.argv[1])
sys.path.insert(0,sys.argv[2])
import service,subtitle_tuned_production as tuned
assert service.GEMMA==tuned.MODEL
assert tuned.NUM_CTX==1344 and tuned.NUM_PREDICT==256
assert tuned.MODEL_ID_PREFIX=='9ccfc3b07081'
print('PRODUCTION MODEL:',service.GEMMA)
print('MODEL ID PIN:',tuned.MODEL_ID_PREFIX)
print('SYSTEM PROMPT SHA256:',tuned.PROFILE['system_sha256'])
print('OFFICIAL CARD:',tuned.MODEL_CARD)
PY
echo "INSTALL COMPLETE: no translation or publication initiated"
echo "BACKUPS: $BACKUPS"
echo "GPU/MODEL PREFLIGHT: python3 $CONTROL/subtitle_tuned_production.py --preflight"
