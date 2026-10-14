#!/usr/bin/env bash
# install-card-due-watch-cron.sh — add the card-due-watch daily job to root's crontab.
#
# Idempotent, backs up the crontab first, and VERIFIES the wrapped payload decodes back
# to the exact command byte for byte before it writes anything - which is the whole
# reason cron-wrap.sh takes base64 (see its own header: naive re-quoting of a crontab
# line is how a job silently becomes a different job).
set -euo pipefail

NAME="card-due-watch"
SCHEDULE="0 13 * * *"          # 13:00 UTC = 09:00 ET in October (EDT, UTC-4)
CMD="/usr/bin/python3 /root/bin/card-due-watch.py --send >> /root/.card-due-watch/run.log 2>&1"
STATE_DIR="/root/.card-due-watch"
WRAP="/usr/local/bin/cron-wrap.sh"

mkdir -p "$STATE_DIR"

if [ ! -x "$WRAP" ]; then
  echo "REFUSING: $WRAP is not executable - wrapping by hand would lose the run record" >&2
  exit 1
fi
if [ ! -f /root/bin/card-due-watch.py ]; then
  echo "REFUSING: /root/bin/card-due-watch.py is not deployed" >&2
  exit 1
fi

B64="$(printf '%s' "$CMD" | base64 -w0)"

# Prove the round trip before writing. A payload that does not decode to the original
# is a job that runs something else, and cron would never tell us.
DECODED="$(printf '%s' "$B64" | base64 -d)"
if [ "$DECODED" != "$CMD" ]; then
  echo "REFUSING: base64 round trip did not reproduce the command" >&2
  exit 1
fi

LINE="$SCHEDULE $WRAP $NAME $B64"

crontab -l > "$STATE_DIR/crontab.bak.$(date -u +%Y%m%dT%H%M%SZ)" 2>/dev/null || true

if crontab -l 2>/dev/null | grep -q "[[:space:]]$NAME[[:space:]]"; then
  echo "ALREADY PRESENT - replacing the existing line"
  crontab -l 2>/dev/null | grep -v "[[:space:]]$NAME[[:space:]]" > "$STATE_DIR/crontab.new"
  echo "$LINE" >> "$STATE_DIR/crontab.new"
  crontab "$STATE_DIR/crontab.new"
else
  { crontab -l 2>/dev/null; echo "$LINE"; } > "$STATE_DIR/crontab.new"
  crontab "$STATE_DIR/crontab.new"
  echo "ADDED"
fi

echo "--- installed line ---"
crontab -l | grep "[[:space:]]$NAME[[:space:]]"
echo "--- verified payload decodes to ---"
crontab -l | grep "[[:space:]]$NAME[[:space:]]" | awk '{print $NF}' | base64 -d
echo
echo "--- total crontab lines: $(crontab -l | wc -l) ---"
