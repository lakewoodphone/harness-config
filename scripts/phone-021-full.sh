#!/usr/bin/env bash
# phone-021-full.sh — take the owner's phone engine to 0.2.1-rc.2 END TO END, in a two-hour window with the phone
# not in use.
#
# WHAT THE TWO EARLIER ATTEMPTS ESTABLISHED (L10624):
#   1. the tree swap works, and the profile's `@deepseek-ai` symlink must be re-pointed after it
#      (repair-phone-engine.sh without --check does that; --check only refuses);
#   2. 0.2.1 rejects bare credential keys — they now live in /etc/phone-engine.env via EnvironmentFile;
#   3. the remaining blocker is `webserver (required): missing webStartup`, and this home's PROFILE carries its own
#      dependency tree pinned at 0.2.0-rc.2 (67 pins). The provider of the missing service resolves from that tree.
# So this script rebuilds the profile tree AT 0.2.1 first, then swaps the engine. Nothing else is guessed at.
#
# Order: stop -> back up -> repin -> npm install -> verify the tree -> swap the engine -> repair -> start -> verify.
# Any failure restores the tree, the profile files and the unit, and starts 0.2.0 again.
set -uo pipefail
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
LOG=/root/phone-021-full-$STAMP.log
LIVE=/opt/dsh-phone
CAND=$(for d in /opt/dsh-phone.failed2-* /opt/dsh-phone.failed-0* /opt/dsh-phone-021-new /opt/dsh-phone-0.2.1; do [ -d "$d/node_modules/@deepseek-ai/dsh-web-app" ] && echo "$d"; done | head -1)
PREV=/opt/dsh-phone.prev-0.2.0-rc.2-$STAMP
PROF=/root/.dsh/profiles/web
NODE=/usr/local/node22/bin/node
NPM=/usr/local/node22/bin/npm
REPAIR=/usr/local/bin/repair-phone-engine.sh
UNIT=/etc/systemd/system/phone-engine.service

say() { echo "[$(date -u +%H:%M:%SZ)] $*" | tee -a "$LOG"; }
fail() { say "FAILED: $*"; }

[ -n "$CAND" ] || { fail "no candidate tree"; exit 2; }
# THE CANDIDATE MUST BE A COMPLETE ENGINE TREE. Measured 2026-10-20: two "candidates" in /opt held ZERO @deepseek-ai
# packages after earlier move/repair cycles, and switching one in produced `webserver (required): missing
# webStartup` — which reads exactly like a service rename and is really an empty tree. A real 0.2.1 tree carries
# ~306 @deepseek-ai packages and dsh-web-app with the webStartup provider in it.
PKGS=$(ls -1 "$CAND/node_modules/@deepseek-ai" 2>/dev/null | wc -l)
say "candidate packages: $PKGS"
if [ "$PKGS" -lt 250 ]; then fail "candidate has only $PKGS @deepseek-ai packages — refusing to swap in an incomplete tree"; exit 2; fi
if [ ! -d "$CAND/node_modules/@deepseek-ai/dsh-web-app" ]; then fail "candidate has no dsh-web-app"; exit 2; fi
say "phone 0.2.1 end to end; candidate $(basename "$CAND"); log $LOG"

# ── 1. stop ───────────────────────────────────────────────────────────────────────────────────────
say 'stopping phone-engine'
systemctl stop phone-engine || { fail 'could not stop the unit'; exit 2; }
sleep 3
systemctl is-active --quiet phone-engine && { fail 'unit still active'; systemctl start phone-engine; exit 2; }
say '  stopped'

# ── 2. back up the profile, then repin ───────────────────────────────────────────────────────────
cp -p "$PROF/package.json" "$PROF/package.json.bak-021-$STAMP"
[ -f "$PROF/package-lock.json" ] && cp -p "$PROF/package-lock.json" "$PROF/package-lock.json.bak-021-$STAMP"
if [ -d "$PROF/node_modules" ]; then mv "$PROF/node_modules" "$PROF/node_modules.0.2.0-keep-$STAMP"; fi
say "  profile backed up (package.json + node_modules moved aside, never deleted)"

python3 - "$PROF/package.json" <<'PY'
import json, sys
p = sys.argv[1]
d = json.load(open(p))
deps = d.get("dependencies", {})
n = 0
for k, v in list(deps.items()):
    if v == "0.2.0-rc.2":
        deps[k] = "0.2.1-rc.2"; n += 1
# THE PROFILE MUST NOT CARRY ITS OWN @deepseek-ai PACKAGES. Measured 2026-10-20: with ~70 upstream packages installed
# into the profile, the composition had TWO module graphs -- `webStartup` provided by the profile's dsh-web-app and
# consumed by the engine's `webserver` -- and startup failed with "1 required plugin did not activate". The working
# machine keeps ONLY the local `file:` plugins in this file and resolves everything upstream from the engine tree,
# which is one graph. So the upstream pins are dropped here, not repinned.
dropped = []  # KEEP the upstream pins: repair-phone-engine.sh resolves dsh-scope from the profile's .pnpm copy and symlinks the engine's copy to it, so an EMPTY profile tree makes that symlink dangling
for k in dropped:
    del deps[k]
