#!/usr/bin/env bash
# switch-worker-021.sh (v2) — move zabz-tech-linux from DSH 0.1.5-rc.1 to 0.2.1-rc.2.
#
# v2 exists because v1 assumed a bare process and this node runs under `dsh-engine.service` (Restart=always), so
# killing the pid only made systemd start it again and the port kept flipping. Ownership of this service belongs to
# systemd: stop it there, install, start it there.
#
# The anchor is moved aside first: `~/.dsh/profiles/node_modules` carries its own copy of the engine's packages, and a
# newer engine that finds them refuses to start ("TWO COPIES ... every prompt will be rejected") — measured on the
# phone engine. Nothing is deleted; the old anchor is kept beside it.
set -uo pipefail
REPO=/home/zabz/code/harness-config/dsh-update
HOME_DSH=/home/zabz/.dsh
ENGINE=/home/zabz/dsh-engine
NODE=/home/zabz/.local/node/bin/node
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
LOG=/home/zabz/dsh-switch-$STAMP.log
ANCHOR=$HOME_DSH/profiles/node_modules
ANCHOR_ASIDE=$HOME_DSH/profiles/node_modules.pre-0.2.1-$STAMP
UNIT=dsh-engine.service

say() { echo "[$(date -u +%H:%M:%SZ)] $*" | tee -a "$LOG"; }

say "switch-worker v2; unit $UNIT; log $LOG"
say "backup: $(ls -dt /home/zabz/dsh-backup-* 2>/dev/null | head -1)"
say "fingerprints: engine $($NODE "$ENGINE/node_modules/@deepseek-ai/dsh/lib/bin.js" --version 2>&1 | tail -1), anchor $([ -e "$ANCHOR" ] && ls -1 "$ANCHOR" | wc -l || echo 0) entries"

# ── 1. stop the unit (systemd owns it) ─────────────────────────────────────────────────────────────
sudo -n systemctl stop "$UNIT" || { say "REFUSED: could not stop $UNIT"; exit 2; }
sleep 4
systemctl is-active --quiet "$UNIT" && { say "REFUSED: unit still active"; sudo -n systemctl start "$UNIT"; exit 2; }
say "unit stopped; port $(ss -ltn 2>/dev/null | grep -q ':3099 ' && echo still-bound || echo free)"

# ── 2. anchor aside ────────────────────────────────────────────────────────────────────────────────
[ -e "$ANCHOR" ] && mv "$ANCHOR" "$ANCHOR_ASIDE" && say "anchor -> $(basename "$ANCHOR_ASIDE")"

# ── 3. install ─────────────────────────────────────────────────────────────────────────────────────
cd "$REPO" || { say "no repo"; exit 2; }
DSH_CONFIG_ROOT=$HOME_DSH DSH_HOME=$HOME_DSH DSH_STATE_HOME=$HOME_DSH \
  "$NODE" tools/install-engine.mjs --version 0.2.1-rc.2 --accept-session-format-upgrade 2>&1 | tee -a "$LOG" | tail -20
RC=${PIPESTATUS[0]}
say "install-engine exit: $RC"

if [ "$RC" -ne 0 ]; then
  say "INSTALL FAILED — restoring the anchor and starting the unit again"
  [ -e "$ANCHOR_ASIDE" ] && mv "$ANCHOR_ASIDE" "$ANCHOR"
  sudo -n systemctl start "$UNIT"
  sleep 20
  say "unit now: $(systemctl is-active "$UNIT"), http $(curl -s -o /dev/null -w '%{http_code}' --max-time 6 http://127.0.0.1:3099/ || echo 000)"
  exit 4
fi

# ── 4. start the unit and watch it ────────────────────────────────────────────────────────────────
say "starting $UNIT"
sudo -n systemctl start "$UNIT"
for i in $(seq 1 18); do
  sleep 5
  S=$(systemctl is-active "$UNIT")
  C=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 http://127.0.0.1:3099/ || true)
  say "  t+$((i*5))s state=$S http=${C:-none}"
  [ "$S" = "active" ] && [ "${C:-000}" != "000" ] && break
done

# ── 5. verify ─────────────────────────────────────────────────────────────────────────────────────
VER=$("$NODE" "$ENGINE/node_modules/@deepseek-ai/dsh/lib/bin.js" --version 2>&1 | tail -1)
CODE=$(curl -s -o /dev/null -w '%{http_code}' --max-time 8 http://127.0.0.1:3099/ || true)
say "version=$VER http=${CODE:-none} restarts=$(systemctl show "$UNIT" -p NRestarts --value) anchor=$([ -e "$ANCHOR" ] && echo "rebuilt ($(ls -1 "$ANCHOR" | wc -l) entries)" || echo absent)"
if [ "$VER" != "0.2.1-rc.2" ]; then
  say "THE NEW ENGINE IS NOT RUNNING — see the log and journalctl -u $UNIT"
  exit 5
fi
say "DONE"
