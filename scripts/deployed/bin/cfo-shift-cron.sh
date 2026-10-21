#!/usr/bin/env bash
# cfo-shift-cron.sh — run ONE bounded CFO shift on a clock, safely.
#
# WHY THIS EXISTS, measured 2026-10-06.
#
# `cfo-shift.py` is the bounded, resumable unit of work that cleans up the owner's books:
# it reads the scoreboard, resolves clusters it can prove, applies the confident ones to
# the accounting ledger, and files at most ONE owner question. Its own docstring says it
# "is what a woken session runs", and the wake system used to feed it.
#
# That feed has run dry. The work ledger for project `cfo` holds 0 todo rows (31 done,
# 3 dropped, 1 blocked = 343), so the keepalive wake claims nothing, reports
# NOTHING-LEFT, and never reaches a shift. Measured that day: six identical empty cfo
# wakes at 15:24, 15:51, 16:46, 17:45, 18:16 and 18:46Z. The root cause of the empty
# wakes is filed separately as housekeeping item 423 ("project-keepalive ignores ledger
# revisit_at and wakes on the work_remaining boolean alone") and is NOT fixed here.
#
# Meanwhile the actual backlog is 1,704 unexplained transactions of 5,932, and the
# program's own projection is 568 shifts = 568 days at one shift a day. In practice,
# closer to never, because the shifts stopped happening at all.
#
# So this wrapper runs the shift on a clock, exactly as `cfo-scoreboard.py` already does
# for the same stated reason (its own cron comment: "this must run on a clock, not only
# on demand"). It is a deliberate duplicate of an intended mechanism, not a replacement
# for fixing it: if item 423 is fixed and the wake loop resumes, this stays harmless,
# because the shift is idempotent and the lock below keeps the two from overlapping.
#
# THE FOUR GUARDS, and what each is for:
#   1. SINGLE-FLIGHT. flock. `cfo-shift.py` has no internal lock, and two shifts writing
#      owner questions or checkpointing at once is how a resumed shift corrupts its own
#      state. A second run exits immediately; it does not queue.
#   2. DISK. Before any write, ask `cfo_backup.space_for_backup` whether there is room for
#      a ledger backup. Measured motive: `/` is at 91% and this host has filled twice
#      (journal P2553, P2799). `cfo-shift.py` would already refuse the backup itself, but
#      failing here means we never even start the research that precedes it.
#   3. A DAILY CEILING on shifts, counted from the shift log. A crash-looping wrapper
#      must not be able to run 700 shifts in a day, because each shift does paid research
#      (web search + model) and the owner pays for it.
#   4. BOUNDED BATCH. `--limit` and `--seconds` are both passed explicitly, so a single
#      run cannot outlast its cron slot or chew through the whole backlog unattended.
#
# IT NEVER TEXTS ANYONE. The shift's only owner-facing output is at most one row in the
# decision queue, through `owner-queue.py add`. The mouth is `cfo-ask.py`, which is a
# separate program on its own schedule, and it is what decides whether he is asked.
#
# Env (all optional):
#   CFO_SHIFT_CRON_MAX_PER_DAY   shifts allowed per UTC day        (default 14)
#   CFO_SHIFT_CRON_LIMIT         clusters per shift                (default 20)
#   CFO_SHIFT_CRON_SECONDS       wall-clock bound per shift        (default 600)
set -uo pipefail

HOME_DIR="$HOME"
BIN="$HOME_DIR/bin"
PY="${PY:-/usr/bin/python3}"
LOG="${LOG:-$HOME_DIR/.cfo/shift-cron.log}"
LOCK="${LOCK:-/tmp/cfo-shift-cron.lock}"
SHIFT_LOG="${CFO_SHIFT_LOG:-$HOME_DIR/.cfo/shifts.jsonl}"
LEDGER="${CFO_ACCT_DB:-$HOME_DIR/accounting-data/live/accounting.db}"
BACKUP_DIR="${CFO_BACKUP_DIR:-$HOME_DIR/.cfo/backups}"

MAX_PER_DAY="${CFO_SHIFT_CRON_MAX_PER_DAY:-14}"
LIMIT="${CFO_SHIFT_CRON_LIMIT:-20}"
SECONDS_BOUND="${CFO_SHIFT_CRON_SECONDS:-600}"

