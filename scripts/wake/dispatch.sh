#!/usr/bin/env bash
# =============================================================================
# wake dispatch — the RELEASE half of the wake system.
#
# WHAT THIS IS. Something on the authority files a flag (a `wake` row). This
# script, run from cron on secratary, turns exactly ONE flag into a real DSH
# session on the always-on desktop and brings the result back:
#
#   scp  prompt file  ->  ZABZ-TECH:C:\Users\ezabz\bin\wake-prompt-<id>-<run>.txt
#   ssh  ZABZ-TECH 'powershell -File ...\wake-run.ps1 -PromptFile ... -OutFile ...'
#        (the desktop runs `dsh --profile headless "<task>"`, answers, exits)
#   scp  the out-file back
#   close the wake row: `finish` on success, `finish --failed` on any failure
#
# HOP VERIFIED END TO END 2026-09-18 (`WAKE_HOP_OK`, exit 0, row closed `done`).
# This script does not redesign that hop; it hardens it:
#
#   1. SINGLE INSTANCE. Two dispatchers at once is the difference between one
#      session and two. `flock -n` on a lock file, and the loser exits quietly.
#   2. REAP FIRST. A dispatcher that died mid-release leaves a `claimed` row;
#      reap at the top of every run returns expired leases to `new`.
#   3. ONE ROW, LEASED. `claim --lease-seconds` claims exactly one row, and the
#      lease is heartbeated every WAKE_HEARTBEAT_SEC while the session runs, so
#      a long session is never reaped and double-run.
#   4. HARD TIMEOUT. The ssh hop is bounded by `timeout -k`; the desktop runner
#      bounds itself too, so a killed ssh cannot leave an orphan dsh behind. Both
#      bounds are sized ABOVE one full child turn (TURN_CAP), because a bound
#      below a real turn kills sessions that are still working and then records
#      the kill as a lost hop (measured 2026-09-20: wake #8/#10 truncated at
#      840 s mid-sentence, reported "ssh hop failed (rc=1)").
#   5. ALWAYS CLOSE THE ROW. Every exit path — success, timeout, ssh failure,
#      scp failure, an unexpected signal — ends in `finish` or `finish --failed`.
#      An EXIT trap closes a claim even if this script dies.
#   6. QUIET ON THE QUIET PATH. Nothing to release -> nothing on stdout, exit 0,
#      so cron does not email on every tick.
#
# The safety envelope lives in wake.py (dedup, cooldown, per-day cap, per-source
# cap, night gate, kill switch, lease, attempt cap, cost cap). The checks here
# are deliberate belt-and-braces on the two that cost money if the store is
# wrong: the daily cap and the kill switch.
#
# WHAT IT MUST NEVER DO. It never files work. A row is only filed by something
# that knows there IS work; releasing on a timer would burn a session every five
# minutes to be told there is nothing to do (CONTRACT §2).
#
# USAGE
#   dispatch.sh --dry-run     the whole decision path, no ssh/scp/dsh, no writes
#   dispatch.sh               the real thing (cron)
#
# Owned by stream W2 (CONTRACT §6). The frozen contract is scripts/wake/CONTRACT.md.
# =============================================================================
set -u
set -o pipefail

PROG=${0##*/}

# --- output helpers, DEFINED BEFORE THE CONFIGURATION THAT USES THEM ----------
# The cap-consistency block below calls `err` and `say` when it cannot read the
# ceilings from wake.py, and warns through `log` when an override drifts from the
# store. Those definitions used to sit ~100 lines further down, so that refusal
# wrote nothing to the audit log and said nothing on stdout: a gate that refuses
# silently is the exact failure this system exists to prevent (measured
# 2026-10-02 while wiring the three outcomes). Nothing here depends on anything
# below it, so moving it up changes no number and no behaviour except that the
# words now actually appear.
DRY_RUN=0
now_iso() { date -u +%Y-%m-%dT%H:%M:%SZ; }
today_utc() { date -u +%Y-%m-%d; }
log() {
  # A dry run must not touch the audit log: the log is what the daily cap is
  # counted from, and a rehearsal must not be mistaken for a release.
  [ "${DRY_RUN:-0}" = 1 ] && return 0
  printf '%s %s\n' "$(now_iso)" "$*" >>"$LOG" 2>/dev/null || true
}
err() { printf '%s: %s\n' "$PROG" "$*" >&2; log "ERROR $*"; }
say() { printf '%s\n' "$*"; }

# --- runtime configuration (env-overridable; contract names kept verbatim) ---
PY=${WAKE_PYTHON:-python3}
WAKE_CLI=${WAKE_CLI:-$HOME/bin/wake.py}          # the §5 CLI this codes against
# Retires QUEUED project packets whose project has no shift-startable ledger work
# (LEDGER item 180). Called in step 3b below, right after `reap`.
DEAD_FLAGS=${WAKE_DEAD_FLAGS:-$HOME/bin/dead-project-flags.py}
DESKTOP=${WAKE_DESKTOP:-zabz-tech-ts}            # always-on desktop, over the mesh
REMOTE_DIR_WIN=${WAKE_REMOTE_DIR:-'C:\Users\ezabz\bin'}
REMOTE_RUNNER=${WAKE_RUNNER:-${WAKE_REMOTE_RUNNER:-$REMOTE_DIR_WIN'\wake-run.ps1'}}
# One staging name per release (row id + UTC stamp + pid), not the fixed
# wake-prompt.txt/wake-out.txt of v0. Measured on the authority 2026-09-18: two
# dispatchers overlapped (wake #2 was still running when #3 was claimed 93 s
# later) and the shared names let one session read and overwrite the other's
# bytes - #2's recorded outcome is the task text echoed back, not an answer. The
# lock below makes that impossible from two dispatchers; unique names make it
# impossible from anything else too (a hand-run ssh, a dispatcher on another
# host). WAKE_REMOTE_PROMPT / WAKE_REMOTE_OUT still override verbatim.
REMOTE_PROMPT_OVERRIDE=${WAKE_REMOTE_PROMPT:-}
REMOTE_OUT_OVERRIDE=${WAKE_REMOTE_OUT:-}
LOG=${WAKE_LOG:-$HOME/.sms-inbox/wake-dispatch.log}
STAGE=${WAKE_STAGE_DIR:-$HOME/.sms-inbox/wake-stage}
LOCK=${WAKE_LOCK_FILE:-$HOME/.sms-inbox/wake-dispatch.lock}
PAUSE_FILE=${WAKE_PAUSE_FILE:-$HOME/.sms-inbox/WAKE_PAUSED}
# THE CEILINGS LIVE IN EXACTLY ONE PLACE: wake.py's DEFAULT_MAX_PER_DAY (release
# count) and DEFAULT_MAX_USD_PER_DAY (USD spend), published by `wake.py stats
# --json`. This file keeps NO literal copy - a second copy is exactly how the live
# gate and the store came to disagree (2026-09-20: wake.py was set to 4/day while
# this file released on 8, and the looser value won). An explicit env override still
# wins for the belt-and-braces gate below; the store remains the enforcer either way.
LEASE=${WAKE_LEASE_SEC:-1200}
HEARTBEAT=${WAKE_HEARTBEAT_SEC:-60}
# The remote child-turn cap. A fanout CHILD turn is bounded by
# MESH_CHILD_TIMEOUT_MS, raised to 1800000 ms (30 min) on 2026-09-18 precisely
# because a real agent turn runs 8-25 minutes. A session that legitimately uses
# the whole cap must not be killed by US, so the cap is the FLOOR of the whole
# envelope below, not an aspiration.
TURN_CAP=${WAKE_TURN_CAP_SEC:-1800}
# Outer bound on the ssh hop: the runner's own bound plus room for the runner to
# taskkill the tree, drain a few hundred KB of pipes, write its verdict, and for
# scp to bring that verdict back.
TIMEOUT=${WAKE_TIMEOUT_SEC:-$((TURN_CAP + 360))}
OUTCOME_BYTES=${WAKE_OUTCOME_BYTES:-600}
SSH_CMD=${WAKE_SSH_CMD:-ssh}
SCP_CMD=${WAKE_SCP_CMD:-scp}
CALLSIGN=${WAKE_CALLSIGN:-wake-dispatch@$(hostname -s 2>/dev/null || echo unknown)}
# --- NODE SELECTION (items 144 and 642) --------------------------------------
# ONE release, ONE node, chosen from an ORDERED list. An entry is `host:kind`;
# kind is `desktop` (Windows PowerShell runner over ssh) or `local` (this host,
# the Linux runner, no hop). `WAKE_NODE=desktop|authority|local` still pins one
# candidate for a manual run.
#
# WHY AN ORDER AND A PROBE. Item 642: the dispatcher used to hard-pin every
# release to zabz-tech-ts with no fallback, and when that desktop slept the whole
# fleet produced nothing for 32 hours (133 consecutive rc=1 SSH refusals in
# wake-dispatch.log). A target that is merely CONFIGURED is not a fallback: the
# dispatcher now probes each candidate's transport BEFORE it claims a row, and
# the first one that answers gets the release. The chosen host is the one named
# in the dispatch log, so "which machine ran it" is a recorded fact, not a guess.
LOCAL_NODE=$(hostname -s 2>/dev/null || hostname)
LOCAL_RUNNER=${WAKE_LOCAL_RUNNER:-$HOME/bin/wake-run.sh}
if [ -n "${WAKE_NODE:-}" ]; then
  case "$WAKE_NODE" in
    authority|local) NODE_ORDER="${LOCAL_NODE}:local" ;;
    *)               NODE_ORDER="${DESKTOP}:desktop" ;;
  esac
elif [ -n "${WAKE_NODE_ORDER:-}" ]; then
  NODE_ORDER=$WAKE_NODE_ORDER
else
  # THE FIX FOR THE 32-HOUR OUTAGE. The desktop stays first because it is the
  # strongest worker and has the checkouts; the authority is second because it
  # holds the same tools, filesystem and ledger, so a release still lands when
  # the desktop is asleep. dsh-mesh cages the turn at 6G, so the authority's
  # company-api is not exposed to it.
  NODE_ORDER="${DESKTOP}:desktop,${LOCAL_NODE}:local"
fi
NODE_KIND=""
NODE_LABEL=""
NODE_PROBE_LOG=""
probe_candidate() {   # host kind -> 0 reachable
  local host=$1 kind=$2 rc=0
  case "$kind" in
    local|authority)
      [ -x "$LOCAL_RUNNER" ] && return 0
      NODE_PROBE_LOG="$NODE_PROBE_LOG $host(local-runner-missing)"
      return 1 ;;
  esac
  # `hostname`, not `true`: sshd on the Windows desktop runs PowerShell, where
  # `true` is not a command (measured: `ssh desktop-ts true` -> rc=1 with "The
  # term 'true' is not recognized"), so probing with it would mark a perfectly
  # reachable desktop unreachable and silently move every release to the
  # fallback. `hostname` answers 0 on both Windows and Linux.
  timeout 12 "$SSH_CMD" -o BatchMode=yes -o ConnectTimeout=8 "$host" hostname >/dev/null 2>&1 || rc=$?
  [ "$rc" -eq 0 ] && return 0
  NODE_PROBE_LOG="$NODE_PROBE_LOG $host(rc=$rc)"
  return 1
}
select_node() {
  local spec host kind oldifs=$IFS
  IFS=','
  for spec in $NODE_ORDER; do
    IFS=$oldifs
    spec=$(printf '%s' "$spec" | tr -d '[:space:]')
    [ -n "$spec" ] || continue
    host=${spec%%:*}
    kind=${spec#*:}
    [ "$kind" = "$spec" ] && kind=desktop
    case "$kind" in
      authority) kind=local ;;
      desktop|local) : ;;
      *) kind=desktop ;;
    esac
    if probe_candidate "$host" "$kind"; then
      NODE_KIND=$kind
      DESKTOP=$host
      NODE_LABEL=$host
      return 0
    fi
    if [ "$DRY_RUN" = 1 ]; then
      say "  node:      $host unreachable, trying the next candidate"
    else
      log "node $host unreachable before claim (probe failed:${NODE_PROBE_LOG:- unknown}); trying the next candidate"
    fi
  done
  IFS=$oldifs
  return 1
}
# --- cap consistency (single source, rewritten 2026-09-30) --------------------
# The store owns the numbers; this dispatcher READS them. Query once and derive
# both ceilings, so a literal can never drift from wake.py again.
WAKE_STATS_JSON=$(python3 "$WAKE_CLI" stats --json 2>/dev/null)
WAKE_CAP_STORE=$(printf '%s' "$WAKE_STATS_JSON" \
  | sed -n 's/.*"max_per_day":[[:space:]]*\([0-9][0-9]*\).*/\1/p' | head -1)
