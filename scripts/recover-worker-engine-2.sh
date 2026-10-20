#!/usr/bin/env bash
# Last-mile recovery: start the worker's engine exactly as its own service definition would, with HOME/DSH_HOME/
# TMPDIR set, then prove whether it serves. Prints everything so the next reader does not have to guess.
set -uo pipefail
NODE=/home/zabz/.local/node/bin/node
BIN=/home/zabz/dsh-engine/node_modules/@deepseek-ai/dsh/lib/bin.js
HOST=zabz-tech-linux.tail93e6e6.ts.net
LOG=/home/zabz/.dsh-worker-3099.recover-$(date -u +%H%M%S).log

echo "=== stop everything ==="
pkill -9 -f 'bin\.js web' 2>/dev/null || true
sleep 5
echo "  procs: $(pgrep -cf 'bin\.js web' || true)"
ss -ltn 2>/dev/null | grep ':3099 ' && echo "  port still bound" || echo "  port free"

echo "=== start with the environment a service would give it ==="
mkdir -p /home/zabz/.dsh-tmp
cd /home/zabz || exit 2
HOME=/home/zabz \
DSH_HOME=/home/zabz/.dsh \
NODE_ENV=production \
TMPDIR=/home/zabz/.dsh-tmp \
setsid nohup "$NODE" "$BIN" web --port 3099 --no-open --trusted-host "$HOST" > "$LOG" 2>&1 &

for i in $(seq 1 15); do
  sleep 3
  if ss -ltn 2>/dev/null | grep -q ':3099 '; then echo "  bound after $((i*3))s"; break; fi
done
sleep 20

echo "=== evidence ==="
echo "  procs: $(pgrep -cf 'bin\.js web' || true)"
ss -ltnp 2>/dev/null | grep ':3099 ' | sed 's/^/  /' || echo "  listener: NONE"
curl -s -o /dev/null -w '  http -> %{http_code}\n' --max-time 8 "http://127.0.0.1:3099/" || true
echo "  log size: $(stat -c%s "$LOG" 2>/dev/null || echo 0) bytes"
echo "  --- log head ---"
head -12 "$LOG" 2>/dev/null | sed 's/^/  /'
echo "  --- log tail ---"
grep -aviE 'CallToolRequest|server\.py|Processing request|^[[:space:]]*$' "$LOG" 2>/dev/null | tail -8 | sed 's/^/  /'
