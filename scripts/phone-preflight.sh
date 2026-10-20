#!/usr/bin/env bash
# Pre-flight for the PHONE engine switch on the authority: what the profile mounts, where its model key comes from,
# what the config still says about 0.2.0-only names, and whether the candidate tree is intact.
U=/opt/dsh-phone
C=/root/.dsh
echo "=== unit ==="
systemctl cat phone-engine.service 2>/dev/null | grep -E '^(ExecStart|Environment|EnvironmentFile|Restart|User)' | sed 's/^/  /'
echo
echo "=== candidate tree (from the 2026-10-20 attempt) ==="
for d in /opt/dsh-phone.failed-* /opt/dsh-phone-0.2.1; do
  [ -d "$d" ] || continue
  v=$(python3 -c "import json;print(json.load(open('$d/node_modules/@deepseek-ai/dsh/package.json'))['version'])" 2>/dev/null || echo "?")
  echo "  $d -> $v"
done
echo
echo "=== profile roster (which bundles this home mounts) ==="
cat "$C/profiles/web/package.json" 2>/dev/null | sed 's/^/  /'
echo
echo "=== anchors ==="
for d in "$C/profiles/node_modules" "$C/profiles/web/node_modules"; do
  [ -d "$d" ] && echo "  $d : $(ls -1 "$d" 2>/dev/null | wc -l) entries, @deepseek-ai=$(ls -d "$d"/@deepseek-ai 2>/dev/null | wc -l)" || echo "  $d : absent"
done
echo
echo "=== where does the model key come from? (names only, never values) ==="
python3 - <<'PY'
import re
p = "/root/.dsh/.credentials.yaml"
try:
    text = open(p, encoding="utf-8").read()
except Exception as e:
    print("  cannot read:", e); raise SystemExit
print(f"  {p}: {len(text)} bytes")
for line in text.split("\n"):
    m = re.match(r"^(\s*)([A-Za-z0-9_./-]+)\s*:\s*(.*)$", line)
    if m and m.group(2) not in ("version", "records", "kind", "payload", "secret", "refs", "scope", "id"):
        val = m.group(3)
        print(f"    {m.group(1)}{m.group(2)}: {'<value>' if val else ''}")
PY
echo
echo "=== does the profile patch still carry 0.2.0-only expressions, and presets {{cwd}}? ==="
P="$C/profiles/web/cordis.patch.yml"
echo "  ctx.webRuntime (code lines): $(grep -c 'ctx\.webRuntime' "$P" 2>/dev/null || echo 0)"
echo "  {{cwd}} tokens: $(grep -c '{{cwd}}' "$P" 2>/dev/null || echo 0)"
echo
echo "=== is the phone engine serving right now? ==="
systemctl is-active phone-engine.service | sed 's/^/  unit: /'
curl -s -o /dev/null -w '  http 3089 -> %{http_code}\n' --max-time 6 http://127.0.0.1:3089/ || true