WAKE_CAP_USD_STORE=$(printf '%s' "$WAKE_STATS_JSON" \
  | sed -n 's/.*"max_usd_per_day":[[:space:]]*\([0-9][0-9.]*\).*/\1/p' | head -1)
if [ -z "$WAKE_CAP_STORE" ] || [ -z "$WAKE_CAP_USD_STORE" ]; then
  err "cannot read the daily caps from \`$WAKE_CLI stats --json\`; refusing to gate on a ceiling I cannot read"
  exit 2
fi
MAX_PER_DAY=${WAKE_MAX_PER_DAY:-$WAKE_CAP_STORE}
MAX_USD_PER_DAY=${WAKE_MAX_USD_PER_DAY:-$WAKE_CAP_USD_STORE}
# COMPARE AS NUMBERS, NOT AS STRINGS. Measured 2026-10-13: cron passes WAKE_MAX_USD_PER_DAY=25
# (an integer) while wake.py prints 25.0 (a float), so the string test `[ "25.0" != "25" ]` was
# TRUE and every dispatch printed "USD cap drift ... The looser value wins" - 434 times in one
# day. A warning that fires when two numbers are EQUAL cannot be believed on the day they
# differ, and the drift that WAS real on that day (the release cap, 500 in wake.py against 150
# in cron) never printed at all, because wake.py reads the override and reports it as its own
# default. Both failures have the same root: the comparison was not a comparison.
caps_differ() { awk -v a="$1" -v b="$2" 'BEGIN { exit !(a + 0 != b + 0) }'; }
# A drift warning is now only possible when an env override is deliberately in force.
if caps_differ "$WAKE_CAP_STORE" "$MAX_PER_DAY"; then
  say "  WARNING:  cap drift - wake.py says ${WAKE_CAP_STORE}/day, WAKE_MAX_PER_DAY overrides to ${MAX_PER_DAY}/day."
  say "            The looser value wins. Unset the override or align wake.py."
  log "WARNING cap drift: wake.py says ${WAKE_CAP_STORE}/day, WAKE_MAX_PER_DAY overrides to ${MAX_PER_DAY}/day. The looser value wins."
fi
if caps_differ "$WAKE_CAP_USD_STORE" "$MAX_USD_PER_DAY"; then
  say "  WARNING:  USD cap drift - wake.py says \$${WAKE_CAP_USD_STORE}/day, WAKE_MAX_USD_PER_DAY overrides to \$${MAX_USD_PER_DAY}/day."
  say "            The looser value wins. Unset the override or align wake.py."
  log "WARNING USD cap drift: wake.py says \$${WAKE_CAP_USD_STORE}/day, WAKE_MAX_USD_PER_DAY overrides to \$${MAX_USD_PER_DAY}/day. The looser value wins."
fi
# NOTE ON WHERE THE EFFECTIVE CEILINGS ARE RECORDED. They are published by `wake-fanout.sh`
# (every minute, including the ticks that start nothing), NOT here. This file is the live
# release path, and when a cap is in force it is exactly the process that does not run - so a
# record written here goes missing precisely when a reader needs it. See the block in
# wake-fanout.sh for the measurement behind it.

# --- liveness -----------------------------------------------------------------
# Write a heartbeat on EVERY run, including the quiet ones and including a run
# that exits early because the queue is empty or the queue is paused. The owner
# digest reads this file and reports the dispatcher's age, because the dangerous
# state of an always-on system is not "a flag is pending" - it is the machinery
# being DEAD, which is indistinguishable from peace unless something records that
# it ran. (Integration addition: the fleet version took the heartbeat to mean the
# lease heartbeat only, and deploying it as-is would have made the digest report
# a healthy dispatcher as dead after 20 minutes - a false alarm is its own harm.)
HEARTBEAT_FILE=${WAKE_HEARTBEAT_FILE:-$HOME/.sms-inbox/wake-heartbeat}
date -Is > "$HEARTBEAT_FILE" 2>/dev/null || true

# The desktop runner bounds itself inside our own bound, so a killed ssh cannot
# leave a dsh session running on the desktop forever. It must stay strictly
# smaller than the outer bound: with WAKE_TIMEOUT_SEC=30 the naive `-60` clamp
# produced a LARGER inner bound (60 > 30) and defeated the whole point, which the
# verification suite caught (S2). WAKE_TIMEOUT_SEC itself is never overridden -
# an explicit setting by the operator is theirs, not ours to "fix".
#
# MEASURED DEFECT, 2026-09-20. The inner bound was TIMEOUT-60 = 840 s against an
# outer bound of 900 s, and 840 s is BELOW the length of a real turn, so the
# runner killed sessions that were still working: wake #8 and #10 were cut
# mid-sentence at 841 s with 218 KB and 378 KB of live reasoning, the runner
# reported 124, ssh returned 1, and the dispatcher recorded "ssh hop failed
# (rc=1)" - a bounded-and-killed hop wearing a network failure's name. The
# sibling release #6 finished at 715 s, i.e. 85 % of the old bound, and the old
# bound was never derived from anything but "a bit less than 15 minutes".
# The bound is TURN_CAP-anchored now, and the gap to the outer bound stays wide
# enough that a runner which really does wedge is still reported, not guessed at.
RUNNER_MARGIN=${WAKE_RUNNER_MARGIN_SEC:-60}
RUNNER_TIMEOUT=$((TIMEOUT - RUNNER_MARGIN))
[ "$RUNNER_TIMEOUT" -lt $((TIMEOUT * 4 / 5)) ] && RUNNER_TIMEOUT=$((TIMEOUT * 4 / 5))
[ "$RUNNER_TIMEOUT" -lt 5 ] && RUNNER_TIMEOUT=5
[ "$RUNNER_TIMEOUT" -ge "$TIMEOUT" ] && RUNNER_TIMEOUT=$((TIMEOUT - 1))
# A runner bound below TURN_CAP truncates a session that is still working (the
# measured defect above). Give it a whole turn whenever the outer bound still has
# room to report the kill afterwards.
if [ "$RUNNER_TIMEOUT" -lt "$TURN_CAP" ] && [ "$((TIMEOUT - TURN_CAP))" -ge 60 ]; then
  RUNNER_TIMEOUT=$TURN_CAP
fi
[ "$RUNNER_TIMEOUT" -ge "$TIMEOUT" ] && RUNNER_TIMEOUT=$((TIMEOUT - 1))
[ "$RUNNER_TIMEOUT" -lt 1 ] && RUNNER_TIMEOUT=1
# A heartbeat interval at or above the lease is a misconfiguration: halve it.
if [ "$HEARTBEAT" -ge "$LEASE" ]; then HEARTBEAT=$((LEASE / 2)); [ "$HEARTBEAT" -lt 5 ] && HEARTBEAT=5; fi

# HOW MUCH MARGIN A HEARTBEAT GETS BEFORE ITS LEASE IS CALLED LOST.
#
# Measured 2026-09-30: four sessions (#172, #173, #174, #175) were killed inside
# sixteen minutes, every one of them with "lease heartbeat failed ... killing the
# session to avoid a double release". Each kill followed THREE failed attempts with
# 2 s between them -- about six seconds of grace -- against a 1200 s lease whose
# last confirmed renewal still had ~19 minutes on it. The failures were the 14 GB
# store answering a lock, which is routine on this box under contention. The
# dispatcher was turning a momentary lock into a dead session, and the work those
# sessions had already done went with them.
#
# The safety property that matters is unchanged: never let a second dispatcher pick
# up a row this one is still running. That is enforced by the deadline below, not by
# a three-strike counter -- the session may keep running only while the lease it last
# confirmed still has margin left.
LEASE_MARGIN=${WAKE_LEASE_MARGIN_SEC:-0}
if [ "$LEASE_MARGIN" -le 0 ]; then
  LEASE_MARGIN=$((HEARTBEAT * 2))
  [ "$LEASE_MARGIN" -lt 120 ] && LEASE_MARGIN=120
fi

# --- state --------------------------------------------------------------------
# (DRY_RUN, log, err, say and the time helpers are defined above the
# configuration block, which calls them.)
CLAIMED_ID=""
FINISHED=0
LEASE_LOST=0
UNVERIFIED=0
LEASE_DEADLINE=0
LEASE_LOSS_REASON=""
LEASE_DECISION=""; LEASE_RC=""; LEASE_ATTEMPT=""
_LEASE_LAST_ERR=""
SESS_PID=""
OUTCOME_REASON=""
RELEASE_RC=""
RUNNER_CODE=""
COST=""
ID=""; SUBJ=""; PRIORITY=""

# The aim this release was called with (ledger #203). Named on BOTH dry-run
# exits - the full rehearsal and the early "nothing to release" path - because
# an aim that matched nothing is exactly when the operator most needs to see
# what was aimed for.
say_aim() {
  if [ -n "${WAKE_ONLY_PROJECT:-}${WAKE_ONLY_ID:-}${WAKE_ONLY_MATCH:-}" ]; then
    say "  aim:       WAKE_ONLY_PROJECT='${WAKE_ONLY_PROJECT:-}' WAKE_ONLY_ID='${WAKE_ONLY_ID:-}' WAKE_ONLY_MATCH='${WAKE_ONLY_MATCH:-}'"
    say "             (wake.py _candidates applies this before every guard, so an aimed release still passes the frozen gates)"
  fi
}
oneline() { printf '%s' "$1" | tr '\t\r\n' '   '; }
# bound a blob to N characters, single line, for the store's outcome column
bounded() { local t; t=$(printf '%s' "$1" | tr '\t\r\n' '   '); printf '%s' "${t:0:$OUTCOME_BYTES}"; }
# WHAT THE SESSION ACTUALLY REPORTED.
# The answer is a NAMED SECTION of the out-file, not its last 2000 bytes.
# Measured 2026-10-18: `outcome` was `tail -c 2000` of a 70-130 KB transcript,
# which is the model's chain-of-thought TRAILER, so `wake.py list` showed the
# shift thinking instead of what it reported. The runner already marks the real
# answer between two banners, so that section is the primary source.
#
# A NO-ANSWER OUT-FILE IS NOT A SHORT OUT-FILE. Measured 2026-10-27: seven
# releases (16:41-19:08Z) exited 1 on `npm error could not determine executable
# to run`, which sits AFTER the runner header. `bounded(tail -c 2000)` kept only
# the header's first 600 characters, so a launch failure was recorded as "ssh hop
# failed" and item 1330's premise guessed host-asleep. The no-answer path now
# reads the failure vocabulary out of the whole file; the tail stays only as the
# last resort, so an unfamiliar format degrades to bytes rather than to silence.
answer_head() {
  awk '
    /^--- stdout \(final answer\) ---[[:space:]]*$/ { inans=1; next }
    /^--- stderr \(provider reasoning\) ---[[:space:]]*$/ { inans=0; next }
    inans { print }
  ' "$1" 2>/dev/null
}
no_answer_excerpt() {
  local f=$1 out
  # 1. The launcher's/engine's own failure vocabulary, anchored at line start.
  out=$(grep -aE '^[[:space:]]*(npm (error|ERR!)|WAKE_(FAIL_REASON|NOT_STARTED_REASON|EMPTY_ANSWER)=)' "$f" 2>/dev/null | head -8)
  # 2. A recognisable failure line anywhere in the file (an older runner, a
  #    traceback, a resolver refusal), before falling back to the header.
  if [ -z "$out" ]; then
    out=$(grep -aiE 'error|exception|traceback|fatal|panic|could not|not found|no such file|refus(ed|ing) to boot|failed' "$f" 2>/dev/null | head -8)
  fi
  # 3. Never return nothing for a file that has bytes.
  [ -n "$out" ] || out=$(tail -c 2000 "$f" 2>/dev/null)
  printf '%s' "$out"
}
extract_result_text() {
  local f=$1
  RESULT_TEXT=""
  RESULT_PRESENT=0
  ANSWER_TEXT=""
  ANSWER_PRESENT=0
  [ -f "$f" ] || return 0
  ANSWER_TEXT=$(answer_head "$f" | sed -e '/./,$!d' | head -c 6000)
  if [ -n "$(printf '%s' "$ANSWER_TEXT" | tr -d '[:space:]')" ]; then
    ANSWER_PRESENT=1
  fi
  if [ "$ANSWER_PRESENT" = 1 ]; then
    RESULT_TEXT=$(bounded "$(printf '%s' "$ANSWER_TEXT" | head -c 2000)")
  else
    RESULT_TEXT=$(bounded "$(no_answer_excerpt "$f")")
  fi
  # Non-empty bytes in THIS session's out-file are the session's own output.
  [ -n "$RESULT_TEXT" ] && RESULT_PRESENT=1
  return 0
}
# Shell-quote an argument the way a human would write it: bare when it is plain,
# single-quoted when it holds spaces (so a dry run prints something readable AND
# copy-pasteable), %q only when a single quote makes that unsafe.
render_arg() {
  case "$1" in
    '') printf "''" ;;
    *"'"*) printf '%q' "$1" ;;
    *[[:space:]]*) printf "'%s'" "$1" ;;
    *) printf '%s' "$1" ;;
  esac
}
render() { local s="" a; for a in "$@"; do s+="$(render_arg "$a") "; done; printf '%s' "${s% }"; }
# Windows path -> scp path. scp reads a backslash as an escape character, so the
# transfer target is the only place a backslash may never appear.
to_scp() { printf '%s' "$1" | tr '\\' '/'; }

