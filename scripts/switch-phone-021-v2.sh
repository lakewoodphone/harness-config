#!/usr/bin/env bash
# switch-phone-021-v2.sh — the phone engine, second attempt, with the step v1 omitted.
#
# WHAT v1 GOT WRONG: after moving /opt/dsh-phone aside and putting 0.2.1 in its place, the profile's
# `@deepseek-ai` symlink still pointed at the OLD tree, so the engine loaded two copies of `dsh-scope` and refused:
#   scope: TWO COPIES — /opt/dsh-phone/node_modules/@deepseek-ai/dsh-scope vs
#          /root/.dsh/profiles/web/node_modules/.pnpm/@deepseek-ai+dsh-scope@0.2.0-rc.2...
# The unit's `ExecStartPre=repair-phone-engine.sh --check` only REPORTS that (exit 2, "wrong"); the repair happens
# when the same script runs without --check. So the swap must be followed by a repair, before the start.
#
# v1 also declared success from the version string while the unit was still "activating" — a version on disk is not
# a running engine. v2 requires: unit active AND http != 000.
set -uo pipefail
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
LOG=/root/phone-switch2-$STAMP.log
LIVE=/opt/dsh-phone
CAND=$(ls -d /opt/dsh-phone.failed-02* 2>/dev/null | head -1)
PREV=/opt/dsh-phone.prev-0.2.0-rc.2-$STAMP
DSH=/root/.dsh
PATCH=$DSH/profiles/web/cordis.patch.yml
CRED=$DSH/.credentials.yaml
UNIT=/etc/systemd/system/phone-engine.service
ENVF=/etc/phone-engine.env
NODE=/usr/local/node22/bin/node
REPAIR=/usr/local/bin/repair-phone-engine.sh

say() { echo "[$(date -u +%H:%M:%SZ)] $*" | tee -a "$LOG"; }

[ -n "$CAND" ] || { say "REFUSED: no candidate"; exit 2; }
say "phone switch v2; candidate $(basename "$CAND")"

# ── backups ──────────────────────────────────────────────────────────────────────────────────────
for f in "$PATCH" "$CRED" "$UNIT"; do cp -p "$f" "$f.bak-phone021v2-$STAMP"; done
say "backed up patch, credentials, unit"

# ── credentials: bare keys -> EnvironmentFile (proven in v1: the engine got past its credentials include) ──────
if grep -qE '^[[:space:]]{0,4}(DEEPSEEK_API_KEY|DEEPINFRA_API_KEY):' "$CRED" 2>/dev/null; then
  python3 - "$CRED" "$ENVF" <<'PY'
import os, re, sys
cred, envf = sys.argv[1], sys.argv[2]
lines = open(cred, encoding="utf-8").read().split("\n")
keep, moved = [], {}
for line in lines:
    m = re.match(r"^(\s{0,4})([A-Z0-9_]+)\s*:\s*(.+?)\s*$", line)
    if m and "/" not in m.group(2) and m.group(2).isupper():
        moved[m.group(2)] = m.group(3).strip().strip('"').strip("'"); continue
    keep.append(line)
with open(envf, "w", encoding="utf-8") as fh:
    for k, v in moved.items(): fh.write(f"{k}={v}\n")
os.chmod(envf, 0o600)
open(cred, "w", encoding="utf-8").write("\n".join(keep))
print(f"  moved {len(moved)} key(s) into {envf}")
PY
else
  say "  no bare credential keys left to move"
fi

if ! grep -q "^EnvironmentFile=$ENVF" "$UNIT" 2>/dev/null; then
  python3 - "$UNIT" "$ENVF" <<'PY'
import sys
unit, envf = sys.argv[1], sys.argv[2]
t = open(unit, encoding="utf-8").read()
a = "Environment=TMPDIR=/root/.dsh-tmp"
if a in t:
    t = t.replace(a, a + f"\nEnvironmentFile={envf}", 1)
    open(unit, "w", encoding="utf-8").write(t)
    print(f"  unit now reads {envf}")
