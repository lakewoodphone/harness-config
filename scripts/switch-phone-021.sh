#!/usr/bin/env bash
# switch-phone-021.sh — the owner's PHONE engine: 0.2.0-rc.2 -> 0.2.1-rc.2 on secratary-cloud.
#
# FOUR THINGS THIS HOST NEEDS THAT THE WORKER DID NOT, each measured today:
#  1. Its credential store holds BARE keys (`DEEPSEEK_API_KEY`, `DEEPINFRA_API_KEY`). 0.2.1's parser enforces
#     `<scope>/<id>` (dsh-credentials/lib/index.js:70) and refuses to boot on anything else — that is exactly what
#     took the worker down. So the keys move OUT of the store and INTO an EnvironmentFile, which is the pattern this
#     estate already uses on the worker ("the key lives in the environment ... so an agent cannot rewrite it").
#  2. Its profile patch still carries `ctx.webRuntime` (0.2.1 injects `webStartup`) and three `{{cwd}}` preset
#     suffixes (0.2.1 registers only provider/model). Both proven fatal elsewhere today.
#  3. `ExecStartPre=/usr/local/bin/repair-phone-engine.sh --check` re-points the profile's @deepseek-ai at the engine
#     tree on every start — that is the two-copies fix, so the anchor must be LEFT ALONE; the unit repairs it.
#  4. `Restart=always`, so ownership of the process is systemd's.
#
# Every step backs up first; any failure restores the tree, the unit, the credentials and the config, and starts the
# old engine again.
set -uo pipefail
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
LOG=/root/phone-switch-$STAMP.log
LIVE=/opt/dsh-phone
CAND=$(ls -d /opt/dsh-phone.failed-* 2>/dev/null | head -1)
PREV=/opt/dsh-phone.prev-0.2.0-rc.2-$STAMP
DSH=/root/.dsh
PATCH=$DSH/profiles/web/cordis.patch.yml
CRED=$DSH/.credentials.yaml
UNIT=/etc/systemd/system/phone-engine.service
ENVF=/etc/phone-engine.env
NODE=/usr/local/node22/bin/node

say() { echo "[$(date -u +%H:%M:%SZ)] $*" | tee -a "$LOG"; }

[ -n "$CAND" ] || { say "REFUSED: no candidate tree (/opt/dsh-phone.failed-*)"; exit 2; }
say "phone switch starting; candidate $(basename "$CAND") -> live; log $LOG"

# ── 0. backups ────────────────────────────────────────────────────────────────────────────────────
cp -p "$PATCH" "$PATCH.bak-phone021-$STAMP"
cp -p "$CRED" "$CRED.bak-phone021-$STAMP"
cp -p "$UNIT" "$UNIT.bak-phone021-$STAMP"
say "backed up patch, credentials, unit with suffix .bak-phone021-$STAMP"

# ── 1. credentials: bare keys out of the store, into a 0600 EnvironmentFile ───────────────────────
say "moving bare credential keys into $ENVF (values never printed)"
python3 - "$CRED" "$ENVF" <<'PY'
import os, re, sys
cred, envf = sys.argv[1], sys.argv[2]
lines = open(cred, encoding="utf-8").read().split("\n")
keep, moved = [], {}
for line in lines:
    m = re.match(r"^(\s{0,4})([A-Z0-9_]+)\s*:\s*(.+?)\s*$", line)
    if m and "/" not in m.group(2) and m.group(2).isupper():
        moved[m.group(2)] = m.group(3).strip().strip('"').strip("'")
        continue
    keep.append(line)
if not moved:
    print("  no bare keys found (nothing to move)")
    sys.exit(0)
with open(envf, "w", encoding="utf-8") as fh:
    for k, v in moved.items():
        fh.write(f"{k}={v}\n")
os.chmod(envf, 0o600)
open(cred, "w", encoding="utf-8").write("\n".join(keep))
print(f"  moved {len(moved)} key(s) to {envf} (mode 600): {', '.join(sorted(moved))}")
PY

# ── 2. the unit learns the EnvironmentFile ───────────────────────────────────────────────────────
if ! grep -q "^EnvironmentFile=$ENVF" "$UNIT"; then
  python3 - "$UNIT" "$ENVF" <<'PY'
