#!/usr/bin/env bash
# Tell the owner when the company's API has stopped, and recover it once.
#
# WHY THIS EXISTS, measured 2026-09-30. `secretary-api.service` has
# StartLimitBurst=3 within StartLimitIntervalSec=900 on purpose -- installed
# 2026-09-28 after 27.9 minutes of downtime in one day, to stop a service that
# cannot become healthy from being restarted without end. That reasoning is sound
# and this script does NOT weaken it.
#
# What it fixes is the failure MODE. When the burst is exhausted the unit goes to
# `failed` and systemd stops trying, and NOTHING noticed: no alert, no recovery,
# no visible symptom until something downstream timed out. A session that deployed
# five fixes in an afternoon hit it, and the company was down until a human ran
# `systemctl reset-failed`. A control whose trip is silent is half a control.
#
# WHAT IT DOES
#   1. If the unit is failed, reset it and start it -- but at most once per hour,
#      recorded in a state file. A genuine crash loop therefore recovers once, and
#      if it fails again the unit stays failed and visible rather than consuming
#      the machine.
#   2. Tell the owner, through the app's own notification queue, so the message
#      goes out on the one channel he reads. Every existing owner-SMS rule applies
#      there, so this cannot become a sender of its own.
#
# Read-only otherwise. Safe to run at any time, by anyone, as often as you like.
set -uo pipefail

UNIT="${WATCHDOG_UNIT:-secretary-api.service}"
STATE="${WATCHDOG_STATE:-/home/zabz/.api-watchdog-state}"
COOLDOWN_SEC="${WATCHDOG_COOLDOWN_SEC:-3600}"
HEALTH_URL="${WATCHDOG_HEALTH_URL:-http://127.0.0.1:8002/health}"
NOTIFY_URL="${WATCHDOG_NOTIFY_URL:-http://127.0.0.1:8002/tools/notify-owner}"
STAMP="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

log() { echo "$STAMP $*"; }

state="$(systemctl is-active "$UNIT" 2>/dev/null || true)"
failed="$(systemctl is-failed "$UNIT" 2>/dev/null || true)"

if [[ "$state" == "active" ]]; then
  log "ok: $UNIT is active"
  exit 0
fi

# ONLY a unit that systemd itself gave up on. `inactive` is a unit that is stopped on
# purpose -- by a human, by a deploy, or because a unit of that name does not exist -- and
# reviving it would undo an intentional stop. Measured 2026-09-30: the first version
# treated `inactive` as a failure and tried to start a unit that was not even installed.
if [[ "$failed" != "failed" && "$state" != "failed" ]]; then
  log "ok: $UNIT is '$state' and not failed - nothing to recover or report"
  exit 0
fi

log "attention: $UNIT is '$state' (failed='$failed')"

# ── the cooldown, so a crash loop cannot be turned into a restart bomb ────────
now="$(date -u +%s)"
last=0
have_last=0
if [[ -s "$STATE" ]]; then
  read -r last < "$STATE" 2>/dev/null || last=0
  [[ "$last" =~ ^[0-9]+$ ]] || last=0
  (( last > 0 )) && have_last=1
fi
# An ABSENT or empty state file means this has never recovered before, so the cooldown does
# not apply. Reading it as 0 made `now - 0` a 56-year elapsed time, which is the opposite
# of the intent and would have been invisible: measured 2026-09-30 on the first run.
if (( have_last )); then
  elapsed=$(( now - last ))
else
  elapsed=$COOLDOWN_SEC
  log "no previous recovery on record - the cooldown does not apply"
fi

recovered="no"
if (( elapsed >= COOLDOWN_SEC )); then
  log "recovering: last recovery was ${elapsed}s ago (cooldown ${COOLDOWN_SEC}s)"
  systemctl reset-failed "$UNIT" 2>/dev/null || true
  if systemctl start "$UNIT" 2>/dev/null; then
    echo "$now" > "$STATE"
    sleep 20
    now_state="$(systemctl is-active "$UNIT" 2>/dev/null || true)"
    log "after start: $UNIT is '$now_state'"
    recovered="$now_state"
  else
    log "start FAILED; leaving it failed and visible"
    recovered="start-failed"
  fi
else
  log "NOT recovering: only ${elapsed}s since the last recovery (cooldown ${COOLDOWN_SEC}s)."
  log "  The unit stays failed on purpose rather than being restarted in a loop."
fi

# ── tell him, on the channel he actually reads ───────────────────────────────
# Only when the API is up enough to hold a message. If it is not, this attempt
# fails silently on purpose: the state file above is the durable record, and the
# last thing this script should do is invent a second way to reach his phone.
body="The company API ($UNIT) was down: state '$state', failed '$failed'. Recovery attempt: $recovered."

# THE RECORD COMES FIRST, and it is kept HERE rather than in the app -- because the app is
# what is down. Measured 2026-09-30: the first version's only durable record was the
# cooldown timestamp, and its only way to tell anyone was a POST to the very API that had
# stopped. That is circular, and it fails in exactly the scenario the script exists for.
# An append-only line costs nothing and survives whatever happens next.
INCIDENTS="${WATCHDOG_INCIDENTS:-/home/zabz/.api-watchdog-incidents.log}"
printf '%s  unit=%s state=%s failed=%s recovered=%s\n' \
  "$STAMP" "$UNIT" "$state" "$failed" "$recovered" >> "$INCIDENTS" 2>/dev/null \
  && log "recorded in $INCIDENTS" \
  || log "WARNING: could not write the incident record to $INCIDENTS"

# BOTH ENCODINGS, form first. `/tools/notify-owner` declares `message: str = Form(...)`,
# so a JSON body gets 422 however right the field name is -- the contract in the code
# comments says JSON and the deployed route says form. `textsend._notify_post` learned
# this already; the watchdog repeated the mistake and would have reported a working app
# as unreachable. A 422 on a required field creates nothing, so trying both cannot notify
# twice. And `-w '%{http_code}'` prints 000 on failure with exit 0, so `|| echo 000` only
# ever APPENDED to it, giving 000000 -- take the last three characters.
notify() {
  local payload="$1" ctype="$2" code
  code="$(curl -s -o /dev/null -m 20 -w '%{http_code}' \
    -X POST "$NOTIFY_URL" -H "Content-Type: $ctype" \
    -d "$payload" 2>/dev/null || true)"
  printf '%s' "${code: -3}"
}

http="$(notify "message=$body" 'application/x-www-form-urlencoded')"
if [[ "$http" == "200" ]]; then
  log "told the owner through the app's queue (form-encoded, HTTP 200)"
else
  alt="$(notify "{\"message\": \"$body\"}" 'application/json')"
  if [[ "$alt" == "200" ]]; then
    log "told the owner through the app's queue (JSON, HTTP 200)"
  else
    log "could not reach the app's queue (form HTTP $http, json HTTP $alt) - the state file is the record"
  fi
fi

exit 0
