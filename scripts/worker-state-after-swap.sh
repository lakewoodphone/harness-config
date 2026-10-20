#!/usr/bin/env bash
# What is the worker's actual state right now, after a swap whose promote step failed?
echo "=== engine tree version ==="
python3 -c "import json;print(json.load(open('/home/zabz/dsh-engine/node_modules/@deepseek-ai/dsh/package.json'))['version'])" 2>/dev/null || echo "  (cannot read)"
echo "=== pin ==="
python3 -c "import json;d=json.load(open('/home/zabz/code/harness-config/dsh-update/state/pin.json'));print(' ',d.get('version'),d.get('installRoot'))" 2>/dev/null || echo "  (no pin)"
echo "=== dsh-update lib present? ==="
ls -1 /home/zabz/code/harness-config/dsh-update/lib/ 2>/dev/null | head -12 | sed 's/^/  /'
echo "  cli.mjs: $(ls -l /home/zabz/code/harness-config/dsh-update/lib/cli.mjs 2>/dev/null || echo MISSING)"
echo "=== what the unit is running ==="
systemctl show dsh-engine.service -p MainPID --value | sed 's/^/  mainpid: /'
ps -o args= -p "$(systemctl show dsh-engine.service -p MainPID --value)" 2>/dev/null | cut -c1-130 | sed 's/^/  /'
echo "  unit: $(systemctl is-active dsh-engine.service) restarts=$(systemctl show dsh-engine.service -p NRestarts --value)"
echo "=== serving? ==="
curl -s -o /dev/null -w '  http -> %{http_code}\n' --max-time 6 http://127.0.0.1:3099/ || true
echo "=== engine log for the current attempt (last 12 non-MCP lines) ==="
journalctl -u dsh-engine -n 60 --no-pager -o cat 2>/dev/null | grep -aviE 'CallToolRequest|server\.py|Processing request|^[[:space:]]*$' | tail -12 | sed 's/^/  /'
echo "=== previous engine tree kept? ==="
ls -d /home/zabz/dsh-engine.prev-* /home/zabz/.dsh/engine.prev-* 2>/dev/null | sed 's/^/  /' || echo "  none"
echo "=== anchors ==="
ls -d /home/zabz/.dsh/profiles/node_modules* 2>/dev/null | sed 's/^/  /'
