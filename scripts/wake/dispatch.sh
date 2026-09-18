#!/usr/bin/env bash
# =============================================================================
# wake dispatch — the RELEASE half of the wake system.
#
# WHAT THIS IS. Something on the authority files a flag (a `wake` row). This
# script, run from cron on secratary, turns exactly ONE flag into a real DSH
# session on the always-on desktop and brings the result back:
#
#   scp  prompt file  ->  ZABZ-TECH:C:\Users\ezabz\bin\wake-prompt.txt
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
#      bounds itself too, so a killed ssh cannot leave an orphan dsh behind.
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

# --- runtime configuration (env-overridable; contract names kept verbatim) ---
PY=${WAKE_PYTHON:-python3}
WAKE_CLI=${WAKE_CLI:-$HOME/bin/wake.py}          # the §5 CLI this codes against
DESKTOP=${WAKE_DESKTOP:-zabz-tech-ts}            # always-on desktop, over the mesh
REMOTE_DIR_WIN=${WAKE_REMOTE_DIR:-'C:\Users\ezabz\bin'}
REMOTE_RUNNER=${WAKE_RUNNER:-$REMOTE_DIR_WIN'\wake-run.ps1'}
REMOTE_PROMPT=${WAKE_REMOTE_PROMPT:-$REMOTE_DIR_WIN'\wake-prompt.txt'}
REMOTE_OUT=${WAKE_REMOTE_OUT:-$REMOTE_DIR_WIN'\wake-out.txt'}
LOG=${WAKE_LOG:-$HOME/.sms-inbox/wake-dispatch.log}
STAGE=${WAKE_STAGE_DIR:-$HOME/.sms-inbox/wake-stage}
LOCK=${WAKE_LOCK_FILE:-$HOME/.sms-inbox/wake-dispatch.lock}
PAUSE_FILE=${WAKE_PAUSE_FILE:-$HOME/.sms-inbox/WAKE_PAUSED}
MAX_PER_DAY=${WAKE_MAX_PER_DAY:-8}
MAX_USD_PER_DAY=${WAKE_MAX_USD_PER_DAY:-3.0}
LEASE=${WAKE_LEASE_SEC:-1200}
HEARTBEAT=${WAKE_HEARTBEAT_SEC:-60}
TIMEOUT=${WAKE_TIMEOUT_SEC:-900}
OUTCOME_BYTES=${WAKE_OUTCOME_BYTES:-600}
SSH_CMD=${WAKE_SSH_CMD:-ssh}
SCP_CMD=${WAKE_SCP_CMD:-scp}
CALLSIGN=${WAKE_CALLSIGN:-wake-dispatch@$(hostname -s 2>/dev/null || echo unknown)}

# The desktop runner bounds itself inside our own bound, so a killed ssh cannot
# leave a dsh session running on the desktop forever. It must stay strictly
# smaller than the outer bound: with WAKE_TIMEOUT_SEC=30 the naive `-60` clamp
# produced a LARGER inner bound (60 > 30) and defeated the whole point, which the
# verification suite caught (S2). WAKE_TIMEOUT_SEC itself is never overridden -
# an explicit setting by the operator is theirs, not ours to "fix".
RUNNER_TIMEOUT=$((TIMEOUT - 60))
[ "$RUNNER_TIMEOUT" -lt $((TIMEOUT * 4 / 5)) ] && RUNNER_TIMEOUT=$((TIMEOUT * 4 / 5))
[ "$RUNNER_TIMEOUT" -lt 5 ] && RUNNER_TIMEOUT=5
[ "$RUNNER_TIMEOUT" -ge "$TIMEOUT" ] && RUNNER_TIMEOUT=$((TIMEOUT - 1))
[ "$RUNNER_TIMEOUT" -lt 1 ] && RUNNER_TIMEOUT=1
# A heartbeat interval at or above the lease is a misconfiguration: halve it.
if [ "$HEARTBEAT" -ge "$LEASE" ]; then HEARTBEAT=$((LEASE / 2)); [ "$HEARTBEAT" -lt 5 ] && HEARTBEAT=5; fi