usage() {
  cat <<EOF
$PROG — release ONE wake row as a real headless DSH session on $DESKTOP.

  $PROG [--dry-run] [--help] [--selftest-lease]

  --dry-run   run the whole decision path (reap, gates, select, build the exact
              commands) and print what it would do. No claim, no ssh, no scp, no
              dsh, no log write. `reap` does run: it is the same maintenance a
              real tick performs, and it is what makes the rehearsal honest.
  --selftest-lease
              exercise the lease policy with a table of cases and exit non-zero on
              any failure. No store, no ssh, no session.

Env: WAKE_CLI WAKE_PYTHON WAKE_DESKTOP WAKE_REMOTE_DIR WAKE_REMOTE_RUNNER
     WAKE_REMOTE_PROMPT WAKE_REMOTE_OUT WAKE_LOG WAKE_STAGE_DIR WAKE_LOCK_FILE
     WAKE_CALLSIGN WAKE_SSH_CMD WAKE_SCP_CMD WAKE_TIMEOUT_SEC WAKE_HEARTBEAT_SEC
     WAKE_TURN_CAP_SEC WAKE_RUNNER_MARGIN_SEC WAKE_LEASE_MARGIN_SEC
     WAKE_ALT_READ_CMD WAKE_ALT_READ_TIMEOUT_SEC WAKE_LIB_ONLY
     WAKE_OUTCOME_BYTES, plus the contract names WAKE_MAX_PER_DAY
     WAKE_MAX_USD_PER_DAY WAKE_LEASE_SEC WAKE_PAUSE_FILE.

OUTCOMES. Every release closes its row as exactly one of:
  done        the session ran and its result was read back (by scp, or by the
              alternate read over the hop when scp failed);
  failed      the session crashed, was killed at its bound, or the hop failed
              with no readable result - its outcome says what was lost;
  unverified  the session ran but its result could not be read back at all. It is
              NOT a failure: `wake.py finish --unverified` files it in its own
              state, refunds the attempt and does not count it as a failure.

WAKE_ALT_READ_CMD overrides the recovery read (a command line whose last argument
is the remote path and whose stdout is the file's bytes base64-encoded).
WAKE_LIB_ONLY=1 sources this file for its functions and runs nothing.

Aim ONE release at a chosen project or row (ledger #203): WAKE_ONLY_PROJECT=NAME,
WAKE_ONLY_ID=N or WAKE_ONLY_MATCH=TEXT. They are passed straight through to
wake.py, which applies the filter inside _candidates BEFORE any guard, so an
aimed release still passes every frozen gate and an aim that matches nothing
stays quiet (exit 0) instead of releasing the wrong row.
EOF
}

# ---------------------------------------------------------------------------
# The lease policy, as a pure function, so it can be proven without a session.
#
#   lease_decision <probe_rc> <now> <renewed_until> <margin>
#     renew : the store just extended the lease
#     lost  : the store itself says we do not hold this row, or the last confirmed
#             lease is inside its margin and cannot be renewed
#     wait  : transient failure and there is still margin -- keep trying
#
# rc is the probe's: 0 renewed, 1 the store says not ours, 2 anything else.
# ---------------------------------------------------------------------------
lease_decision() {
  case "$1" in
    0) printf 'renew' ;;
    1) printf 'lost' ;;
    *) if [ "$2" -ge "$(( $3 - $4 ))" ]; then printf 'lost'; else printf 'wait'; fi ;;
  esac
}

selftest_lease() {
  local fails=0 got
  _t() {
    got=$(lease_decision "$2" "$3" "$4" "$5")
    if [ "$got" = "$6" ]; then printf 'PASS  %s\n' "$1"
    else printf 'FAIL  %s: wanted %s, got %s\n' "$1" "$6" "$got"; fails=$((fails + 1)); fi
  }
  _t "a successful heartbeat renews"                 0 1000 1200 120 renew
  _t "the store saying not-claimed loses the lease"  1 1000 1200 120 lost
  _t "a locked store with margin left keeps trying"  2 1000 1200 120 wait
  _t "a locked store exactly at the margin is lost"  2 1080 1200 120 lost
  _t "a locked store past the margin is lost"        2 1500 1200 120 lost
  printf '\nRESULT: %s FAIL\n' "$fails"
  [ "$fails" -eq 0 ]
}

# ---------------------------------------------------------------------------
# THE OUT-FILE RECOVERY PATH, as pure functions, so it can be proven without a
# session, a desktop or a claim. They live here - above everything that runs -
# because the only way to exercise them is to source this file, and sourcing must
# not acquire the lock, reap the store or release anything.
#
#   try_alternate_read     read the far-side out-file over the hop (base64), 0/1
#   bring_back_out_file    scp, then the alternate read; sets SCP_BACK_RC and
#                          RECOVERED_VIA ("scp" | "local" | "alt-read" | "")
#   recovery_note          one clause naming which path recovered the bytes
#
# WAKE_LIB_ONLY=1 stops the file here, after the definitions and before any
# execution. WAKE_ALT_READ_CMD overrides the read command (test/ops): a command
# line whose LAST argument is the remote path, whose stdout is that file's bytes
# base64-encoded.
# ---------------------------------------------------------------------------
RECOVERED_VIA=""
ALT_READ_RC=""
# The remote path is passed to the read command only when the command expects it
# (the WAKE_ALT_READ_CMD override); the built-in `-EncodedCommand` form carries the
# path inside its own script and must be given no argument at all.
ALT_READ_ARGS=()

recovery_note() {
  case "${RECOVERED_VIA:-}" in
    scp)      printf 'recovered via scp' ;;
    local)    printf 'the out-file was written in place on this node (no transfer needed)' ;;
    alt-read) printf 'recovered via the alternate read over the ssh hop, after scp rc=%s failed' "${SCP_BACK_RC:-?}" ;;
    *)        printf 'nothing was recovered' ;;
  esac
}

try_alternate_read() {
  # 0 = this session's out-file is now readable here; 1 = it is not.
  [ "${#ALT_READ_RUN[@]}" -eq 0 ] && return 1
  rm -f "$ALT_READ_OUT" "$LOCAL_OUT.alt"
  # `${ALT_READ_TIMEOUT:-45}`: the variable is set beside the command below, and
  # this default keeps the function whole when it is called from a test that
  # sourced only the definitions (WAKE_LIB_ONLY=1).
  #
  # The rc is captured on its own line, NOT as `$?` inside an `if ! cmd; then`:
  # there, `$?` is the status of the negated compound, which is always 0, so the
  # failure reason came back as "0". (Measured 2026-10-02 - the first version of
  # this function reported a real ssh failure as rc=0.)
  timeout -k 10 "${ALT_READ_TIMEOUT:-45}" "${ALT_READ_RUN[@]}" "${ALT_READ_ARGS[@]}" \
    >"$ALT_READ_OUT" 2>>"$SSH_LOG"
  local rc=$?
  if [ "$rc" -ne 0 ]; then
    ALT_READ_RC=$rc
    return 1
  fi
  # The hop's stdout is base64; strip the CRLF the ssh pipe adds and decode. The
  # bytes land in a temp file first, so a half-decoded read can never replace a
  # good out-file.
  if ! tr -d '\r\n' <"$ALT_READ_OUT" | base64 -d >"$LOCAL_OUT.alt" 2>>"$SSH_LOG"; then
    ALT_READ_RC="decode-failed"
    rm -f "$LOCAL_OUT.alt"
    return 1
  fi
  if [ ! -s "$LOCAL_OUT.alt" ]; then
    ALT_READ_RC="empty"
    rm -f "$LOCAL_OUT.alt"
    return 1
  fi
  mv -f "$LOCAL_OUT.alt" "$LOCAL_OUT"
  RECOVERED_VIA="alt-read"
  return 0
}

# ---------------------------------------------------------------------------
# THE SESSION-ID SIDECAR (ledger housekeeping item 12). wake-cost.py records a
# release's run TOKEN but never its DSH session id, so release -> session was
# DERIVED from timing and content. wake-run.ps1 now writes the id it started to
# `wake-session-<release id>-<run token>.txt` beside the out-file; this brings it
# to ~/.sms-inbox/, the directory wake-cost.py `_recorded_session_ids()` reads,
# turning a `near`/`window`/`none` row into a `recorded` one.
#
# ADDITIVE, AND FAILURE IS ONLY LOGGED: it never touches $LOCAL_OUT, RECOVERED_VIA
# or the verdict, so a sidecar that cannot be fetched degrades to the old
# behaviour instead of failing a release that actually worked.
# ---------------------------------------------------------------------------
SIDECAR_FETCHED=""
bring_back_session_sidecar() {
  local name="wake-session-${ID}-${RUN_TOKEN}.txt"
  local dest="${WAKE_SIDECAR_DIR:-$HOME/.sms-inbox}/$name"
  if [ "${NODE_KIND:-}" = local ] || [ "${NODE_KIND:-}" = authority ]; then
    # The Linux runner wrote the sidecar on this host, so it is already where
    # wake-cost.py reads session ids. Record it; there is no hop to cross.
    if [ -s "$dest" ]; then
      SIDECAR_FETCHED="$name"
      log "wake #$ID: session-id sidecar recorded on $NODE_LABEL at $dest"
    else
      log "wake #$ID: local runner produced no session sidecar at $dest"
    fi
    return 0
  fi
  [ "${NODE_KIND:-}" = desktop ] || return 0
  [ -n "${SSH_CMD:-}" ] || return 0
  local tmp="$STAGE/sidecar.b64"
  mkdir -p "$(dirname "$dest")" 2>/dev/null || return 0
  # Same -EncodedCommand rule as the alternate read below: the path lives INSIDE
  # the encoded UTF-16LE script, so no Windows parser meets a quote.
  local ps="[Convert]::ToBase64String([IO.File]::ReadAllBytes('${REMOTE_DIR_WIN}\\${name}'))"
  local enc
  enc=$("$PY" -c 'import base64,sys; sys.stdout.write(base64.b64encode(sys.argv[1].encode("utf-16-le")).decode())' "$ps" 2>/dev/null || true)
  [ -n "$enc" ] || return 0
  if ! timeout -k 10 "${ALT_READ_TIMEOUT:-45}" "$SSH_CMD" "${SSH_OPTS[@]}" "$DESKTOP" \
        "powershell -NoProfile -EncodedCommand $enc" >"$tmp" 2>>"$SSH_LOG"; then
    rm -f "$tmp"; return 0
  fi
  if tr -d '\r\n' <"$tmp" | base64 -d >"$dest.tmp" 2>>"$SSH_LOG" && [ -s "$dest.tmp" ]; then
    mv -f "$dest.tmp" "$dest"
    SIDECAR_FETCHED="$name"
    log "wake #$ID: session-id sidecar recorded to $dest"
  else
    rm -f "$dest.tmp"
  fi
  rm -f "$tmp"
  return 0
}

bring_back_out_file() {
  SCP_BACK_RC=0
  if [ "${#SCP_BACK[@]}" -gt 0 ]; then
    "${SCP_BACK[@]}" >>"$SSH_LOG" 2>&1 || SCP_BACK_RC=$?
    if [ "$SCP_BACK_RC" -eq 0 ] && [ -s "$LOCAL_OUT" ]; then RECOVERED_VIA="scp"; fi
  elif [ -s "$LOCAL_OUT" ]; then
    RECOVERED_VIA="local"
  fi
  # A failed or empty copy is a reason to READ, not a verdict: the file exists on
  # the far side, and scp failing does not mean the session failed.
  if [ "$SCP_BACK_RC" -ne 0 ] || [ ! -s "$LOCAL_OUT" ]; then
    if try_alternate_read; then
      log "wake #$ID: out-file recovered by the alternate read after scp rc=$SCP_BACK_RC"
    else
      log "wake #$ID: out-file could not be recovered (scp rc=$SCP_BACK_RC, alternate read rc=${ALT_READ_RC:-n/a})"
    fi
  fi
  return 0
}

