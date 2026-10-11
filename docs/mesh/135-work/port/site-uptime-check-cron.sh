#!/bin/bash
# site-uptime-check-cron.sh — Deterministic hourly uptime check for the critical endpoints.
#
# WHY: The agent-driven `seed_site_uptime_check` work order failed 63x/week purely because the
# trailing "review" goal step is never claimed by an agent. Actual services have NOT been down —
# the failures were execution-mechanism failures, not outages. This cron does the real check
# deterministically. It does NOT auto-SMS the owner (owner-alert SMS requires explicit
# per-message approval); it records, exits non-zero when something is down, and lets the estate's
# cron ledger be the reader.
#
# PORTED TO THE CLOUD AUTHORITY 2026-10-11 (workstream 135). Three changes, each deliberate:
#
#  1. THE IPv4 PIN. `local_api` was `http://localhost:8002/health`. On the cloud box `localhost`
#     can resolve to `::1` first, and the API listens on 127.0.0.1 ONLY. The cutover's own record
#     (H3407 §6) is that this exact mismatch answered 502 through the tunnel for 40 minutes while a
#     healthy API was listening: cloudflared dialled `::1` and nothing was there. So the local leg
#     is pinned to `http://127.0.0.1:8002/health` and curl is told `--ipv4`. This is not cosmetic —
#     an unpinned check reports the API down when it is up, which is its own kind of lie.
#
#  2. THE LOG IS /var/log SYSLOG, NOT $HOME. On the cloud box the job runs as root and the office
#     convention of `$HOME/site-uptime-check.log` would put an unrotated file in `/root`. This
#     version logs through `logger` into the system journal (self-rotating, readable with
#     `journalctl -t site-uptime-check`), AND the per-run ledger row that `cron-wrap.sh` writes to
#     `/root/.cron-status/runs.tsv` carries the first 160 chars of stderr. If `logger` is missing,
#     the script still fails correctly — the ledger row is the durable record either way.
#
#  3. IT EXITS NON-ZERO WHEN AN ENDPOINT IS DOWN. The office version always exited 0 (its
#     `down` count went only into the log), so the ledger could not distinguish an outage from a
#     clean hour. That is precisely the "runs, exits 0, produces nothing" defect family. rc=0 means
#     every endpoint answered 200; rc=1 means at least one did not; rc=2 means the check itself
#     could not run.
#
# LOCK guard prevents overlapping runs.
set -uo pipefail

LOG_FILE="${SITE_UPTIME_LOG:-/var/log/site-uptime-check.log}"
LOCK_FILE="${SITE_UPTIME_LOCK:-/run/site-uptime-check.lock}"
LOCAL_API="${SITE_UPTIME_LOCAL_API:-http://127.0.0.1:8002/health}"

log() {
  local line="[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] $1"
  printf '%s\n' "$line"
  # Best effort: the journal if we can, a file under /var/log if we cannot. Never $HOME.
  if command -v logger >/dev/null 2>&1; then
    logger -t site-uptime-check -- "$1" 2>/dev/null || true
  fi
  if [ -w "$(dirname "$LOG_FILE")" ] || [ -w "$LOG_FILE" ]; then
    printf '%s\n' "$line" >> "$LOG_FILE" 2>/dev/null || true
  fi
}

# The lock path must exist as a directory we can write; fall back to /tmp rather than dying.
if ! exec 9>"$LOCK_FILE" 2>/dev/null; then
  LOCK_FILE="/tmp/site-uptime-check.lock"
  exec 9>"$LOCK_FILE" || { log "FAULT: cannot open any lock file"; exit 2; }
fi
if ! flock -n 9; then
  log "SKIPPED: previous run still in progress"
  exit 0
fi

# '|' separator to avoid clashing with ':' inside https:// URLs.
# The local leg uses $LOCAL_API so the IPv4 pin is one explicit, greppable place.
checks=(
  "local_api|$LOCAL_API|secretary_api"
  "tunnel|https://ai.abletelsolutions.com/health|cloudflare_tunnel"
  "lpt_site|https://lakewoodphoneandtech.com/|lpt_website"
  # The app is advertised, so a silent outage costs money. /api/health returns 503 when Postgres is
  # unreachable and 200 only when it can serve data, so HTTP 200 is a complete signal here.
  "chumash|https://chumash.lakewoodphoneandtech.com/api/health|chumash_timeline"
)

declare -i down=0
for entry in "${checks[@]}"; do
  name="${entry%%|*}"; rest="${entry#*|}"
  url="${rest%%|*}"; label="${rest#*|}"
  # --ipv4: see the IPv4 pin note above. --max-time 15 keeps the whole job bounded.
  http=$(curl -4 -s --max-time 15 -o /dev/null -w "%{http_code}" "$url" 2>/dev/null)
  if [ "$http" = "200" ]; then
    log "OK $name ($label) HTTP $http"
  else
    down+=1
    log "DOWN $name ($label) http=$http URL=$url"
    # stderr reaches the cron ledger's stderr column; stdout does not.
    echo "DOWN $name ($label) http=$http" >&2
  fi
done

if [ "$down" -gt 0 ]; then
  log "RESULT: $down endpoint(s) down at $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
  exit 1
fi
log "RESULT: all endpoints up at $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
exit 0
