#!/usr/bin/env bash
# phone-021-final.sh — the attempt that follows the evidence.
#
# WHAT THE LAST FIVE ATTEMPTS PROVED, in order:
#   * the tree swap works; the profile's @deepseek-ai symlink must be re-pointed after it;
#   * 0.2.1 rejects bare credential keys -> they live in /etc/phone-engine.env now;
#   * a 0.2.1 profile + a 0.2.1 engine COMPOSES 421 rows including web-startup/webserver/web-runtime (measured with
#     a scratch home), so the config is not the problem;
#   * and the boot failure is the ONE SYMLINK: /opt/dsh-phone/node_modules/@deepseek-ai/dsh-scope pointed at
#     `/root/.dsh/profiles/web/node_modules/.pnpm/@deepseek-ai+dsh-scope@0.2.0-rc.2...`. During a switch the profile
#     is moved aside and reinstalled, so that absolute path stops existing -> dsh-scope does not load -> every
#     service stays pending -> `webserver (required): missing webStartup`. A v2.1 tree whose dsh-scope is a REAL
#     directory exists at failed2-...121549Z, which is the candidate this script uses.
#
# FIX: after installing the profile at 0.2.1 (flat npm tree, no .pnpm), point the ENGINE's dsh-scope at the
# PROFILE's 0.2.1 copy explicitly — the same "one symlink" the repair script intends, with a path that exists.
set -uo pipefail
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
LOG=/root/phone-final-$STAMP.log
LIVE=/opt/dsh-phone
CAND=/opt/dsh-phone.failed2-20261020T121549Z
PREV=/opt/dsh-phone.prev-0.2.0-rc.2-$STAMP
PROF=/root/.dsh/profiles/web
NODE=/usr/local/node22/bin/node
NPM=/usr/local/node22/bin/npm

say() { echo "[$(date -u +%H:%M:%SZ)] $*" | tee -a "$LOG"; }

[ -d "$CAND/node_modules/@deepseek-ai/dsh-web-app" ] || { say "candidate missing"; exit 2; }
[ -d "$CAND/node_modules/@deepseek-ai/dsh-scope" ] && [ ! -L "$CAND/node_modules/@deepseek-ai/dsh-scope" ] || {
  say "REFUSED: candidate's dsh-scope is not a real directory"; exit 2; }
say "final attempt; candidate $(basename "$CAND")"

say 'stopping the unit'
systemctl stop phone-engine || { say 'stop failed'; exit 2; }
sleep 3

say 'backing up the profile and installing it at 0.2.1'
cp -p "$PROF/package.json" "$PROF/package.json.bak-final-$STAMP"
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

say 'pointing the engine dsh-scope at the profile 0.2.1 copy (the ONE symlink, with a path that exists)'
SC_PROF="$PROF/node_modules/@deepseek-ai/dsh-scope"
[ -d "$SC_PROF" ] || { say "  REFUSED: profile has no dsh-scope after install"; exit 3; }
SC_ENG="$CAND/node_modules/@deepseek-ai/dsh-scope"
say "  profile dsh-scope -> $(python3 -c "import json;print(json.load(open('$SC_PROF/package.json'))['version'])" 2>/dev/null)"
rm -rf "$SC_ENG" && ln -s "$SC_PROF" "$SC_ENG" && say "  engine dsh-scope -> $SC_PROF"

say 'swapping the engine tree'
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
  cp -p "$PROF/package.json.bak-final-$STAMP" "$PROF/package.json"
  mv "$LIVE" "/opt/dsh-phone.failed3-$STAMP" 2>/dev/null; mv "$PREV" "$LIVE"
  systemctl start phone-engine
  sleep 20
  say "  after rollback: unit=$(systemctl is-active phone-engine) version=$("$NODE" "$LIVE/node_modules/@deepseek-ai/dsh/lib/bin.js" --version 2>&1 | tail -1) http=$(curl -s -o /dev/null -w '%{http_code}' --max-time 6 http://127.0.0.1:3089/ || echo 000)"
  exit 4
fi
say "DONE — phone engine on $VER, serving; previous tree $PREV"
