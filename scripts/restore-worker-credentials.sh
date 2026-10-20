#!/usr/bin/env bash
# Restore the credential file to its pre-edit content and bring the worker's engine back.
#
# THE CAUSE, measured at 03:40Z: I appended `DEEPSEEK_API_KEY: <value>` to ~/.dsh/.credentials.yaml. That file's
# keys must be "<scope>/<id>" (e.g. llm-deepseek/api-key) — dsh-credentials/lib/index.js:70 throws
#   credential key "DEEPSEEK_API_KEY" must be "<scope>/<id>"
# so the engine's boot failed on its own credentials include and systemd restarted it every ~60 s (17 restarts).
# The file was valid YAML, which is why my earlier "it parses OK" check cleared it: YAML validity is not schema
# validity. The pipeline's own credential reader searches for a nested key of that NAME and accepted it, so verify
# ran G4/G5 happily while the engine it was judging could not boot. Two readers, two rules, one file.
set -uo pipefail
F=/home/zabz/.dsh/.credentials.yaml
BAK=$(ls -t "$F".bak-cred-* 2>/dev/null | head -1)

echo "=== backups available ==="
ls -1t "$F".bak-cred-* 2>/dev/null | head -3 | sed 's/^/  /'

if [ -z "$BAK" ]; then echo "REFUSED: no backup to restore from"; exit 2; fi

echo "=== current bad line ==="
grep -n 'DEEPSEEK_API_KEY' "$F" 2>/dev/null | sed 's/:.*/: <redacted>/' | sed 's/^/  /'

echo "=== restoring $BAK ==="
cp -p "$BAK" "$F"
grep -c 'DEEPSEEK_API_KEY' "$F" 2>/dev/null | sed 's/^/  DEEPSEEK_API_KEY occurrences now: /'

echo "=== restart the unit and watch it ==="
sudo -n systemctl restart dsh-engine.service || { echo "  restart failed"; exit 3; }
for i in $(seq 1 12); do
  sleep 5
  STATE=$(systemctl is-active dsh-engine.service)
  CODE=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 http://127.0.0.1:3099/ || echo 000)
  echo "  t+$((i*5))s state=$STATE http=$CODE"
  if [ "$STATE" = "active" ] && [ "$CODE" != "000" ]; then break; fi
done

echo "=== final ==="
systemctl is-active dsh-engine.service | sed 's/^/  unit: /'
systemctl show dsh-engine.service -p NRestarts --value | sed 's/^/  restarts: /'
ss -ltnp 2>/dev/null | grep ':3099 ' | sed 's/^/  /' || echo "  listener: NONE"
curl -s -o /dev/null -w '  http -> %{http_code}\n' --max-time 8 http://127.0.0.1:3099/ || true
journalctl -u dsh-engine -n 6 --no-pager -o cat 2>/dev/null | grep -viE 'CallToolRequest|server\.py' | tail -4 | sed 's/^/  /'
