#!/usr/bin/env bash
# cron-wrap.sh -- run one cron job and RECORD WHAT IT DID.
#
# WHY THIS EXISTS
# ---------------
# On 2026-09-30 five cron jobs on this host called programs that had not existed for 28 hours, and
# two more had lost their execute bit weeks earlier. Nothing noticed. cron's only output is a line in
# a per-job log that no reader opens, and this host has no `mail` binary at all, so a job that fails
# every single run is indistinguishable from a job with nothing to do. The existence half is now
# covered by `cron-target-guard.py`; THIS is the other half: a job that exists and fails.
#
# WHAT IT DOES, and nothing more
#   * runs the command it is given, with its original shell, redirections and all;
#   * appends one line per run to ~/.cron-status/runs.tsv:
#         <ISO-8601 UTC>\t<name>\t<rc>\t<seconds>\t<the reason, if any>
#   * appends nothing else anywhere; the job's own stdout/stderr go exactly where they went before,
#     because the command string is passed through untouched.
#
# The command is passed BASE64-ENCODED. Not for security -- for quoting: these lines contain single
# quotes, backticks, `$`, `%` and nested quotes, and every naive re-quoting of a crontab line is a
# chance to silently change what it runs. Base64 cannot be misquoted, and the installer verifies that
# decoding each wrapped payload reproduces the original line byte for byte.
#
# USAGE
#     cron-wrap.sh <name> <base64-of-the-command>
#
# EXIT CODE: the command's own exit code, always. A wrapper that swallowed it would be a new instance
# of the problem it exists to fix.
#
# ---------------------------------------------------------------------------------------------
# FIELD 5 IS THE REASON, NOT A WINDOW THAT CUTS IT OFF. (fixed 2026-10-11)
#
# The column COUNT and ORDER are a frozen contract -- `sources/cron-failures.py` does
# `line.split("\t")` and reads `parts[4]`, and other monitors read the same 5 fields. Do not change
# the field count or order. What follows changes only the CONTENT of field 5.
#
# THE DEFECT THIS REPLACES, measured on the authority 2026-10-11. The old expression was:
#
#     ERRTAIL="$(tail -c 400 "$ERRFILE" | tr '\n\t' '  ' | cut -c1-160)"
#
# Read it left to right: `tail -c 400` keeps the LAST 400 bytes of stderr (bytes N-400..N), and then
# `cut -c1-160` keeps the FIRST 160 characters of that flattened tail -- i.e. bytes N-400..N-240.
# The final 240 bytes are discarded outright. A Python traceback ENDS with its exception line
# (`ValueError: ...`), which is exactly the line in those discarded bytes, so the ledger preserved the
# tail of the last `File "...", line N, in f` frame and threw away the cause. Two failures that day
# could not be diagnosed from the ledger alone because of this. Measured: of 2302 rows,
# 143 recorded rc != 0 with an EMPTY field 5.
#
# THE REPLACEMENT keeps the useful end of stderr:
#   * it reads the last 8 KB (bounded, so a job that floods stderr stays cheap);
#   * the LAST NON-EMPTY LINE of stderr is the anchor, because that is where the exception and its
#     message are;
#   * when the anchor alone fits in 160 characters it is kept WHOLE -- never cut;
#   * when the anchor is longer than 160 characters we keep its FRONT, not its back, because the
#     token that identifies the failure ("ValueError: ", "sh: 1: ", "curl: (7)") is at the front;
#   * earlier lines are back-filled in front of the anchor while they fit, so a traceback reads
#     `...line 212, in main ValueError: bad thing` -- location and cause inside the field;
#   * a leading `...` marks that something was dropped;
#   * rc != 0 with an EMPTY stderr records an explicit marker instead of a blank field, because a job
#     that prints its reason to stdout is a real, measured population (143 of 2302 rows).
# The field is always one flattened line with no tab or newline, and never exceeds 160 characters.
set -uo pipefail

