#!/usr/bin/env bash
# Full state of the worker BEFORE anyone reboots it: what is running, what is restarting the engine, is any agent
# mid-work, and what does the engine actually print when it starts. Read-only except one deliberate foreground run.
echo "=== host / uptime / memory ==="
hostname; uptime; free -m | head -2
echo
echo "=== who is logged in / any ssh sessions from other hosts ==="
who 2>/dev/null | head -5
ss -tnp 2>/dev/null | grep -E ':(22)\s' | head -5
echo
echo "=== node processes, with parents and age ==="
ps -eo pid,ppid,etime,rss,args | grep -E 'node|dsh' | grep -v grep | cut -c1-150 | head -20
echo
echo "=== is any AGENT work in flight? (headless children, mesh mailbox dirs, recent session writes) ==="
ps -eo pid,etime,args | grep -E 'headless|mesh-mailbox|subagent' | grep -v grep | cut -c1-120 | head -8
ls -dt "$HOME"/.dsh-mesh-mailboxes/* 2>/dev/null | head -3
find "$HOME/.dsh/sessions" -type f -mmin -30 2>/dev/null | head -5
echo
echo "=== what could be restarting the engine? ==="
echo "--- user units ---"
systemctl --user list-units --all --no-legend 2>/dev/null | grep -iE 'dsh|engine' | head -5
ls -1 "$HOME/.config/systemd/user" 2>/dev/null | head -10
echo "--- system units ---"
systemctl list-units --all --no-legend 2>/dev/null | grep -iE 'dsh|engine' | head -5
echo "--- cron ---"
crontab -l 2>/dev/null | grep -vE '^\s*#' | grep -vE '^\s*$' | head -8
echo "--- any supervisor-ish process ---"
ps -eo pid,args | grep -E 'pm2|forever|supervisor|watchdog|nodemon' | grep -v grep | head -5
echo
echo "=== engine start, FOREGROUND, output captured to a file ==="
LOG=/home/zabz/engine-foreground-$(date -u +%H%M%S).log
cd /home/zabz || exit 2
timeout 25 /home/zabz/.local/node/bin/node \
  /home/zabz/dsh-engine/node_modules/@deepseek-ai/dsh/lib/bin.js web --port 3098 --no-open \
  --trusted-host zabz-tech-linux.tail93e6e6.ts.net > "$LOG" 2>&1
echo "  foreground exit: $?"
echo "  log: $LOG ($(stat -c%s "$LOG" 2>/dev/null) bytes)"
echo "  --- first 20 lines ---"
head -20 "$LOG" | sed 's/^/  /'
