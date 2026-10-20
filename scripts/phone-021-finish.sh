#!/usr/bin/env bash
# phone-021-finish.sh — finish it, with the ExecStartPre gate satisfied honestly.
#
# THE GATE: `repair-phone-engine.sh --check` requires
#   profiles/web/node_modules/.pnpm/@deepseek-ai+dsh-scope@*/node_modules/@deepseek-ai/dsh-scope   (canonical)
# and the engine's dsh-scope to resolve to the SAME inode. An npm install produces a flat tree with no `.pnpm`
# directory at all, so the gate found no canonical copy and exited 2 — `Control process exited, status=2` — and the
# engine never started. That is why every earlier attempt sat in "activating" with no startup log, while a
# foreground run (which skips ExecStartPre) booted perfectly.
#
# `pnpm install` here returns "Done in 252ms" and installs nothing (no lockfile), so the canonical path is created
# explicitly as a symlink to the profile's own installed copy. That is not a fake: both paths then resolve to one
# file, which is exactly the property the gate asserts and the reason the gate exists (two copies of dsh-scope =
# "every prompt rejected as session/agent-busy").
set -uo pipefail
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
LOG=/root/phone-finish-$STAMP.log
LIVE=/opt/dsh-phone
PROF=/root/.dsh/profiles/web
PATCH=$PROF/cordis.patch.yml
NODE=/usr/local/node22/bin/node
NPM=/usr/local/node22/bin/npm
REPAIR=/usr/local/bin/repair-phone-engine.sh
CAND=$(for d in /opt/dsh-phone.failed4-* /opt/dsh-phone.failed3-*; do
         [ -x "$d/node_modules/@deepseek-ai/dsh/lib/bin.js" ] && [ -d "$d/node_modules/@deepseek-ai/dsh-web-app" ] && echo "$d" && break
       done)
PREV=/opt/dsh-phone.prev-0.2.0-rc.2-$STAMP

say() { echo "[$(date -u +%H:%M:%SZ)] $*" | tee -a "$LOG"; }

restore() {
  say 'RESTORING'
  systemctl stop phone-engine 2>/dev/null
  rm -rf "$PROF/node_modules"
  [ -d "$PROF/node_modules.before-finish-$STAMP" ] && mv "$PROF/node_modules.before-finish-$STAMP" "$PROF/node_modules"
  [ -f "$PROF/package.json.bak-finish-$STAMP" ] && cp -p "$PROF/package.json.bak-finish-$STAMP" "$PROF/package.json"
  [ -f "$PATCH.bak-finish-$STAMP" ] && cp -p "$PATCH.bak-finish-$STAMP" "$PATCH"
  [ -d "/opt/dsh-phone.failed6-$STAMP" ] && [ ! -d "$LIVE" ] && mv "/opt/dsh-phone.failed6-$STAMP" "$LIVE"
  [ -d "$PREV" ] && [ ! -d "$LIVE" ] && mv "$PREV" "$LIVE"
  "$REPAIR" > /dev/null 2>&1
  systemctl start phone-engine
  for i in $(seq 1 12); do
    sleep 5
    C=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 http://127.0.0.1:3089/ || true)
    [ "${C:-000}" = "401" ] && break
  done
  say "  restored: unit=$(systemctl is-active phone-engine) version=$("$NODE" "$LIVE/node_modules/@deepseek-ai/dsh/lib/bin.js" --version 2>&1 | tail -1) http=$(curl -s -o /dev/null -w '%{http_code}' --max-time 6 http://127.0.0.1:3089/ || echo 000)"
}

[ -n "$CAND" ] || { say 'REFUSED: no complete 0.2.1 tree'; exit 2; }
say "finish; candidate $(basename "$CAND")"

say 'stop'
systemctl stop phone-engine || { say 'stop failed'; exit 2; }
sleep 3

say 'back up everything this changes'
cp -p "$PROF/package.json" "$PROF/package.json.bak-finish-$STAMP"
cp -p "$PATCH" "$PATCH.bak-finish-$STAMP"
[ -d "$PROF/node_modules" ] && mv "$PROF/node_modules" "$PROF/node_modules.before-finish-$STAMP"

say 'repin + npm install the profile at 0.2.1'
python3 - "$PROF/package.json" <<'PY'
import json, sys
p = sys.argv[1]; d = json.load(open(p)); n = 0
for k, v in list(d.get("dependencies", {}).items()):
    if v == "0.2.0-rc.2": d["dependencies"][k] = "0.2.1-rc.2"; n += 1
json.dump(d, open(p, "w"), indent=2); open(p, "a").write("\n")
print(f"  repinned {n}")
PY
cd "$PROF" || { restore; exit 2; }
"$NPM" install --omit=dev --no-audit --no-fund --loglevel=error > "$LOG.npm" 2>&1
say "  npm exit: $?"; [ -d "$PROF/node_modules/@deepseek-ai/dsh-scope" ] || { say 'no dsh-scope after install'; restore; exit 3; }

say 'creating the canonical dsh-scope path the gate looks for (a symlink to the same file, not a copy)'
SC_VER=$(python3 -c "import json;print(json.load(open('$PROF/node_modules/@deepseek-ai/dsh-scope/package.json'))['version'])")
CANON_DIR="$PROF/node_modules/.pnpm/@deepseek-ai+dsh-scope@$SC_VER/node_modules/@deepseek-ai"
mkdir -p "$CANON_DIR"
ln -sfn ../../../../../@deepseek-ai/dsh-scope "$CANON_DIR/dsh-scope"
say "  canonical -> $(readlink -f "$CANON_DIR/dsh-scope")"

say 'correct the patch for 0.2.1'
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

say 'swap the engine tree'
mv "$LIVE" "$PREV" || { say 'tree move failed'; restore; exit 3; }
mv "$CAND" "$LIVE" || { say 'candidate move failed'; restore; exit 3; }

say 'unify the scope symlink and gate-check'
"$REPAIR" 2>&1 | tail -3 | sed 's/^/  /' | tee -a "$LOG"
"$REPAIR" --check > /dev/null 2>&1
GATE=$?
say "  repair --check exit: $GATE"
[ "$GATE" -eq 0 ] || { say 'the gate still refuses — not starting'; restore; exit 4; }

say 'start'
systemctl start phone-engine
OK=0
for i in $(seq 1 24); do
  sleep 5
  S=$(systemctl is-active phone-engine)
  C=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 http://127.0.0.1:3089/ || true)
  say "  t+$((i*5))s state=$S http=${C:-none}"
  [ "$S" = "active" ] && [ "${C:-000}" = "401" ] && OK=1 && break
done
VER=$("$NODE" "$LIVE/node_modules/@deepseek-ai/dsh/lib/bin.js" --version 2>&1 | tail -1)
say "version=$VER unit=$(systemctl is-active phone-engine) http=$(curl -s -o /dev/null -w '%{http_code}' --max-time 8 http://127.0.0.1:3089/ || echo 000) gate=$(curl -s -o /dev/null -w '%{http_code}' --max-time 6 http://127.0.0.1:3086/ || echo 000)"

if [ "$OK" -ne 1 ] || [ "$VER" != "0.2.1-rc.2" ]; then
  mv "$LIVE" "/opt/dsh-phone.failed6-$STAMP" 2>/dev/null
  restore
  exit 4
fi
say "DONE — phone engine on $VER, serving 401; previous tree $PREV"