# ---------------------------------------------------------------------------
# THE CONTRACT EVERY WOKEN SESSION RECEIVES (added 2026-10-02).
#
# WHY HERE AND NOWHERE ELSE. The `prompt` column holds whatever the flagging
# source wrote, and a released session is a headless DSH turn that never met the
# house rules: measured 2026-10-02, releases asked the owner questions our own
# ledger could answer, texted him machine instructions ("on the desktop run ..."),
# and closed with "remembered" and "on it" - none of which is a result. The one
# choke point every release passes through is this file, so this is where the
# contract is attached: the prompt the session actually runs is CONTRACT + the
# store's prompt, built by exactly one writer (PROMPT_HELPER), used by both the
# real path and the dry run so the rehearsal is byte-identical to the release.
# It is defined ABOVE the library guard so a test can prove the bytes.
# ---------------------------------------------------------------------------
WAKE_PROMPT_CONTRACT=$(cat <<'CONTRACT'
=== WAKE CONTRACT - read this before you do anything ===
1. READ THE CASE FILE FIRST. The store, the ledger, the repo and the vendor
   history hold the evidence for this subject. Read it before you form a view.
2. NEVER ASK THE OWNER WHAT OUR OWN RECORDS ANSWER. Search the store, the
   ledger, the vendors, the repo, the web - then decide. If a question is
   genuinely his, it is ONE question, in plain words, with your recommendation.
3. NEVER SEND HIM AN INTERNAL NOTE OR A MACHINE INSTRUCTION. He is the owner,
   not the operator of our machinery: no "run this on your desktop", no
   "remembered", no bare acknowledgement.
4. REPORT A RESULT, NOT A PROMISE. Say what you changed and the command or file
   that proves it. "I will look into it" is not an outcome.
5. NEVER INSTALL, PROVISION OR WIRE UP SOFTWARE ON A MACHINE THE OWNER USES
   UNLESS HE ASKED FOR THAT THING ON THAT MACHINE. An approved goal ("dictate
   on the Yoga side", "make dictation work") authorises the work; it is NOT
   permission to install an app, add a startup item, claim a hotkey, or leave a
   scheduled task on his laptop or desktop. State the exact thing and ask him,
   once, with a recommendation. A route decision is not an install request, and
   a sentence he said about another machine is not a requirement for this one.
   Server-side and fleet machinery is a different question and stays yours.
6. NOTHING OUTBOUND without his explicit yes to that exact message, and never
   raise a wake flag from inside a session.
   A REMINDER IS NOT A MESSAGE, and you may set one. If the work leaves something
   the owner must act on at a TIME - a deadline, a callback, a payment - schedule it:
     python3 /root/bin/reminder-add.py --message "call the vendor about the 10/20 payment" \
       --at "tomorrow 9am" --source-ref "ledger-518"
   --at accepts ISO8601, "in 2h", "in 3d" or "tomorrow 9am" and REFUSES anything else rather
   than guessing. It writes one row to the dashboard reminder queue and never sends a text,
   so rule 6 still governs anything that leaves the building. --source-ref is the dedupe
   key: the same key twice is a no-op, so a re-run cannot double-schedule the same thing.
7. CLAIM FROM THE LEDGER, BECAUSE IT IS THE ONLY PLACE WORK LIVES. Run exactly:
   `python3 /root/bin/work.py claim-next --project <project> --by <handle> --lease 5400 --json --owner-queue-db /root/authority.db`
   `<handle>` is the one the project body below gives you, and it MUST be the same string
   you pass to `close` in rule 8: the lease is keyed on it, and a claim closed under a
   different handle is one the reaper cannot match back to its worker.
   If it answers `nothing-todo`, SAY SO AND STOP. Never invent work to look busy: the point
   of a budget is that it is spent on real work, and an invented task spends it on nothing.
   (`--owner-queue-db /root/authority.db` is required. The built-in default names
   /home/zabz/personal-secretary-mvp/data/secretary.db - a STALE copy that really exists on
   the authority and holds ZERO rows. work.py falls back by CONTENT, so the default does
   answer correctly today (measured 2026-10-16); it would silently start answering from the
   stale copy the day a row lands in it, which is why the flag is passed, not relied on.)
8. CLOSE THE LEDGER ITEM WITH A PROOF, OR YOU PRODUCED NOTHING. Every shift ends with:
   `python3 /root/bin/work.py close <id> --by <the same handle> --state done|blocked \
      --did "<what you changed>" --proof "<the exact command that shows it>" \
      --result "<that command's output line>" --left "<what remains>" --exit-code <n>`
   `exit=0` is not a result. A summary is not a proof. A shift that ends without this close
   is recorded as having produced nothing, however well it reads -- and if you genuinely
   could not proceed, close `--state blocked --blocked-on "<the measurement>"` instead, so
   the next shift starts from your evidence rather than re-deriving it.
   NOTE (measured 2026-10-16, ledger item 462): `close` and `add` act on the WORK
   ledger, which is a DIFFERENT store from the owner queue named in rule 7. Do NOT
   carry `--owner-queue-db /root/authority.db` across from rule 7, and never give
   close/add `--db /root/authority.db`: that path is the OWNER QUEUE. Pointing the
   ledger at it once created empty ledger tables inside the live production store and
   then answered `error:no-such-item` with exit status 0, so the close was recorded
   nowhere while the shift believed it had landed. With no db flag at all these verbs
   answer correctly. (work.py now redirects such a --db to the real ledger and says so
   on stderr, but the flag is still wrong.)
=== END WAKE CONTRACT ===
CONTRACT
)
export WAKE_PROMPT_CONTRACT

# THE ONE PROMPT BUILDER. Prepending is the only place the two halves are joined,
# and it lives here so a second builder cannot appear beside it.
PROMPT_HELPER='
import os, sys

def write_prompt(path, prompt):
    """The prompt a session runs: the wake contract, then the store prompt."""
    pre = os.environ.get("WAKE_PROMPT_CONTRACT", "")
    body = prompt or ""
    with open(path, "w", encoding="utf-8") as f:
        f.write((pre + "\n\n" + body) if pre else body)
'

if [ "${WAKE_LIB_ONLY:-}" = 1 ]; then
  # Sourced by a test: every function above is defined, nothing below has run.
  return 0 2>/dev/null || exit 0
fi

while [ $# -gt 0 ]; do  case "$1" in
    --dry-run|-n) DRY_RUN=1 ;;
    --selftest-lease) selftest_lease; exit $? ;;
    --help|-h) usage; exit 0 ;;
    *) err "unknown argument: $1"; usage >&2; exit 2 ;;
  esac
  shift
done

# NODE SELECTION, AFTER ARGUMENT PARSING. `--help` must never probe, and a
# --dry-run rehearsal must never write a probe line into the audit log; both are
# only knowable once the flags are parsed. Refusing here is BEFORE the claim, so
# an unreachable fleet cannot burn a row's attempts or its lease.
if ! select_node; then
  err "no dispatch candidate answered (order=$NODE_ORDER${NODE_PROBE_LOG:+; probes:$NODE_PROBE_LOG}); nothing claimed"
  exit 4
fi

mkdir -p "$(dirname "$LOG")" "$STAGE" 2>/dev/null || true
chmod 700 "$STAGE" 2>/dev/null || true

# ---------------------------------------------------------------------------
# 0. Close a claim even if this shell dies (killed cron, `timeout`, a scanner).
#    Registered before anything can claim, so there is no window in which a
#    claim exists and no trap does.
# ---------------------------------------------------------------------------
cleanup() {
  local rc=$?
  if [ -n "$CLAIMED_ID" ] && [ "$FINISHED" -eq 0 ]; then
    # Do not leave a session running behind a closed row. Children inherit the
    # lock fd, so killing this also releases the single-instance lock.
    if [ -n "$SESS_PID" ] && kill -0 "$SESS_PID" 2>/dev/null; then
      kill "$SESS_PID" 2>/dev/null
      log "killed the in-flight session (pid $SESS_PID) on the way out"
    fi
    log "ERROR exited (rc=$rc) with wake #$CLAIMED_ID still claimed - closing as failed"
    "$PY" "$WAKE_CLI" finish "$CLAIMED_ID" --failed \
      --outcome "dispatcher exited before the session outcome was recorded (rc=$rc); session killed" \
      >/dev/null 2>&1 \
      || log "ERROR could not close wake #$CLAIMED_ID; reap will recover the lease"
  fi
  exit $rc
}
trap cleanup EXIT
# A signal is converted into a normal exit so the EXIT trap above always runs:
# a dispatcher killed mid-release must still close its claim, not leave it for
# the lease to time out.
trap 'exit 143' INT TERM

# ---------------------------------------------------------------------------
# 1. Single instance. Two dispatchers at once = two sessions for one flag.
# ---------------------------------------------------------------------------
exec 9>"$LOCK" 2>/dev/null || { err "cannot open lock file $LOCK"; exit 2; }
if ! flock -n 9; then
  log "another dispatcher holds $LOCK - skipping this tick"
  [ "$DRY_RUN" = 1 ] && say "dry-run: another dispatcher holds $LOCK (a real run would skip too)"
  exit 0
fi

# ---------------------------------------------------------------------------
# 2. Kill switch, then the daily caps. The store enforces these as well; a
#    store bug must not be the only thing standing between us and 300 sessions.
# ---------------------------------------------------------------------------
if [ -e "$PAUSE_FILE" ]; then
  log "paused ($PAUSE_FILE exists) - not releasing"
  [ "$DRY_RUN" = 1 ] && say "dry-run: paused ($PAUSE_FILE exists) - would release nothing"
  exit 0
fi

TODAY=$(today_utc)
RELEASES_TODAY=$(grep -c " released $TODAY wake #" "$LOG" 2>/dev/null) || RELEASES_TODAY=0
# The measured spend comes from the SAME wake.py that owns the ceiling; it sums
# ~/.sms-inbox/wake-cost.jsonl (wake-cost.py prices each release from its DSH
# session's tokens). The dispatch log says cost=none on every line because the
# desktop runner cannot report a cost, so summing the log could only ever give 0.0
# - a cap that cannot fire. JSON null (unmeasurable) must not read as zero, but the
# store still enforces; the belt gate simply does not block on a number it lacks.
SPEND_TODAY=$(printf '%s' "$WAKE_STATS_JSON" \
  | sed -n 's/.*"spend_today_usd":[[:space:]]*\([0-9][0-9.]*\).*/\1/p' | head -1)
[ -n "$SPEND_TODAY" ] || SPEND_TODAY=0

if [ "$RELEASES_TODAY" -ge "$MAX_PER_DAY" ]; then
  log "daily cap reached ($RELEASES_TODAY/$MAX_PER_DAY) - not releasing"
  [ "$DRY_RUN" = 1 ] && say "dry-run: daily cap reached ($RELEASES_TODAY/$MAX_PER_DAY) - would release nothing"
  exit 0
fi
if [ "$(awk -v s="$SPEND_TODAY" -v m="$MAX_USD_PER_DAY" 'BEGIN { print (s + 0 >= m + 0) ? "yes" : "no" }')" = yes ]; then
  log "daily cost cap reached (\$$SPEND_TODAY/\$$MAX_USD_PER_DAY) - not releasing"
  [ "$DRY_RUN" = 1 ] && say "dry-run: daily cost cap reached (\$$SPEND_TODAY/\$$MAX_USD_PER_DAY) - would release nothing"
  exit 0
fi

# ---------------------------------------------------------------------------
# 3. Reap first: recovery from a dispatcher that died mid-release. Safe to run
#    in a dry run — it is maintenance the real run performs anyway.
# ---------------------------------------------------------------------------
REAP_OUT=$("$PY" "$WAKE_CLI" reap 2>&1); REAP_RC=$?
if [ "$REAP_RC" -ne 0 ]; then
  err "reap failed (rc=$REAP_RC): $(oneline "$REAP_OUT")"
  exit 2
fi

