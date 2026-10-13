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
STATE_DIR="${TRANSCRIPT_STATE_DIR:-$HOME/.transcript-archive}"
MAX_BYTES="${TRANSCRIPT_MAX_BYTES:-3000000000}"
ROUNDS="${TRANSCRIPT_ROUNDS:-3}"
MACHINES="${TRANSCRIPT_MACHINES:---all}"
STAMP="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"

# WHERE THE SCRIPTS ARE. This used to default to /home/zabz/code/harness-config/scripts, which is
# right on the office box and WRONG on the authority, where the checkout is /root/code/harness-config.
# A cron entry that inherits a wrong default fails with "no such file" and records rc=127 in the
# ledger -- which nobody reads. Resolve it, and take the first that exists.
if [ -n "${TRANSCRIPT_SCRIPTS:-}" ]; then
  SCRIPTS="$TRANSCRIPT_SCRIPTS"
else
  SCRIPTS=""
  for cand in "$HOME/code/harness-config/scripts" "$HOME/harness-config/scripts" \
              "$(dirname "$(readlink -f "$0")")"; do
    [ -f "$cand/transcript-archive-pull.py" ] && { SCRIPTS="$cand"; break; }
  done
fi
JOURNAL="${TRANSCRIPT_JOURNAL:-$(dirname "${SCRIPTS:-/root/code/harness-config/scripts}")/journal/tools/journal.py}"

# ── THE FREE-SPACE FLOOR ────────────────────────────────────────────────────────────────────────
# WHY THIS EXISTS, MEASURED 2026-10-13. `transcript-archive-pull.py` stages every machine's tar in
# SPOOL = <archive root>/incoming -- the SAME filesystem as the company database -- and this script
# runs up to $ROUNDS rounds of up to $MAX_BYTES each, so one pass can write up to
# $((MAX_BYTES * ROUNDS)) bytes with NO free-space check anywhere in either file.
#
# The consequence was not theoretical. On 2026-10-13 the authority's disk swung from 92% / 6.1 GB
# free (measured) to 98.7% / 0.0 GB free (`disk-guard` CRITICAL at 13:00:03Z) in the same hour, and
# `prune-backups` logged `FLOOR BREACHED ... Pruned NOTHING; investigate what filled the disk.` A
# 3 GB pass against 6 GB free is the whole explanation, and the box that fills is the sole writer of
# the company database. Journal P3161.
#
# The floor is the budget for THIS pass plus headroom for everything else that is running, and it is
# re-checked before every round, because the first round's own tar is what consumes the space the
# second would spend.
FREE_RESERVE_BYTES="${TRANSCRIPT_FREE_RESERVE_BYTES:-2000000000}"
need_bytes=$((MAX_BYTES + FREE_RESERVE_BYTES))

free_bytes() {
  # POSIX `df -Pk` field 4 is "available", in 1K blocks. No --output (GNU-only), no parse of the
  # human-readable column.
  df -Pk "$1" 2>/dev/null | awk 'NR==2 {print $4 * 1024}'
}

mkdir -p "$STATE_DIR" "$ARCHIVE/logs" "$ARCHIVE/incoming"
LOG="$ARCHIVE/logs/pull-$(date -u '+%Y%m%d').jsonl"

have_bytes="$(free_bytes "$ARCHIVE")"
if [ -z "$have_bytes" ] || [ "$have_bytes" -lt "$need_bytes" ]; then
  {
    printf '%s TRANSCRIPT ARCHIVE REFUSED TO START — not enough free space to stage a pull\n' "$STAMP"
    printf '  archive   : %s\n' "$ARCHIVE"
    printf '  free      : %s bytes\n' "${have_bytes:-unknown}"
    printf '  needs     : %s bytes (max-bytes %s + reserve %s)\n' "$need_bytes" "$MAX_BYTES" "$FREE_RESERVE_BYTES"
    printf '  These tars stage inside the archive root, on the same filesystem as the company database.\n'
    printf '  Lower TRANSCRIPT_MAX_BYTES, free space, or raise the floor deliberately. Do not widen the\n'
    printf '  budget to make this pass — that is how the disk filled on 2026-10-13.\n'
  } | tee "$STATE_DIR/ALARM" >&2
  exit 3
