#!/usr/bin/env bash
# Restore the phone engine to 0.2.0 NOW, keeping the failed candidate's logs for diagnosis.
set -uo pipefail
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
LIVE=/opt/dsh-phone
PREV=$(ls -dt /opt/dsh-phone.prev-0.2.0-rc.2-* 2>/dev/null | head -1)
NODE=/usr/local/node22/bin/node
DSH=/root/.dsh
PATCH=$DSH/profiles/web/cordis.patch.yml
CRED=$DSH/.credentials.yaml
UNIT=/etc/systemd/system/phone-engine.service

echo "=== capture the candidate's own log before touching anything ==="
tail -25 /root/.dsh-phone/engine-3089.err 2>/dev/null | grep -aviE 'CallToolRequest|server\.py|Processing request' | tail -14 | sed 's/^/  /'
echo "  --- stdout log ---"
tail -10 /root/.dsh-phone/engine-3089.log 2>/dev/null | sed 's/^/  /'

echo "=== stopping the failed unit ==="
systemctl stop phone-engine 2>/dev/null

echo "=== restoring tree ==="
if [ -n "$PREV" ] && [ -d "$PREV" ]; then
  mv "$LIVE" "/opt/dsh-phone.failed-021-$STAMP" 2>/dev/null
  mv "$PREV" "$LIVE" && echo "  restored $LIVE from $(basename "$PREV")"
else
  echo "  REFUSED: no previous tree found"; exit 2
fi

echo "=== restoring unit, credentials, config ==="
for f in "$UNIT" "$CRED" "$PATCH"; do
  B=$(ls -t "$f".bak-phone021-* 2>/dev/null | head -1)
  [ -n "$B" ] && cp -p "$B" "$f" && echo "  restored $f from $(basename "$B")"
done
systemctl daemon-reload

echo "=== starting the old engine ==="
systemctl start phone-engine
for i in $(seq 1 12); do
  sleep 5
  S=$(systemctl is-active phone-engine)
  C=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 http://127.0.0.1:3089/ || true)
  echo "  t+$((i*5))s state=$S http=${C:-none}"
  [ "$S" = "active" ] && [ "${C:-000}" != "000" ] && break
done
echo "=== final ==="
echo "  unit: $(systemctl is-active phone-engine)  version: $($NODE "$LIVE/node_modules/@deepseek-ai/dsh/lib/bin.js" --version 2>&1 | tail -1)"
curl -s -o /dev/null -w '  http 3089 -> %{http_code}\n' --max-time 8 http://127.0.0.1:3089/ || true
