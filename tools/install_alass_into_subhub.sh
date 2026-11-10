#!/usr/bin/env bash
# Add standalone alass to the EXISTING SubHub publisher. No new service,
# dashboard, media directory, or subtitle-provider account.
set -euo pipefail
umask 077

DEST="$HOME/bruiser-pilot/subhub-control"
PIN="2d0489917a36fd3c91164b66969a068afcfe1ec4"
BASE="https://raw.githubusercontent.com/SteezyMode/bruiser-subhub/$PIN/tools"
ALASS="$HOME/bruiser-pilot/sync-compare.WfaxCBpD/alass-linux64"
fail() { printf 'ALASS INTEGRATION HELD: %s\n' "$*" >&2; exit 1; }

[[ -d "$DEST" && ! -L "$DEST" ]] || fail "Existing SubHub controller not found"
for f in ja_first_publish_queue.py ja_first_ffsubsync.py ja_first_publish_staged.py ja_first_priority.py; do
  [[ -f "$DEST/$f" && ! -L "$DEST/$f" ]] || fail "Missing existing dependency: $f"
done
[[ -x "$ALASS" && -f "$ALASS" && ! -L "$ALASS" ]] ||
  fail "Known-working standalone alass binary missing"

# The existing queue may have unpublished host-local changes. Never replace
# a queue we have not identified; preserve those changes for an additive patch.
PYTHONDONTWRITEBYTECODE=1 python3 - "$DEST/ja_first_publish_queue.py" <<'PY'
import hashlib,sys
from pathlib import Path
body=Path(sys.argv[1]).read_bytes()
blob=hashlib.sha1(b"blob "+str(len(body)).encode()+b"\0"+body).hexdigest()
expected="f95c40cb83a58705e9dcceaba404471cb53dda08"
if blob!=expected:
    raise SystemExit("ALASS INTEGRATION HELD: deployed queue differs from inspected baseline; protect host-local changes (blob="+blob[:12]+")")
print("LIVE QUEUE: matches inspected version; safe additive replacement")
PY
[[ "$(uname -m)" == "x86_64" ]] || fail "Unexpected architecture"
[[ ! -e "$DEST/ja_first_alass.py" && ! -L "$DEST/ja_first_alass.py" ]] ||
  fail "Existing alass module present; review rather than overwrite"

for svc in bruiser-ja-source-autofill.service bruiser-subhub-season-sources.service; do
  if systemctl --user --quiet is-active "$svc" 2>/dev/null; then
    fail "Active source worker ($svc). Do not hot-swap code"
  fi
done

work="$(mktemp -d "$DEST/.alass-install.XXXXXXXX")"
backup=""
rollback=0
cleanup() {
  rc=$?
  if [[ "$rollback" == "1" ]]; then
    cp -f -- "$backup/ja_first_publish_queue.py" "$DEST/ja_first_publish_queue.py"
    rm -f -- "$DEST/ja_first_alass.py"
    printf 'ROLLED BACK: source restored; backup: %s\n' "$backup" >&2
  fi
  rm -rf -- "$work"
  exit "$rc"
}
trap cleanup EXIT

for name in ja_first_alass.py ja_first_publish_queue.py; do
  [[ ! -L "$DEST/$name" ]] || fail "Symlinked source file"
  curl -fsSL --retry 3 --connect-timeout 10 --max-time 50 \
    "$BASE/$name" -o "$work/$name"
  chmod 600 "$work/$name"
done

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$work:$DEST" python3 - <<'PY'
import ast, os
from pathlib import Path
work=Path(os.environ["PYTHONPATH"].split(":")[0])
for fn in ("ja_first_alass.py","ja_first_publish_queue.py"):
    ast.parse((work/fn).read_text("utf-8"),filename=fn)
import ja_first_alass as alass
import ja_first_publish_queue as queue
assert alass.available()
queue.self_test()
def stamp(ms):
    h,rem=divmod(ms,3600000)
    m,rem=divmod(rem,60000)
    s,ms=divmod(rem,1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"
def subtitle(shift):
    return ("\n\n".join(
        f"{i+1}\n{stamp(30000+5000*i+shift(i))} --> "
        f"{stamp(32000+5000*i+shift(i))}\n日本語の字幕 {i}"
        for i in range(100))+"\n").encode()
src=subtitle(lambda _:0)
fixed=subtitle(lambda i: -1900 if i<30 else 300 if i<70 else 2300)
report=alass.assess(src,fixed,1000)
assert report["nonuniform_correction"] and report["cues"]==100
print("PREFLIGHT: alass binary, queue import, multi-section shift test passed")
PY

backup="$DEST/.alass-source-backup-$(date +%Y%m%dT%H%M%S)"
mkdir -m 700 "$backup"
cp -p -- "$DEST/ja_first_publish_queue.py" "$backup/"
rollback=1
for name in ja_first_alass.py ja_first_publish_queue.py; do
  mv -f -- "$work/$name" "$DEST/$name"
done
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$DEST" \
  python3 "$DEST/ja_first_publish_queue.py" --self-test
rollback=0
printf '\nALASS INTEGRATED into the existing SubHub publisher.\n'
printf 'Source backup: %s\n' "$backup"
printf 'No daemon restarted; no source search, AI work or media writes.\n'
printf 'Standalone alass is preferred for new staged JA; ffsubsync remains fallback.\n'
