#!/usr/bin/env bash
# The phone's presets are reported BROKEN because two rows never start: `tool-ralph` and `mcp-client` are present in
# the ENGINE tree but were dropped from the PROFILE tree when it was reinstalled at 0.2.1 (they were transitive
# before, and the preset rows reference them by name). A broken row makes the whole preset invalid, which is what the
# phone shows as "agent preset invalid" when a session is opened.
#
# This finds EVERY @deepseek-ai package the presets name that the profile cannot resolve, pins them at the engine's
# version, installs, restores the canonical dsh-scope path the unit's ExecStartPre gate requires, and restarts.
set -uo pipefail
PROF=/root/.dsh/profiles/web
NODE=/usr/local/node22/bin/node
NPM=/usr/local/node22/bin/npm
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
LOG=/root/phone-presets-$STAMP.log
say() { echo "[$(date -u +%H:%M:%SZ)] $*" | tee -a "$LOG"; }

say 'finding preset packages the profile cannot resolve'
MISSING=$(python3 - <<'PY'
import json, os, re
patch = "/root/.dsh/profiles/web/cordis.patch.yml"
text = open(patch, encoding="utf-8").read()
s = text.find("preset-rows: BEGIN"); e = text.find("preset-rows: END")
block = text[s:e]
names = sorted(set(re.findall(r'name:\s*"(@deepseek-ai/[a-z0-9-]+)"', block)))
prof = "/root/.dsh/profiles/web/node_modules/@deepseek-ai"
eng = "/opt/dsh-phone/node_modules/@deepseek-ai"
missing = []
for n in names:
    pkg = n.split("/")[1]
    if not os.path.isdir(os.path.join(prof, pkg)) and os.path.isdir(os.path.join(eng, pkg)):
        missing.append(pkg)
print(" ".join(missing))
PY
)
say "  missing from the profile: ${MISSING:-none}"
[ -n "$MISSING" ] || { say 'nothing to add'; exit 0; }

ENGVER=$(python3 -c "import json;print(json.load(open('/opt/dsh-phone/node_modules/@deepseek-ai/dsh/package.json'))['version'])")
say "  pinning them at $ENGVER"

cd "$PROF" || exit 2
cp -p package.json "package.json.bak-presets-$STAMP"
python3 - "$MISSING" "$ENGVER" <<'PY'
import json, sys
pkgs = sys.argv[1].split(); ver = sys.argv[2]
p = "/root/.dsh/profiles/web/package.json"
d = json.load(open(p)); deps = d.setdefault("dependencies", {})
for k in pkgs:
    deps[f"@deepseek-ai/{k}"] = ver
json.dump(d, open(p, "w"), indent=2); open(p, "a").write("\n")
print(f"  added {len(pkgs)} dependency(ies)")
PY

say 'installing'
"$NPM" install --omit=dev --no-audit --no-fund --loglevel=error > "$LOG.npm" 2>&1
say "  npm exit: $? ($(tail -1 "$LOG.npm"))"

say 'restoring the canonical dsh-scope path the gate needs'
SC="$PROF/node_modules/@deepseek-ai/dsh-scope"
if [ -d "$SC" ]; then
  V=$(python3 -c "import json;print(json.load(open('$SC/package.json'))['version'])")
  D="$PROF/node_modules/.pnpm/@deepseek-ai+dsh-scope@$V/node_modules/@deepseek-ai"
  mkdir -p "$D"; ln -sfn ../../../../../@deepseek-ai/dsh-scope "$D/dsh-scope"
  say "  canonical -> $(readlink -f "$D/dsh-scope")"
fi
/usr/local/bin/repair-phone-engine.sh > /dev/null 2>&1
/usr/local/bin/repair-phone-engine.sh --check > /dev/null 2>&1
say "  repair --check exit: $?"

say 'restarting'
systemctl restart phone-engine
for i in $(seq 1 12); do
  sleep 5
  C=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 http://127.0.0.1:3089/ || true)
  say "  t+$((i*5))s $(systemctl is-active phone-engine) http=${C:-none}"
  [ "${C:-000}" = "401" ] && break
done

say 'preset registry, read from the engine itself'
cd /tmp && rm -f cj.txt
curl -s -c cj.txt -o /dev/null --max-time 10 http://127.0.0.1:3086/
curl -s -b cj.txt -X POST -H "Content-Type: application/json" -H "Origin: http://127.0.0.1:3086" \
  -d '{"type":"client-request","rpcId":"1","method":"agentPresets/list","payload":{"args":{}}}' \
  --max-time 12 http://127.0.0.1:3086/api/agentPresets/list | tee -a "$LOG" | python3 -c "
import json,sys
d=json.load(sys.stdin)
res=d.get('result',{})
if not res.get('ok'): print('  ERROR:', res.get('error')); raise SystemExit
for p in res['value']['presets']:
    b = p.get('broken')
    print(f\"  {p['id']:12} default={p.get('isDefault')} broken={b or 'no'}\")
"
