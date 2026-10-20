#!/usr/bin/env bash
# Compose the phone's config with the 0.2.1 candidate (read-only) and look for the web-app/webserver rows.
# This answers "is the bundle even mounted?" without touching the running engine.
CAND=$(for d in /opt/dsh-phone.failed2-*; do [ -d "$d/node_modules/@deepseek-ai/dsh-web-app" ] && echo "$d" && break; done)
echo "candidate: $CAND"
NODE=/usr/local/node22/bin/node
HOME_DIR=/root/.dsh

echo "=== compose (0.2.1) with the live profile ==="
DSH_HOME=$HOME_DIR timeout 120 "$NODE" "$CAND/node_modules/@deepseek-ai/dsh/lib/bin.js" --profile web --dump-config > /tmp/phone-compose.txt 2>/tmp/phone-compose.err
echo "  exit: $?  rows: $(grep -cE '^\s*-\s+id:' /tmp/phone-compose.txt)"
echo "  errors: $(grep -acE 'error|cannot|skipping' /tmp/phone-compose.err)"

echo "=== rows mentioning web ==="
grep -E '^\s*-\s+id: .*web' /tmp/phone-compose.txt | head -12 | sed 's/^/  /'
echo "=== does the composition carry web-app / webserver at all? ==="
for id in web-app webApp webserver web-server webStartup; do
  printf '  %-14s %s\n' "$id" "$(grep -cE "id: '$id'|id: $id$|webStartup" /tmp/phone-compose.txt)"
done
echo "=== what the profile bundles say ==="
python3 -c "import json;d=json.load(open('/root/.dsh/profiles/web/package.json'));print('  bundles:', d['dsh']['profile']['bundles']);print('  deps:', len(d.get('dependencies',{})))"
echo "=== dsh-web-app present where? ==="
for p in "$CAND/node_modules/@deepseek-ai/dsh-web-app" "/root/.dsh/profiles/web/node_modules/@deepseek-ai/dsh-web-app"; do
  [ -d "$p" ] && echo "  $p -> $(python3 -c "import json;print(json.load(open('$p/package.json'))['version'])" 2>/dev/null)" || echo "  $p -> ABSENT"
done
