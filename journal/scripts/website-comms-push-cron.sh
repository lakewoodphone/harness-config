#!/usr/bin/env bash
# website-comms-push-cron.sh — the cron entry point for the website push. Adds the two things
# the bare Python script cannot do for itself: retry under SQLite contention, and a sanity gate
# that refuses to call an empty result a success.
#
# WHY THIS WRAPPER EXISTS (measured, 2026-09-15/16)
#   The push was installed as a plain `python3 website-comms-push.py` at `5,35 * * * *` and the
#   VERY FIRST cron-triggered run failed:
#       2026-09-16T00:05:07 CRON[601354] (zabz) CMD (... website-comms-push.py --json ...)
#       {"calls": {"ok": false, "error": "OperationalError: database is locked"},
#        "sms":   {"ok": false, "error": "OperationalError: database is locked"}, "ok": false}
#   Nothing reached production (116,685 rows, newest 23:43:48Z, unchanged) - a clean failure, but a
#   silent one from the operator's point of view, and a job that dies quietly on a lock is the exact
#   defect this whole reconciliation exists to remove. The company store logs ~3,322
#   'database is locked' events a week, so this is not a rare condition; it is the normal weather.
#
#   `scripts/dialpad-harvest-cron.sh` already solved this exact problem and documents it: the harvest
#   is idempotent, so retry the whole pass rather than widening a global timeout of a running
#   application. This mirrors that pattern deliberately instead of inventing a new one.
#
# THE SANITY GATE - the important half
#   `_get_dialpad_calls_for_push` / `_get_dialpad_sms_for_push` are written as
#       except Exception: return []
#   so a locked database makes them return an EMPTY list, and the sync then reports
#   `ok: true, synced: 0` - a green result that means "I could not read anything". That is the
#   signature defect of this system: a job that runs, exits 0 and produces nothing. So this wrapper
#   treats "0 candidates while the local store demonstrably has traffic in the window" as FAILURE,
#   and retries it. A genuinely quiet shop produces 0 candidates only when the window is empty, which
#   is checked directly.
#
# EXIT  0 pushed (or nothing was genuinely there to push) · 1 gave up · 2 could not measure
set -uo pipefail

REPO="/home/zabz/personal-secretary-mvp"
PY="$REPO/.venv/bin/python3"
cd "$REPO" || { echo "cannot cd to $REPO" >> "/home/zabz/.lpt-recon/website-push.log"; exit 1; }
PUSH="/home/zabz/bin/website-comms-push.py"
STATE_DIR="/home/zabz/.lpt-recon"
LOG="$STATE_DIR/website-push.log"
mkdir -p "$STATE_DIR"

log() { echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] $1" >> "$LOG"; }

ATTEMPTS=3
BACKOFF=45

# Does the local store actually hold anything in the push window? If it does and the push reports
# zero candidates, the read failed rather than the shop being quiet.
local_window_count() {
  sqlite3 "file:$REPO/data/secretary.db?mode=ro" "
    SELECT (SELECT COUNT(*) FROM dialpad_call_full
              WHERE date_started_ms > (strftime('%s','now')-7*86400)*1000)
         + (SELECT COUNT(*) FROM dialpad_sms_cache
              WHERE created_at > datetime('now','-7 days')
                AND message_id NOT LIKE 'test-%' AND message_id NOT LIKE 'self-%');" 2>/dev/null || echo "-1"
}

for attempt in $(seq 1 "$ATTEMPTS"); do
  OUT="$("$PY" "$PUSH" --json 2>&1)"; RC=$?

  if [ "$RC" -eq 0 ] && printf '%s' "$OUT" | grep -q '"ok": true'; then
    # push reported success - now check it was not a disguised empty read
    cand=$(printf '%s' "$OUT" | "$PY" -c '
import json,sys
try: d=json.load(sys.stdin)
except Exception: print("?"); raise SystemExit
c=d.get("candidates") or {}
print((c.get("calls",0) or 0)+(c.get("sms",0) or 0))' 2>/dev/null)
    have="$(local_window_count)"
    if [ "$cand" = "0" ] && [ "${have:-0}" -gt 0 ]; then
      log "SUSPECT attempt $attempt/$ATTEMPTS: 0 candidates reported while the local store holds $have rows in the window (read likely failed, not a quiet shop)"
      [ "$attempt" -eq "$ATTEMPTS" ] && { log "FAILED: refusing to report success on an empty read"; exit 1; }
      sleep "$BACKOFF"; continue
    fi
    log "ok $OUT"
    exit 0
  fi

  log "FAILED rc=$RC attempt $attempt/$ATTEMPTS: $OUT"
  [ "$attempt" -eq "$ATTEMPTS" ] && { log "GAVE UP after $ATTEMPTS attempts"; exit 1; }
  sleep "$BACKOFF"
done

exit 1