# THE WRAPPER'S OWN FAILURE MUST BE AS VISIBLE AS THE JOB'S.
# Measured 2026-10-02: the pain-check line was written with its command RAW instead of encoded
# (`cron-wrap.sh pain-check /home/zabz/bin/pain-check.py --write-status`). `base64 -d` refused it,
# this script exited 2 BEFORE writing a run record, and cron's only output went to a log nobody
# reads -- so the pain check suite had not run for 37 h, its watchdog source reported "signal
# unreadable" rather than filing work, and the loop that closes fixed defects was silently dead.
# A refusal now leaves a row in the same runs.tsv every other job writes, with rc=2, so
# "this job has not run" is a thing that can be read instead of inferred.
refuse() {
  local why="$1" dir stamp
  dir="${CRON_STATUS_DIR:-$HOME/.cron-status}"
  mkdir -p "$dir" 2>/dev/null || true
  stamp="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
  printf '%s\t%s\t2\t0\tcron-wrap REFUSED: %s\n' "$stamp" "$NAME" "$why" >> "$dir/runs.tsv" 2>/dev/null || true
  echo "cron-wrap: $why" >&2
  exit 2
}

NAME="${1:-unnamed}"
PAYLOAD="${2:-}"
if [ -z "$PAYLOAD" ]; then
  refuse "no payload for $NAME -- the crontab line is not wrapped (run ~/bin/wrap-crontab.py --install)"
fi

CMD="$(printf '%s' "$PAYLOAD" | base64 -d 2>/dev/null)" || {
  refuse "payload for $NAME is not valid base64 -- the crontab line is not wrapped (run ~/bin/wrap-crontab.py --install)"
}
if [ -z "$CMD" ]; then
  refuse "payload for $NAME decoded to nothing -- refusing to run an empty command"
fi

STATE_DIR="${CRON_STATUS_DIR:-$HOME/.cron-status}"
mkdir -p "$STATE_DIR"
STAMP="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
START="$(date +%s)"

ERRFILE="$(mktemp "${TMPDIR:-/tmp}/cron-wrap-XXXXXX")"
# The command runs with its ORIGINAL text, under `sh -c`, so every redirection and every shell
# construct in the crontab line behaves exactly as it did unwrapped.
sh -c "$CMD" 2>"$ERRFILE"
RC=$?

END="$(date +%s)"

# Field 5: the reason, taken from the END of stderr. See the header for why this is shaped this way.
# `awk` is handed the last 8 KB only, so cost does not scale with how much a job decides to print.
ERRTAIL="$(tail -c 8000 "$ERRFILE" 2>/dev/null | awk '
  {
    sub(/\r$/, "")                    # CRLF stderr
    gsub(/[[:space:]]+/, " ")         # collapse runs so more of the reason fits
    sub(/^ /, ""); sub(/ $/, "")      # trim
    if (length($0) > 0) lines[++n] = $0
  }
  END {
    max = 160
    if (n == 0) exit 0                # no stderr at all -- the caller decides what that means
    anchor = lines[n]                 # the exception line lives here
    if (length(anchor) > max - 4) {
      # No room for a `...` marker and context. Keep the anchor whole if it fits, else keep its
      # FRONT (the failure token), never its back.
      if (length(anchor) <= max) printf "%s", anchor
      else printf "%s...", substr(anchor, 1, max - 3)
      exit 0
    }
    budget = max - 4 - length(anchor) # 4 = leading "..." plus the joining space
    pre = ""
    for (i = n - 1; i >= 1; i--) {
      cand = (pre == "" ? lines[i] : lines[i] " " pre)
      if (length(cand) <= budget) pre = cand
      else break
    }
    if (n == 1)      printf "%s", anchor
    else if (pre == "") printf "...%s", anchor        # context existed and did not fit
    else             printf "...%s %s", pre, anchor
  }
' )"
rm -f "$ERRFILE"

# A non-zero exit with nothing on stderr is a REAL, MEASURED case -- the job printed its reason to
# stdout, or to its own log, and exited non-zero. A blank column reads as "no error"; say so instead.
if [ -z "$ERRTAIL" ] && [ "$RC" -ne 0 ]; then
  ERRTAIL="[no stderr; rc=$RC -- reason is on stdout or in the job's own log]"
fi

printf '%s\t%s\t%s\t%s\t%s\n' "$STAMP" "$NAME" "$RC" "$((END - START))" "$ERRTAIL" >> "$STATE_DIR/runs.tsv"

# Keep the log from growing without bound: it is one line per run, and the fan-out runs every minute.
SIZE="$(stat -c%s "$STATE_DIR/runs.tsv" 2>/dev/null || echo 0)"
if [ "${SIZE:-0}" -gt 5000000 ]; then
  tail -n 20000 "$STATE_DIR/runs.tsv" > "$STATE_DIR/runs.tsv.tmp" && mv "$STATE_DIR/runs.tsv.tmp" "$STATE_DIR/runs.tsv"
fi

exit "$RC"