# ---------------------------------------------------------------------------
# 3b. Retire QUEUED project packets whose project has no shift-startable ledger
#     work (LEDGER item 180, residual of item 142). `reap` ages rows out; it
#     cannot know that a project's whole non-terminal backlog is `blocked` with a
#     revisit still in the future. So a stale project-keepalive packet sits `new`
#     and buys a full ~30-minute session whose only possible answer is
#     `claim-next -> nothing-todo` - measured 2026-10-14: 30 such packets (15
#     chumash, 15 rental-system) against two projects blocked to 2026-10-21, while
#     chumash alone had been released 8 times that day, every one exit=0.
#     `project-keepalive` asks the ledger before it FILES (item 142); this is the
#     SAME verdict (imported, never re-implemented) applied to what is already
#     QUEUED. Nothing is released and no session starts: the row is retired
#     (state `cancelled`, outcome naming the reason) and every refusal is written
#     to the dispatch log. FAIL OPEN - an unreadable ledger retires nothing, so a
#     broken new signal can slow the fleet down but never silence a project.
# ---------------------------------------------------------------------------
if [ -f "$DEAD_FLAGS" ]; then
  if [ "$DRY_RUN" = 1 ]; then
    DEAD_OUT=$("$PY" "$DEAD_FLAGS" --dry-run 2>&1); DEAD_RC=$?
    if [ "$DEAD_RC" -ne 0 ]; then
      err "dead-project-flags failed (rc=$DEAD_RC): $(oneline "$DEAD_OUT")"
    elif [ -n "$DEAD_OUT" ]; then
      say "  queued:    $(oneline "$DEAD_OUT")"
    fi
  else
    DEAD_OUT=$("$PY" "$DEAD_FLAGS" --apply 2>&1); DEAD_RC=$?
    if [ "$DEAD_RC" -ne 0 ]; then
      err "dead-project-flags failed (rc=$DEAD_RC): $(oneline "$DEAD_OUT")"
    elif [ -n "$DEAD_OUT" ]; then
      printf '%s\n' "$DEAD_OUT" | while IFS= read -r _dead_line; do
        [ -n "$_dead_line" ] && log "$_dead_line"
      done
    fi
  fi
fi

# ---------------------------------------------------------------------------
# 4. Select exactly one row. The real path asks the store (`claim`) so the
#    frozen guards (dedup, cooldown, per-source cap, night gate, kill switch,
#    cost cap) are evaluated in exactly one place. A dry run cannot call claim
#    — that would leave a real row claimed — so it reads the queue and applies
#    the frozen row-selection rule itself, and says so.
# ---------------------------------------------------------------------------
CLAIM_JSON="$STAGE/claim.json"
PROMPT_FILE="$STAGE/prompt.txt"
LOCAL_OUT="$STAGE/wake-out.txt"
SSH_LOG="$STAGE/wake-ssh.log"
CLAIM_SIMULATED=0

# (WAKE_PROMPT_CONTRACT and PROMPT_HELPER - the one prompt builder - are defined
# above the library guard, so a test can prove what a session is handed.)

SELECT_PY="$PROMPT_HELPER"'
import datetime, json, sys

def parse(s):
    if not s:
        return None
    t = str(s).strip().replace("Z", "+00:00")
    try:
        dt = datetime.datetime.fromisoformat(t)
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt

raw = sys.stdin.read()
try:
    d = json.loads(raw)
except Exception:
    sys.exit(3)
rows = d.get("rows") if isinstance(d, dict) else d
if rows is None and isinstance(d, dict):
    rows = d.get("row") or d.get("wake") or []
if isinstance(rows, dict):
    rows = [rows]
if not isinstance(rows, list):
    sys.exit(3)
now = datetime.datetime.now(datetime.timezone.utc)
rank = {"high": 0, "normal": 1, "low": 2}
best = None
for r in rows:
    if not isinstance(r, dict):
        continue
    if str(r.get("state") or "") != "new":
        continue
    nb = parse(r.get("not_before"))
    if nb is not None and nb > now:
        continue
    try:
        attempts = int(r.get("attempts") or 0)
        max_attempts = int(r.get("max_attempts") or 2)
    except Exception:
        attempts, max_attempts = 0, 2
    if attempts >= max_attempts:
        continue
    try:
        rid = int(r.get("id") or 0)
    except Exception:
        rid = 0
    key = (rank.get(str(r.get("priority") or "normal"), 1), rid)
    if best is None or key < best[0]:
        best = (key, r)
if best is None:
    sys.exit(10)
r = best[1]
sys.stdout.write("\t".join([
    str(r.get("id") or ""), str(r.get("subject") or ""), str(r.get("priority") or "")]))
write_prompt(sys.argv[1], r.get("prompt") or "")
'

CLAIM_PY="$PROMPT_HELPER"'
import json, sys
try:
    d = json.load(open(sys.argv[1], encoding="utf-8"))
except Exception:
    sys.exit(3)
row = d.get("row") if isinstance(d, dict) else None
if row is None:
    sys.exit(10)
write_prompt(sys.argv[2], row.get("prompt") or "")
sys.stdout.write("\t".join([
    str(row.get("id") or ""), str(row.get("subject") or ""), str(row.get("priority") or "")]))
'

if [ "$DRY_RUN" = 1 ]; then
  LIST_OUT=$("$PY" "$WAKE_CLI" list --state new --json --limit 500 2>/dev/null)
  SELECTED=$(printf '%s' "$LIST_OUT" | "$PY" -c "$SELECT_PY" "$PROMPT_FILE" 2>/dev/null); SEL_RC=$?
  case "$SEL_RC" in
    10) say "  gates:     releases today $RELEASES_TODAY/$MAX_PER_DAY, spend today \$$SPEND_TODAY/\$$MAX_USD_PER_DAY, pause file absent"
        say_aim
        say "dry-run: nothing to release (no row is new and eligible)"; exit 0 ;;
    0)  : ;;
    *)  err "dry-run: could not read the wake queue (list --json rc=$SEL_RC); refusing to guess"; exit 2 ;;
  esac
  IFS=$'\t' read -r ID SUBJ PRIORITY <<<"$SELECTED"
  CLAIM_SIMULATED=1
else
  CLAIM_OUT=$("$PY" "$WAKE_CLI" claim --by "$CALLSIGN" --lease-seconds "$LEASE" --json 2>&1); CLAIM_RC=$?
  if [ "$CLAIM_RC" -ne 0 ]; then
    err "claim failed (rc=$CLAIM_RC): $(oneline "$CLAIM_OUT")"
    exit 2
  fi
  printf '%s' "$CLAIM_OUT" >"$CLAIM_JSON"
  SELECTED=$("$PY" -c "$CLAIM_PY" "$CLAIM_JSON" "$PROMPT_FILE" 2>/dev/null); SEL_RC=$?
  case "$SEL_RC" in
    10) exit 0 ;;   # nothing to release: stay silent, exit 0 (quiet path)
    0)  : ;;
    *)  err "claim returned something that is not §5 JSON: $(oneline "$CLAIM_OUT")"; exit 2 ;;
  esac
  IFS=$'\t' read -r ID SUBJ PRIORITY <<<"$SELECTED"
  CLAIMED_ID=$ID
  # ---------------------------------------------------------------------------
  # 4b. ONE SHIFT PER PROJECT TREE (added 2026-10-28).
  # MEASURED with where-are-shifts-overlapping.py over 7 days: 111 same-project overlaps, including
  # #1597 (project:lpt-website:20261027) overlapping #1622 (project:lpt-website:20261028) by 3544 s -
  # two sessions inside /root/repos/phone-and-tech-full at once, a 1.6 GB checkout with 25 linked
  # worktrees. The estate's own rule is one owner per shared resource per fleet, and the fan-out
  # deliberately runs several releases at a time, so this is a measured collision, not a theory: a
  # branch switch or a `git checkout test` under another session's feet loses work that no proof
  # line can recover.
  #
  # The lock is keyed on the subject's PROJECT, held on fd 8 for the life of this dispatcher, and so
  # released the moment the process exits (including a kill -9). A row whose project is busy is PUT
  # BACK rather than spent: `refund` returns it to `new` with its attempt given back, which is the
  # same vocabulary the launcher-fault path uses, so an unavailable tree never costs an item a try.
  PROJECT_KEY=$(printf '%s' "$SUBJ" | awk -F: '{ if ($1=="project" || $1=="checkout-health") print $2; else print $1 }')
  if [ -n "$PROJECT_KEY" ]; then
    TREE_LOCK_DIR=${WAKE_TREE_LOCK_DIR:-$HOME/.sms-inbox/tree-lock}
    mkdir -p "$TREE_LOCK_DIR" 2>/dev/null
    TREE_LOCK="$TREE_LOCK_DIR/$PROJECT_KEY.lock"
    # >> not >: opening with > truncates the file even when another process holds the lock, which
    # would erase the holder's name exactly when it is needed.
    exec 8>>"$TREE_LOCK" 2>/dev/null
    if ! flock -n 8; then
      HOLDER=$(head -1 "$TREE_LOCK" 2>/dev/null)
      log "wake #$ID ($SUBJ): the $PROJECT_KEY tree is held by another shift${HOLDER:+ [$HOLDER]} - putting the row back, no attempt spent"
      [ "$DRY_RUN" = 1 ] && say "dry-run: the $PROJECT_KEY tree is busy - a real run would put this row back"
      "$PY" "$WAKE_CLI" refund "$ID" --by "$CALLSIGN" \
        --why "another shift was already working the $PROJECT_KEY tree; no session was started and no attempt was spent" \
        >/dev/null 2>&1 || log "ERROR could not refund wake #$ID; the lease will expire and reap will recover it"
      CLAIMED_ID=""
      exit 0
    fi
    printf '%s %s wake #%s %s\n' "$(date -u +%FT%TZ)" "$CALLSIGN" "$ID" "$(printf '%s' "$SUBJ" | cut -c1-80)" > "$TREE_LOCK"
  fi
  # The lease ran from the moment the claim wrote it. From here the session may run
  # until this deadline minus the margin; every successful heartbeat moves it.
  LEASE_DEADLINE=$(( $(date -u +%s) + LEASE ))
fi

# ---------------------------------------------------------------------------
# 5. Build the exact commands. Built identically in both modes, so what a dry
#    run prints is character-for-character what a release runs.
# ---------------------------------------------------------------------------
RUN_TOKEN="$(date -u +%Y%m%dT%H%M%SZ)-$$"
if [ -n "$REMOTE_PROMPT_OVERRIDE" ]; then
  REMOTE_PROMPT=$REMOTE_PROMPT_OVERRIDE
else
  REMOTE_PROMPT="${REMOTE_DIR_WIN}\\wake-prompt-${ID}-${RUN_TOKEN}.txt"
fi
if [ -n "$REMOTE_OUT_OVERRIDE" ]; then
  REMOTE_OUT=$REMOTE_OUT_OVERRIDE
else
  REMOTE_OUT="${REMOTE_DIR_WIN}\\wake-out-${ID}-${RUN_TOKEN}.txt"
fi
REMOTE_PROMPT_SCP=$(to_scp "$REMOTE_PROMPT")
REMOTE_OUT_SCP=$(to_scp "$REMOTE_OUT")

# --- THE MODEL LANE, SCALED WITH THE BALANCE (2026-10-14) --------------------
# "Scale the cost per unit of work too, not just the total." The cheap-lane lever already exists,
# and it is already the supported way to choose a seat model: `wake-model.ps1:143` makes
# `WAKE_AGENT_MODEL` the AUTHORITATIVE candidate chain (validated against the live catalog, and
# `wake-model.ps1:151` already prefers the catalog's own fast/flash tier when nothing is named).
# What was missing was anything that SET it from the money. This reads the ONE budget file - the
# same one `wake_budget.py` writes and `wake-budget-env.sh` exports as `WAKE_BUDGET_LANE` - and
# pins the cheapest lane on the provider this prepaid balance funds (`deepseek-flash`, 0.15/0.60
# USD per M, against `deepseek-v4-pro`'s 0.66/1.98) whenever the tier is not `ok`.
# The `-Model` argument is carried to `wake-run.ps1` on the desktop, which applies it to
# `$env:WAKE_AGENT_MODEL` before it calls the resolver.
# company-api's own lane (`smart_router.py:833` secretary-fast, gated by
# `smart_router.py:1609` premium_cost_threshold()) is NOT patched here: /opt/company is
# read-only for this workstream. The report carries the exact hook and why it is undeployed.
LANE=${WAKE_BUDGET_LANE:-}
if [ -z "$LANE" ]; then
  LANE=$(python3 - "${WAKE_BUDGET_FILE:-$HOME/.sms-inbox/wake-budget.json}" <<'PY' 2>/dev/null || true
import json, sys
try:
    d = json.load(open(sys.argv[1], encoding="utf-8"))
    tier = str(d.get("tier") or "")
    print("" if tier == "ok" else (d.get("lane") or ""))
except Exception:
    print("")
PY
)
fi
# --- CAPABILITY LADDER, BY PRIORITY (2026-10-18) ---------------------------
# Until today the seat model depended ONLY on the balance tier, so priority and kind were invisible
# to it and a customer-facing critical repair got the same model as a routine tidy-up. Measured
# distribution: 4 high vs 25 normal releases in one day. Every failure on a high row costs a whole
# shift, so a stronger lane there is worth cents against the daily ceiling; the balance lever above
# still forces the cheap lane whenever the tier is not `ok`.
#
# THE ID COMES FROM THE LIVE CATALOG, NEVER A LITERAL. A hardcoded model name is a time bomb on
# this estate (journal L1606: every live AI call failed for a week while a fallback hid it). If
# nothing in the preference chain is listed, LANE stays empty and the default seat is used --
# a missing or unreadable catalog must never make this guess.
# DISABLED BY DEFAULT 2026-10-18: this pinned deepseek/deepseek-v4-pro from the LOCAL catalog file
# and the runner validates against a LIVE catalog, so wake #1123 and #1186 FAILED at 05:08 with
# "FAIL-LOUD UNRESOLVED ... could not validate". Two shifts, on a lane that had never been run.
# The code is kept so the next round can point it at the catalog the runner actually reads; it is
# inert until WAKE_CAPABILITY_LANE=1 is exported by whoever has proved the id.
if [ -z "$LANE" ] && [ "$PRIORITY" = "high" ] && [ "${WAKE_CAPABILITY_LANE:-0}" = "1" ]; then
  # ITEM 587 (2026-10-22). The gateway catalog FILE lists only the PREFIXED id
  # deepseek/deepseek-v4-pro, so the old resolution here silently pinned nothing.
  # The catalog the runner actually validates against is
  # https://api.deepseek.com/v1/models, and MEASURED 2026-10-22 it lists the BARE
  # id deepseek-v4-pro (and deepseek-flash). Pin that exact id here.
  LANE="deepseek-v4-pro"
  LANE_REASON="capability:high-priority"