fi

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
  # Re-check the floor before every round: the previous round's tar is what ate the space.
  have_bytes="$(free_bytes "$ARCHIVE")"
  if [ -z "$have_bytes" ] || [ "$have_bytes" -lt "$need_bytes" ]; then
    printf '%s round %d: STOPPED on the free-space floor (%s bytes free, %s needed)\n' \
      "$STAMP" "$round" "${have_bytes:-unknown}" "$need_bytes" >> "$ARCHIVE/logs/run.log"
    printf '{"at":"%s","round":%d,"stopped_on_free_space":true,"free":%s,"need":%s}\n' \
      "$STAMP" "$round" "${have_bytes:-0}" "$need_bytes" >> "$LOG"
    break
  fi
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
alarm_text=""
alarm_title=""
alarm_exit=0

if [ "$check_rc" -eq 1 ]; then
  alarm_text="$(printf '%s TRANSCRIPT ARCHIVE GAP — data exists on a machine the archive does not hold\n%s\n' \
    "$STAMP" "$check_out")"
  alarm_title="The transcript archive is behind: a machine holds transcripts the archive does not"
  alarm_exit=1
fi

# A PULL THAT FAILED IS ALSO AN ALARM. This branch is why the 2026-10-10 stall went unseen: the pull
# died on every machine with `cursor generation failed` and the runner exited 3, but only a GAP
# (check_rc 1) ever raised ALARM or filed a journal entry. Nothing was watching the thing that
# actually broke, for two days, while `~/.cron-status/runs.tsv` recorded rc=3 every hour and nobody
# read it. Exit code alone is not a monitor (AGENTS.md §1 trap 2, in a different costume).
if [ "$alarm_text" = "" ] && [ "$pull_rc" -ne 0 ]; then
  alarm_text="$(printf '%s TRANSCRIPT ARCHIVE PULL FAILED — machines could not be pulled, so nothing was archived this pass\n%s\n' \
    "$STAMP" "$(tail -c 2000 "$LOG")")"
  alarm_title="The transcript archive pull is failing: nothing is being archived from any machine"
  alarm_exit=3
fi

# An exit code the check does not define (anything but 0/1/2) means the check itself could not run --
# a wrong --db path, a missing script, an unreadable archive. Without this branch the script fell
# through to "transcript archive current" and exited 0 on a check that never happened, which is the
# same defect as the one above wearing a different hat.
if [ "$alarm_text" = "" ] && [ "$check_rc" -ne 0 ] && [ "$check_rc" -ne 1 ] && [ "$check_rc" -ne 2 ]; then
  alarm_text="$(printf '%s TRANSCRIPT ARCHIVE CHECK FAILED — the staleness check itself did not run (rc=%s)\n%s\n' \
    "$STAMP" "$check_rc" "$check_out")"
  alarm_title="The transcript archive check cannot run: the freshness monitor is itself broken"
  alarm_exit=3
fi

if [ -n "$alarm_text" ]; then
  printf '%s\n' "$alarm_text" > "$alarm"
  # tell the journal once per distinct alarm, not once per hour
  sig="$(printf '%s' "$alarm_text" | md5sum | cut -c1-16)"
  if [ "$(cat "$STATE_DIR/.last-alarm-sig" 2>/dev/null)" != "$sig" ]; then
    printf '%s' "$sig" > "$STATE_DIR/.last-alarm-sig"
    python3 "$JOURNAL" append pain --no-fetch \
      --title "$alarm_title" \
      --body "$(printf 'Filed automatically by transcript-archive-run.sh at %s.\n\n%s\n\nFix: read %s, then pull that machine. Check with:\n  python3 %s/transcript-archive-server.py --check' \
        "$STAMP" "$alarm_text" "$STATE_DIR/status.json" "$SCRIPTS")" >/dev/null 2>&1 || true
  fi
  cat "$alarm" >&2
  exit "$alarm_exit"
fi

rm -f "$alarm"
if [ "$check_rc" -eq 2 ]; then
  printf '%s archive holds no gap; a machine is silent (idle or unreachable — cannot be told apart here)\n' \
    "$STAMP" >&2
  exit 2
fi
printf '%s transcript archive current\n' "$STAMP" >> "$ARCHIVE/logs/run.log"
exit 0
