#!/bin/bash
# wake-fanout.sh - keep N shifts in flight, counted by PROCESS, within an explicit ceiling.
#
# WHAT WENT WRONG IN MY FIRST TWO VERSIONS, measured 2026-09-28 19:54Z:
#   * SIX `wake-dispatch.sh` processes were alive against WAKE_FANOUT_TARGET=5. Two had been running
#     15.5 minutes; four more had started in the previous 30 seconds.
#   * `wake.py claim` answered **`database is locked`** while four dispatchers polled and heartbeated the
#     same sqlite store every 60 s, and one heartbeat process sat in uninterruptible sleep.
# THE CAUSE: the loop counted a row as "in flight" only once the STORE said `claimed`. Between launching
# a dispatcher and its claim landing there is a window of seconds, and every pass of the loop that
# landed inside that window concluded there was room and launched another. Polling to close the window
# was not enough - a slow claim, a gated claim, or a claim taken by a different dispatcher all let it
# through. Counting the STORE is not the same as counting the PROCESSES, and the PROCESSES are what
# consume the machine and contend for the database.
#
# THE FIX: count our own live dispatch processes, take the LARGER of that and the store's claimed count,
# and never start more than (target - that). Plus an absolute ceiling on processes. A store count alone
# can never again authorise an overshoot.
#
# WHY EACH CONCURRENT SHIFT NEEDS ITS OWN STATE (unchanged, and still true): `wake-dispatch.sh` names
# its staging dir and its lock FIXED and shared - `~/.sms-inbox/wake-stage/{claim.json,prompt.txt,
# wake-out.txt,wake-ssh.log}` and `wake-dispatch.lock` - so one lock serves one shift and a second call
# held the lock, saw it held, and exited in a second (measured: three launches, all three gone in under
# a second). The dispatcher ALREADY supports:
#     WAKE_STAGE_DIR   per-instance staging
#     WAKE_LOCK_FILE   per-instance single-instance guard
#     WAKE_LOG         deliberately SHARED, so the day's release count the caps are computed from stays
#                      one file (appends of a few hundred bytes are atomic enough on Linux)
# and the worker needs nothing: the dispatcher already names the remote prompt and output files
# `wake-prompt-<id>-<token>.txt` / `wake-out-<id>-<token>.txt` with a per-run token.
#
# EVERY EXISTING GUARD STILL APPLIES, because the dispatcher itself is unmodified: one row per claim,
# the store's lease, the daily backstop, the spend ceiling, the pause file, and the refusal to raise a
# flag from inside a woken session.
#
# Usage: wake-fanout.sh [--target N] [--max N] [--dry-run]
# Env:   WAKE_FANOUT_TARGET (3) shifts to keep in flight
#        WAKE_FANOUT_MAX    (5) hard ceiling on dispatch processes
#        WAKE_DISPATCH      (/home/zabz/bin/wake-dispatch.sh)

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

