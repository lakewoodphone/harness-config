#!/usr/bin/env bash
# ============================================================
# Hetzner backup freshness monitor — run from the secretary
# Checks both Hetzner boxes' restic backup freshness every 6h.
# On staleness (>26h) it alerts the CEO via the secretary API
# so the failure is never silent.
#
# Install (secretary crontab):
#   0 */6 * * * /home/zabz/scripts/monitor-hetzner-backups.sh
# It logs itself to $HOME/monitor-hetzner-backups.log, so cron needs no redirect
# (/var/log is root:syslog 775; a user cron cannot create files there).
# ============================================================
set -u

LOG="${LOG:-$HOME/monitor-hetzner-backups.log}"
exec >>"$LOG" 2>&1
STAMP=$(date '+%Y-%m-%d %H:%M:%S')
ALERTED=/tmp/hetzner-backup-alerted  # state file to avoid spamming CEO every 6h

check_box() {
  local NAME="$1" ALIAS="$2"
  local OUT
  OUT=$(ssh -o BatchMode=yes -o ConnectTimeout=10 "$ALIAS" "/root/backup-status-check.sh" 2>&1)
  local RC=$?
  echo "[$STAMP] $NAME: rc=$RC — $OUT"
  if [ $RC -ne 0 ]; then
    return 1
  fi
  return 0
}

# Collect failures
FAIL=""
check_box "waze-mdm-01" "hetzner"   || FAIL="$FAIL waze-mdm-01"
check_box "lpt-apps-01" "lpt-apps"  || FAIL="$FAIL lpt-apps-01"

if [ -n "$FAIL" ]; then
  # Only alert once per stale event (clear state file on OK)
  if [ ! -f "$ALERTED" ]; then
    MSG="BACKUP STALENESS ALERT: Hetzner boxes stale >26h:$(echo $FAIL). Run: ssh hetzner|lpt-apps '/root/backup-status-check.sh'. Check R2 restic repo health."
    curl -s -m 20 -X POST http://localhost:8002/ceo/chat \
      -H "Content-Type: application/json" \
      -d "{\"message\": \"$MSG\"}" >/dev/null 2>&1
    echo "[$STAMP] ALERTED CEO for:$FAIL"
    touch "$ALERTED"
  else
    echo "[$STAMP] still stale ($FAIL) — already alerted, waiting for recovery"
  fi
  exit 1
else
  rm -f "$ALERTED"
  echo "[$STAMP] all backups fresh"
  exit 0
fi

