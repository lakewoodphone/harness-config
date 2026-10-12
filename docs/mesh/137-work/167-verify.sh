#!/bin/sh
# 167 -- verify the honest-closing patch on the cloud authority, read-only.
# The database is opened by the script itself as file:...?mode=ro (uri=True), so every
# run below is read-only. Nothing here restarts company-api, cloudflared,
# secretary-dashboard or phone-redirector, and nothing writes to authority.db.
set -u
OUT=/tmp/167-run.txt
: > "$OUT"
exec >>"$OUT" 2>&1

run() {
  AI_GATEWAY_HEALTH_DB=/root/authority.db \
  AI_GATEWAY_HEALTH_CONFIG=/opt/company/app/config.py \
  AI_GATEWAY_HEALTH_CATALOGUE=1 \
  AI_GATEWAY_HEALTH_KEY_FILE=/opt/company/.env \
  AI_GATEWAY_HEALTH_TIER_COLLAPSE_IS_CONDITION=1 \
  /opt/company/.venv/bin/python /usr/local/bin/ai-gateway-health.py --days 7
  echo "RC=$?"
}

echo "=== BEFORE sha ==="
sha256sum /usr/local/bin/ai-gateway-health.py

echo "=== BEFORE run (live file, cron env) ==="
run

echo "=== BEFORE self-test tail ==="
AI_GATEWAY_HEALTH_TIER_COLLAPSE_IS_CONDITION=1 \
  /opt/company/.venv/bin/python /usr/local/bin/ai-gateway-health.py --self-test | tail -3

echo "=== BACKUP ==="
cp -p /usr/local/bin/ai-gateway-health.py \
      /root/out/migration-review/167-ai-gateway-health.py.before-honest-closing
sha256sum /root/out/migration-review/167-ai-gateway-health.py.before-honest-closing

echo "=== APPLY PATCH ==="
/usr/bin/python3 /root/out/migration-review/167-patch-honest-closing.py
echo "PATCH_RC=$?"

BACKUP=/root/out/migration-review/167-ai-gateway-health.py.before-honest-closing
rollback() {
  echo "$1 -- RESTORING $BACKUP"
  cp -p "$BACKUP" /usr/local/bin/ai-gateway-health.py
  sha256sum /usr/local/bin/ai-gateway-health.py
  echo "=== DONE (rolled back, cron untouched) ==="
  exit 1
}

echo "=== py_compile ==="
if /opt/company/.venv/bin/python -m py_compile /usr/local/bin/ai-gateway-health.py; then
  echo COMPILE_OK
else
  rollback "COMPILE_FAILED"
fi

echo "=== AFTER sha ==="
sha256sum /usr/local/bin/ai-gateway-health.py

echo "=== AFTER self-test (full) ==="
AI_GATEWAY_HEALTH_TIER_COLLAPSE_IS_CONDITION=1 \
  /opt/company/.venv/bin/python /usr/local/bin/ai-gateway-health.py --self-test
ST=$?
echo "SELFTEST_RC=$ST"
if [ "$ST" -ne 0 ]; then
  rollback "SELF_TEST_FAILED"
fi

echo "=== AFTER run (live file, cron env) ==="
run

echo "=== runs.tsv tail ==="
tail -3 /root/.cron-status/runs.tsv

echo "=== DONE ==="
