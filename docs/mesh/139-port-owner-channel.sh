#!/bin/bash
# ============================================================================
# 139-port-owner-channel — THE COMPLETE, IDEMPOTENT INSTALLER (workstream 139)
# ============================================================================
# Author: Zabz, ZABZ-YOGA session, 2026-10-11.
#
# READ docs/mesh/139-PORT-OWNER-CHANNEL.md FIRST. This script is the whole port in
# one place: it assumes /root/_staging/files/ already holds the tool bodies (shipped
# by scp from the office box, every sha256 verified against the office file) and
# /root/_staging/139-FINISH.sh its second half.
#
# SAFE TO RE-RUN. It never overwrites a path it did not create without saying so,
# it never touches /root/authority.db, and it never sends anything to any human.
# ============================================================================
set -uo pipefail
say() { printf '%s\n' "$*"; }
S=/root/_staging
F=$S/files

say "########## 1. /home/zabz aliases: root's HOME is /root, payloads say /home/zabz ##########"
mkdir -p /root/bin /root/code
for pair in "bin:/root/bin" "code:/root/code" \
            "accounting-data:/root/accounting-data" ".sms-inbox:/root/.sms-inbox" \
            ".owner-ask:/root/.owner-ask" ".cfo:/root/.cfo" ".cfo-asks:/root/.cfo-asks" \
            ".hours-drift:/root/.hours-drift" ".lpt-reports:/root/.lpt-reports" \
            ".lpt-verify:/root/.lpt-verify" ".lpt-recon:/root/.lpt-recon" \
            ".lpt-ops:/root/.lpt-ops" ".lpt-hub-refresh:/root/.lpt-hub-refresh" \
            ".cron-status:/root/.cron-status" "work:/root/work" ".dsh:/root/.dsh"; do
  name="${pair%%:*}"; target="${pair#*:}"
  if [ -L "/home/zabz/$name" ]; then continue; fi
  if [ -e "/home/zabz/$name" ]; then say "  SKIP-EXISTS /home/zabz/$name"; continue; fi
  mkdir -p "$target"; ln -s "$target" "/home/zabz/$name"; say "  created /home/zabz/$name -> $target"
done
for t in /root/personal-secretary-mvp /home/zabz/personal-secretary-mvp; do
  if [ -L "$t" ] || [ -e "$t" ]; then continue; fi
  ln -s /opt/company "$t"; say "  created $t -> /opt/company"
done

say "########## 2. install the tool bodies (56 files, every sha256 == the office file) ##########"
bash "$F/../install-tools.sh" 2>/dev/null || bash /root/_staging/install-tools.sh

say "########## 3. the two corrections that are not path plumbing ##########"
# (a) owner-queue.py and owner-ask.py default to the app data dir, which on this box is a
#     1.8 MB stub with NO owner_decision_queue -> a confident "nothing to ask" while 160
#     questions wait. Point them at the authority; keep the office original beside each.
for f in /root/bin/owner-queue.py /root/bin/owner-ask.py; do
  [ -f "$f.office-default" ] || cp -p "$f" "$f.office-default"
done
sed -i 's#"/home/zabz/personal-secretary-mvp/data/secretary.db"#"/root/authority.db"#' /root/bin/owner-queue.py
sed -i 's#HOME / "personal-secretary-mvp/data/secretary.db"#Path("/root/authority.db")#' /root/bin/owner-ask.py
say "  owner-queue.py -> $(grep -A1 'DEFAULT_DB = os.environ.get' /root/bin/owner-queue.py | tail -1)"
say "  owner-ask.py   -> $(grep '^APP_DB' /root/bin/owner-ask.py)"
# (b) three modules cfo-scoreboard.py imports and the brief's dependency list does not name
for f in cfo_rules.py cfo-resolve.py cfo-balances.py merchant_resolve.py; do
  if [ -f "$F/$f" ]; then cp -f "$F/$f" /root/bin/$f; chmod 755 /root/bin/$f; say "  installed $f"; fi
done

say "########## 4. the inbox store (office state, byte-for-byte, if not already in place) ##########"
if [ -f /root/.sms-inbox/inbox.db ]; then
  /usr/bin/python3 -c "
import sqlite3
c=sqlite3.connect('file:/root/.sms-inbox/inbox.db?mode=ro',uri=True)
print('  inbox.db integrity:',c.execute('pragma integrity_check').fetchone()[0],
      '| messages',c.execute('select count(*) from messages').fetchone()[0],
      '| permissions',c.execute('select count(*) from permissions').fetchone()[0],
      '| wake',c.execute('select count(*) from wake').fetchone()[0])"
else
  say "  ABSENT. If /root/_staging/inbox-office.db exists (sha256 2c0070dcca4fbd21a5b144478a57b59a60bbb6488a2b8e4b17904404257983af):"
  say "    cp /root/_staging/inbox-office.db /root/.sms-inbox/inbox.db && chmod 600 /root/.sms-inbox/inbox.db"
fi

say "########## 5. prove every enabled job, by hand, exactly as its cron line runs it ##########"
export HOME=/root
cd /root
for j in "/root/bin/sms-inbox.py sync --pages 3" "/root/bin/sms-inbox.py probe" \
         "/root/bin/reconcile-sent-status.py --apply --hours 48" \
         "/root/bin/cfo-scoreboard.py" "/root/bin/hours-drift-check.py" \
         "/root/bin/owner-queue.py stats"; do
  say "--- $j"
  timeout 240 /usr/bin/python3 $j 2>&1 | tail -6
  say "    rc=$?"
done

say "########## 6. cron: the three read-only lines, plus the two proven CFO/ops lines ##########"
bash "$S/install-cron.sh" 2>/dev/null || bash /root/_staging/install-cron.sh
bash "$S/139-FINISH.sh" 2>/dev/null || say "  139-FINISH.sh not staged; install cron lines from the report section 10"

say "########## 7. state of the box ##########"
crontab -l | grep -c . || true
df -h / | tail -1
say "DONE. Read /root/.cron-status/runs.tsv in five minutes for the first tick."
