#!/usr/bin/env bash
# The phone is UP but answering 404 where it used to answer 401: my last switch rewrote the profile patch
# (webRuntime -> webStartup) and its rollback restored the tree and package.json but NOT the patch. A 0.2.0 engine
# cannot inject `webStartup`, so the web rows fail and the root path 404s. Restore the patch from the newest backup
# and verify the 401 that means "engine up, auth required".
set -uo pipefail
P=/root/.dsh/profiles/web/cordis.patch.yml
NODE=/usr/local/node22/bin/node

echo "=== backups available ==="
ls -1t "$P".bak-* 2>/dev/null | head -5 | sed 's/^/  /'
echo "=== current patch ==="
echo "  ctx.webStartup : $(grep -c 'ctx.webStartup' "$P" 2>/dev/null)"
echo "  ctx.webRuntime : $(grep -c 'ctx.webRuntime' "$P" 2>/dev/null)"

B=$(ls -1t "$P".bak-* 2>/dev/null | head -1)
if [ -z "$B" ]; then echo "REFUSED: no backup"; exit 2; fi
echo "=== restoring $B ==="
cp -p "$B" "$P"
echo "  after restore -> webStartup: $(grep -c 'ctx.webStartup' "$P")  webRuntime: $(grep -c 'ctx.webRuntime' "$P")"

echo "=== restart and verify ==="
systemctl restart phone-engine
for i in $(seq 1 12); do
  sleep 5
  S=$(systemctl is-active phone-engine)
  C=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 http://127.0.0.1:3089/ || true)
  echo "  t+$((i*5))s state=$S http=${C:-none}"
  [ "$S" = "active" ] && [ "${C:-000}" = "401" ] && break
done
echo "=== final ==="
echo "  unit=$(systemctl is-active phone-engine) restarts=$(systemctl show phone-engine -p NRestarts --value)"
echo "  version=$($NODE /opt/dsh-phone/node_modules/@deepseek-ai/dsh/lib/bin.js --version 2>&1 | tail -1)"
curl -s -o /dev/null -w '  http 3089 -> %{http_code}\n' --max-time 8 http://127.0.0.1:3089/ || true
echo "  phone gate 3086: $(curl -s -o /dev/null -w '%{http_code}' --max-time 6 http://127.0.0.1:3086/ || echo 000)"