# --- state --------------------------------------------------------------------
DRY_RUN=0
CLAIMED_ID=""
FINISHED=0
LEASE_LOST=0
SESS_PID=""
OUTCOME_REASON=""
RELEASE_RC=""
RUNNER_CODE=""
COST=""
ID=""; SUBJ=""; PRIORITY=""

now_iso() { date -u +%Y-%m-%dT%H:%M:%SZ; }
today_utc() { date -u +%Y-%m-%d; }
log() {
  # A dry run must not touch the audit log: the log is what the daily cap is
  # counted from, and a rehearsal must not be mistaken for a release.
  [ "$DRY_RUN" = 1 ] && return 0
  printf '%s %s\n' "$(now_iso)" "$*" >>"$LOG" 2>/dev/null || true
}
err() { printf '%s: %s\n' "$PROG" "$*" >&2; log "ERROR $*"; }
say() { printf '%s\n' "$*"; }
oneline() { printf '%s' "$1" | tr '\t\r\n' '   '; }
# bound a blob to N characters, single line, for the store's outcome column
bounded() { local t; t=$(printf '%s' "$1" | tr '\t\r\n' '   '); printf '%s' "${t:0:$OUTCOME_BYTES}"; }
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

  $PROG [--dry-run] [--help]

  --dry-run   run the whole decision path (reap, gates, select, build the exact
              commands) and print what it would do. No claim, no ssh, no scp, no
              dsh, no log write. `reap` does run: it is the same maintenance a
              real tick performs, and it is what makes the rehearsal honest.

Env: WAKE_CLI WAKE_PYTHON WAKE_DESKTOP WAKE_REMOTE_DIR WAKE_REMOTE_RUNNER
     WAKE_REMOTE_PROMPT WAKE_REMOTE_OUT WAKE_LOG WAKE_STAGE_DIR WAKE_LOCK_FILE
     WAKE_CALLSIGN WAKE_SSH_CMD WAKE_SCP_CMD WAKE_TIMEOUT_SEC WAKE_HEARTBEAT_SEC
     WAKE_OUTCOME_BYTES, plus the contract names WAKE_MAX_PER_DAY
     WAKE_MAX_USD_PER_DAY WAKE_LEASE_SEC WAKE_PAUSE_FILE.
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run|-n) DRY_RUN=1 ;;
    --help|-h) usage; exit 0 ;;
    *) err "unknown argument: $1"; usage >&2; exit 2 ;;
  esac
  shift
done

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
SPEND_TODAY=$(awk -v d="$TODAY" '
  index($0, " released " d " wake #") {
    for (i = 1; i <= NF; i++) if ($i ~ /^cost=/) { s += substr($i, 6) + 0 }
  }
  END { printf "%.4f", s + 0 }' "$LOG" 2>/dev/null)
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

SELECT_PY='
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
with open(sys.argv[1], "w", encoding="utf-8") as f:
    f.write(r.get("prompt") or "")
'

CLAIM_PY='
import json, sys
try:
    d = json.load(open(sys.argv[1], encoding="utf-8"))
except Exception:
    sys.exit(3)
row = d.get("row") if isinstance(d, dict) else None
if row is None:
    sys.exit(10)
with open(sys.argv[2], "w", encoding="utf-8") as f:
    f.write(row.get("prompt") or "")
sys.stdout.write("\t".join([
    str(row.get("id") or ""), str(row.get("subject") or ""), str(row.get("priority") or "")]))
'

if [ "$DRY_RUN" = 1 ]; then
  LIST_OUT=$("$PY" "$WAKE_CLI" list --state new --json --limit 500 2>/dev/null)
  SELECTED=$(printf '%s' "$LIST_OUT" | "$PY" -c "$SELECT_PY" "$PROMPT_FILE" 2>/dev/null); SEL_RC=$?
  case "$SEL_RC" in
    10) say "dry-run: nothing to release (no row is new and eligible)"; exit 0 ;;
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
fi

