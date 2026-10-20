#!/usr/bin/env bash
# EMERGENCY: get the phone engine serving 0.2.0 again. It is crash-looping after a failed switch whose rollback
# restored the tree and profile but not a working boot.
set -uo pipefail
LIVE=/opt/dsh-phone
PROF=/root/.dsh/profiles/web
NODE=/usr/local/node22/bin/node
REPAIR=/usr/local/bin/repair-phone-engine.sh

echo "=== state ==="
systemctl is-active phone-engine | sed 's/^/  unit: /'
echo "  engine: $($NODE $LIVE/node_modules/@deepseek-ai/dsh/lib/bin.js --version 2>&1 | tail -1)"
echo "  profile @deepseek-ai: $(test -d $PROF/node_modules/@deepseek-ai && echo present || echo MISSING)"
echo "  profile version markers: $(ls $PROF/node_modules/@deepseek-ai 2>/dev/null | wc -l) packages"
echo "  engine dsh-scope: $(ls -ld $LIVE/node_modules/@deepseek-ai/dsh-scope 2>/dev/null | cut -c1-100)"
echo "  dangling links in engine: $(find $LIVE/node_modules/@deepseek-ai -maxdepth 1 -type l ! -exec test -e {} \; -print 2>/dev/null | wc -l)"

echo "=== stop, repair, start ==="
systemctl stop phone-engine 2>/dev/null
sleep 3
echo "  repair run:"; "$REPAIR" 2>&1 | tail -5 | sed 's/^/    /'
systemctl daemon-reload
systemctl reset-failed phone-engine 2>/dev/null
systemctl start phone-engine

for i in $(seq 1 15); do
  sleep 5
  S=$(systemctl is-active phone-engine)
  C=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 http://127.0.0.1:3089/ || true)
  echo "  t+$((i*5))s state=$S http=${C:-none}"
  [ "$S" = "active" ] && [ "${C:-000}" != "000" ] && break
done

echo "=== final ==="
echo "  unit: $(systemctl is-active phone-engine) restarts=$(systemctl show phone-engine -p NRestarts --value)"
echo "  version: $($NODE $LIVE/node_modules/@deepseek-ai/dsh/lib/bin.js --version 2>&1 | tail -1)"
curl -s -o /dev/null -w '  http 3089 -> %{http_code}\n' --max-time 8 http://127.0.0.1:3089/ || true
journalctl -u phone-engine -n 6 --no-pager -o cat 2>/dev/null | grep -aviE 'CallToolRequest|server\.py' | tail -4 | sed 's/^/    /'
