#!/usr/bin/env bash
# Recover the worker's engine: exactly one process, bound to 3099, old (0.1.5) tree, original command line.
set -uo pipefail
NODE=/home/zabz/.local/node/bin/node
BIN=/home/zabz/dsh-engine/node_modules/@deepseek-ai/dsh/lib/bin.js
LOG=/home/zabz/.dsh-worker-3099.log

echo "=== before ==="
pgrep -cf 'dsh/lib/bin.js web' | sed 's/^/  procs: /'
ss -ltnp 2>/dev/null | grep 3099 | sed 's/^/  /' || echo "  listener: none"

echo "=== killing every engine process ==="
pkill -f 'dsh/lib/bin.js web'
sleep 8
pgrep -cf 'dsh/lib/bin.js web' | sed 's/^/  procs now: /'

echo "=== waiting for the port to be free ==="
for i in $(seq 1 12); do
  if ss -ltn 2>/dev/null | grep -q ':3099 '; then sleep 5; else break; fi
done
ss -ltn 2>/dev/null | grep ':3099 ' | sed 's/^/  still bound: /' || echo "  port free"

echo "=== starting one engine (old tree) ==="
cd /home/zabz || exit 2
mv "$LOG" "$LOG.before-$RANDOM" 2>/dev/null
nohup "$NODE" "$BIN" web --port 3099 --no-open --trusted-host zabz-tech-linux.tail93e6e6.ts.net > "$LOG" 2>&1 &
sleep 30

echo "=== after ==="
pgrep -cf 'dsh/lib/bin.js web' | sed 's/^/  procs: /'
ss -ltnp 2>/dev/null | grep 3099 | sed 's/^/  /' || echo "  listener: NONE"
curl -s -o /dev/null -w '  3099 -> %{http_code}\n' --max-time 8 http://127.0.0.1:3099/ || true
echo "=== log tail ==="
grep -viE 'CallToolRequest|server.py|Processing request' "$LOG" 2>/dev/null | tail -8 | sed 's/^/  /'
