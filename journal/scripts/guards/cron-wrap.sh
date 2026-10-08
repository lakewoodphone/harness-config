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
#         <ISO-8601 UTC>\t<name>\t<rc>\t<seconds>\t<first 160 chars of stderr, if any>
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
set -uo pipefail

NAME="${1:-unnamed}"
PAYLOAD="${2:-}"
if [ -z "$PAYLOAD" ]; then
  echo "cron-wrap: no payload for $NAME" >&2
  exit 2
fi

CMD="$(printf '%s' "$PAYLOAD" | base64 -d 2>/dev/null)" || {
  echo "cron-wrap: payload for $NAME is not valid base64" >&2
  exit 2
}

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
ERRTAIL="$(tail -c 400 "$ERRFILE" 2>/dev/null | tr '\n\t' '  ' | cut -c1-160)"
rm -f "$ERRFILE"

printf '%s\t%s\t%s\t%s\t%s\n' "$STAMP" "$NAME" "$RC" "$((END - START))" "$ERRTAIL" >> "$STATE_DIR/runs.tsv"

# Keep the log from growing without bound: it is one line per run, and the fan-out runs every minute.
SIZE="$(stat -c%s "$STATE_DIR/runs.tsv" 2>/dev/null || echo 0)"
if [ "${SIZE:-0}" -gt 5000000 ]; then
  tail -n 20000 "$STATE_DIR/runs.tsv" > "$STATE_DIR/runs.tsv.tmp" && mv "$STATE_DIR/runs.tsv.tmp" "$STATE_DIR/runs.tsv"
fi

exit "$RC"
