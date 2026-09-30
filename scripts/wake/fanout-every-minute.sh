set -u
C=/tmp/cron.proposed
crontab -l > /tmp/cron.current
BEFORE_LINES=$(wc -l < /tmp/cron.current)
BEFORE_5=$(grep -c '^\*/5 \* \* \* \* WAKE_FANOUT_TARGET' /tmp/cron.current)

# Work on the FILE crontab produced, which is LF by definition. The previous attempt piped a
# PowerShell-written script and its CRLF reached the parser, which rejected the whole crontab.
sed 's|^\*/5 \(\* \* \* \* WAKE_FANOUT_TARGET=5 WAKE_FANOUT_MAX=8 /bin/bash /home/zabz/bin/wake-fanout.sh\)|* \1|' /tmp/cron.current > "$C"

AFTER_LINES=$(wc -l < "$C")
AFTER_1=$(grep -c '^\* \* \* \* \* WAKE_FANOUT_TARGET' "$C")
echo "lines before=$BEFORE_LINES after=$AFTER_LINES   every-5 lines before=$BEFORE_5 every-1 in proposal=$AFTER_1"

if [ "$AFTER_LINES" != "$BEFORE_LINES" ] || [ "$AFTER_1" != "1" ] || [ "$BEFORE_5" != "1" ]; then
  echo "REFUSED: the proposal does not look like exactly one changed line - nothing installed"
  echo "--- the only differing lines ---"
  diff /tmp/cron.current "$C" | head -6
  exit 0
fi

echo "--- the only difference ---"
diff /tmp/cron.current "$C" | head -6
crontab "$C"
echo "installed. now live:"
crontab -l | grep WAKE_FANOUT_TARGET | cut -c1-100
echo "line count live: $(crontab -l | wc -l) (was $BEFORE_LINES)"
