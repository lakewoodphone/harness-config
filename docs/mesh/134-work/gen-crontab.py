import base64, json
jobs = [
 ("*/5",  "cron-target-guard",   "/usr/bin/python3 /usr/local/bin/cron-target-guard.py --write-status >> /root/.cron-targets/guard.log 2>&1"),
 ("*/5",  "cron-script-guard",   "/usr/bin/python3 /usr/local/bin/cron-script-guard.py >> /root/.cron-scripts/guard.log 2>&1"),
 ("*/5",  "store-write-check",   "/usr/bin/python3 /usr/local/bin/store-write-check.py --db /root/.store-write-check/scratch.db --slow-seconds 5 >> /root/.store-write-check/guard.log 2>&1"),
 ("*/5",  "deadman",             "/usr/bin/python3 /usr/local/bin/deadman.py >> /root/.sms-inbox/deadman.log 2>&1"),
 ("*/15", "guard-registry",      "/usr/bin/python3 /usr/local/bin/guard-registry-check.py --write-status >> /root/.guard-registry/cron.log 2>&1"),
 ("*/15", "journal-commit",      "/usr/local/bin/journal-commit.sh"),
 ("*/15", "text-channel-check",  "/bin/bash /usr/local/bin/text-channel-check.sh >/dev/null 2>&1"),
 ("*/20", "tmpfs-reaper",        "mkdir -p /root/tmp-rescue && MIN_FREE_MB=600 TARGET_FREE_MB=1500 RESCUE_ROOT=/root/tmp-rescue /bin/bash /usr/local/bin/tmpfs-reaper.sh >/dev/null 2>&1"),
 ("*/30", "tree-integrity-check","TREE_INTEGRITY_DRY_RUN=1 /bin/bash /usr/local/bin/tree-integrity-check.sh >/dev/null 2>&1"),
 ("*/30", "report-offsite-age",  "/usr/local/bin/report-offsite-age.sh >> /root/report-offsite-age.log 2>&1"),
 ("45 5", "prune-backups",       "/usr/local/bin/prune-backups.sh /var/lib/authority-snapshots >> /var/log/authority-backup-prune.log 2>&1"),
 ("17 4 * * 0", "db-integrity-check", "SECRETARY_DB=/root/authority.db DB_INTEGRITY_BACKUP_ROOT=/var/lib/authority-snapshots /usr/bin/python3 /usr/local/bin/db-integrity-check.py --write-status >> /root/.db-integrity/cron.log 2>&1"),
]
header = """SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
# == the cloud authority crontab, written by the 2026-10-11 cutover port ========================
# Every job runs through the estate's own wrapper, so each run appends one row to
# /root/.cron-status/runs.tsv: <ISO-8601 UTC>\\t<name>\\t<rc>\\t<seconds>\\t<first 160 chars of stderr>.
# The NAME is the office job's name wherever the job is the same job, so the ledger and any monitor
# that keyed on it still read true. The payload is the command, base64-encoded, so nothing in it can
# be re-quoted wrongly by cron.
#
# SCHEDULING, and why these times: the offsite backup (systemd, authority-offsite-backup.timer) runs
# at 05:20 and is the one heavy disk job on this box. prune-backups sits at 05:45 -- after the
# backup has finished and before anything else -- and db-integrity-check is weekly at 04:17 Sunday,
# far from both. Nothing here may overlap the backup: one disk, 75 GB, a 23.7 GB live database.
"""
lines = [header]
for sched, name, cmd in jobs:
    if len(sched.split()) == 5:
        cron = sched
    else:
        cron = sched + " * * *"
    b64 = base64.b64encode(cmd.encode()).decode()
    lines.append("%-13s /usr/local/bin/cron-wrap.sh %s %s" % (cron, name, b64))
open(r"C:\\Users\\ezabz\\code\\_port-staging\cloud-crontab.txt", "w", encoding="utf-8", newline="\n").write("\n".join(lines) + "\n")
for sched, name, cmd in jobs:
    print("%-13s %-22s %s" % (sched, name, base64.b64encode(cmd.encode()).decode()))