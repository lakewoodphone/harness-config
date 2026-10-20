#!/usr/bin/env bash
# Hard reset of the worker's engine: zero processes, one clean start, 60 s to bind, then evidence either way.
set -uo pipefail
NODE=/home/zabz/.local/node/bin/node
BIN=/home/zabz/dsh-engine/node_modules/@deepseek-ai/dsh/lib/bin.js
LOG=/home/zabz/.dsh-worker-3099.$(date -u +%H%M%S).log
HOST=zabz-tech-linux.tail93e6e6.ts.net

echo "=== kill everything ==="
pkill -9 -f 'bin\.js web' 2>/dev/null
sleep 5
echo "  procs: $(pgrep -cf 'bin\.js web')"

echo "=== port state ==="
ss -ltn 2>/dev/null | grep ':3099 ' && echo "  STILL BOUND" || echo "  free"

echo "=== start one, detached, fresh log: $LOG ==="
cd /home/zabz || exit 2
setsid nohup "$NODE" "$BIN" web --port 3099 --no-open --trusted-host "$HOST" > "$LOG" 2>&1 &
for i in $(seq 1 20); do
  sleep 3
  if ss -ltn 2>/dev/null | grep -q ':3099 '; then echo "  bound after $((i*3))s"; break; fi
done

echo "=== after 60s ==="
sleep 25
echo "  procs: $(pgrep -cf 'bin\.js web')"
ss -ltnp 2>/dev/null | grep ':3099 ' | sed 's/^/  /' || echo "  listener: NONE"
curl -s -o /dev/null -w '  http 127.0.0.1 -> %{http_code}\n' --max-time 8 "http://127.0.0.1:3099/" || true
curl -s -o /dev/null -w '  http tailnet  -> %{http_code}\n' --max-time 8 "http://$HOST:3099/" || true
echo "=== log: first lines that mention http or error ==="
grep -aiE 'http://|listening|error|EADDRINUSE' "$LOG" 2>/dev/null | head -6 | sed 's/^/  /'
echo "=== log tail (non-MCP) ==="
grep -aviE 'CallToolRequest|server.py|Processing request|^\s*$' "$LOG" 2>/dev/null | tail -10 | sed 's/^/  /'
