#!/usr/bin/env bash
# Reproduce the engine's failure the way systemd runs it, and capture EVERYTHING it writes (stdout, stderr, and any
# log file it creates under ~/.dsh). The unit's journal shows no engine output at all, so the diagnostic has to come
# from a run we can see. Never prints the contents of /etc/dsh-worker.env.
set -uo pipefail
NODE=/home/zabz/.local/node/bin/node
BIN=/home/zabz/dsh-engine/node_modules/@deepseek-ai/dsh/lib/bin.js
LOG=/home/zabz/engine-repro-$(date -u +%H%M%S).log
BEFORE=$(find /home/zabz/.dsh -maxdepth 3 -type f -newermt '-1 minute' 2>/dev/null | wc -l)

echo "=== stop the unit so it is not fighting us (systemd will start it again afterwards) ==="
sudo -n systemctl stop dsh-engine.service 2>/dev/null && echo "  unit stopped" || echo "  could not stop the unit"
sleep 3

echo "=== run exactly as the unit does, 70 s ==="
cd /home/zabz/code || exit 2
set -a
# shellcheck disable=SC1091
. /etc/dsh-worker.env 2>/dev/null || echo "  (no /etc/dsh-worker.env or unreadable)"
set +a
HOME=/home/zabz DSH_HOME=/home/zabz/.dsh NODE_ENV=production \
  timeout 70 "$NODE" "$BIN" web --port 3099 --no-open \
  --trusted-host zabz-tech-linux.tail93e6e6.ts.net > "$LOG" 2>&1
echo "  exit: $?  (124 = still running at the 70 s mark)"
echo "  captured: $(stat -c%s "$LOG" 2>/dev/null) bytes"

echo "=== what it printed (first 30 lines, MCP noise removed) ==="
grep -aviE 'CallToolRequest|server\.py|Processing request|^[[:space:]]*$' "$LOG" 2>/dev/null | head -30 | sed 's/^/  /'

echo "=== files it wrote under ~/.dsh in the last 2 minutes ==="
find /home/zabz/.dsh -maxdepth 3 -type f -newermt '-2 minutes' 2>/dev/null | head -12 | sed 's/^/  /'

echo "=== any fresh engine log under ~/.dsh/logs ==="
ls -lt /home/zabz/.dsh/logs 2>/dev/null | head -4 | sed 's/^/  /'

echo "=== give the unit back ==="
sudo -n systemctl start dsh-engine.service 2>/dev/null && echo "  unit started" || echo "  COULD NOT START THE UNIT"
