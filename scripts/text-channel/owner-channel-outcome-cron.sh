#!/usr/bin/env bash
# owner-channel-outcome-cron.sh — run the outcome monitor and MAKE THE FAILURE ACT.
#
# WHY A WRAPPER AND NOT JUST THE CRON LINE
# ----------------------------------------
# Measured 2026-10-21: this estate has a long history of monitors that wrote a finding
# into a log nobody read. `text-health.py` reported 20/20 OK through a two-day owner
# blackout; `/var/log/cfo-shift.log` stayed 0 bytes while the CFO engine was gated for
# 17.5 h a day. A reading that produces a line is not a control.
#
# So a FAIL here does two things:
#   1. appends one JSON line to the run history (so drift is visible over time), and
#   2. raises a WAKE FLAG with a stable subject, which is the estate's mechanism for
#      starting a real repair session with nobody at a keyboard.
#
# `wake.py flag` always exits 0 and prints filed/deduped/suppressed/capped. Suppressed
# is a real decision (dedup, cooldown, cap, pause file) and never an error; `error:` is
# a failure and is written to the log so a broken store is not mistaken for quiet.
#
# Deliberately NOT an SMS: this is machinery reporting on machinery, which is exactly
# what the owner's own suppression list says must never reach his phone. The flag costs
# a session; a text costs his attention. Wrong currency for this class.

set -uo pipefail

BIN="/root/bin"
MON="$BIN/owner-channel-outcome-monitor.py"
LOG_DIR="/root/.owner-text"
HIST="$LOG_DIR/outcome-history.jsonl"
LOG="$LOG_DIR/outcome-cron.log"
PY="/usr/bin/python3"

mkdir -p "$LOG_DIR"

now="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

# One JSON report. Never abort the wrapper on a monitor exception -- a crashed monitor
# must itself become a finding, not a silent gap in the history.
report="$("$PY" "$MON" --json 2>>"$LOG")"
rc=$?
if [ $rc -ne 0 ] || [ -z "$report" ]; then
  echo "$now MONITOR FAILED rc=$rc (no report); see $LOG" >> "$LOG"
  "$PY" "$BIN/wake.py" flag \
    --subject "owner-channel-monitor-broken:$(date -u +%Y-%m-%d)" \
    --prompt "The owner-channel outcome monitor exited rc=$rc and produced no report. Repair /root/bin/owner-channel-outcome-monitor.py so it runs, then verify it reports the real queue state. Log: $LOG" \
    --kind text-channel --source owner-channel-outcome --priority high >> "$LOG" 2>&1
  exit 0
fi

# Keep the history bounded by rotating at ~2 MB rather than growing without end.
if [ -f "$HIST" ] && [ "$(stat -c %s "$HIST")" -gt 2000000 ]; then
  mv -f "$HIST" "$HIST.1"
fi
printf '%s\n' "$report" | "$PY" -c '
import json,sys
d=json.load(sys.stdin)
d["_logged_at"]=sys.argv[1]
print(json.dumps(d,sort_keys=True))
' "$now" >> "$HIST"

failed="$("$PY" -c '
import json,sys
d=json.load(sys.stdin)
print(",".join(d.get("failed") or []))
' <<<"$report")"

if [ -z "$failed" ]; then
  echo "$now OK all checks" >> "$LOG"
  exit 0
fi

echo "$now FAIL $failed" >> "$LOG"

# One flag per DAY, not per check and not per tick: the subject is the dedup key, and a
# 30-minute cron would otherwise file 48 rows a day for one condition. The prompt names
# the failing checks so the woken session starts from the measurement, not from a guess.
"$PY" "$BIN/wake.py" flag \
  --subject "owner-channel-blackout:$(date -u +%Y-%m-%d)" \
  --prompt "The owner text channel is failing outcome checks: $failed. Run /root/bin/owner-channel-outcome-monitor.py for the details, then repair the CAUSE of each failing check -- do not silence the check. Read /root/code/harness-config/docs/text-channel/STATE-2026-10-21.md first: it records three separate silent blackouts found on 2026-10-20 and the decisions already made. Repairs go in /opt/company (the running tree) or /root/bin; publish any change to a running script by atomic rename. Prove each fix with the monitor going green for that check." \
  --kind text-channel --source owner-channel-outcome --priority high >> "$LOG" 2>&1

exit 0
