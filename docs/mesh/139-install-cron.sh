#!/bin/bash
# Install THIS workstream's cron lines. Read-modify-write the crontab so that whatever
# another workstream has already installed is preserved verbatim: our block is removed
# by marker and re-appended, nothing else is touched.
set -uo pipefail
CUR=/root/_staging/crontab.before
crontab -l > "$CUR" 2>/dev/null || : > "$CUR"
echo "--- existing crontab: $(wc -l < "$CUR") line(s) ---"
grep -v '^# >>> 139-port-owner-channel' "$CUR" | grep -v '^# <<< 139-port-owner-channel' | awk '
  BEGIN{skip=0}
  /^# >>> 139-port-owner-channel/{skip=1; next}
  /^# <<< 139-port-owner-channel/{skip=0; next}
  skip==0{print}
' > /root/_staging/crontab.new

cat >> /root/_staging/crontab.new <<'CRON'
# >>> 139-port-owner-channel (workstream 139, installed 2026-10-11T06:38Z)
# Every payload is base64; the decoded command is in the line above each one in
# docs/mesh/139-PORT-OWNER-CHANNEL.md. cron-wrap.sh records one row per run in
# /root/.cron-status/runs.tsv. Nothing in this block sends a message to any human.
# sms-inbox: READ-ONLY against Twilio. The office ran a 4-command chain here and the
# other three are deliberately NOT installed (see the report, "COULD NOT BE ENABLED").
#   decode: /usr/bin/python3 /home/zabz/bin/sms-inbox.py sync --pages 3 >> /home/zabz/.sms-inbox/sync.log 2>&1
*/5 * * * * /usr/local/bin/cron-wrap.sh sms-inbox L3Vzci9iaW4vcHl0aG9uMyAvaG9tZS96YWJ6L2Jpbi9zbXMtaW5ib3gucHkgc3luYyAtLXBhZ2VzIDMgPj4gL2hvbWUvemFiei8uc21zLWluYm94L3N5bmMubG9nIDI+JjE=
#   decode: cd /home/zabz && /usr/bin/python3 /home/zabz/bin/mirror-owner-sms.py --apply >> /home/zabz/.sms-inbox/mirror.log 2>&1
*/5 * * * * /usr/local/bin/cron-wrap.sh mirror-owner-sms Y2QgL2hvbWUvemFieiAmJiAvdXNyL2Jpbi9weXRob24zIC9ob21lL3phYnovYmluL21pcnJvci1vd25lci1zbXMucHkgLS1hcHBseSA+PiAvaG9tZS96YWJ6Ly5zbXMtaW5ib3gvbWlycm9yLmxvZyAyPiYx
#   decode: cd /home/zabz && /usr/bin/python3 /home/zabz/bin/reconcile-sent-status.py --apply --hours 48 >> /home/zabz/.sms-inbox/sent-status.log 2>&1
*/10 * * * * /usr/local/bin/cron-wrap.sh reconcile-sent-status Y2QgL2hvbWUvemFieiAmJiAvdXNyL2Jpbi9weXRob24zIC9ob21lL3phYnovYmluL3JlY29uY2lsZS1zZW50LXN0YXR1cy5weSAtLWFwcGx5IC0taG91cnMgNDggPj4gL2hvbWUvemFiei8uc21zLWluYm94L3NlbnQtc3RhdHVzLmxvZyAyPiYx
# <<< 139-port-owner-channel
CRON

crontab /root/_staging/crontab.new
echo "--- installed ---"
crontab -l
echo "--- byte-for-byte decode check of every payload we installed ---"
crontab -l | while IFS= read -r line; do
  case "$line" in
    */usr/local/bin/cron-wrap.sh\ *)
      : ;;
    *) continue ;;
  esac
  nm=$(printf '%s' "$line" | awk '{print $7}')
  pl=$(printf '%s' "$line" | awk '{print $8}')
  printf '%s\t%s\n' "$nm" "$(printf '%s' "$pl" | base64 -d 2>&1)"
done