# ---------------------------------------------------------------------------
# 5. Build the exact commands. Built identically in both modes, so what a dry
#    run prints is character-for-character what a release runs.
# ---------------------------------------------------------------------------
REMOTE_PROMPT_SCP=$(to_scp "$REMOTE_PROMPT")
REMOTE_OUT_SCP=$(to_scp "$REMOTE_OUT")
REMOTE_CMD="powershell -NoProfile -ExecutionPolicy Bypass -File \"$REMOTE_RUNNER\" -PromptFile \"$REMOTE_PROMPT\" -OutFile \"$REMOTE_OUT\" -TimeoutSec $RUNNER_TIMEOUT"
SSH_OPTS=(-o BatchMode=yes -o ConnectTimeout=15 -o ServerAliveInterval=30 -o ServerAliveCountMax=10)

SCP_IN=("$SCP_CMD" -q -o BatchMode=yes -o ConnectTimeout=15 "$PROMPT_FILE" "$DESKTOP:$REMOTE_PROMPT_SCP")
SSH_RUN=("$SSH_CMD" "${SSH_OPTS[@]}" "$DESKTOP" "$REMOTE_CMD")
TIMEOUT_RUN=(timeout -k 30 "$TIMEOUT" "${SSH_RUN[@]}")
SCP_BACK=("$SCP_CMD" -q -o BatchMode=yes -o ConnectTimeout=15 "$DESKTOP:$REMOTE_OUT_SCP" "$LOCAL_OUT")

if [ "$DRY_RUN" = 1 ]; then
  PROMPT_BYTES=$(wc -c <"$PROMPT_FILE" 2>/dev/null || echo 0)
  say "wake dispatch --dry-run   ($(now_iso))  host=$(hostname 2>/dev/null || echo '?')"
  say "  lock:      $LOCK (acquired)"
  say "  gates:     releases today $RELEASES_TODAY/$MAX_PER_DAY, spend today \$$SPEND_TODAY/\$$MAX_USD_PER_DAY, pause file absent"
  say "  reap:      $(oneline "${REAP_OUT:-<no output>}")"
  say "  claim:     would claim wake #$ID (priority=$PRIORITY, by=$CALLSIGN) — simulated from \`list --state new\`; the real run calls \`claim\`, which applies the store guards (per-source cap, cooldown, night gate) too"
  say "  prompt:    $PROMPT_BYTES bytes -> $PROMPT_FILE (written exactly as the store holds it)"
  say "  would run:"
  say "    1. $(render "${SCP_IN[@]}")"
  say "    2. $(render "${TIMEOUT_RUN[@]}")"
  say "       (lease ${LEASE}s, heartbeat every ${HEARTBEAT}s, hard timeout ${TIMEOUT}s, runner self-bound ${RUNNER_TIMEOUT}s)"
  say "    3. $(render "${SCP_BACK[@]}")"
  say "    4. $PY $WAKE_CLI finish $ID --outcome \"<bounded outcome>\"   # or --failed on any failure"
  say "  would log: released $TODAY wake #$ID done exit=0 cost=none dur=<secs> subject=\"$SUBJ\""
  say "  no claim, no ssh, no scp, no dsh, and no log write. reap ran (the maintenance the"
  say "  real run performs every tick); nothing else touched the store."
  exit 0
fi

DUR_START=$(date -u +%s)
log "releasing wake #$ID ($(oneline "$SUBJ")) by $CALLSIGN -> $DESKTOP"

# ---------------------------------------------------------------------------
# 6. Transfer the prompt. It travels as a FILE precisely so no nested quoting
#    is ever constructed anywhere on this path.
# ---------------------------------------------------------------------------
if ! "${SCP_IN[@]}" >>"$SSH_LOG" 2>&1; then
  OUTCOME="prompt transfer to $DESKTOP failed ($(to_scp "$REMOTE_PROMPT")); no session was started"
  log "released $TODAY wake #$ID failed exit=n/a cost=none dur=0s subject=\"$(oneline "$SUBJ")\""
  log "  outcome: $OUTCOME"
  "$PY" "$WAKE_CLI" finish "$ID" --failed --outcome "$OUTCOME" >/dev/null 2>&1 || log "ERROR finish failed for wake #$ID"
  FINISHED=1
  exit 1
fi

