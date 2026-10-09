#!/usr/bin/env bash
# transcript-archive-run.sh — one scheduled pass of the permanent transcript archive.
#
# THE RULE: every DSH session and every VS Code Copilot chat is archived forever, off the machine
# that wrote it. The owner, 2026-10-09: "we need copies of all vscode copilot chats and all dsh
# sessions forever for data and training data, and those a copy always needs to exist".
#
# This is the thing that runs on its own. It is deliberately dumb: pull, check, record, and be
# LOUD when the archive is behind. It never deletes anything and never prunes the archive.
#
# WHY IT IS DRIVEN FROM HERE AND NOT FROM EACH LAPTOP
#   `PersonalSecretary-PushVSCodeChats` on ZABZ-YOGA reported LastTaskResult=0 -- success -- every
#   hour for 21 days while the Copilot archive stood still (measured 2026-10-09). A workstation-side
#   scheduler cannot tell "nothing to send" from "I am broken". This host is always on, so the pull
#   either happens or fails where cron-wrap.sh records the exit code.
#
# Exit codes: 0 = archive current. 1 = a real gap (data on a machine the archive does not hold).
#             2 = machine silence only (cannot be judged from the authority). 3 = the pull failed.

set -uo pipefail

ARCHIVE="${TRANSCRIPT_ARCHIVE_ROOT:-/home/zabz/lpt-transcripts}"
SCRIPTS="${TRANSCRIPT_SCRIPTS:-/home/zabz/code/harness-config/scripts}"
STATE_DIR="${TRANSCRIPT_STATE_DIR:-$HOME/.transcript-archive}"
MAX_BYTES="${TRANSCRIPT_MAX_BYTES:-3000000000}"
ROUNDS="${TRANSCRIPT_ROUNDS:-3}"
MACHINES="${TRANSCRIPT_MACHINES:---all}"
STAMP="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"

mkdir -p "$STATE_DIR" "$ARCHIVE/logs" "$ARCHIVE/incoming"
LOG="$ARCHIVE/logs/pull-$(date -u '+%Y%m%d').jsonl"

# One pass at a time: an hourly job that outlives its hour must not stack up on itself.
exec 9>"$STATE_DIR/.lock"
if ! flock -n 9; then
  printf '%s\tSKIPPED\tanother pass is still running\n' "$STAMP" >> "$ARCHIVE/logs/run.log"
  exit 0
fi

pull_rc=0
pull_out=""
round=0
while [ "$round" -lt "$ROUNDS" ]; do
  round=$((round + 1))
  # shellcheck disable=SC2086
  pull_out="$(python3 "$SCRIPTS/transcript-archive-pull.py" $MACHINES --max-bytes "$MAX_BYTES" 2>&1)"
  printf '{"at":"%s","round":%d,"out":%s}\n' "$STAMP" "$round" \
    "$(printf '%s' "$pull_out" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')" >> "$LOG"
  if ! printf '%s' "$pull_out" | grep -q '"truncated": *true'; then break; fi
  printf '%s round %d: more to pull (chunked), continuing\n' "$STAMP" "$round" >> "$ARCHIVE/logs/run.log"
done
printf '%s' "$pull_out" | grep -q '"ok": false' && pull_rc=3

# The check. This is the part that has to fail loudly -- journal H340 is why: a stale archive was
# found by accident, which means nothing was watching.
check_out="$(python3 "$SCRIPTS/transcript-archive-server.py" --check 2>&1)"
check_rc=$?

python3 - "$STATE_DIR/status.json" "$STAMP" "$pull_rc" "$check_rc" "$check_out" <<'PY'
import json, sys
path, stamp, pull_rc, check_rc, check_out = sys.argv[1:6]
try:
    check = json.loads(check_out[check_out.index("{"):check_out.rindex("}") + 1])
except Exception:
    check = {"parse_error": check_out[-400:]}
with open(path, "w") as fh:
    json.dump({"at": stamp, "pull_rc": int(pull_rc), "check_rc": int(check_rc),
               "check": check}, fh, indent=1)
PY

alarm="$STATE_DIR/ALARM"
if [ "$check_rc" -eq 1 ]; then
  printf '%s TRANSCRIPT ARCHIVE GAP — data exists on a machine the archive does not hold\n%s\n' \
    "$STAMP" "$check_out" > "$alarm"
  # tell the journal once per distinct alarm, not once per hour
  sig="$(printf '%s' "$check_out" | md5sum | cut -c1-16)"
  if [ "$(cat "$STATE_DIR/.last-alarm-sig" 2>/dev/null)" != "$sig" ]; then
    printf '%s' "$sig" > "$STATE_DIR/.last-alarm-sig"
    python3 "$HOME/code/harness-config/journal/tools/journal.py" append pain --no-fetch \
      --title "The transcript archive is behind: a machine holds transcripts the archive does not" \
      --body "$(printf 'Filed automatically by transcript-archive-run.sh at %s.\n\n%s\n\nFix: read %s, then pull that machine. Check with:\n  python3 %s/transcript-archive-server.py --check' \
        "$STAMP" "$check_out" "$STATE_DIR/status.json" "$SCRIPTS")" >/dev/null 2>&1 || true
  fi
  cat "$alarm" >&2
  exit 1
fi

rm -f "$alarm"
if [ "$pull_rc" -ne 0 ]; then
  printf '%s one or more machines could not be pulled — see %s\n' "$STAMP" "$LOG" >&2
  exit 3
fi
if [ "$check_rc" -eq 2 ]; then
  printf '%s archive holds no gap; a machine is silent (idle or unreachable — cannot be told apart here)\n' \
    "$STAMP" >&2
  exit 2
fi
printf '%s transcript archive current\n' "$STAMP" >> "$ARCHIVE/logs/run.log"
exit 0