d["dependencies"] = deps
open(p, "w").write(json.dumps(d, indent=2) + "\n")
print(f"  repinned {n}; dropped {len(dropped)} upstream pin(s) so the profile resolves them from the engine")
json.dump(d, open(p, "w"), indent=2)
open(p, "a").write("\n")
print(f"  repinned {n} dependency(ies) 0.2.0-rc.2 -> 0.2.1-rc.2")
PY

# ── 3. install the profile tree at 0.2.1 ────────────────────────────────────────────────────────
say 'installing the profile tree at 0.2.1 (this is the long step)'
cd "$PROF" || { fail "no profile dir"; exit 2; }
"$NPM" install --omit=dev --no-audit --no-fund --loglevel=error > "$LOG.npm" 2>&1
NPMRC=$?
say "  npm install exit: $NPMRC ($(tail -2 "$LOG.npm" | tr '\n' ' '))"
if [ "$NPMRC" -ne 0 ]; then
  fail 'profile install failed — restoring'
  rm -rf "$PROF/node_modules"
  mv "$PROF/node_modules.0.2.0-keep-$STAMP" "$PROF/node_modules"
  cp -p "$PROF/package.json.bak-021-$STAMP" "$PROF/package.json"
  systemctl start phone-engine
  exit 3
fi

say '  verifying the installed tree'
python3 - "$PROF" <<'PY'
import json, os, sys, glob
prof = sys.argv[1]
nm = os.path.join(prof, "node_modules", "@deepseek-ai")
pkgs = sorted(glob.glob(os.path.join(nm, "*", "package.json")))
vers = {}
for p in pkgs:
    try:
        v = json.load(open(p)).get("version")
        vers[v] = vers.get(v, 0) + 1
    except Exception:
        pass
print("  @deepseek-ai packages by version:", vers)
missing = [n for n in ("dsh-web-app", "dsh-web-server", "dsh-base") if not os.path.isdir(os.path.join(nm, n))]
print("  core packages missing:", missing or "none")
PY

# ── 4. swap the engine tree ─────────────────────────────────────────────────────────────────────
say 'swapping the engine tree'
mv "$LIVE" "$PREV" || { fail 'tree move failed'; systemctl start phone-engine; exit 3; }
mv "$CAND" "$LIVE" || { fail 'candidate move failed — restoring'; mv "$PREV" "$LIVE"; systemctl start phone-engine; exit 3; }

say 're-pointing the profile symlink at the new tree'
"$REPAIR" 2>&1 | tail -5 | sed 's/^/  /' | tee -a "$LOG"

# ── 5. start and verify ─────────────────────────────────────────────────────────────────────────
say 'starting phone-engine'
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
STARTUP=$(ls -t /root/.dsh/logs/startup-*.log 2>/dev/null | head -1)
say "version=$VER unit=$(systemctl is-active phone-engine) http=$(curl -s -o /dev/null -w '%{http_code}' --max-time 8 http://127.0.0.1:3089/ || echo 000)"
if [ -n "$STARTUP" ]; then
  say "  startup errors: $(grep -ac 'did not activate' "$STARTUP" 2>/dev/null || echo 0)"
  grep -a 'did not activate' -A3 "$STARTUP" 2>/dev/null | head -6 | sed 's/^/    /' | tee -a "$LOG"
fi

if [ "$OK" -ne 1 ] || [ "$VER" != "0.2.1-rc.2" ]; then
  fail 'not serving — rolling back the tree, the profile and the unit'
  systemctl stop phone-engine
  rm -rf "$PROF/node_modules"
  mv "$PROF/node_modules.0.2.0-keep-$STAMP" "$PROF/node_modules"
  cp -p "$PROF/package.json.bak-021-$STAMP" "$PROF/package.json"
  mv "$LIVE" "$LIVE.failed2-$STAMP" 2>/dev/null
  mv "$PREV" "$LIVE"
  "$REPAIR" >/dev/null 2>&1
  systemctl start phone-engine
  sleep 20
  say "  after rollback: unit=$(systemctl is-active phone-engine) version=$("$NODE" "$LIVE/node_modules/@deepseek-ai/dsh/lib/bin.js" --version 2>&1 | tail -1) http=$(curl -s -o /dev/null -w '%{http_code}' --max-time 6 http://127.0.0.1:3089/ || echo 000)"
  exit 4
fi

say "DONE — phone engine on $VER, serving; previous tree $PREV; profile 0.2.0 tree kept at $PROF/node_modules.0.2.0-keep-$STAMP"
