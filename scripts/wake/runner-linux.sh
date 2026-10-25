#!/bin/bash
# =============================================================================
# wake-run.sh - the Linux half of the release hop (ledger housekeeping item 642).
#
# WHAT THIS IS. wake-dispatch.sh has always been able to run a release on THIS
# host (`NODE_KIND=local`) but the runner it named, `$HOME/bin/wake-run.sh`,
# did not exist on the authority, so that branch could only fail. This is that
# runner. It takes the same shape as the Windows `wake-run.ps1`: read a prompt
# file, run one `dsh --profile headless` turn under a bound, write the answer
# plus a machine-readable exit line to an out-file, and write a session sidecar
# on the node that actually ran the turn.
#
# WHY IT IS SAFE ON THE AUTHORITY. It prefers /usr/local/bin/dsh-mesh, which
# pins DSH_HOME=/root/.dsh-worker and wraps the turn in systemd-run --scope with
# MemoryMax=6G. A release therefore cannot become a second engine on the phone's
# /root/.dsh and cannot drive the company-api host into a global OOM.
#
# WHAT IT DOES NOT DO. It never claims, files, flags or finishes a wake row;
# the dispatcher owns the row. It installs nothing: the dispatcher may stage this
# file on a node, but running it changes no system state beyond the turn itself.
#
# BOUND. `timeout` bounds the dsh-mesh CLIENT. `systemd-run --scope` is a
# transient unit, so a hard kill of the client does not guarantee the scope is
# gone; the 6G MemoryMax is the backstop and the model harness has its own turn
# cap. Do not raise this bound above WAKE_TURN_CAP_SEC.
# =============================================================================
set -u

PROMPT_FILE=""
OUT_FILE=""
TIMEOUT_SEC=1800
PROFILE=headless
RELEASE_ID="?"
RUN_TOKEN="?"
SIDECAR_DIR="${WAKE_SIDECAR_DIR:-$HOME/.sms-inbox}"
MODEL=""

while [ $# -gt 0 ]; do
  case "$1" in
    --prompt-file) PROMPT_FILE=${2:-}; shift 2 ;;
    --out-file)    OUT_FILE=${2:-}; shift 2 ;;
    --timeout-sec) TIMEOUT_SEC=${2:-1800}; shift 2 ;;
    --profile)     PROFILE=${2:-headless}; shift 2 ;;
    --release-id)  RELEASE_ID=${2:-?}; shift 2 ;;
    --run-token)   RUN_TOKEN=${2:-?}; shift 2 ;;
    --sidecar-dir) SIDECAR_DIR=${2:-}; shift 2 ;;
    --model)       MODEL=${2:-}; shift 2 ;;
    -h|--help)
      sed -n '2,30p' "$0"; exit 0 ;;
    *) echo "wake-run.sh: unknown argument: $1" >&2; exit 2 ;;
  esac
done

if [ -z "$PROMPT_FILE" ] || [ ! -r "$PROMPT_FILE" ]; then
  echo "wake-run.sh: prompt file is missing or unreadable: ${PROMPT_FILE:-<none>}" >&2
  exit 2
fi
if [ -z "$OUT_FILE" ]; then
  echo "wake-run.sh: --out-file is required" >&2
  exit 2
fi

# The executor. dsh-mesh is the caged authority form; plain dsh is what the
# Linux worker nodes expose. Absolute paths, because a non-login shell may not
# have either directory on PATH.
if [ -x /usr/local/bin/dsh-mesh ]; then
  DSH=/usr/local/bin/dsh-mesh
elif [ -x /usr/local/bin/dsh ]; then
  DSH=/usr/local/bin/dsh
elif command -v dsh >/dev/null 2>&1; then
  DSH=$(command -v dsh)
else
  echo "wake-run.sh: no dsh executor on $(hostname 2>/dev/null || echo this host)" >&2
  exit 2
fi

START_ISO=$(date -u +%Y-%m-%dT%H:%M:%SZ)
START_EPOCH=$(date +%s)
PROMPT=$(cat "$PROMPT_FILE")
mkdir -p "$(dirname "$OUT_FILE")" 2>/dev/null || true
: >"$OUT_FILE"

# One turn. stderr is folded into the answer on purpose: a session that dies at
# start leaves its reason there, and the dispatcher stores a bounded tail. The
# two banners are NOT decoration: wake-dispatch.sh's answer_head() extracts the
# final answer from between them, and without them a perfectly good session is
# recorded `unverified` (measured on this runner's first acceptance release).
STDOUT_TMP="$OUT_FILE.stdout"
STDERR_TMP="$OUT_FILE.stderr"
timeout -k 30 "$TIMEOUT_SEC" "$DSH" --profile "$PROFILE" "$PROMPT" >"$STDOUT_TMP" 2>"$STDERR_TMP"
RC=$?
{
  echo "--- stdout (final answer) ---"
  cat "$STDOUT_TMP" 2>/dev/null
  echo
  echo "--- stderr (provider reasoning) ---"
  cat "$STDERR_TMP" 2>/dev/null
  echo
  echo "=== exit code: $RC ==="
  echo "WAKE_EXIT_CODE=$RC"
} >>"$OUT_FILE"
rm -f "$STDOUT_TMP" "$STDERR_TMP"

# --- the session sidecar, ON THIS NODE --------------------------------------
# Item 642's definition of done asks for the sidecar file to exist on the node
# that ran the release, not only on the authority. The DSH session id is the
# newest `session-*` directory created since this turn started; if it cannot be
# resolved the sidecar still records the release, the host and the window, and
# says `unresolved` rather than inventing an id.
SID="unresolved"
DSH_HOME_GUESS="${DSH_HOME:-}"
[ -z "$DSH_HOME_GUESS" ] && [ "$DSH" = /usr/local/bin/dsh-mesh ] && DSH_HOME_GUESS=/root/.dsh-worker
[ -z "$DSH_HOME_GUESS" ] && DSH_HOME_GUESS=$HOME/.dsh
if [ -d "$DSH_HOME_GUESS/sessions" ]; then
  newest=$(find "$DSH_HOME_GUESS/sessions" -maxdepth 2 -type d -name 'session-*' \
             -newermt "@$((START_EPOCH - 2))" 2>/dev/null | head -1)
  [ -n "$newest" ] && SID=$(basename "$newest")
fi

if [ -n "$SIDECAR_DIR" ]; then
  mkdir -p "$SIDECAR_DIR" 2>/dev/null || true
  SIDE="$SIDECAR_DIR/wake-session-${RELEASE_ID}-${RUN_TOKEN}.txt"
  {
    echo "wake-session sidecar -- written by wake-run.sh (ledger housekeeping item 642)"
    echo "release id : $RELEASE_ID"
    echo "run token  : $RUN_TOKEN"
    echo "session id : $SID"
    echo "confidence : $( [ "$SID" = unresolved ] && echo none || echo unique )"
    echo "host       : $(hostname -s 2>/dev/null || hostname 2>/dev/null || echo unknown)"
    echo "created at : $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "cwd        : $(pwd)"
    echo "prompt file: $PROMPT_FILE"
    echo "prompt sha : $(sha256sum "$PROMPT_FILE" 2>/dev/null | cut -d' ' -f1 | tr 'a-f' 'A-F')"
    echo "window     : $START_ISO .. $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "exit code  : $RC"
  } >"$SIDE" 2>/dev/null || true
  echo "WAKE_SIDECAR=$SIDE"
fi

exit "$RC"
