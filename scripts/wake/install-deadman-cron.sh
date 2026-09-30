set -u
C=/tmp/cron.deadman
crontab -l > /tmp/cron.before
BEFORE=$(wc -l < /tmp/cron.before)
HAVE=$(grep -c 'deadman.py' /tmp/cron.before)

if [ "$HAVE" != "0" ]; then
  echo "already scheduled ($HAVE lines) - nothing to do"
  crontab -l | grep deadman.py
  exit 0
fi

cp /tmp/cron.before "$C"
cat >> "$C" <<'EOF'
# dead-man switch (2026-09-30): the authority pings an EXTERNAL check every 5 minutes. Every other
# heartbeat this system keeps is read by something on the authority itself, so if the authority dies its
# own health checks die with it and nobody is told. This is the only mechanism that can report that, because
# the report does not come from here. Period 900s, grace 300s, all notification channels. The ping body
# carries the wake-state counts and the in-flight dispatcher count, so an alert arrives with context.
*/5 * * * * /usr/bin/python3 /home/zabz/bin/deadman.py >> /home/zabz/.sms-inbox/deadman.log 2>&1
EOF

AFTER=$(wc -l < "$C")
ADDED=$(grep -c 'deadman.py' "$C")
echo "lines before=$BEFORE after=$AFTER added_lines=$((AFTER-BEFORE)) deadman_lines=$ADDED"
if [ "$ADDED" != "1" ] || [ "$AFTER" -le "$BEFORE" ]; then
  echo "REFUSED: the proposal does not contain exactly one deadman line - nothing installed"
  exit 0
fi
if [ "$(grep -c 'WAKE_FANOUT_TARGET' "$C")" != "1" ] || [ "$(grep -c 'run-wake-sources' "$C")" != "1" ]; then
  echo "REFUSED: the existing wake lines are not intact in the proposal - nothing installed"
  exit 0
fi
diff /tmp/cron.before "$C" | head -8
crontab "$C"
echo "installed. live now:"
crontab -l | grep -A1 deadman | cut -c1-120
echo "live line count: $(crontab -l | wc -l) (was $BEFORE)"
echo "--- and one immediate run, to prove the installed path works end to end ---"
/usr/bin/python3 /home/zabz/bin/deadman.py
tail -2 /home/zabz/.sms-inbox/deadman.log 2>/dev/null
