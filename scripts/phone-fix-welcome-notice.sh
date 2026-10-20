#!/usr/bin/env bash
# The phone shows the "Preview Notice" on every new session and its Continue button fails with
# "The acknowledgement could not be saved. Please try again."
#
# WHY: dsh-client-ui-settings-models compares the stored `welcomeNoticeVersion` for EXACT equality with
# `WELCOME_NOTICE_VERSION = "2026-09-28.1"` (lib/client.js:3058). This estate's settings pin that field to the older
# `2026-08-13.1`, so the notice thinks it has never been acknowledged. Pressing Continue writes the new value into the
# settings document — a GENERATED block (`settings-from-yaml`, written by dsh-update/tools/settings-to-entries.mjs) —
# and that write is what fails.
#
# The durable fix is not to make the write work: it is to acknowledge the notice in the settings SOURCE, so the value
# is already equal and nothing needs saving. Both the live patch and the repo's settings source are corrected here.
set -uo pipefail
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
P=/root/.dsh/profiles/web/cordis.patch.yml
REPO=/root/code/harness-config/settings/base.yaml
NODE=/usr/local/node22/bin/node

echo "=== before ==="
grep -n "welcomeNoticeVersion" "$P" | cut -c1-120 | sed 's/^/  /'
grep -n "welcomeNoticeVersion" "$REPO" 2>/dev/null | cut -c1-120 | sed 's/^/  repo: /'

cp -p "$P" "$P.bak-welcome-$STAMP"
[ -f "$REPO" ] && cp -p "$REPO" "$REPO.bak-welcome-$STAMP"

echo "=== setting it to the version the client checks for (2026-09-28.1) ==="
python3 - "$P" "$REPO" <<'PY'
import pathlib, re, sys
new = "2026-09-28.1"
for path in sys.argv[1:]:
    p = pathlib.Path(path)
    if not p.exists():
        print(f"  {path}: absent, skipped"); continue
    t = p.read_text(encoding="utf-8")
    t2 = re.sub(r"(welcomeNoticeVersion:\s*)[0-9][0-9.\-]*", rf"\g<1>{new}", t)
    if t2 != t:
        p.write_text(t2, encoding="utf-8")
        print(f"  {path}: updated")
    else:
        print(f"  {path}: unchanged")
PY

echo "=== after ==="
grep -n "welcomeNoticeVersion" "$P" | cut -c1-120 | sed 's/^/  /'
grep -n "welcomeNoticeVersion" "$REPO" 2>/dev/null | cut -c1-120 | sed 's/^/  repo: /'

echo "=== restart and verify ==="
systemctl restart phone-engine
for i in $(seq 1 12); do
  sleep 5
  C=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 http://127.0.0.1:3089/ || true)
  echo "  t+$((i*5))s $(systemctl is-active phone-engine) http=${C:-none}"
  [ "${C:-000}" = "401" ] && break
done
echo "  composed value: $(DSH_HOME=/root/.dsh $NODE /opt/dsh-phone/node_modules/@deepseek-ai/dsh/lib/bin.js --profile web --dump-config 2>/dev/null | grep -oE 'welcomeNoticeVersion: [0-9.\-]+' | head -1)"
echo "  unit=$(systemctl is-active phone-engine) version=$($NODE /opt/dsh-phone/node_modules/@deepseek-ai/dsh/lib/bin.js --version 2>&1 | tail -1) http=$(curl -s -o /dev/null -w '%{http_code}' --max-time 6 http://127.0.0.1:3089/ || echo 000) gate=$(curl -s -o /dev/null -w '%{http_code}' --max-time 6 http://127.0.0.1:3086/ || echo 000)"
