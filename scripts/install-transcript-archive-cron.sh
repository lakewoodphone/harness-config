#!/usr/bin/env bash
# install-transcript-archive-cron.sh — install (or reinstall) the hourly transcript-archive job.
#
# Run this ON the authority. It is idempotent: it removes any previous transcript-archive line and
# writes one fresh one. It follows this estate's crontab convention, `cron-wrap.sh`, which records
# every run's exit code in ~/.cron-status/runs.tsv -- so "the job has not run" and "the job ran and
# failed" are both readable facts rather than things to infer from silence.
#
# The command is passed BASE64-encoded because these lines contain quotes and redirections and every
# naive re-quoting is a chance to silently change what cron runs (see cron-wrap.sh's own header).
set -euo pipefail

RUNNER="${TRANSCRIPT_RUNNER:-$HOME/bin/transcript-archive-run.sh}"
STATE_DIR="${TRANSCRIPT_STATE_DIR:-$HOME/.transcript-archive}"
SCHEDULE="${TRANSCRIPT_CRON:-23 * * * *}"

mkdir -p "$STATE_DIR"
CMD="$RUNNER >/dev/null 2>>$STATE_DIR/cron.err"
PAYLOAD="$(printf '%s' "$CMD" | base64 -w0)"
LINE="$SCHEDULE /home/zabz/bin/cron-wrap.sh transcript-archive $PAYLOAD"

TMP="$(mktemp)"
crontab -l 2>/dev/null | grep -v 'cron-wrap.sh transcript-archive ' > "$TMP" || true
printf '%s\n' "$LINE" >> "$TMP"
crontab "$TMP"
rm -f "$TMP"

echo "installed:"
crontab -l | grep 'cron-wrap.sh transcript-archive ' || true
echo
echo "verify it is a real command (base64 round-trips):"
printf '%s' "$PAYLOAD" | base64 -d; echo
