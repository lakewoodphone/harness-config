#!/usr/bin/env bash
# phone-021-proven.sh — the switch that mirrors a configuration PROVEN to boot and serve.
#
# PROOF (2026-10-20 12:4xZ): a clean 0.2.1 tree (/opt/dsh-021-clean, 306 packages, real dsh-scope) run in the
# FOREGROUND against a home whose profile is at 0.2.1 AND whose patch was corrected (webRuntime -> webStartup,
# {{cwd}} -> pwd instruction) printed `dsh web: http://127.0.0.1:3092/?token=...` and stayed up (exit 124 at the
# 50 s timeout). Every earlier attempt differed from this in one of exactly three ways: an incomplete engine tree
# (0 packages), an unfixed patch, or the repair step re-pointing dsh-scope at a .pnpm path that no longer existed.
# So this script does exactly the proven four things and NOT the repair step.
set -uo pipefail
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
LOG=/root/phone-proven-$STAMP.log
LIVE=/opt/dsh-phone
CAND=/opt/dsh-021-clean
PREV=/opt/dsh-phone.prev-0.2.0-rc.2-$STAMP
PROF=/root/.dsh/profiles/web
NODE=/usr/local/node22/bin/node
NPM=/usr/local/node22/bin/npm

say() { echo "[$(date -u +%H:%M:%SZ)] $*" | tee -a "$LOG"; }

[ -d "$CAND/node_modules/@deepseek-ai/dsh-web-app" ] || { say "REFUSED: candidate incomplete"; exit 2; }
[ -d "$CAND/node_modules/@deepseek-ai/dsh-scope" ] && [ ! -L "$CAND/node_modules/@deepseek-ai/dsh-scope" ] || { say "REFUSED: candidate dsh-scope is not a real dir"; exit 2; }
say "proven switch; candidate $CAND"

say 'stopping the unit'
systemctl stop phone-engine || { say 'stop failed'; exit 2; }
sleep 3

say 'profile -> 0.2.1'
cp -p "$PROF/package.json" "$PROF/package.json.bak-proven-$STAMP"
[ -d "$PROF/node_modules" ] && mv "$PROF/node_modules" "$PROF/node_modules.0.2.0-keep-$STAMP"
python3 - "$PROF/package.json" <<'PY'
import json, sys
p = sys.argv[1]; d = json.load(open(p)); n = 0
for k, v in list(d.get("dependencies", {}).items()):
    if v == "0.2.0-rc.2": d["dependencies"][k] = "0.2.1-rc.2"; n += 1
json.dump(d, open(p, "w"), indent=2); open(p, "a").write("\n")
print(f"  repinned {n}")
PY
cd "$PROF" || exit 2
"$NPM" install --omit=dev --no-audit --no-fund --loglevel=error > "$LOG.npm" 2>&1
say "  npm exit: $? ($(tail -1 "$LOG.npm"))"

say 'correcting the live patch (the step whose absence failed every earlier boot)'
python3 - "$PROF/cordis.patch.yml" <<'PY'
import pathlib, sys
p = pathlib.Path(sys.argv[1]); t = p.read_text(encoding="utf-8"); n = 0; out = []
for line in t.split("\n"):
    new = line
    if not line.lstrip().startswith("#") and "ctx.webRuntime.trustedHosts" in new:
        new = new.replace("ctx.webRuntime.trustedHosts", "ctx.webStartup.trustedHosts")
    if "Your working directory is {{cwd}}." in new:
        new = new.replace("Your working directory is {{cwd}}.", "Run pwd in your shell for the working directory; never assume a path.")
    if new != line: n += 1
    out.append(new)
p.write_text("\n".join(out), encoding="utf-8")
print(f"  patch lines changed: {n}")
PY

say 'swapping the tree (no repair step: it re-pointed dsh-scope at a path that stops existing)'
mv "$LIVE" "$PREV" || { say 'tree move failed'; systemctl start phone-engine; exit 3; }
mv "$CAND" "$LIVE" || { say 'candidate move failed'; mv "$PREV" "$LIVE"; systemctl start phone-engine; exit 3; }

say 'starting'
systemctl start phone-engine
OK=0
for i in $(seq 1 20); do
  sleep 5
  S=$(systemctl is-active phone-engine)
  C=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 http://127.0.0.1:3089/ || true)
  say "  t+$((i*5))s state=$S http=${C:-none}"
  if [ "$S" = "active" ] && [ "${C:-000}" != "000" ]; then OK=1; break; fi
done
VER=$("$NODE" "$LIVE/node_modules/@deepseek-ai/dsh/lib/bin.js" --version 2>&1 | tail -1)
say "version=$VER unit=$(systemctl is-active phone-engine) http=$(curl -s -o /dev/null -w '%{http_code}' --max-time 8 http://127.0.0.1:3089/ || echo 000)"

if [ "$OK" -ne 1 ] || [ "$VER" != "0.2.1-rc.2" ]; then
  say 'NOT SERVING — rolling back'
  systemctl stop phone-engine
  rm -rf "$PROF/node_modules"; mv "$PROF/node_modules.0.2.0-keep-$STAMP" "$PROF/node_modules"
  cp -p "$PROF/package.json.bak-proven-$STAMP" "$PROF/package.json"
  mv "$LIVE" "/opt/dsh-phone.failed4-$STAMP" 2>/dev/null; mv "$PREV" "$LIVE"
  systemctl start phone-engine
  sleep 20
  say "  after rollback: unit=$(systemctl is-active phone-engine) version=$("$NODE" "$LIVE/node_modules/@deepseek-ai/dsh/lib/bin.js" --version 2>&1 | tail -1) http=$(curl -s -o /dev/null -w '%{http_code}' --max-time 6 http://127.0.0.1:3089/ || echo 000)"
  exit 4
fi
say "DONE — phone engine on $VER, serving"
