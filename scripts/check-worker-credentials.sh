#!/usr/bin/env bash
# Was the credential append I made at ~03:05 the thing that broke this engine's boot? Validate the YAML, and if it
# is invalid, restore the backup taken immediately before the edit and restart the engine.
set -uo pipefail
F=/home/zabz/.dsh/.credentials.yaml
BAK=$(ls -t "$F".bak-cred-* 2>/dev/null | head -1)
echo "credential file: $F"
echo "backup found  : ${BAK:-none}"
echo "=== parse test ==="
python3 - "$F" <<'PY'
import sys
try:
    import yaml
except Exception:
    print("  (no python yaml module; using a crude structural check)")
    text = open(sys.argv[1], encoding="utf-8").read()
    bad = [f"{i+1}: {l}" for i, l in enumerate(text.split("\n")) if l and not l.startswith((" ", "#")) and ":" not in l]
    print("  lines that look malformed:", len(bad))
    for b in bad[:5]:
        print("   ", b)
    sys.exit(0)
try:
    doc = yaml.safe_load(open(sys.argv[1], encoding="utf-8"))
    print("  parses OK; top-level keys:", list(doc) if isinstance(doc, dict) else type(doc).__name__)
except Exception as exc:
    print("  YAML IS INVALID:", str(exc)[:300])
    sys.exit(3)
PY
RC=$?
echo "  parse exit: $RC"
if [ "$RC" -ne 0 ] && [ -n "$BAK" ]; then
  echo "=== restoring $BAK ==="
  cp -p "$BAK" "$F"
  python3 -c "import yaml,sys; yaml.safe_load(open('$F')); print('  restored file parses OK')" 2>&1 | sed 's/^/  /'
  echo "=== restarting the engine (cron will also try at :00/:30) ==="
  pkill -f 'bin\.js web' 2>/dev/null || true
  sleep 5
  cd /home/zabz || exit 2
  HOME=/home/zabz DSH_HOME=/home/zabz/.dsh setsid nohup /home/zabz/.local/node/bin/node \
    /home/zabz/dsh-engine/node_modules/@deepseek-ai/dsh/lib/bin.js web --port 3099 --no-open \
    --trusted-host zabz-tech-linux.tail93e6e6.ts.net > /home/zabz/.dsh-worker-3099.restore.log 2>&1 &
  sleep 40
  ss -ltnp 2>/dev/null | grep ':3099 ' | sed 's/^/  /' || echo "  listener: NONE"
  curl -s -o /dev/null -w '  http -> %{http_code}\n' --max-time 8 http://127.0.0.1:3099/ || true
  grep -aviE 'CallToolRequest|server\.py|Processing request|^[[:space:]]*$' /home/zabz/.dsh-worker-3099.restore.log 2>/dev/null | tail -6 | sed 's/^/  /'
fi
