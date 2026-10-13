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
JOURNAL="${TRANSCRIPT_JOURNAL:-$HOME/code/harness-config/journal/tools/journal.py}"
STATE_DIR="${TRANSCRIPT_STATE_DIR:-$HOME/.transcript-archive}"
MAX_BYTES="${TRANSCRIPT_MAX_BYTES:-3000000000}"
ROUNDS="${TRANSCRIPT_ROUNDS:-3}"
MACHINES="${TRANSCRIPT_MACHINES:---all}"
STAMP="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"

mkdir -p "$STATE_DIR" "$ARCHIVE/logs" "$ARCHIVE/incoming"
LOG="$ARCHIVE/logs/pull-$(date -u '+%Y%m%d').jsonl"

# ── THE FREE-SPACE FLOOR ────────────────────────────────────────────────────────────────────────
# WHY THIS EXISTS, MEASURED 2026-10-13. `transcript-archive-pull.py` stages every machine's tar in
# SPOOL = <archive root>/incoming -- the SAME filesystem as the company database -- and this loop
# runs up to $ROUNDS rounds of up to $MAX_BYTES each. Neither this file nor the pull checked free
# space anywhere, so the script's OWN DEFAULTS (3,000,000,000 x 3) describe a pass that can stage
# 9 GB, on the box that is the sole writer of the company database.
#
# The deployed wrapper bounds it at 500 MB per round, so a real pass is ~1.5 GB -- this guard is NOT
# an explanation of any past reading and is not claimed to be one. It closes the hole that opens the
# moment someone runs this script WITHOUT the wrapper, which is exactly what a new host or a
# recovery session does. Journal P3163.
#
# The floor is this pass's budget plus headroom for everything else running, and it is re-checked
# before every round, because the previous round's own tar is what consumed the space.
FREE_RESERVE_BYTES="${TRANSCRIPT_FREE_RESERVE_BYTES:-2000000000}"
need_bytes=$((MAX_BYTES + FREE_RESERVE_BYTES))

free_bytes() {
  # POSIX `df -Pk` field 4 is "available", in 1K blocks. No --output (GNU-only), no human columns.
  df -Pk "$1" 2>/dev/null | awk 'NR==2 {print $4 * 1024}'
}