# --- RUNWAY-AWARE CADENCE (2026-10-14) ---------------------------------------
# A balance-aware control that bounds dollars but not the RATE is half a control. The cap is
# derived as balance / runway_days by wake-balance.py; at a 5.70 balance that is ~1.90/day, which
# at the measured 0.0639 USD per release still buys ~29 releases - and 29 releases with three
# dispatchers in flight is a different load, and a different burn, from one. This is the hook that
# makes the surviving releases cost less per unit of wall-clock, and it is ALSO defence in depth:
# it reads the same state file even when the cron wrapper (wake-budget-env.sh) is bypassed.
# It only ever LOWERS the target. WAKE_BUDGET_THROTTLE=0 restores the unthrottled behaviour.
BUDGET_FILE=${WAKE_BUDGET_FILE:-$HOME/.sms-inbox/wake-budget.json}
BUDGET_TIER=${WAKE_BUDGET_TIER:-}
if [ -z "$BUDGET_TIER" ] && [ -r "$BUDGET_FILE" ]; then
  BUDGET_TIER=$(python3 -c 'import json,sys
try:
    print(json.load(open(sys.argv[1])).get("tier") or "")
except Exception:
    print("")' "$BUDGET_FILE" 2>/dev/null || true)
fi
if [ "${WAKE_BUDGET_THROTTLE:-1}" != 0 ] && [ -n "$BUDGET_TIER" ] && [ "$BUDGET_TIER" != "ok" ]; then
  LOW_TARGET=${WAKE_BUDGET_LOW_TARGET:-1}
  LOW_MAX=${WAKE_BUDGET_LOW_MAX:-2}
  [ "$TARGET" -gt "$LOW_TARGET" ] && TARGET=$LOW_TARGET
  [ "$MAX" -gt "$LOW_MAX" ] && MAX=$LOW_MAX
  say "fanout: budget tier=$BUDGET_TIER - cadence throttled to target=$TARGET max=$MAX"
  note "budget tier=$BUDGET_TIER: cadence throttled to target=$TARGET max=$MAX ($BUDGET_FILE)"
fi

# A LOCKED STORE IS NOT AN EMPTY STORE. Retry, and return -1 for "could not read" - never 0, because a
# zero from an unreadable store is how a full queue looks idle.
count_state() {
  python3 - "$WAKE_CLI" "$1" <<'PY' 2>/dev/null || echo -1
import json, subprocess, sys
last = None
for _ in range(3):
    try:
        out = subprocess.run(["python3", sys.argv[1], "stats", "--json"],
                             capture_output=True, text=True, timeout=90).stdout
        d = json.loads(out)
        if not d.get("ok", True):
            last = "not-ok"
            continue
        print(int((d.get("states") or {}).get(sys.argv[2]) or 0))
        raise SystemExit(0)
    except SystemExit:
        raise
    except Exception as exc:
        last = type(exc).__name__
print(-1)
PY
}

count_priority_new() {
  # How many HIGH-priority rows are waiting to be released RIGHT NOW. Read through
  # `wake list --state new --json`, and skip anything still inside its not_before cooldown so
  # a gated row cannot inflate the target.
  python3 - "$WAKE_CLI" <<'PY' 2>/dev/null || echo -1
import datetime, json, subprocess, sys
def now():
    return datetime.datetime.now(datetime.timezone.utc)
for _ in range(3):
    try:
        out = subprocess.run(["python3", sys.argv[1], "list", "--state", "new", "--json"],
                             capture_output=True, text=True, timeout=90).stdout
        d = json.loads(out or "[]")
        rows = d if isinstance(d, list) else (d.get("rows") or d.get("items") or [])
        n = 0
        for r in rows:
            if str(r.get("priority")) != "high":
                continue
            nb = r.get("not_before")
            if nb:
                try:
                    t = datetime.datetime.fromisoformat(str(nb).replace("Z", "+00:00"))
                    if t.tzinfo is None:
                        t = t.replace(tzinfo=datetime.timezone.utc)
                    if t > now():
                        continue
                except Exception:
                    pass
            n += 1
        print(n)
        raise SystemExit(0)
    except SystemExit:
        raise
    except Exception:
        pass
print(-1)
PY
}

# COUNT ONLY REAL DISPATCHERS. `pgrep -f "wake-dispatch.sh"` matches any command line CONTAINING that
# string - including the ssh probe that asked the question, and including a fan-out whose own argument
# list mentions it. Measured 2026-09-28: a dry run reported "processes 1" with no dispatcher running,
# and the live probe reported 2 with one. An inflated count is not harmless: it makes the loop believe
# shifts are in flight that are not, so it never reaches its target - a stall in the opposite
# direction. So match the ARGUMENT SHAPE instead: a bash process whose first argument is the dispatcher.
count_procs() {
  ps -eo args= 2>/dev/null | grep -c '^bash /home/zabz/bin/wake-dispatch.sh' || true
}

if [ -e "$PAUSE_FILE" ]; then
  note "paused ($PAUSE_FILE exists) - starting nothing"
  [ "$DRY_RUN" = 1 ] && say "dry-run: paused"
  exit 0
fi
mkdir -p "$INST_ROOT" 2>/dev/null || true

# PUBLISH THE CEILINGS THIS LOOP IS ACTUALLY GATING ON. Measured 2026-10-13: the release cap
# that really stopped the operation was 150/day, set as WAKE_MAX_PER_DAY on this one crontab
# line, while `autonomy-status.sh` - run by a human in a shell that carries neither override -
# printed "releases today : 150 of 500 backstop" with an empty caps-in-force line. The system
# had refused every release for 3h44m and the status tool could not show it, so the owner's
# "is it alive" question had no honest answer available. wake.py is still the ONLY source of
# the numbers; this loop only RECORDS the reading, in the environment where the numbers are
# true, so a reader outside cron can see it. Written here rather than in wake-dispatch.sh on
# purpose: the dispatcher is the live release path and, when a cap is in force, it is exactly
# the process that does not run - so a record written there is missing precisely when it is
# needed. This runs every minute, including the ticks that start nothing.
python3 - "$WAKE_CLI" "${WAKE_CAPS_FILE:-$HOME/.sms-inbox/wake-caps-effective.json}" <<'PY' 2>/dev/null || true
import datetime, json, os, subprocess, sys
try:
    raw = subprocess.run(["python3", sys.argv[1], "stats", "--json"],
                         capture_output=True, text=True, timeout=90).stdout
    d = json.loads(raw or "{}")
    caps = d.get("caps") or {}
    json.dump({
        "at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "written_by": "wake-fanout.sh",
        "caps": caps,
        "caps_in_force": d.get("caps_in_force") or [],
        "released_today": d.get("released_today"),
        "spend_today_usd": d.get("spend_today_usd"),
        "env": {k: os.environ.get(k)
                for k in ("WAKE_MAX_PER_DAY", "WAKE_MAX_USD_PER_DAY")},
    }, open(sys.argv[2], "w"), sort_keys=True)
    open(sys.argv[2], "a").write("\n")
except Exception:
    pass
PY

STORED=$(count_state claimed)
PROCS=$(count_procs)
QUEUED=$(count_state new)
if [ "$STORED" -lt 0 ] || [ "$QUEUED" -lt 0 ]; then
  say "fanout: the store could not be read (locked?) - starting nothing this tick"
  note "abort: store unreadable (claimed=$STORED new=$QUEUED procs=$PROCS)"
  exit 0
fi

# --- lpt-hub stale-rebase pre-flight (item 274; auto-heal item 288) -------------
# The shared lpt-hub clone is what lpt-sync shifts read and commit to. When a shift
# starts a rebase in it, hits a conflict and dies, .git/rebase-merge is left behind with
# no live git process: the clone sits on a detached HEAD and EVERY in-clone truth reading
# is bogus (item 209 measured a bogus C01=8/C06=2/C07=2) until a later shift happens to
# notice. lpt-hub-rebase-guard.sh (item 242) detects that in one command and can clear it
# with --fix, but item 274 wired only the READ-ONLY --check, so the pre-flight said
# STALE_REBASE and left the clone broken for the next shift (5th occurrence 2026-10-01,
# item 288). Ask at the gate, before any dispatcher is started, and CLEAR it: the guard's
# --fix refuses a LIVE rebase and (without --force) a recent one, so this never aborts a
# rebase out from under a running git, and no operator is needed. A disabled switch
# (WAKE_REBASE_AUTOFIX=0) restores report-only. The heal is a repair, not a dispatcher
# start, so it runs under --dry-run too. Quiet when the clone is clean, so a cron tick
# with nothing wrong stays silent on stdout; the reading always lands in the fan-out log.
REBASE_GUARD=${WAKE_REBASE_GUARD:-$HOME/bin/lpt-hub-rebase-guard.sh}
REBASE_REPO=${WAKE_REBASE_REPO:-/home/zabz/repos/lpt-hub}
REBASE_AUTOFIX=${WAKE_REBASE_AUTOFIX:-1}
if [ -x "$REBASE_GUARD" ] && [ -e "$REBASE_REPO/.git" ]; then
  RBOUT=$(timeout 30 "$REBASE_GUARD" --check "$REBASE_REPO" 2>&1 || true)
  note "preflight rebase: ${RBOUT:-guard-failed}"
  case "$RBOUT" in
    STALE_REBASE*)
      say "fanout: $RBOUT"
      if [ "$REBASE_AUTOFIX" = 1 ]; then
        RBHEAL=$(timeout 60 "$REBASE_GUARD" --fix "$REBASE_REPO" 2>&1 || true)
        note "preflight rebase autofix: ${RBHEAL:-guard-failed}"
        case "$RBHEAL" in
          REBASE_ABORTED*)
            RB2=$(timeout 30 "$REBASE_GUARD" --check "$REBASE_REPO" 2>&1 || true)
            note "preflight rebase recheck: ${RB2:-guard-failed}"
            say "fanout: $RBHEAL"
            say "fanout: $RB2"
            ;;
          *)
            say "fanout: rebase autofix refused/failed: ${RBHEAL:-guard-failed} (left for a human)"
            ;;
        esac
      else
        say "fanout: autofix disabled (WAKE_REBASE_AUTOFIX=0); clear it with $REBASE_GUARD --fix $REBASE_REPO"
      fi
      ;;
    *)
      [ "$DRY_RUN" = 1 ] && say "fanout: $RBOUT"
      ;;
  esac