mkdir -p "$(dirname "$LOG")"
exec >>"$LOG" 2>&1
ts() { date -u '+%Y-%m-%dT%H:%M:%SZ'; }

# ── 1. single-flight ────────────────────────────────────────────────────────
exec 9>"$LOCK"
if ! flock -n 9; then
  echo "$(ts) another shift holds the lock; exiting without doing anything"
  exit 0
fi

# ── 3. the daily ceiling, counted from the shift log's own record ───────────
# Counted from the log rather than a counter file: the log is the durable record of what
# actually ran, and a counter file that drifts from it would be a second source of truth.
TODAY="$(date -u '+%Y-%m-%d')"
RAN_TODAY=0
if [ -s "$SHIFT_LOG" ]; then
  RAN_TODAY="$("$PY" - "$SHIFT_LOG" "$TODAY" <<'PY'
import json, sys
path, day = sys.argv[1], sys.argv[2]
n = 0
try:
    for line in open(path, encoding="utf-8", errors="replace"):
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
            if str(row.get("at", ""))[:10] != day:
                continue
            # Only CRON work counts against the burn ceiling. A row with no `origin` predates the
            # field and is counted: we cannot prove it was not a cron shift, and counting it is the
            # conservative choice. Measured 2026-10-16: the ceiling refused the loop from 03:00Z
            # because a session's diagnostic runs had pushed the day to 20/14.
            if str(row.get("origin", "cron")) != "cron":
                continue
            n += 1
        except Exception:
            continue
except OSError:
    pass
print(n)
PY
)"
fi
# A HARD CRASH USED NOT TO COUNT. The ceiling above is read from shifts.jsonl, which
# cfo-shift.py appends only when it finishes -- so a shift that died mid-run left no row,
# and a crash loop could consume all 48 daily slots while the ceiling reported 0. Measured
# 2026-10-21 by an independent audit. An attempt marker is written BEFORE the work, so a
# crash costs its slot exactly like a completed run. The ceiling takes the larger of the
# two counts, so an existing day with completions and no attempts still counts correctly.
ATTEMPT_LOG="${CFO_SHIFT_ATTEMPT_LOG:-$HOME_DIR/.cfo/shift-attempts.log}"
STARTED_TODAY=0
if [ -s "$ATTEMPT_LOG" ]; then
  STARTED_TODAY="$(grep -c "^$TODAY" "$ATTEMPT_LOG" 2>/dev/null || echo 0)"
fi
if [ "${STARTED_TODAY:-0}" -gt "${RAN_TODAY:-0}" ]; then
  RAN_TODAY="$STARTED_TODAY"
fi
if [ "${RAN_TODAY:-0}" -ge "$MAX_PER_DAY" ]; then
  echo "$(ts) daily ceiling reached: $RAN_TODAY/$MAX_PER_DAY slots used on $TODAY (completed=${RAN_TODAY} started=${STARTED_TODAY}); skipping"
  exit 0
fi

# ── 2. the disk guard, asked before any research is paid for ────────────────
SPACE="$("$PY" "$BIN/cfo_backup.py" --ledger "$LEDGER" --backup-dir "$BACKUP_DIR" \
         --check-space-only 2>&1)"
SPACE_RC=$?
echo "$(ts) space: $SPACE"
if [ "$SPACE_RC" -ne 0 ]; then
  echo "$(ts) refusing to run a shift: no room for a ledger backup"
  exit 0
fi

# ── 4. the shift itself, bounded on both axes ───────────────────────────────
echo "$(ts) running shift $((RAN_TODAY + 1))/$MAX_PER_DAY today (limit=$LIMIT clusters, ${SECONDS_BOUND}s)"
T0=$(date +%s)
printf '%s %s\n' "$(date -u '+%Y-%m-%d')" "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" >> "$ATTEMPT_LOG" 2>/dev/null || true
CFO_SHIFT_ORIGIN=cron "$PY" "$BIN/cfo-shift.py" --once --apply --limit "$LIMIT" \
    --seconds "$SECONDS_BOUND"
RC=$?
T1=$(date +%s)
echo "$(ts) shift finished rc=$RC in $((T1-T0))s"
exit "$RC"