fi
# Publish which model actually served the shift. Nothing read the choice before, so "the cheaper
# lane is used when balance is low" was unverifiable from the store; this line makes it greppable.
LANE_REASON="${LANE_REASON:-}"
if [ -n "$LANE" ]; then
  echo "$(date -Is) wake #${ID:-?} priority=${PRIORITY:-?} lane=$LANE reason=${LANE_REASON:-balance}" \
    >> "$HOME/.sms-inbox/wake-lane.log" 2>/dev/null || true
fi
LANE_ARG=""
[ -n "$LANE" ] && LANE_ARG=" -Model \"$LANE\""
REMOTE_CMD="powershell -NoProfile -ExecutionPolicy Bypass -File \"$REMOTE_RUNNER\" -PromptFile \"$REMOTE_PROMPT\" -OutFile \"$REMOTE_OUT\" -TimeoutSec $RUNNER_TIMEOUT$LANE_ARG"
SSH_OPTS=(-o BatchMode=yes -o ConnectTimeout=15 -o ServerAliveInterval=30 -o ServerAliveCountMax=10)

SCP_IN=("$SCP_CMD" -q -o BatchMode=yes -o ConnectTimeout=15 "$PROMPT_FILE" "$DESKTOP:$REMOTE_PROMPT_SCP")
SSH_RUN=("$SSH_CMD" "${SSH_OPTS[@]}" "$DESKTOP" "$REMOTE_CMD")
TIMEOUT_RUN=(timeout -k 30 "$TIMEOUT" "${SSH_RUN[@]}")
SCP_BACK=("$SCP_CMD" -q -o BatchMode=yes -o ConnectTimeout=15 "$DESKTOP:$REMOTE_OUT_SCP" "$LOCAL_OUT")
if [ "$NODE_KIND" = authority ] || [ "$NODE_KIND" = local ]; then
  # LOCAL NODE (item 144): the prompt is already a file on this host, the runner
  # is bash, and no scp/ssh is built at all. The out-file is written in place, so
  # step 8 below reads it exactly as it reads a copied-back one.
  if [ ! -x "$LOCAL_RUNNER" ]; then
    err "local node requested but the runner is not executable: $LOCAL_RUNNER"
    exit 2
  fi
  REMOTE_PROMPT=$PROMPT_FILE
  REMOTE_OUT=$LOCAL_OUT
  REMOTE_PROMPT_SCP=$REMOTE_PROMPT
  REMOTE_OUT_SCP=$REMOTE_OUT
  REMOTE_CMD="$LOCAL_RUNNER --prompt-file \"$PROMPT_FILE\" --out-file \"$LOCAL_OUT\" --timeout-sec $RUNNER_TIMEOUT --release-id $ID --run-token $RUN_TOKEN --sidecar-dir \"${WAKE_SIDECAR_DIR:-$HOME/.sms-inbox}\""
  SCP_IN=()
  SCP_BACK=()
  TIMEOUT_RUN=(timeout -k 30 "$TIMEOUT" "$LOCAL_RUNNER" --prompt-file "$PROMPT_FILE" --out-file "$LOCAL_OUT" --timeout-sec "$RUNNER_TIMEOUT" --profile headless --release-id "$ID" --run-token "$RUN_TOKEN" --sidecar-dir "${WAKE_SIDECAR_DIR:-$HOME/.sms-inbox}")
fi

# ---------------------------------------------------------------------------
# 5b. THE ALTERNATE READ (2026-10-02). When the session ran but scp could not
#     bring its out-file back, this dispatcher used to close the row `failed`
#     with the words "the result is unverified" - and the store had no way to
#     tell that from a session that never worked (wake #498, 2026-10-02). Before
#     anything is called unverified, READ THE FILE OVER THE HOP: the bytes are
#     still on the desktop, and scp can fail while ssh works (a locked file, a
#     banner on the pipe, a truncated transfer). `[Convert]::ToBase64String`
#     gets them back byte-exact through a Windows console that would otherwise
#     mangle the answer. Only if ssh cannot read it either is the result really
#     unreadable. Built here, beside the other hop commands, so a dry run prints
#     the recovery path it would take.
# ---------------------------------------------------------------------------
ALT_READ_OUT="$STAGE/alt-read.b64"
ALT_READ_TIMEOUT=${WAKE_ALT_READ_TIMEOUT_SEC:-45}
ALT_READ_RUN=()
ALT_READ_ARGS=()
if [ -n "${WAKE_ALT_READ_CMD:-}" ]; then
  # Ops/test override: a command line whose stdout is that file's bytes
  # base64-encoded, and to which the remote path is passed as its LAST argument.
  # Word-split deliberately.
  read -r -a ALT_READ_RUN <<<"${WAKE_ALT_READ_CMD}"
  ALT_READ_ARGS=("$REMOTE_OUT")
elif [ "$NODE_KIND" = desktop ]; then
  # `-EncodedCommand` takes a UTF-16LE base64 SCRIPT, so what the remote shell
  # sees is ONE token with no quotes and no spaces - nothing for cmd.exe or
  # PowerShell to re-parse. The quoted `-Command "[Convert]::..."` form was tried
  # first and came back "ParserError ... UnexpectedToken" through the real hop
  # (measured 2026-10-02): a Windows argument inside an ssh command inside a bash
  # array is three parsers deep, and quoting that is a losing game. The path is
  # INSIDE the encoded script, so this form takes no argument of its own (passing
  # one makes PowerShell answer "a command is already specified with -Command or
  # -EncodedCommand"). Verified against the real desktop, read-only, same day.
  ALT_READ_PS="[Convert]::ToBase64String([IO.File]::ReadAllBytes('$REMOTE_OUT'))"
  ALT_READ_ENC=$("$PY" -c \
    'import base64,sys; sys.stdout.write(base64.b64encode(sys.argv[1].encode("utf-16-le")).decode())' \
    "$ALT_READ_PS" 2>/dev/null || true)
  if [ -z "$ALT_READ_ENC" ]; then
    ALT_READ_RUN=()          # no encoder -> no alternate read, never a wrong one
  else
    ALT_READ_RUN=("$SSH_CMD" "${SSH_OPTS[@]}" "$DESKTOP" \
                  "powershell -NoProfile -EncodedCommand $ALT_READ_ENC")
  fi
fi

if [ "$DRY_RUN" = 1 ]; then
  PROMPT_BYTES=$(wc -c <"$PROMPT_FILE" 2>/dev/null || echo 0)
  say "wake dispatch --dry-run   ($(now_iso))  host=$(hostname 2>/dev/null || echo '?')"
  say "  lock:      $LOCK (acquired)"
  say "  gates:     releases today $RELEASES_TODAY/$MAX_PER_DAY, spend today \$$SPEND_TODAY/\$$MAX_USD_PER_DAY, pause file absent"
  say_aim
  say "  reap:      $(oneline "${REAP_OUT:-<no output>}")"
  say "  claim:     would claim wake #$ID (priority=$PRIORITY, by=$CALLSIGN) — simulated from \`list --state new\`; the real run calls \`claim\`, which applies the store guards (per-source cap, cooldown, night gate) too"
  say "  prompt:    $PROMPT_BYTES bytes -> $PROMPT_FILE (the wake contract, then the store's prompt - one builder, so this is byte-for-byte what a release sends)"
  say "  would run:"
  if [ "$NODE_KIND" = authority ] || [ "$NODE_KIND" = local ]; then
    say "    1. (local node: no transfer - the prompt file is $PROMPT_FILE on this host)"
  else
    say "    1. $(render "${SCP_IN[@]}")"
  fi
  say "    2. $(render "${TIMEOUT_RUN[@]}")"
  say "       (lease ${LEASE}s, heartbeat every ${HEARTBEAT}s, hard timeout ${TIMEOUT}s, runner self-bound ${RUNNER_TIMEOUT}s, child-turn cap ${TURN_CAP}s)"
  if [ "$NODE_KIND" = authority ] || [ "$NODE_KIND" = local ]; then
    say "    3. (local node: the out-file is written in place at $LOCAL_OUT)"
  else
    say "    3. $(render "${SCP_BACK[@]}")"
  fi
  if [ "${#ALT_READ_RUN[@]}" -gt 0 ]; then
    say "    3b. $(render "${ALT_READ_RUN[@]}" "${ALT_READ_ARGS[@]}")   # ONLY if step 3 failed: read the out-file over the hop before calling the result unverified"
  else
    say "    3b. (no alternate read on this node: the out-file is already local, or no reader could be built)"
  fi
  say "    4. $PY $WAKE_CLI finish $ID --outcome \"<bounded outcome>\"   # or --failed on any failure, or --unverified when the session ran and its result could not be read back"
  say "  would log: released $TODAY wake #$ID done exit=0 cost=none dur=<secs> subject=\"$SUBJ\""
  say "  no claim, no ssh, no scp, no dsh, and no log write. reap ran (the maintenance the"
  say "  real run performs every tick); nothing else touched the store."
  exit 0
fi

DUR_START=$(date -u +%s)
log "releasing wake #$ID ($(oneline "$SUBJ")) by $CALLSIGN -> $NODE_LABEL"

# ---------------------------------------------------------------------------
# 6. Transfer the prompt. It travels as a FILE precisely so no nested quoting
#    is ever constructed anywhere on this path.
# ---------------------------------------------------------------------------
if [ "$NODE_KIND" = authority ] || [ "$NODE_KIND" = local ]; then
  : # local node: the prompt file is already on this host, nothing to transfer
else
  # THE PROMPT COPY IS THE ONE STEP WITH NO RECOVERY, AND IT IS THE STEP THAT KILLS THE SUBJECT.
  # Measured 2026-10-18: every real failure in the preceding 48 hours read
  #   prompt transfer to zabz-tech-ts failed (C:/Users/ezabz/bin/wake-prompt-<id>.txt);
  #   no session was started
  # -- 20 of the 30 rows finished in one day, and ten of them were at attempts=2 of max=2, i.e.
  # permanently dead work items. The per-instance ssh log shows `scp: Connection closed` 13-15 s
  # in, with the desktop reachable and ~188 GB free: the transport died under a burst of
  # concurrent dispatchers, not the path and not the disk. A single attempt turned a transient
  # ssh refusal into a LOST WORK ITEM, and the stored outcome carried neither the rc nor the
  # stderr, so the row could not be diagnosed from the store afterwards.
  # So: two attempts with a short backoff, and the real error carried into the outcome.
  # This is a transport retry only -- it never re-sends a prompt that already landed, because a
  # successful copy breaks the loop immediately.
  scp_rc=0
  scp_err=""
  for scp_attempt in 1 2; do
    scp_rc=0
    "${SCP_IN[@]}" >>"$SSH_LOG" 2>&1 || scp_rc=$?
    [ "$scp_rc" -eq 0 ] && break
    scp_err=$(tail -n 2 "$SSH_LOG" 2>/dev/null | tr '\n' ' ' | cut -c1-160)
    log "wake #$ID: prompt transfer attempt $scp_attempt failed (scp rc=$scp_rc): $scp_err"
    if [ "$scp_attempt" = 1 ]; then sleep 3; fi
  done
  if [ "$scp_rc" -ne 0 ]; then
    OUTCOME="prompt transfer to $DESKTOP failed after 2 attempts (scp rc=$scp_rc): $scp_err; no session was started"
    log "released $TODAY wake #$ID failed exit=n/a cost=none dur=0s subject=\"$(oneline "$SUBJ")\""
    log "  outcome: $OUTCOME"
    "$PY" "$WAKE_CLI" finish "$ID" --failed --outcome "$OUTCOME" >/dev/null 2>&1 || log "ERROR finish failed for wake #$ID"
    FINISHED=1
    exit 1
  fi