# ---------------------------------------------------------------------------
# 7. Run the session, heartbeating the lease while it runs so a long session is
#    never reaped and double-run.
# ---------------------------------------------------------------------------
: >"$SSH_LOG"
"${TIMEOUT_RUN[@]}" >>"$SSH_LOG" 2>&1 &
SESS_PID=$!
# The ssh hop is already bounded by `timeout`, but this loop must never be able
# to outlive it: a reaped-but-not-yet-noticed child would otherwise spin the
# heartbeat forever. Belt: stop waiting 2 minutes past the outer bound.
LOOP_DEADLINE=$(( $(date -u +%s) + TIMEOUT + 120 ))

heartbeat_lease() {
  local out rc i
  for i in 1 2 3; do
    out=$("$PY" "$WAKE_CLI" heartbeat "$ID" --by "$CALLSIGN" --lease-seconds "$LEASE" 2>&1); rc=$?
    [ "$rc" -eq 0 ] && return 0
    log "WARN heartbeat for wake #$ID failed (attempt $i/3, rc=$rc): $(oneline "$out")"
    sleep 2
  done
  return 1
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
    if ! heartbeat_lease; then
      # The lease is the only thing stopping a second dispatcher from picking
      # this row up. If it cannot be extended, stop the session rather than
      # risk two sessions for one flag.
      LEASE_LOST=1
      OUTCOME_REASON="lease heartbeat lost three times"
      log "ERROR lease heartbeat failed for wake #$ID - killing the session to avoid a double release"
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
#    out-file is the only evidence of what the session did.
# ---------------------------------------------------------------------------
SCP_BACK_RC=0
"${SCP_BACK[@]}" >>"$SSH_LOG" 2>&1 || SCP_BACK_RC=$?

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
RESULT_TEXT=""
[ -f "$LOCAL_OUT" ] && RESULT_TEXT=$(bounded "$(tail -c 2000 "$LOCAL_OUT")")

# ---------------------------------------------------------------------------
# 9. Decide success. ssh rc alone is not enough: the runner reports the exit
#    code of `dsh --profile headless` itself, and a run that aborted exits 1
#    inside a perfectly successful ssh hop.
# ---------------------------------------------------------------------------
SUCCESS=0
if [ "$LEASE_LOST" = 1 ]; then
  SUCCESS=1
  OUTCOME="$OUTCOME_REASON; session killed so it could not be double-run (session ran ${DUR}s)"
elif [ "$RELEASE_RC" -eq 124 ] || [ "$RELEASE_RC" -eq 137 ] || [ "$RELEASE_RC" -eq 143 ]; then
  SUCCESS=1
  OUTCOME="timed out after ${TIMEOUT}s (session killed; runner self-bound ${RUNNER_TIMEOUT}s); last output: $RESULT_TEXT"
elif [ "$RELEASE_RC" -ne 0 ]; then
  SUCCESS=1
  OUTCOME="ssh hop failed (rc=$RELEASE_RC) after ${DUR}s; desktop output: $(bounded "$(tail -c 2000 "$SSH_LOG")")"
elif [ "$SCP_BACK_RC" -ne 0 ]; then
  SUCCESS=1
  OUTCOME="session finished but the output file could not be copied back (scp rc=$SCP_BACK_RC) - the result is unverified"
elif [ "$RUNNER_CODE_MALFORMED" = 1 ]; then
  SUCCESS=1
  OUTCOME="the runner's exit-code line was unreadable, so the session's verdict is unknown (failing closed); output: $RESULT_TEXT"
elif [ -n "$RUNNER_CODE" ] && [ "$RUNNER_CODE" != "0" ]; then
  SUCCESS=1
  OUTCOME="dsh exited $RUNNER_CODE; output: $RESULT_TEXT"
else
  OUTCOME="$RESULT_TEXT"
  [ -n "$OUTCOME" ] || OUTCOME="session reported success with no output"
fi
# The outcome column is for a human reading `wake.py list`, not for a log dump.
OUTCOME=$(bounded "$OUTCOME")

# ---------------------------------------------------------------------------
# 10. Close the row. Always. Never leave a claim dangling.
# ---------------------------------------------------------------------------
if [ "$SUCCESS" -eq 0 ]; then
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

if [ "$SUCCESS" -eq 0 ]; then
  exit 0
fi
printf '%s: wake #%s failed: %s\n' "$PROG" "$ID" "$(bounded "$OUTCOME" 300)" >&2
exit 1
