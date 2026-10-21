#!/usr/bin/env bash
# decision-deliver-cron.sh — pace the owner's decision queue, one question at a time.
#
# THE PACING IS THE POINT. He asked for "a question one at a time" and "don't overdo it or
# spam me" (2026-09-22). A queue of 97 answered all at once is the same failure as a queue
# of 97 answered never: it spends his attention and teaches him to ignore the channel. So
# this runs often and sends almost never -- the deliverer itself enforces max 6/day, a
# 60-minute gap and his waking hours (owner raised it from 2 on 2026-10-21), and this wrapper adds the one thing the deliverer
# cannot know: whether the owner has approved the queue's content.
#
# THE APPROVAL SENTINEL
#   ~/.decision-deliver/APPROVED  exists  -> live sends
#   absent                                -> dry runs, logged, nothing leaves
#
# The owner's rule is that nothing outbound goes without his per-message yes. Triage and
# composition can be autonomous; the moment of sending cannot. One file, one decision, and
# removing it stops every send without a deploy.

set -uo pipefail

# THE OWNER SET THIS, 2026-10-21 01:53Z: "it doesnt have to be limited at two a day.
# Probably the limit should be 6 a day." It lives here rather than in the crontab line
# because cron-wrap reads its payload from $2 and an env assignment there is not base64 --
# measured 2026-10-21, cron-wrap refused the line outright and nothing ran.
export DECISION_DELIVER_MAX_PER_DAY="${DECISION_DELIVER_MAX_PER_DAY:-6}"

BIN="/root/bin"
STATE_DIR="/root/.decision-deliver"
APPROVED="$STATE_DIR/APPROVED"
LOG="$STATE_DIR/deliver-cron.log"
PY="/usr/bin/python3"
mkdir -p "$STATE_DIR"

now="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

if [ -f "$APPROVED" ]; then
  MODE="--send"
  tag="LIVE"
else
  MODE=""
  tag="DRY"
fi

out="$("$PY" "$BIN/decision-deliver.py" $MODE 2>&1)"
rc=$?

# A dry run writes one WOULD_SEND row per tick, which would grow without bound; the
# deliverer records it so the next preview is different, which is what we want for a real
# send and NOT what we want for a preview. So a dry tick that says WOULD_SEND is logged
# and then forgotten, keeping the preview stable until approval.
if [ "$tag" = "DRY" ] && printf '%s' "$out" | grep -q '^WOULD_SEND'; then
  "$PY" - <<'PY' >>"$LOG" 2>&1
import sqlite3, os, pathlib
p = pathlib.Path(os.environ.get("HOME", "/root")) / ".decision-deliver" / "state.db"
c = sqlite3.connect(p, timeout=10)
c.execute("DELETE FROM send WHERE verdict='WOULD_SEND'")
c.commit()
PY
fi

printf '%s %-4s rc=%d %s\n' "$now" "$tag" "$rc" \
  "$(printf '%s' "$out" | tr '\n' ' ' | cut -c1-300)" >> "$LOG"

# Bound the log by rotating at 1 MB rather than growing forever.
if [ -f "$LOG" ] && [ "$(stat -c %s "$LOG")" -gt 1000000 ]; then
  mv -f "$LOG" "$LOG.1"
fi

exit 0