fi

# ---------------------------------------------------------------------------
# 7. Run the session, heartbeating the lease while it runs so a long session is
#    never reaped and double-run.
# ---------------------------------------------------------------------------
: >"$SSH_LOG"
# COMMIT-THE-RESULT (item 143): the copied-back path is FIXED and reused by
# every release, so an out-file left by an earlier run could be mistaken for
# this session's answer. Remove it before the hop; after this, a present
# out-file can only be this session's own, and its absence is a real absence.
rm -f "$LOCAL_OUT"
"${TIMEOUT_RUN[@]}" >>"$SSH_LOG" 2>&1 &
SESS_PID=$!
# The ssh hop is already bounded by `timeout`, but this loop must never be able
# to outlive it: a reaped-but-not-yet-noticed child would otherwise spin the
# heartbeat forever. Belt: stop waiting 2 minutes past the outer bound.
LOOP_DEADLINE=$(( $(date -u +%s) + TIMEOUT + 120 ))

# ---------------------------------------------------------------------------
# WAKE-STORE LOCK HOLDERS (ledger item 584).
# A heartbeat refused with `database is locked` used to record only the error.
# SQLite keeps no history of a lock holder, so the failure itself is the only
# moment it can be named: scan /proc/*/fd (no lsof) for processes with the store
# open and record each PID with its command line. The path follows the same
# SMS_INBOX_DB override wake.py uses, so a test store is named correctly.
# ---------------------------------------------------------------------------
wake_store_path() {
  printf '%s' "${SMS_INBOX_DB:-${WAKE_STORE:-$HOME/.sms-inbox/inbox.db}}"
}

wake_db_holders() {
  "$PY" - "$(wake_store_path)" <<'PY' 2>/dev/null
import os, sys
target = os.path.realpath(sys.argv[1])
me = os.getpid()
out = []
for d in os.listdir("/proc"):
    if not d.isdigit() or int(d) == me:
        continue
    try:
        for fd in os.listdir("/proc/%s/fd" % d):
            try:
                if os.path.realpath("/proc/%s/fd/%s" % (d, fd)) == target:
                    try:
                        cmd = open("/proc/%s/cmdline" % d, "rb").read()
                        cmd = cmd.replace(b"\x00", b" ").decode("utf-8", "replace").strip()
                    except OSError:
                        cmd = "?"
                    out.append("pid %s %s" % (d, cmd[:200]))
                    break
            except OSError:
                pass
    except OSError:
        pass
print(" ; ".join(out))
PY
}

lease_probe() {
  # 0 = renewed. 1 = the store itself says we do NOT hold this row: a real loss, and
  # the only thing that may stop a session. 2 = transient (a lock, a timeout, a
  # traceback), which is never a reason to kill work.
  local out rc
  out=$("$PY" "$WAKE_CLI" heartbeat "$ID" --by "$CALLSIGN" --lease-seconds "$LEASE" 2>&1); rc=$?
  if [ "$rc" -eq 0 ]; then
    _LEASE_HOLDERS=""
    _LEASE_LOCK_LOGGED_AT=0
    return 0
  fi
  case "$out" in
    *not-claimed*|*no-such-row*) return 1 ;;
  esac
  _LEASE_LAST_ERR="$(oneline "$out")"
  _LEASE_HOLDERS=""
  case "$out" in
    *"database is locked"*)
      # One line per minute per wake, not one per 5 s retry: a 30 s stall must
      # leave a finding, not bury the log in six copies of it.
      _LEASE_HOLDERS="$(wake_db_holders)"
      local now
      now=$(date -u +%s)
      if [ $(( now - ${_LEASE_LOCK_LOGGED_AT:-0} )) -ge 60 ]; then
        _LEASE_LOCK_LOGGED_AT=$now
        log "WARN heartbeat for wake #$ID: database is locked; holders of $(wake_store_path): ${_LEASE_HOLDERS:-(none visible)}"
      fi
      ;;
  esac
  return 2
}

heartbeat_lease() {
  local rc decision attempt=0
  while :; do
    attempt=$((attempt + 1))
    lease_probe; rc=$?
    decision=$(lease_decision "$rc" "$(date -u +%s)" "$LEASE_DEADLINE" "$LEASE_MARGIN")
    case "$decision" in
      renew)
        LEASE_DEADLINE=$(( $(date -u +%s) + LEASE ))
        if [ "$attempt" -gt 1 ]; then
          log "WARN heartbeat for wake #$ID renewed on attempt $attempt after $((attempt - 1)) transient failure(s): ${_LEASE_LAST_ERR:-no output}"
        fi
        return 0 ;;
      lost)
        if [ "$rc" -eq 1 ]; then
          LEASE_LOSS_REASON="the store reports the row is no longer claimed by us"
        else
          LEASE_LOSS_REASON="the store could not be reached before the lease expired (${LEASE_MARGIN}s margin)"
        fi
        # 2026-10-18: a kill printed "unknown" although this branch always sets the reason above, so
        # the decision and the probe's rc are carried out to the kill line to name the path next time.
        LEASE_DECISION="$decision"; LEASE_RC="$rc"; LEASE_ATTEMPT="$attempt"
        return 1 ;;
      *)
        if [ $(( attempt % 6 )) -eq 1 ]; then
          log "WARN heartbeat for wake #$ID could not renew (attempt $attempt, rc=$rc): ${_LEASE_LAST_ERR:-no output}; retrying while the lease has margin"
        fi
        sleep 5 ;;
    esac
  done
}

# SETTLED_GUARD: read this row's state straight from the store (one primary-key lookup).
# Exists for the 2026-10-18 defect below; it is the only reason the dispatcher reads `state`.
row_state() {
  python3 - "$ID" "${WAKE_STORE:-$HOME/.sms-inbox/inbox.db}" <<'PY' 2>/dev/null || echo unknown
import sqlite3, sys
try:
    c = sqlite3.connect("file:%s?mode=ro" % sys.argv[2], uri=True)
    r = c.execute("select state from wake where id = ?", (sys.argv[1],)).fetchone()
    print(r[0] if r else "missing")
except Exception:
    print("unknown")
PY
}

while kill -0 "$SESS_PID" 2>/dev/null; do
  if [ "$(date -u +%s)" -ge "$LOOP_DEADLINE" ]; then
      LEASE_LOST=1
      OUTCOME_REASON="the session outlived the hard bound by 120s"
      log "ERROR wake #$ID: the session outlived the hard bound by 120s - killing it"
    kill "$SESS_PID" 2>/dev/null
    break
  fi
  sleep "$HEARTBEAT" &
  HB_SLEEP=$!
  while kill -0 "$SESS_PID" 2>/dev/null && kill -0 "$HB_SLEEP" 2>/dev/null; do sleep 1; done
  kill "$HB_SLEEP" 2>/dev/null
  wait "$HB_SLEEP" 2>/dev/null
  if kill -0 "$SESS_PID" 2>/dev/null; then
    # Record the ACTUAL status, not just "non-zero": MEASURED 2026-10-18 the function failed without
    # taking either of its own return paths, and only the number can tell an interrupt (128+N) from a
    # decision. Same condition, same behaviour, one datum kept. No `set -e` in this script.
    heartbeat_lease; HB_RC=$?
    if [ "$HB_RC" -ne 0 ]; then
      # Two different things, and only one of them is a lost lease. Both stop the
      # session: a second dispatcher must never pick up a row this one is running.
      # Before 2026-09-30 this branch also fired on a six-second lock and said
      # "lost three times" about a lease that had nineteen minutes left.
      # IF THE ROW IS ALREADY SETTLED, DO NOT OVERWRITE ITS VERDICT.
      # Measured 2026-10-18, wake #1175: the store read `state=done` with a complete shift report at
      # 02:06:57, and 49 s LATER this branch fired -- "the store reports the row is no longer claimed
      # by us" -- killed the still-running session and re-finished the row as `failed`, destroying the
      # report and refunding the attempt (attempts 2 -> 0). One occurrence in ~1200 rows, and two
      # candidate causes that this guard does not need to tell apart: either a second dispatcher
      # settled the row, or the row was settled by this one while the session process lived on.
      # Under BOTH, the row's verdict is already written and re-writing it is pure data loss. So:
      # kill the session (a second worker must never run the same row), then stop WITHOUT finishing.
      _settled_state=$(row_state)
      if [ "$_settled_state" != "claimed" ] && [ "$_settled_state" != "unknown" ]; then
        log "ERROR lease for wake #$ID: the row is already '$_settled_state' - killing the session but NOT re-finishing it (a settled row's verdict must not be overwritten)"
        kill "$SESS_PID" 2>/dev/null
        FINISHED=1
        exit 0
      fi
      LEASE_LOST=1
      # MEASURED 2026-10-18: this printed "unknown" for three kills while the actual cause --
      # "wake: database error: database is locked" -- sat in _LEASE_LAST_ERR and was discarded.
      # A kill message that cannot say why is the same defect as a monitor that measures nothing.
      OUTCOME_REASON="lease not renewed: ${LEASE_LOSS_REASON:-${_LEASE_LAST_ERR:-unknown}}"
      log "ERROR lease for wake #$ID not renewed - killing the session to avoid a double release: ${LEASE_LOSS_REASON:-${_LEASE_LAST_ERR:-unknown}} [hbrc=${HB_RC:-unset} decision=${LEASE_DECISION:-unset} rc=${LEASE_RC:-unset} attempt=${LEASE_ATTEMPT:-unset} err=${_LEASE_LAST_ERR:-none} holders=${_LEASE_HOLDERS:-none}]"
      kill "$SESS_PID" 2>/dev/null
      break
    fi
  fi
done

wait "$SESS_PID" 2>/dev/null
RELEASE_RC=$?
DUR=$(( $(date -u +%s) - DUR_START ))

# ---------------------------------------------------------------------------
# 8. Bring the result back. Attempted even after a failure, because a partial
#    out-file is the only evidence of what the session did. And: a copy that
#    failed is not yet an unreadable result - try the alternate read first.
#    (Both steps are defined above as functions so a test can prove them without
#    a session: bring_back_out_file sets SCP_BACK_RC and RECOVERED_VIA.)
# ---------------------------------------------------------------------------
bring_back_out_file
bring_back_session_sidecar

RUNNER_CODE=""
COST=""
RUNNER_CODE_MALFORMED=0
if [ -f "$LOCAL_OUT" ]; then
  # Machine-readable line written by runner.ps1; the sed fallback keeps this
  # working against the v0 runner if an older copy is still on the desktop.
  RUNNER_CODE=$(grep -o 'WAKE_EXIT_CODE=[0-9-]*' "$LOCAL_OUT" 2>/dev/null | tail -1 | cut -d= -f2)
  [ -n "$RUNNER_CODE" ] || RUNNER_CODE=$(sed -n 's/.*=== *exit code: *\([0-9-]*\) *===.*/\1/p' "$LOCAL_OUT" 2>/dev/null | tail -1)
  # A present-but-valueless line means the runner failed to report. Fail closed:
  # "I could not read the verdict" is not "it worked".
  if [ -z "$RUNNER_CODE" ] && grep -q 'WAKE_EXIT_CODE=' "$LOCAL_OUT" 2>/dev/null; then
    RUNNER_CODE_MALFORMED=1
  fi
  COST=$(grep -o 'WAKE_COST_USD=[0-9][0-9.]*' "$LOCAL_OUT" 2>/dev/null | tail -1 | cut -d= -f2)
fi
# The extractor is defined above the WAKE_LIB_ONLY guard, so a test can prove
# what THIS file returns without running the dispatcher.
extract_result_text "$LOCAL_OUT"

# ---------------------------------------------------------------------------
# 9. Decide success. ssh rc alone is not enough: the runner reports the exit
#    code of `dsh --profile headless` itself, and a run that aborted exits 1
#    inside a perfectly successful ssh hop.
# ---------------------------------------------------------------------------
SUCCESS=0
# WHAT A KILLED SESSION LOST. "failed" alone does not say whether the work was
# never started or was cut in the middle of doing it, and the difference is what
# the next session has to know. Every kill path says the bound, the elapsed time
# and that the work may be half-done.
LOSS_NOTE="the bound cut the session while it was working: the work may be half-done, only output that reached the out-file survived"

if [ "$LEASE_LOST" = 1 ]; then
  SUCCESS=1
  OUTCOME="$OUTCOME_REASON; session killed so it could not be double-run (session ran ${DUR}s) - LOST: $LOSS_NOTE"
