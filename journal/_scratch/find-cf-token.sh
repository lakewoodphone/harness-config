#!/bin/bash
# Hunt for the Cloudflare token/mater token. NAMES ONLY - never print a value.
echo "=== sudo ls /opt ==="
sudo -n ls -la /opt 2>/dev/null | head -20
echo "=== /opt files mentioning cloudflare (file names only) ==="
sudo -n grep -rl -i cloudflare /opt 2>/dev/null | head -25
echo "=== env var NAMES in likely deploy env files ==="
for f in /opt/lpt/.env /opt/lpt/.env.production /opt/lpt/.env.test /opt/lpt/.env.local /home/zabz/.env /home/zabz/.env.production; do
  if sudo -n test -f "$f" 2>/dev/null; then
    echo "-- $f"
    sudo -n grep -ohE '^[A-Za-z0-9_]*(CLOUDFLARE|CF|WRANGLER|NETLIFY|PAGES)[A-Za-z0-9_]*' "$f" 2>/dev/null | sort -u
  fi
done
echo "=== containers ==="
sudo -n docker ps --format '{{.Names}}' 2>/dev/null | head -25
echo "=== container env NAMES mentioning cloudflare/cf/wrangler/netlify ==="
for c in $(sudo -n docker ps --format '{{.Names}}' 2>/dev/null); do
  n=$(sudo -n docker inspect "$c" --format '{{range .Config.Env}}{{println .}}{{end}}' 2>/dev/null | grep -ioE '^[a-z_0-9]*(cloudflare|cf_|wrangler|netlify)[a-z_0-9]*' | sort -u | tr '\n' ' ')
  [ -n "$n" ] && echo "$c: $n"
done
echo "=== any file in zabz home naming a cloudflare token (maxdepth 4, names only) ==="
grep -rl -i 'cloudflare_api_token\|cloudflare_token\|cf_api_token\|cloudflare_master' ~ --include='*' --exclude-dir=.git --exclude-dir=node_modules 2>/dev/null | head -25
echo "=== done ==="
