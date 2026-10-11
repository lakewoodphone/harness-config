set -e
echo "=== create state dirs ==="
mkdir -p /root/.cron-status /root/.cron-targets /root/.cron-scripts /root/.guard-registry \
         /root/.db-integrity /root/.pain-check /root/.store-write-check /root/tmp-rescue \
         /var/lib/authority-snapshots /var/log
chmod 755 /root/.cron-status /root/.cron-targets /root/.cron-scripts /root/.guard-registry \
          /root/.db-integrity /root/.pain-check /root/.store-write-check /root/tmp-rescue \
          /var/lib/authority-snapshots
ls -ld /root/.cron-status /root/.cron-targets /root/.cron-scripts /root/.guard-registry \
       /root/.db-integrity /root/.pain-check /root/.store-write-check /root/tmp-rescue \
       /var/lib/authority-snapshots
echo "=== critical paths (the files NO crontab names) ==="
cat > /root/.cron-targets/critical.txt <<'EOF'
# Files this authority NEEDS that no crontab line names. One absolute path per line.
# Maintained by the 2026-10-11 cutover port (family 10 / guards). A file here is checked for
# existence, readability, the execute bit (shell scripts) and CR bytes -- see cron-target-guard.py.
#
# THE ROLLBACK ANCHOR, on the office box. Nothing on this authority may delete it; this line is
# how the authority gets told if it ever goes missing.
/home/zabz/personal-secretary-mvp/data/secretary.db
#
# the offsite leg (owned by the offsite-backup workstream -- checked here, never edited)
/usr/local/bin/authority-offsite-backup.sh
/etc/systemd/system/authority-offsite-backup.timer
/root/.lpt-r2.env
/root/.ssh/id_ed25519_hetzner
#
# the external dead-man switch
/usr/local/bin/authority-deadman.py
/root/.sms-inbox/deadman.env
#
# this port's own programs
/usr/local/bin/cron-wrap.sh
/usr/local/bin/cron-target-guard.py
/usr/local/bin/cron-script-guard.py
/usr/local/bin/db-integrity-check.py
/usr/local/bin/prune-backups.sh
/usr/local/bin/tmpfs-reaper.sh
/usr/local/bin/report-offsite-age.sh
/usr/local/bin/guard-registry-check.py
#
# the company application
/opt/company/.venv/bin/python
/root/authority.db
EOF
chmod 644 /root/.cron-targets/critical.txt
wc -l /root/.cron-targets/critical.txt
echo "=== cron-wrap selftest: one deliberate run ==="
/usr/local/bin/cron-wrap.sh ledger-selftest "$(printf '%s' 'echo hello-from-cron-wrap' | base64 -w0)"
echo "rc=$?"
echo "=== exit code passthrough ==="
/usr/local/bin/cron-wrap.sh ledger-selftest-fail "$(printf '%s' 'exit 7' | base64 -w0)"; echo "rc=$?"
echo "=== the ledger ==="
cat /root/.cron-status/runs.tsv
