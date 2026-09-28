#!/bin/bash
# wake-fanout.sh - keep SEVERAL shifts in flight, each in its own isolated state.
#
# WHY THIS EXISTS. The owner, 2026-09-28: "There's no reason to limit how much you could do per day
# ... if there's legitimate reasons to wake more than 12 times, then why not? I want to be really
# powerful and autonomous and able to actually finish projects really fast and move on."
#
# THE MEASURED BOTTLENECK WAS NEVER POLICY. `wake-dispatch.sh` named these files FIXED and shared:
#     STAGE=/home/zabz/.sms-inbox/wake-stage      (claim.json, prompt.txt, wake-out.txt, wake-ssh.log)
#     LOCK=/home/zabz/.sms-inbox/wake-dispatch.lock
# so it held a single-instance lock for the WHOLE length of a shift (a measured 6-13 minutes), cron
# fired it every 5 minutes, and every tick in between logged "another dispatcher holds ... skipping
# this tick". Measured 2026-09-28 19:26Z: 13 rows waiting, 1 in flight, 3 fan-out attempts all
# released instantly with in_flight still 1. The cap on throughput was an accident of two filenames.
#
# FIRST ATTEMPT WAS WRONG, and the log proved it: three shifts were launched and all three exited in
# a second. Reading the child log showed why - each call saw its own lock held, because one lock
# serves one shift. So this version gives every concurrent shift WHAT THE DISPATCHER ALREADY SUPPORTS:
#     WAKE_STAGE_DIR   per-instance staging (the dispatcher uses $STAGE for claim.json, prompt.txt,
#                      wake-out.txt, wake-ssh.log - all FIXED names inside it)
#     WAKE_LOCK_FILE   per-instance single-instance guard (so one shift cannot collide with another,
#                      while still preventing two shifts for the same row)
#     WAKE_LOG         deliberately SHARED, so the day's release count the caps are computed from
#                      stays one file. Appends of a few hundred bytes are atomic enough on Linux.
# The worker side needs nothing: the dispatcher already names the remote prompt and output files
# `wake-prompt-<id>-<token>.txt` / `wake-out-<id>-<token>.txt` with a per-run token, so concurrent
# shifts cannot overwrite each other on the desktop.
#
# EVERY EXISTING GUARD STILL APPLIES, because the dispatcher itself is unmodified: one row per claim,
# the store's lease, the daily backstop, the spend ceiling, the pause file, and the refusal to raise
# a flag from inside a woken session.
#
# CONCURRENCY IS BOUNDED ON PURPOSE - integration is the real ceiling on a fleet, so the default is
# small and it is one line to change.
#
# USAGE   wake-fanout.sh [--target N] [--max N] [--dry-run]
# ENV     WAKE_FANOUT_TARGET (3)  shifts to keep in flight
#         WAKE_FANOUT_MAX    (5)  hard ceiling for one run
#         WAKE_DISPATCH      (/home/zabz/bin/wake-dispatch.sh)

set -u
PROG=$(basename "$0")
DISPATCH=${WAKE_DISPATCH:-/home/zabz/bin/wake-dispatch.sh}
TARGET=${WAKE_FANOUT_TARGET:-3}
MAX=${WAKE_FANOUT_MAX:-5}
PAUSE_FILE=${WAKE_PAUSE_FILE:-$HOME/.sms-inbox/WAKE_PAUSED}
WAKE_CLI=${WAKE_CLI:-$HOME/bin/wake.py}
WAKE_LOG=${WAKE_LOG:-$HOME/.sms-inbox/wake-dispatch.log}
INST_ROOT=${WAKE_INSTANCE_ROOT:-$HOME/.sms-inbox/wake-instances}
FANOUT_LOG=${WAKE_FANOUT_LOG:-$HOME/.sms-inbox/wake-fanout.log}
DRY_RUN=0

