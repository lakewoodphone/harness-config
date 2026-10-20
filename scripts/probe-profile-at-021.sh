#!/usr/bin/env bash
# Does a profile tree installed AT 0.2.1 still compose the web-startup/webserver rows? Read-only experiment: the
# live profile is copied to a scratch home, repinned, installed, and composed. Nothing live is touched.
set -uo pipefail
CAND=$(for d in /opt/dsh-phone.failed2-*; do [ -d "$d/node_modules/@deepseek-ai/dsh-web-app" ] && echo "$d" && break; done)
NODE=/usr/local/node22/bin/node
NPM=/usr/local/node22/bin/npm
SCRATCH=/root/.dsh-probe021
echo "candidate: $CAND"
rm -rf "$SCRATCH"; mkdir -p "$SCRATCH/profiles"
cp -a /root/.dsh/profiles/web "$SCRATCH/profiles/web"
rm -rf "$SCRATCH/profiles/web/node_modules.0.2.0-keep"* 2>/dev/null
# copy the non-node_modules parts of the home the compose needs
for f in settings.yaml .credentials.yaml; do [ -f "/root/.dsh/$f" ] && cp -p "/root/.dsh/$f" "$SCRATCH/$f"; done
[ -d /root/.dsh/.agent-presets ] && cp -a /root/.dsh/.agent-presets "$SCRATCH/.agent-presets"

echo "=== repin the scratch profile to 0.2.1 and install ==="
python3 - "$SCRATCH/profiles/web/package.json" <<'PY'
import json, sys
p = sys.argv[1]; d = json.load(open(p)); n = 0
for k, v in list(d.get("dependencies", {}).items()):
    if v == "0.2.0-rc.2":
        d["dependencies"][k] = "0.2.1-rc.2"; n += 1
json.dump(d, open(p, "w"), indent=2); open(p, "a").write("\n")
print(f"  repinned {n}")
PY
cd "$SCRATCH/profiles/web" || exit 2
rm -rf node_modules
"$NPM" install --omit=dev --no-audit --no-fund --loglevel=error > /tmp/probe021-npm.log 2>&1
echo "  npm exit: $? ($(tail -1 /tmp/probe021-npm.log))"

echo "=== compose the scratch home with the 0.2.1 candidate ==="
DSH_HOME=$SCRATCH timeout 120 "$NODE" "$CAND/node_modules/@deepseek-ai/dsh/lib/bin.js" --profile web --dump-config > /tmp/probe021-compose.txt 2>/tmp/probe021-compose.err
echo "  exit: $?  rows: $(grep -cE '^\s*-\s+id:' /tmp/probe021-compose.txt)"
echo "  web rows:"
grep -E '^\s*-\s+id: .*web' /tmp/probe021-compose.txt | head -10 | sed 's/^/    /'
echo "  webStartup mentions: $(grep -c webStartup /tmp/probe021-compose.txt)"
echo "  web-startup row:     $(grep -cE \"id: '?web-startup'?\" /tmp/probe021-compose.txt)"
echo "  compose stderr (first 3 non-MCP):"
grep -avE 'CallToolRequest|server\.py|Processing request|^\s*$' /tmp/probe021-compose.err | head -3 | sed 's/^/    /'
echo "=== versions in the scratch tree ==="
for p in dsh-web-app dsh-host-webserver dsh-base; do
  f="$SCRATCH/profiles/web/node_modules/@deepseek-ai/$p/package.json"
  [ -f "$f" ] && echo "  $p -> $(python3 -c "import json;print(json.load(open('$f'))['version'])")" || echo "  $p -> ABSENT"
done