import sys
unit, envf = sys.argv[1], sys.argv[2]
text = open(unit, encoding="utf-8").read()
anchor = "Environment=TMPDIR=/root/.dsh-tmp"
if anchor not in text:
    print("  REFUSED: no Environment= anchor in the unit"); sys.exit(2)
text = text.replace(anchor, anchor + f"\nEnvironmentFile={envf}", 1)
open(unit, "w", encoding="utf-8").write(text)
print(f"  unit now has EnvironmentFile={envf}")
PY
else
  say "  unit already references $ENVF"
fi
systemctl daemon-reload && say "daemon-reload done"

# ── 3. config for 0.2.1 ──────────────────────────────────────────────────────────────────────────
say "correcting the live profile patch for 0.2.1"
python3 - "$PATCH" "$DSH" <<'PY'
import pathlib, sys
patch, home = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
OLD_SUFFIX = "Your working directory is {{cwd}}."
NEW_SUFFIX = "Run `pwd` in your shell for the working directory; never assume a path."
def fix(p):
    t = p.read_text(encoding="utf-8"); out = []; n = 0
    for line in t.split("\n"):
        new = line
        if not line.lstrip().startswith("#") and "ctx.webRuntime.trustedHosts" in new:
            new = new.replace("ctx.webRuntime.trustedHosts", "ctx.webStartup.trustedHosts")
        if OLD_SUFFIX in new:
            new = new.replace(OLD_SUFFIX, NEW_SUFFIX)
        if new != line: n += 1
        out.append(new)
    if n: p.write_text("\n".join(out), encoding="utf-8")
    return n
total = fix(patch)
for p in sorted(home.glob(".agent-presets/*/agent.cordis.yml")):
    total += fix(p)
print(f"  lines changed: {total}")
PY

# ── 4. stop, swap, start ────────────────────────────────────────────────────────────────────────
say "stopping phone-engine"
systemctl stop phone-engine || { say "REFUSED: could not stop the unit"; exit 2; }
sleep 3
systemctl is-active --quiet phone-engine && { say "REFUSED: still active"; exit 2; }

say "swapping $LIVE -> $(basename "$PREV"), candidate -> $LIVE"
mv "$LIVE" "$PREV" || { say "swap step 1 failed"; systemctl start phone-engine; exit 3; }
mv "$CAND" "$LIVE" || { say "swap step 2 failed — restoring"; mv "$PREV" "$LIVE"; systemctl start phone-engine; exit 3; }

say "starting phone-engine"
systemctl start phone-engine
for i in $(seq 1 18); do
  sleep 5
  S=$(systemctl is-active phone-engine)
  C=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 http://127.0.0.1:3089/ || true)
  say "  t+$((i*5))s state=$S http=${C:-none}"
  [ "$S" = "active" ] && [ "${C:-000}" != "000" ] && break
done

VER=$($NODE "$LIVE/node_modules/@deepseek-ai/dsh/lib/bin.js" --version 2>&1 | tail -1)
CODE=$(curl -s -o /dev/null -w '%{http_code}' --max-time 8 http://127.0.0.1:3089/ || true)
say "version=$VER http=${CODE:-none}"
journalctl -u phone-engine -n 12 --no-pager -o cat 2>/dev/null | grep -aviE 'CallToolRequest|server\.py|Processing request' | tail -6 | sed 's/^/  /' | tee -a "$LOG"

if [ "$VER" != "0.2.1-rc.2" ]; then
  say "THE NEW ENGINE IS NOT RUNNING — rolling back tree, unit, credentials and config"
  systemctl stop phone-engine
  mv "$LIVE" "/opt/dsh-phone.failed-$STAMP" && mv "$PREV" "$LIVE"
  cp -p "$UNIT.bak-phone021-$STAMP" "$UNIT" && systemctl daemon-reload
  cp -p "$CRED.bak-phone021-$STAMP" "$CRED"
  cp -p "$PATCH.bak-phone021-$STAMP" "$PATCH"
  systemctl start phone-engine
  sleep 15
  say "  after rollback: $(systemctl is-active phone-engine) $($NODE "$LIVE/node_modules/@deepseek-ai/dsh/lib/bin.js" --version 2>&1 | tail -1) http $(curl -s -o /dev/null -w '%{http_code}' --max-time 6 http://127.0.0.1:3089/ || echo 000)"
  exit 4
fi
say "DONE — phone engine on $VER; previous tree kept at $PREV"