PY
fi
systemctl daemon-reload

# ── config for 0.2.1 ─────────────────────────────────────────────────────────────────────────────
python3 - "$PATCH" "$DSH" <<'PY'
import pathlib, sys
patch, home = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
OLD, NEW = "Your working directory is {{cwd}}.", "Run `pwd` in your shell for the working directory; never assume a path."
def fix(p):
    t = p.read_text(encoding="utf-8"); out = []; n = 0
    for line in t.split("\n"):
        new = line
        if not line.lstrip().startswith("#") and "ctx.webRuntime.trustedHosts" in new:
            new = new.replace("ctx.webRuntime.trustedHosts", "ctx.webStartup.trustedHosts")
        if OLD in new: new = new.replace(OLD, NEW)
        if new != line: n += 1
        out.append(new)
    if n: p.write_text("\n".join(out), encoding="utf-8")
    return n
total = fix(patch)
for p in sorted(home.glob(".agent-presets/*/agent.cordis.yml")): total += fix(p)
print(f"  config lines changed: {total}")
PY

# ── stop, swap, REPAIR, start ───────────────────────────────────────────────────────────────────
say "stopping phone-engine"
systemctl stop phone-engine || { say "REFUSED: stop failed"; exit 2; }
sleep 3

say "swapping trees"
mv "$LIVE" "$PREV" || { say "swap failed"; systemctl start phone-engine; exit 3; }
mv "$CAND" "$LIVE" || { say "install failed — restoring"; mv "$PREV" "$LIVE"; systemctl start phone-engine; exit 3; }

say "re-pointing the profile symlink at the new tree ($REPAIR)"
"$REPAIR" 2>&1 | tail -6 | sed 's/^/  /' | tee -a "$LOG"
say "  repair exit: $?"

say "starting phone-engine"
systemctl start phone-engine
OK=0
for i in $(seq 1 18); do
  sleep 5
  S=$(systemctl is-active phone-engine)
  C=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 http://127.0.0.1:3089/ || true)
  say "  t+$((i*5))s state=$S http=${C:-none}"
  if [ "$S" = "active" ] && [ "${C:-000}" != "000" ]; then OK=1; break; fi
done

VER=$($NODE "$LIVE/node_modules/@deepseek-ai/dsh/lib/bin.js" --version 2>&1 | tail -1)
say "version=$VER unit=$(systemctl is-active phone-engine) http=$(curl -s -o /dev/null -w '%{http_code}' --max-time 8 http://127.0.0.1:3089/ || echo 000)"

if [ "$OK" -ne 1 ] || [ "$VER" != "0.2.1-rc.2" ]; then
  say "NOT SERVING — rolling back everything"
  journalctl -u phone-engine -n 8 --no-pager -o cat 2>/dev/null | grep -aviE 'CallToolRequest|server\.py' | tail -4 | sed 's/^/  /' | tee -a "$LOG"
  systemctl stop phone-engine
  mv "$LIVE" "/opt/dsh-phone.failed2-$STAMP" && mv "$PREV" "$LIVE"
  for f in "$UNIT" "$CRED" "$PATCH"; do B=$(ls -t "$f".bak-phone021v2-* 2>/dev/null | head -1); [ -n "$B" ] && cp -p "$B" "$f"; done
  systemctl daemon-reload
  "$REPAIR" >/dev/null 2>&1
  systemctl start phone-engine
  sleep 15
  say "  after rollback: unit=$(systemctl is-active phone-engine) version=$($NODE "$LIVE/node_modules/@deepseek-ai/dsh/lib/bin.js" --version 2>&1 | tail -1) http=$(curl -s -o /dev/null -w '%{http_code}' --max-time 6 http://127.0.0.1:3089/ || echo 000)"
  exit 4
fi
say "DONE — phone engine on $VER, serving; previous tree at $PREV"
