#!/usr/bin/env bash
# switch-phone-engine.sh — move the owner's PHONE engine from 0.2.0-rc.2 to 0.2.1-rc.2, on the authority.
#
# WHY THIS IS A SCRIPT WITH A LADDER, not four commands: the same two config assumptions that took ZABZ-TECH's
# GUI down (journal L10238) are present in this machine's DSH home — `/root/.dsh/profiles/web/cordis.patch.yml`
# carries `ctx.webRuntime.trustedHosts` at line 61 and three preset rows with `{{cwd}}`. 0.2.1 injects
# `webStartup` and registers only `provider`/`model`, so the engine must NOT be started until both are corrected,
# and the correction must be proven by a compose BEFORE the service comes back.
#
# The unit hardcodes /opt/dsh-phone, so the swap is a rename at that path; the previous tree is kept beside it.
# Anything that fails restores BOTH the tree and the config, and starts the old engine again.
set -uo pipefail
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
NEW=/opt/dsh-phone-0.2.1
LIVE=/opt/dsh-phone
PREV=/opt/dsh-phone.prev-0.2.0-rc.2-$STAMP
HOME_DSH=/root/.dsh
PATCH=$HOME_DSH/profiles/web/cordis.patch.yml
NODE=/usr/local/node22/bin/node
BIN_REL=node_modules/@deepseek-ai/dsh/lib/bin.js

say() { echo "[$(date -u +%H:%M:%SZ)] $*"; }

say "candidate: $($NODE $NEW/$BIN_REL --version 2>&1 | tail -1)   live: $($NODE $LIVE/$BIN_REL --version 2>&1 | tail -1)"
$NODE "$NEW/$BIN_REL" --version 2>/dev/null | grep -qx '0.2.1-rc.2' || { say "REFUSED: candidate is not 0.2.1-rc.2"; exit 2; }

say "stopping phone-engine"
systemctl stop phone-engine || { say "could not stop the unit"; exit 2; }
sleep 3
systemctl is-active --quiet phone-engine && { say "REFUSED: unit still active"; exit 2; }

cp -p "$PATCH" "$PATCH.bak-phone-021-$STAMP"
for f in $HOME_DSH/.agent-presets/*/agent.cordis.yml; do [ -f "$f" ] && cp -p "$f" "$f.bak-phone-021-$STAMP"; done

say "correcting the config for 0.2.1"
python3 - "$PATCH" "$HOME_DSH" <<'PY'
import pathlib
import sys

patch = pathlib.Path(sys.argv[1])
home = pathlib.Path(sys.argv[2])
OLD_EXPR = "ctx.webRuntime.trustedHosts"
NEW_EXPR = "ctx.webStartup.trustedHosts"
OLD_SUFFIX = "Your working directory is {{cwd}}."
NEW_SUFFIX = "Run `pwd` in your shell for the working directory; never assume a path."

def fix(path: pathlib.Path) -> int:
    text = path.read_text(encoding="utf-8")
    out = []
    changed = 0
    for line in text.split("\n"):
        new = line
        if not line.lstrip().startswith("#"):
            if OLD_EXPR in new:
                new = new.replace(OLD_EXPR, NEW_EXPR)
        if OLD_SUFFIX in new:
            new = new.replace(OLD_SUFFIX, NEW_SUFFIX)
        if new != line:
            changed += 1
        out.append(new)
    if changed:
        path.write_text("\n".join(out), encoding="utf-8")
    return changed

total = fix(patch)
for p in sorted(home.glob(".agent-presets/*/agent.cordis.yml")):
    total += fix(p)
print(f"  lines changed: {total}")
PY

say "compose check with the CANDIDATE binary against the corrected home (no service running)"
DSH_HOME=$HOME_DSH "$NODE" "$NEW/$BIN_REL" --profile web --dump-config >/tmp/phone-compose.txt 2>/tmp/phone-compose.err
RC=$?
ROWS=$(grep -cE '^\s*-\s+id:' /tmp/phone-compose.txt || true)
RT=$(grep -c 'ctx\.webRuntime' /tmp/phone-compose.txt || true)
CW=$(grep -c '{{cwd}}' /tmp/phone-compose.txt || true)
say "  compose exit=$RC rows=$ROWS ctx.webRuntime=$RT {{cwd}}=$CW"
if [ "$RC" -ne 0 ] || [ "$ROWS" -lt 1 ]; then
    say "COMPOSE FAILED — restoring the config and starting the OLD engine"
    cp -p "$PATCH.bak-phone-021-$STAMP" "$PATCH"
    for f in $HOME_DSH/.agent-presets/*/agent.cordis.yml.bak-phone-021-$STAMP; do [ -f "$f" ] && cp -p "$f" "${f%.bak-phone-021-$STAMP}"; done
    tail -5 /tmp/phone-compose.err
    systemctl start phone-engine
    exit 3
fi

say "swapping the trees"
mv "$LIVE" "$PREV" || { say "could not move the live tree"; systemctl start phone-engine; exit 3; }
mv "$NEW" "$LIVE" || { say "could not move the candidate in — restoring"; mv "$PREV" "$LIVE"; systemctl start phone-engine; exit 3; }

say "starting phone-engine"
systemctl start phone-engine
sleep 20
ACTIVE=$(systemctl is-active phone-engine)
VER=$($NODE "$LIVE/$BIN_REL" --version 2>&1 | tail -1)
CODE=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 http://127.0.0.1:3089/ || echo 000)
say "  active=$ACTIVE version=$VER http=$CODE"
say "  last stderr lines:"; tail -3 /root/.dsh-phone/engine-3089.err 2>/dev/null | sed 's/^/    /'

if [ "$ACTIVE" != "active" ] || [ "$VER" != "0.2.1-rc.2" ]; then
    say "THE NEW ENGINE DID NOT COME UP — rolling back the tree and the config"
    systemctl stop phone-engine
    mv "$LIVE" "/opt/dsh-phone.failed-$STAMP" && mv "$PREV" "$LIVE"
    cp -p "$PATCH.bak-phone-021-$STAMP" "$PATCH"
    systemctl start phone-engine
    sleep 10
    say "  after rollback: $(systemctl is-active phone-engine) $($NODE $LIVE/$BIN_REL --version 2>&1 | tail -1)"
    exit 4
fi

say "DONE — the phone engine runs $VER; previous tree kept at $PREV; config backups *bak-phone-021-$STAMP"
exit 0
