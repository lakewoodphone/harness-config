#!/bin/bash
# site-uptime-check-cron.sh — Deterministic hourly uptime check for the 3
# critical endpoints (mirrors prior finance-sync cron precedent).
#
# WHY: The agent-driven `seed_site_uptime_check` work order failed 63x/week
# purely because the trailing "review" goal step is never claimed by an agent
# (goal swept stale by lifecycle_sweep). Actual services have NOT been down —
# the failures are execution-mechanism failures, not outages. This cron does
# the real check deterministically and writes to a log; it does NOT auto-SMS
# the owner (owner-alert SMS requires explicit per-message approval). A human
# or the agent can read the log / a separate alert path handles emergencies.
#
# Installed via crontab (hourly):
#   7 * * * * /home/zabz/personal-secretary-mvp/scripts/site-uptime-check-cron.sh
#
# LOCK guard prevents overlapping runs.
set -uo pipefail

LOG_FILE="$HOME/site-uptime-check.log"
LOCK_FILE="$HOME/.site-uptime-check.lock"

log() { echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] $1" >> "$LOG_FILE"; }

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] SKIPPED: previous run still in progress" >> "$LOG_FILE"
  exit 0
fi

# Using '|' separator to avoid clashing with ':' inside https:// URLs
checks=(
  "local_api|http://localhost:8002/health|secretary_api"
  "tunnel|https://ai.abletelsolutions.com/health|cloudflare_tunnel"
  "lpt_site|https://lakewoodphoneandtech.com/|lpt_website"
  # Added 2026-10-05: the app is about to be advertised, so a silent outage
  # now costs money. /api/health returns 503 when Postgres is unreachable and
  # 200 only when it can serve data, so HTTP 200 is a complete signal here.
  "chumash|https://chumash.lakewoodphoneandtech.com/api/health|chumash_timeline"
)

declare -i down=0
for entry in "${checks[@]}"; do
  name="${entry%%|*}"; rest="${entry#*|}"
  url="${rest%%|*}"; label="${rest#*|}"
  http=$(curl -s --max-time 15 -o /dev/null -w "%{http_code}" "$url" 2>/dev/null)
  if [ "$http" = "200" ]; then
    log "OK $name ($label) HTTP $http"
  else
    down+=1
    log "DOWN $name ($label) http=$http URL=$url"
  fi
done

if [ "$down" -gt 0 ]; then
  log "RESULT: $down endpoint(s) down at $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
else
  log "RESULT: all endpoints up at $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
fi