fi

# DO NOT START A DISPATCHER WHEN NOTHING CAN BE CLAIMED. Measured 2026-09-30: the fan-out started a
# dispatcher every five minutes through a 55-minute stretch in which no row was claimable, and each time
# the dispatcher correctly exited having done nothing. The preserved evidence from one of those ticks:
#   {"ok": true, "row": null, "blocked_by": "row-gates",
#    "gated": {"not_before": 10, "night_quiet": 0, "source_hourly_cap": 4, "new_rows": 14}}
# Ask before starting, and say which gate is in force. Covers the not_before gate; a tick gated only by a
# source cap still costs one start - a known gap, recorded rather than ignored.
if [ "$DRY_RUN" != 1 ]; then
  NCOUT=$(python3 "${WAKE_NEXTCLAIM:-/home/zabz/bin/wake-nextclaim.py}" --json 2>/dev/null || true)
  NCZERO=$(printf '%s' "$NCOUT" | python3 -c 'import json,sys
try:
    print(1 if json.load(sys.stdin).get("claimable_now", 0) == 0 else 0)
except Exception:
    print("")' 2>/dev/null)
  if [ "$NCZERO" = "1" ]; then
    say "fanout: nothing claimable now - starting nothing this tick"
    note "skip: nothing claimable; procs=$PROCS gate=$NCOUT"
    exit 0
  fi
fi

IN_FLIGHT=$STORED
[ "$PROCS" -gt "$IN_FLIGHT" ] && IN_FLIGHT=$PROCS

# A WAITING HIGH-PRIORITY ROW OPENS EXTRA SLOTS, UP TO THE CEILING.
#
# Measured 2026-09-30, and it is the reason the owner's text sat unanswered for minutes: the
# fan-out kept a FIXED number of shifts in flight (target 5) and started nothing more once it
# was reached, whatever was waiting behind it. The claim query orders high before normal, but
# that ordering can only choose among rows the gate actually lets through -- so a high-priority
# row queued behind five project shifts, each of which may run for 36 minutes. High priority
# has to mean something AT THE GATE, not only in the claim order.
#
# One extra slot per waiting high-priority row, never above the ceiling: the machine bound is
# unchanged, and the owner's own text stops waiting behind housekeeping.
HIGH_WAITING=$(count_priority_new)
if [ "$HIGH_WAITING" -gt 0 ] && [ "$TARGET" -lt "$MAX" ]; then
  NEW_TARGET=$((TARGET + HIGH_WAITING))
  [ "$NEW_TARGET" -gt "$MAX" ] && NEW_TARGET=$MAX
  say "fanout: $HIGH_WAITING high-priority row(s) waiting - target $TARGET -> $NEW_TARGET (ceiling $MAX)"
  note "raise target: high_waiting=$HIGH_WAITING target=$TARGET -> $NEW_TARGET max=$MAX"
  TARGET=$NEW_TARGET
fi

say "fanout: in flight $IN_FLIGHT (store $STORED, processes $PROCS), target $TARGET, ceiling $MAX, waiting $QUEUED"
note "start in_flight=$IN_FLIGHT store=$STORED procs=$PROCS target=$TARGET max=$MAX waiting=$QUEUED"

started=0
while :; do
  STORED=$(count_state claimed)
  PROCS=$(count_procs)
  QUEUED=$(count_state new)
  if [ "$STORED" -lt 0 ] || [ "$QUEUED" -lt 0 ]; then
    note "stop: store unreadable mid-run (claimed=$STORED new=$QUEUED)"
    break
  fi
  CUR=$STORED
  [ "$PROCS" -gt "$CUR" ] && CUR=$PROCS

  if [ "$CUR" -ge "$TARGET" ]; then
    say "fanout: $CUR in flight, at target - starting nothing more"
    note "stop at target (in_flight=$CUR procs=$PROCS)"
    break
  fi
  if [ "$PROCS" -ge "$MAX" ]; then
    say "fanout: $PROCS dispatch process(es) alive, at ceiling $MAX - starting nothing more"
    note "stop at process ceiling (procs=$PROCS)"
    break
  fi
  if [ "$QUEUED" -le 0 ]; then
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
    say "dry-run: would start a shift (in flight $CUR, waiting $QUEUED)"
    started=$((started + 1))
    continue
  fi

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

  # Wait for the CLAIM to land or for the child to exit. Both endings are informative, and the in-flight
  # count now includes this new process, so a slow claim can never authorise a second start.
  claimed=0
  for _ in $(seq 1 30); do
    sleep 1
    NOW_STORED=$(count_state claimed)
    if [ "$NOW_STORED" -gt "$STORED" ]; then claimed=1; break; fi
    if ! kill -0 "$pid" 2>/dev/null; then break; fi
  done
  if [ "$claimed" = 1 ]; then
    say "fanout: shift #$started (pid $pid) CLAIMED; processes now $(count_procs)"
    note "started shift #$started pid=$pid claimed=yes procs=$(count_procs)"
  else
    # KEEP THE EVIDENCE, AND SAY WHY IT FAILED. This used to be `rm -rf "$INST"`, which deleted
    # wake-ssh.log, claim.json and prompt.txt - the only record of WHY a claim failed. Measured
    # 2026-09-30: eleven consecutive ticks failed to claim over 55 minutes and left nothing behind.
    # A failed instance is now MOVED ASIDE, never deleted here; cleanup is by age, separately.
    FAILED_DIR="$INST_ROOT/../wake-failed"
    mkdir -p "$FAILED_DIR" 2>/dev/null || true
    kept="left in place"
    if mv "$INST" "$FAILED_DIR/$(basename "$INST")-$(date -u +%Y%m%dT%H%M%SZ)" 2>/dev/null; then
      kept="kept in $FAILED_DIR"
    fi
    gate=$(python3 "${WAKE_NEXTCLAIM:-/home/zabz/bin/wake-nextclaim.py}" --json 2>/dev/null || true)
    say "fanout: shift #$started (pid $pid) did not claim - stopping this run ($kept)"
    say "fanout: gate: ${gate:-unknown}"
    note "started shift #$started pid=$pid claimed=no; stopping; evidence=$kept; gate=${gate:-unknown}"
    break
  fi
done

say "fanout: started $started this run; processes $(count_procs)"
note "end started=$started procs=$(count_procs)"
exit 0
