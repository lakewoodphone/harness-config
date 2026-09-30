#!/usr/bin/env bash
# Install the API watchdog as a systemd unit + timer, and prove it on a throwaway unit
# first. The real unit is never broken for a test.
set -uo pipefail

install -m 0755 /tmp/api-watchdog.sh /home/zabz/bin/api-watchdog.sh

cat > /etc/systemd/system/secretary-api-watchdog.service <<'EOF'
# Tells the owner when the company's API has stopped, and recovers it once.
#
# WHY, measured 2026-09-30: `secretary-api.service` caps itself at 3 starts per 15 minutes
# on purpose (installed 2026-09-28 after 27.9 minutes of downtime in one day). When that
# burst is exhausted the unit goes to `failed`, systemd stops trying, and NOTHING notices --
# no alert, no recovery, no symptom until something downstream times out. A session that
# deployed several fixes in an afternoon hit it and the company was down until a human ran
# `systemctl reset-failed`. This is the alert and the one-shot recovery for that state. It
# does NOT weaken the cap: the watchdog itself will not recover more than once an hour.
[Unit]
Description=Watch the company API unit and report if it has stopped
After=network-online.target

[Service]
Type=oneshot
Environment=WATCHDOG_UNIT=secretary-api.service
Environment=WATCHDOG_STATE=/home/zabz/.api-watchdog-state
Environment=WATCHDOG_INCIDENTS=/home/zabz/.api-watchdog-incidents.log
Environment=WATCHDOG_COOLDOWN_SEC=3600
ExecStart=/home/zabz/bin/api-watchdog.sh
EOF

cat > /etc/systemd/system/secretary-api-watchdog.timer <<'EOF'
[Unit]
Description=Check the company API unit every five minutes

[Timer]
OnBootSec=3min
OnUnitActiveSec=5min
AccuracySec=30s
Unit=secretary-api-watchdog.service

[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
systemctl enable --now secretary-api-watchdog.timer >/dev/null 2>&1
echo "timer: $(systemctl is-active secretary-api-watchdog.timer) / $(systemctl is-enabled secretary-api-watchdog.timer)"

echo
echo "=== prove it on a throwaway failed unit (real unit untouched) ==="
U=wd-install-probe.service
cat > "/etc/systemd/system/$U" <<'EOF'
[Unit]
Description=throwaway
[Service]
Type=oneshot
ExecStart=/bin/false
Restart=no
EOF
systemctl daemon-reload >/dev/null 2>&1
systemctl start "$U" 2>/dev/null || true
sleep 1
rm -f /home/zabz/.api-watchdog-probe-state /home/zabz/.api-watchdog-probe-incidents.log
WATCHDOG_UNIT="$U" \
WATCHDOG_STATE=/home/zabz/.api-watchdog-probe-state \
WATCHDOG_INCIDENTS=/home/zabz/.api-watchdog-probe-incidents.log \
WATCHDOG_NOTIFY_URL=http://127.0.0.1:9/dead \
  bash /home/zabz/bin/api-watchdog.sh 2>&1 | sed 's/^/  /'
echo "  --- incident record ---"
cat /home/zabz/.api-watchdog-probe-incidents.log 2>/dev/null | sed 's/^/  /' || echo "  (NONE - a bug)"
echo "  --- cooldown state ---"
cat /home/zabz/.api-watchdog-probe-state 2>/dev/null | sed 's/^/  /' || echo "  (none, because the throwaway unit cannot start - correct)"

systemctl stop "$U" 2>/dev/null || true
systemctl reset-failed "$U" 2>/dev/null || true
rm -f "/etc/systemd/system/$U" /home/zabz/.api-watchdog-probe-state /home/zabz/.api-watchdog-probe-incidents.log
systemctl daemon-reload >/dev/null 2>&1

echo
echo "=== the real unit ==="
echo "  secretary-api: $(systemctl is-active secretary-api) pid=$(systemctl show secretary-api -p MainPID --value)"
echo "  next watchdog run: $(systemctl list-timers secretary-api-watchdog.timer --no-pager 2>/dev/null | sed -n 2p | awk '{print $1, $2, $3}')"
