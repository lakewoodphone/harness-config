#!/usr/bin/env bash
# phone-021-done.sh — finish the phone engine, with the cause that every previous attempt missed.
#
# THE CAUSE, measured: the unit runs `ExecStartPre=repair-phone-engine.sh --check`. That script requires the
# engine's `dsh-scope` and the profile's canonical copy — `profiles/web/node_modules/.pnpm/@deepseek-ai+dsh-scope@*`
# — to resolve to the SAME inode, and it exits 2 when the canonical copy does not exist. Every earlier attempt
# installed the profile with `npm` (a flat tree, NO `.pnpm`), so `--check` found no canonical copy, exited 2, and
# systemd recorded `Control process exited, code=exited, status=2/INVALIDARGUMENT` and restarted forever in
# "activating". The engine never started at all — which is why no startup log was ever written.
# A foreground run bypassed ExecStartPre, which is why it booted and served.
#
# SO: the profile must be installed with pnpm (it ships pnpm-workspace.yaml for exactly this), at 0.2.1, so the
# canonical dsh-scope exists and matches the engine's.
set -uo pipefail
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
LOG=/root/phone-done-$STAMP.log
LIVE=/opt/dsh-phone
PROF=/root/.dsh/profiles/web
PATCH=$PROF/cordis.patch.yml
NODE=/usr/local/node22/bin/node
PNPM="/usr/local/node22/bin/corepack pnpm"
REPAIR=/usr/local/bin/repair-phone-engine.sh
CAND=$(for d in /opt/dsh-phone.failed4-* /opt/dsh-phone.failed3-* /opt/dsh-021-clean; do
         [ -x "$d/node_modules/@deepseek-ai/dsh/lib/bin.js" ] && [ -d "$d/node_modules/@deepseek-ai/dsh-web-app" ] && echo "$d" && break
       done)
PREV=/opt/dsh-phone.prev-0.2.0-rc.2-$STAMP

say() { echo "[$(date -u +%H:%M:%SZ)] $*" | tee -a "$LOG"; }

[ -n "$CAND" ] || { say "REFUSED: no complete 0.2.1 tree"; exit 2; }
say "candidate $CAND ($(ls -1 "$CAND/node_modules/@deepseek-ai" | wc -l) packages)"

say 'stopping the unit'
systemctl stop phone-engine || { say 'stop failed'; exit 2; }
sleep 3

say 'backing up EVERY file this script will change'
cp -p "$PROF/package.json" "$PROF/package.json.bak-done-$STAMP"
cp -p "$PATCH" "$PATCH.bak-done-$STAMP"
[ -d "$PROF/node_modules" ] && mv "$PROF/node_modules" "$PROF/node_modules.before-done-$STAMP"
say "  backups: package.json.bak-done-$STAMP, cordis.patch.yml.bak-done-$STAMP, node_modules.before-done-$STAMP"

say 'repinning the profile to 0.2.1'
python3 - "$PROF/package.json" <<'PY'
import json, sys
p = sys.argv[1]; d = json.load(open(p)); n = 0
for k, v in list(d.get("dependencies", {}).items()):
    if v == "0.2.0-rc.2": d["dependencies"][k] = "0.2.1-rc.2"; n += 1
json.dump(d, open(p, "w"), indent=2); open(p, "a").write("\n")
print(f"  repinned {n}")
PY

say 'installing the profile with pnpm (the layout repair-phone-engine.sh requires)'
cd "$PROF" || { say 'no profile dir'; exit 2; }
CI=1 $PNPM install --prod --no-frozen-lockfile --ignore-scripts --config.confirmModulesPurge=false > "$LOG.pnpm" 2>&1
PN=$?
say "  pnpm exit: $PN ($(tail -2 "$LOG.pnpm" | tr '\n' ' '))"
if [ "$PN" -ne 0 ]; then
  say 'pnpm failed — restoring and starting the old engine'
  rm -rf "$PROF/node_modules"
  mv "$PROF/node_modules.before-done-$STAMP" "$PROF/node_modules"
  cp -p "$PROF/package.json.bak-done-$STAMP" "$PROF/package.json"
  systemctl start phone-engine; exit 3
fi

say 'checking the canonical dsh-scope'
CANON=$(ls -d "$PROF"/node_modules/.pnpm/"@deepseek-ai+dsh-scope"@*/node_modules/@deepseek-ai/dsh-scope 2>/dev/null | head -1)
say "  canonical: ${CANON:-NONE}"
if [ -z "$CANON" ]; then say 'REFUSED: pnpm produced no canonical dsh-scope'; exit 3; fi
say "  canonical version: $(python3 -c "import json;print(json.load(open('$CANON/package.json'))['version'])" 2>/dev/null)"

say 'correcting the patch for 0.2.1'
python3 - "$PATCH" <<'PY'
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

say 'swapping the engine tree'
mv "$LIVE" "$PREV" || { say 'tree move failed'; systemctl start phone-engine; exit 3; }
mv "$CAND" "$LIVE" || { say 'candidate move failed'; mv "$PREV" "$LIVE"; systemctl start phone-engine; exit 3; }

say 'unifying the scope symlink (the step that makes ExecStartPre pass)'
"$REPAIR" 2>&1 | tail -4 | sed 's/^/  /' | tee -a "$LOG"
"$REPAIR" --check > /dev/null 2>&1; say "  repair --check exit: $?"

say 'starting'
systemctl start phone-engine
OK=0
for i in $(seq 1 24); do
  sleep 5
  S=$(systemctl is-active phone-engine)
  C=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 http://127.0.0.1:3089/ || true)
  say "  t+$((i*5))s state=$S http=${C:-none}"
  [ "$S" = "active" ] && [ "${C:-000}" != "000" ] && OK=1 && break
done
VER=$("$NODE" "$LIVE/node_modules/@deepseek-ai/dsh/lib/bin.js" --version 2>&1 | tail -1)
say "version=$VER unit=$(systemctl is-active phone-engine) http=$(curl -s -o /dev/null -w '%{http_code}' --max-time 8 http://127.0.0.1:3089/ || echo 000)"

if [ "$OK" -ne 1 ] || [ "$VER" != "0.2.1-rc.2" ]; then
  say 'NOT SERVING — full rollback (tree, profile, patch, package.json)'
  systemctl stop phone-engine
  rm -rf "$PROF/node_modules"; mv "$PROF/node_modules.before-done-$STAMP" "$PROF/node_modules"
  cp -p "$PROF/package.json.bak-done-$STAMP" "$PROF/package.json"
  cp -p "$PATCH.bak-done-$STAMP" "$PATCH"
  mv "$LIVE" "/opt/dsh-phone.failed5-$STAMP" 2>/dev/null; mv "$PREV" "$LIVE"
  "$REPAIR" > /dev/null 2>&1
  systemctl start phone-engine
  for i in $(seq 1 10); do
    sleep 5
    C=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 http://127.0.0.1:3089/ || true)
    [ "${C:-000}" = "401" ] && break
  done
  say "  after rollback: unit=$(systemctl is-active phone-engine) version=$("$NODE" "$LIVE/node_modules/@deepseek-ai/dsh/lib/bin.js" --version 2>&1 | tail -1) http=$(curl -s -o /dev/null -w '%{http_code}' --max-time 6 http://127.0.0.1:3089/ || echo 000)"
  exit 4
fi
say "DONE — phone engine on $VER, serving"