have_bytes="$(free_bytes "$ARCHIVE")"
if [ -z "$have_bytes" ] || [ "$have_bytes" -lt "$need_bytes" ]; then
  {
    printf '%s TRANSCRIPT ARCHIVE REFUSED TO START — not enough free space to stage a pull\n' "$STAMP"
    printf '  archive   : %s\n' "$ARCHIVE"
    printf '  free      : %s bytes\n' "${have_bytes:-unknown}"
    printf '  needs     : %s bytes (max-bytes %s + reserve %s)\n' "$need_bytes" "$MAX_BYTES" "$FREE_RESERVE_BYTES"
    printf '  These tars stage inside the archive root, on the same filesystem as the company database.\n'
    printf '  Lower TRANSCRIPT_MAX_BYTES, free space, or raise the floor deliberately. Do not widen the\n'
    printf '  budget to make this pass go — the box that fills is the one holding the company database.\n'
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
# WAS: printf '%s' "$pull_out" | grep -q '"ok": false' && pull_rc=3
#
# THAT LINE WAS THE DEFECT (measured 2026-10-12 on secratary-cloud). It greps the WHOLE pull JSON as
# text, so it matched the PER-MACHINE `"ok": false` of any single machine -- and the pull reports
# `"failed": [ ... ]` for every machine it cannot reach. One unreachable machine therefore made
# pull_rc=3, which failed transcript-archive-pull.service AND wrote an ALARM reading "PULL FAILED --
# machines could not be pulled, so nothing was archived this pass" on a pass that had just ingested
# ok=1 from four other machines. The unit failed every hour and the alarm was false.
#
# THE DISTINCTION THE WHOLE ARCHIVE IS BUILT ON (AGENTS.md section 1): a machine whose data we cannot
# get is a GAP; a machine we cannot REACH is SILENCE, and from here a powered-off laptop and a broken
# pull look identical. This runner's own contract says exit 3 means "the pull failed", so:
#   * a machine that has NEVER contacted this archive is SILENCE. The pull has never reached it, so
#     nothing changed and nothing was lost; --check reports it and it must not fail the unit.
#   * a machine that HAS contacted us before and is now unreachable is a mechanism fault -- exactly
#     the 2026-10-10 stall this exit code exists to catch. That stays exit 3.
# The manifest is read directly: it needs no network and no rescan of any machine.
# Two counts, not one, because "there were no failures at all" and "the failures were all
# machines we have never reached" are DIFFERENT states and only the first is success.
#
# WAS: a single `new_machines` count with `if new_machines > 0 ... else pull_rc=3`. Measured on
# secratary-cloud 2026-10-13 (pass 13:23Z): that pair printed `failed: []`, ingested ok=1 from
# all five machines, and then took the `else` branch -- so a PERFECT pass set pull_rc=3, failed
# transcript-archive-pull.service every hour, and wrote an ALARM reading
#   "TRANSCRIPT ARCHIVE PULL FAILED -- cannot reach , which this archive has pulled before"
# with an EMPTY machine name (the .failed-machines file held one newline). The check itself said
# gaps: [] and silent: []. A monitor that cries wolf on every healthy run is not a monitor: the
# one pass that really is behind would arrive in a journal already full of this.
counts=$(python3 - "$ARCHIVE/manifest.sqlite" "$pull_out" <<'PY'
import json, sqlite3, sys
db = sys.argv[1]
try:
    d = json.loads(sys.argv[2])
    if not isinstance(d, dict) or "ok" not in d:
        raise ValueError("not a pull report")
except Exception:
    # No parsable pull report: an empty failure list and a dead pull look identical here, so this
    # must NOT read as success. Report one known failure so the caller fails the unit, exactly as
    # an unreachable machine we have pulled before does.
    print(0, 1)
    sys.exit(0)
failed = d.get("failed") or []
try:                                     # the primary key IS the column, so a read-only URI needs
    c = sqlite3.connect(db)              # no -wal/-shm access; the same DB --check reads.
    seen = {r[0] for r in c.execute("SELECT DISTINCT machine FROM machine_contact")}
    c.close()
    judged = True
except Exception:                        # cannot judge -> treat as joined, do NOT suppress the alarm
    seen, judged = set(), False
if not failed:
    print(0, 0)                          # a clean pass: no silence, no mechanism fault
elif not judged:
    print(len(failed), len(failed))
else:
    new = sum(1 for m in failed if m not in seen)
    print(new, len(failed) - new)        # <never contacted> <contacted before = mechanism fault>
PY
)
new_machines="${counts%% *}"
known_failures="${counts##* }"
printf '%s' "$pull_out" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(", ".join(d.get("failed") or []))' \
  > "$STATE_DIR/.failed-machines" 2>/dev/null || printf 'unknown' > "$STATE_DIR/.failed-machines"
# A machine that HAS contacted this archive before and is now unreachable is the mechanism fault
# exit 3 exists to catch. It is tested FIRST so a pass that fails on both kinds still fails loudly.
if [ "${known_failures:-0}" -gt 0 ]; then
  pull_rc=3
elif [ "${new_machines:-0}" -gt 0 ]; then
  printf 'transcript-archive-pass: %s machine(s) failed and have NEVER contacted this archive; that is SILENCE (a machine the pull has never reached), not a broken pull -- --check decides it from the manifest\n' "$new_machines" >&2
  rm -f "$STATE_DIR/ALARM"
fi

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
  alarm_text="$(printf '%s TRANSCRIPT ARCHIVE PULL FAILED — cannot reach %s, which this archive has pulled before, so it is now behind\n%s\n' \
    "$STAMP" "$(cat "$STATE_DIR/.failed-machines" 2>/dev/null)" "$(tail -c 2000 "$LOG")")"
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