elif [ "$RELEASE_RC" -eq 124 ] || [ "$RELEASE_RC" -eq 137 ] || [ "$RELEASE_RC" -eq 143 ]; then
  SUCCESS=1
  OUTCOME="timed out after ${TIMEOUT}s (session killed at the OUTER bound; runner self-bound ${RUNNER_TIMEOUT}s) after ${DUR}s - LOST: $LOSS_NOTE; last output: $RESULT_TEXT"
elif [ "$RELEASE_RC" -ne 0 ]; then
  # A runner that hit its OWN bound is not a network failure, and calling it one
  # is how the 2026-09-20 defect stayed invisible: wake #8/#10 were recorded as
  # "ssh hop failed (rc=1)" when the runner had in fact killed a working session
  # at its bound and said so (WAKE_EXIT_CODE=124). Name the real cause - and say
  # what it cost.
  # NEVER_STARTED is terminal for this verdict. It is a separate variable because the block
  # below is an INDEPENDENT if/elif chain that assigns OUTCOME again: until 2026-10-27 the
  # boot-refusal branch above it was therefore INERT. MEASURED: `grep -c "the session never
  # started" wake-dispatch.log` = 0 after six days, while 2026-10-21T13:08:19Z and
  # 2026-10-25T06:44:20Z releases with runner exit 3 were still recorded as "ssh hop failed
  # (rc=1) ... out-file was recovered (runner exit 3)" and still spent their item's attempt.
  # A fix nobody has seen fire is not a fix.
  NEVER_STARTED=0
  # READ THE MARKER FROM THE FILE, NOT FROM $RESULT_TEXT. MEASURED 2026-10-27 23:48Z, on the
  # first attempt at this very fix: $RESULT_TEXT is `bounded()` output, which runs
  # `tr '\t\r\n' '   '` and so squashes every newline to a space, and it is only the last 2000
  # bytes of the transcript. An ANCHORED grep ('^WAKE_NOT_STARTED=1') therefore cannot match it
  # even when the marker is present - the release recorded the old "ssh hop failed ... out-file
  # was recovered" line, spent the attempt, and a test row proved it. Grep the out-file itself.
  if grep -q '^WAKE_NOT_STARTED=1' "$LOCAL_OUT" 2>/dev/null; then
    # THE LAUNCHER NEVER RAN DSH (2026-10-27). The runner says so itself, in its own marker,
    # with a positive third-party signal (npm's error vocabulary) - see wake-run.ps1. Nothing
    # was attempted, so the item must keep its attempt: the vocabulary below is the exact
    # prefix wake.py's _retryable_reason matches to refund it with a 1800 s backoff.
    NEVER_STARTED=1
    SUCCESS=1
    BOOT_CAUSE=$(grep -m1 '^WAKE_NOT_STARTED_REASON=' "$LOCAL_OUT" 2>/dev/null | cut -d= -f2- | cut -c1-240)
    OUTCOME="the session never started: after ${DUR}s the launcher could not start dsh (runner exit ${RUNNER_CODE:-unknown}) - ${BOOT_CAUSE:-the runner reported that no session was launched}. No work was attempted, so the item's attempt is refunded and it retries later."
  elif [ "$RUNNER_CODE" = "3" ] && { grep -qiE 'refusing to boot|FAIL-LOUD UNRESOLVED' "$LOCAL_OUT" 2>/dev/null || printf '%s' "$RESULT_TEXT" | grep -qiE 'refusing to boot|FAIL-LOUD UNRESOLVED'; }; then
    # A SESSION THAT NEVER STARTED IS NOT A FAILED SUBJECT. MEASURED 2026-10-21 13:08:19Z and
    # 13:08:20Z: two releases died in 13 s because the model resolver returned no model on the
    # desktop ("model: FAIL-LOUD UNRESOLVED ... HttpClient.Timeout of 8 seconds"). The line this
    # branch replaces read "ssh hop failed ... but the session's out-file was recovered (runner
    # exit 3)", and wake.py's _retryable_reason EXCLUDES any line carrying "out-file was
    # recovered" on purpose - so no work was attempted AND the item spent one of its two
    # attempts. A model outage of a few minutes could permanently kill items nobody had looked at.
    #
    # The contract with wake.py is the FIRST LINE: _RETRY_PREFIX_SIGNATURES matches
    # "the session never started" and refunds the attempt with a 1800 s backoff, so an outage
    # costs about two retries an hour per subject instead of draining the queue, and no subject
    # is ever spent. Only the resolver's own words are quoted - never the raw out-file, which
    # would re-introduce the exclusion this branch exists to remove.
    SUCCESS=1
    BOOT_CAUSE=$(printf '%s' "$RESULT_TEXT" | grep -oiE '(model: FAIL-LOUD UNRESOLVED|refusing to boot)[^;]*' | head -1 | cut -c1-240)
    OUTCOME="the session never started: the runner refused to boot after ${DUR}s (runner exit 3) - ${BOOT_CAUSE:-the runner reported a boot refusal with no cause line}. No work was attempted, so the item's attempt is refunded and it retries later."
    NEVER_STARTED=1
  fi
  if [ "$NEVER_STARTED" = 1 ]; then
    # The verdict above is final: no session existed, so there is no result to recover and
    # nothing that a later branch may reinterpret. Before this guard the RESULT_PRESENT branch
    # below rewrote it to "ssh hop failed ... out-file was recovered", which wake.py refuses to
    # retry - the exact opposite of what the branch above had just decided.
    :
  elif [ "$RUNNER_CODE" = "124" ]; then
    SUCCESS=1
    OUTCOME="the desktop runner hit its own ${RUNNER_TIMEOUT}s bound and killed the session (exit 124) after ${DUR}s - that is a bound cutting live work, not a lost hop. LOST: $LOSS_NOTE; desktop output: $(bounded "$(tail -c 2000 "$SSH_LOG")")"
  elif [ "$RESULT_PRESENT" = 1 ]; then
    # COMMIT-THE-RESULT (item 143). The hop returned nonzero, but the child had
    # already written its out-file and scp brought it back. Measured 2026-09-30:
    # wake #8/#9/#10/#11 read "ssh hop failed (rc=1) after 843s; desktop output:
    # ** WARNING: ... post-quantum key exchange ..." - the hop's stderr banner
    # became the outcome while the session's answer sat in the out-file. Prefer
    # the session's own bytes and keep the hop failure visible in the same line.
    # WHICH PATH brought them back is recorded too: "recovered" without saying how
    # is the same unverifiable claim this item exists to remove.
    if [ "$RUNNER_CODE" = "0" ]; then
      SUCCESS=0
      OUTCOME="the ssh hop returned rc=$RELEASE_RC after ${DUR}s, but the session completed (runner exit 0) and its out-file was $(recovery_note): $RESULT_TEXT"
    else
      SUCCESS=1
      OUTCOME="ssh hop failed (rc=$RELEASE_RC) after ${DUR}s, but the session's out-file was $(recovery_note) (runner exit ${RUNNER_CODE:-unknown}); output: $RESULT_TEXT"
    fi
  else
    SUCCESS=1
    OUTCOME="ssh hop failed (rc=$RELEASE_RC) after ${DUR}s; desktop output: $(bounded "$(tail -c 2000 "$SSH_LOG")")"
  fi
elif [ "$SCP_BACK_RC" -ne 0 ]; then
  # THE SCP FAILURE THAT IS NOT A SESSION FAILURE (2026-10-02). Two different
  # facts used to wear one word here. If the out-file was recovered - by scp on a
  # retry, or by the alternate read over the hop - the session's own bytes decide
  # the verdict, exactly as in the item-143 block above. Only a result nobody could
  # read is `unverified`: a third outcome, which does not consume an attempt and
  # does not count as a failure, because the session may have finished its work
  # perfectly and we simply failed to collect the evidence.
  if [ "$RESULT_PRESENT" = 1 ]; then
    if [ "$RUNNER_CODE" = "0" ]; then
      SUCCESS=0
      OUTCOME="the output file could not be copied back (scp rc=$SCP_BACK_RC) after ${DUR}s, but the session completed (runner exit 0) and its out-file was $(recovery_note): $RESULT_TEXT"
    else
      SUCCESS=1
      OUTCOME="the output file could not be copied back (scp rc=$SCP_BACK_RC) after ${DUR}s; the out-file was $(recovery_note) and the runner exited ${RUNNER_CODE:-unknown}: $RESULT_TEXT"
    fi
  else
    UNVERIFIED=1
    OUTCOME="the session ran for ${DUR}s but its result could not be read back (scp rc=$SCP_BACK_RC, alternate read rc=${ALT_READ_RC:-not-attempted}) - UNVERIFIED, not failed: the session's own verdict is unknown, so this row does not consume an attempt and is not counted as a failure"
  fi
elif [ "$RUNNER_CODE_MALFORMED" = 1 ]; then
  SUCCESS=1
  OUTCOME="the runner's exit-code line was unreadable, so the session's verdict is unknown (failing closed); output: $RESULT_TEXT"
elif [ -n "$RUNNER_CODE" ] && [ "$RUNNER_CODE" != "0" ]; then
  SUCCESS=1
  OUTCOME="dsh exited $RUNNER_CODE; output: $RESULT_TEXT"
else
  if [ "$ANSWER_PRESENT" != 1 ]; then
    # A SESSION THAT ANSWERED NOTHING DID NOT REPORT A RESULT.
    # Measured 2026-10-18: `done` meant "the runner exited 0 and the out-file has bytes", and the
    # runner writes its header BEFORE it launches -- so every started run is non-empty, and a
    # session that booted, did nothing and exited 0 was recorded as `done`. Nothing in the store
    # could tell that apart from real work, which is why every downstream number ("11 items closed
    # today", "0.089 USD per closed item") rested on an unverified claim. The answer section is now
    # REQUIRED: absent, the row is `unverified` -- which refunds the attempt and is not counted as
    # a failure -- because "we cannot tell" and "it worked" must never be the same word.
    UNVERIFIED=1
    OUTCOME="the session exited 0 after ${DUR}s but produced NO ANSWER in the out-file's final-answer section, so it cannot be recorded as done (unverified; attempt refunded); out-file ${LOCAL_OUT}"
  else
    OUTCOME="$RESULT_TEXT"
  fi
fi
# The outcome column is for a human reading `wake.py list`, not for a log dump.
OUTCOME=$(bounded "$OUTCOME")

# ---------------------------------------------------------------------------
# 10. Close the row. Always. Never leave a claim dangling.
# ---------------------------------------------------------------------------
if [ "$UNVERIFIED" = 1 ]; then
  STATE=unverified
elif [ "$SUCCESS" -eq 0 ]; then
  STATE=done
else
  STATE=failed
fi

if [ "$STATE" = done ]; then
  if [ -n "$COST" ]; then
    "$PY" "$WAKE_CLI" finish "$ID" --outcome "$OUTCOME" --cost-usd "$COST" >/dev/null 2>&1
  else
    "$PY" "$WAKE_CLI" finish "$ID" --outcome "$OUTCOME" >/dev/null 2>&1
  fi
elif [ "$STATE" = unverified ]; then
  "$PY" "$WAKE_CLI" finish "$ID" --unverified --outcome "$OUTCOME" >/dev/null 2>&1
else
  "$PY" "$WAKE_CLI" finish "$ID" --failed --outcome "$OUTCOME" >/dev/null 2>&1
fi
FINISH_RC=$?
FINISHED=1
if [ "$FINISH_RC" -ne 0 ]; then
  log "ERROR finish failed (rc=$FINISH_RC) for wake #$ID; reap will recover the lease"
fi

log "released $TODAY wake #$ID $STATE exit=${RELEASE_RC} runner_code=${RUNNER_CODE:-?} cost=${COST:-none} dur=${DUR}s subject=\"$(oneline "$SUBJ")\""
log "  outcome: $OUTCOME"
[ -n "$COST" ] || log "  cost: not reported by this harness surface (dsh --profile headless prints no cost)"
log "  staging: $(to_scp "$REMOTE_PROMPT") and $(to_scp "$REMOTE_OUT") (kept on the desktop; names are unique per release, so they cannot collide and need no cleanup)"

if [ "$SUCCESS" -eq 0 ] && [ "$UNVERIFIED" -eq 0 ]; then
  exit 0
fi
if [ "$UNVERIFIED" = 1 ]; then
  # NOT a failure: exit 1 so the tick is still noticed, but say which fact this
  # was, because the store now records the difference.
  printf '%s: wake #%s UNVERIFIED (not failed; attempt refunded): %s\n' \
    "$PROG" "$ID" "$(bounded "$OUTCOME" 300)" >&2
  exit 1
fi
printf '%s: wake #%s failed: %s\n' "$PROG" "$ID" "$(bounded "$OUTCOME" 300)" >&2
exit 1