while [ $# -gt 0 ]; do
  case "$1" in
    --target) TARGET=$2; shift 2 ;;
    --max) MAX=$2; shift 2 ;;
    --dry-run|-n) DRY_RUN=1; shift ;;
    *) echo "$PROG: unknown argument $1" >&2; exit 2 ;;
  esac
done

say() { printf '%s\n' "$*"; }
note() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >>"$FANOUT_LOG" 2>/dev/null || true; }

count_state() {
  python3 - "$WAKE_CLI" "$1" <<'PY' 2>/dev/null || echo 0
import json, subprocess, sys
try:
    out = subprocess.run(["python3", sys.argv[1], "stats", "--json"],
                         capture_output=True, text=True, timeout=60).stdout
    print(int((json.loads(out).get("states") or {}).get(sys.argv[2]) or 0))
except Exception:
    print(0)
PY
}

if [ -e "$PAUSE_FILE" ]; then
  note "paused ($PAUSE_FILE exists) - starting nothing"
  [ "$DRY_RUN" = 1 ] && say "dry-run: paused"
  exit 0
fi

mkdir -p "$INST_ROOT" 2>/dev/null || true

BEFORE=$(count_state claimed)
QUEUED=$(count_state new)
say "fanout: in flight $BEFORE, target $TARGET, ceiling $MAX, waiting $QUEUED"
note "start in_flight=$BEFORE target=$TARGET max=$MAX waiting=$QUEUED"

started=0
while :; do
  CUR=$(count_state claimed)
  LEFT=$(count_state new)
  if [ "$CUR" -ge "$TARGET" ]; then
    say "fanout: $CUR shift(s) in flight, at target - starting nothing more"
    note "stop at target (in_flight=$CUR)"
    break
  fi
  if [ "$LEFT" -le 0 ]; then
    say "fanout: nothing waiting - nothing to start"
    note "stop: queue empty"
    break
  fi
  if [ "$started" -ge "$MAX" ]; then
    say "fanout: reached this run's ceiling of $MAX"
    note "stop at max ($started started)"
    break
  fi

  if [ "$DRY_RUN" = 1 ]; then
    say "dry-run: would start a shift (in flight $CUR, waiting $LEFT)"
    started=$((started + 1))
    continue
  fi

  # ONE INSTANCE = ONE DIRECTORY + ONE LOCK. The shift writes its intermediates there and nowhere
  # else, so two shifts cannot read each other's claim or prompt.
  INST="$INST_ROOT/inst-$$-$started"
  mkdir -p "$INST" 2>/dev/null || true
  (
    WAKE_STAGE_DIR="$INST" \
    WAKE_LOCK_FILE="$INST/lock" \
    WAKE_LOG="$WAKE_LOG" \
    "$DISPATCH" >>"$INST/run.log" 2>&1
  ) &
  pid=$!
  started=$((started + 1))

  # Wait for this shift to actually CLAIM something before counting it, so the loop is driven by the
  # store rather than by optimism. A dispatcher that finds nothing to release exits at once.
  claimed=0
  for _ in $(seq 1 25); do
    sleep 1
    if [ "$(count_state claimed)" -gt "$CUR" ]; then claimed=1; break; fi
    if ! kill -0 "$pid" 2>/dev/null; then break; fi
  done
  if [ "$claimed" = 1 ]; then
    say "fanout: shift #$started (pid $pid) CLAIMED a row; in flight now $(count_state claimed)"
    note "started shift #$started pid=$pid claimed=yes in_flight=$(count_state claimed)"
  else
    say "fanout: shift #$started (pid $pid) did not claim (nothing eligible, or gated) - stopping"
    note "started shift #$started pid=$pid claimed=no; stopping"
    rm -rf "$INST" 2>/dev/null
    break
  fi
done

AFTER=$(count_state claimed)
say "fanout: started $started this run; in flight $AFTER"
note "end started=$started in_flight=$AFTER"
exit 0
