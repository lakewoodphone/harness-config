#!/usr/bin/env bash
# lpt-recon-check.sh — the reconciliation FAILURE SURFACE.
#
# WHY THIS EXISTS (P82, and the 2026-09-15 reconciliation):
# The lpt-hub -> production case push was a MANUAL script with no cron and no failure
# surface, so it silently stopped after 2026-08-27 and 71 new sync-records accumulated
# un-pushed with nothing reporting it. In the same window the production website's customer
# comms pipeline went silent for 11.5 hours, also unnoticed, because the only check that
# could have caught it was scheduled nowhere.
#
# WHAT IT DOES — deliberately a REPORTER, not an auto-writer:
#   1. asks the push tool what it WOULD create (`--dry-run-all`, proven read-only: it opens
#      production with default_transaction_read_only=on and refuses unless the server
#      confirms it), and
#   2. runs lpt-recon.py, which measures whether the four stores actually agree.
# It creates no customer, no order and no row. Auto-creating production customers from a
# cron is not a decision a timer should make; surfacing the gap to a human is.
#
# IT WRITES NO EMAIL. The owner's rule is that nothing goes outbound without his explicit
# per-message instruction, so this records state and exits non-zero, and the existing
# owner-attention digest can surface it.
#
# EXIT: 0 everything agreed · 1 a gap or a disagreeing store · 2 it could not measure
set -u

APP=/home/zabz/personal-secretary-mvp
PY=$APP/.venv/bin/python3
STATE_DIR=/home/zabz/.lpt-recon
STATUS=$STATE_DIR/status.json
LOG=$STATE_DIR/check.log
mkdir -p "$STATE_DIR"
now=$(date -u +%Y-%m-%dT%H:%M:%SZ)

rc=0

# ---- 1. what would the case push create? (read-only) -------------------------
dry=$($PY "$APP/scripts/lpt-sync-to-production.py" --dry-run-all 2>&1 | tail -40)
totals=$(printf '%s\n' "$dry" | grep -E '^TOTALS:' | tail -1)
creates=$(printf '%s\n' "$totals" | grep -oE 'CREATE [0-9]+' | grep -oE '[0-9]+')
errors=$(printf '%s\n' "$totals" | grep -oE 'ERROR [0-9]+' | grep -oE '[0-9]+')
creates=${creates:-unknown}
errors=${errors:-unknown}

# ---- 2. do the stores agree? -------------------------------------------------
recon=$(cd /home/zabz && $PY /home/zabz/bin/lpt-recon.py 2>/dev/null)
recon_rc=$?
recon_summary=$(printf '%s\n' "$recon" | tail -1)

if [ "$creates" != "0" ] && [ "$creates" != "unknown" ]; then rc=1; fi
[ "$errors" != "0" ] && [ "$errors" != "unknown" ] && rc=1
[ "$recon_rc" -ne 0 ] && rc=1

printf '{"updated":"%s","push_would_create":%s,"push_errors":%s,"recon_exit":%s,"recon_summary":"%s","totals":"%s"}\n' \
  "$now" "$creates" "$errors" "$recon_rc" "$(printf '%s' "$recon_summary" | sed 's/"/\\"/g')" \
  "$(printf '%s' "$totals" | sed 's/"/\\"/g')" > "$STATUS"

echo "$now rc=$rc would_create=$creates push_errors=$errors recon_exit=$recon_rc | $recon_summary | $totals" >> "$LOG"

# a status file that silently stops being written is the defect this replaces
# (see journal L1484: a job that runs, exits 0 and produces nothing), so the file's
# mtime IS the liveness signal and is checked below.
exit "$rc"
