import base64, sys, re
path = r"C:\\Users\\ezabz\\code\\_port-staging\cloud-crontab.txt"
expect = {
 "cron-target-guard": "/usr/bin/python3 /usr/local/bin/cron-target-guard.py --write-status >> /root/.cron-targets/guard.log 2>&1",
 "cron-script-guard": "/usr/bin/python3 /usr/local/bin/cron-script-guard.py >> /root/.cron-scripts/guard.log 2>&1",
 "store-write-check": "/usr/bin/python3 /usr/local/bin/store-write-check.py --db /root/.store-write-check/scratch.db --slow-seconds 5 >> /root/.store-write-check/guard.log 2>&1",
 "deadman": "/usr/bin/python3 /usr/local/bin/deadman.py >> /root/.sms-inbox/deadman.log 2>&1",
 "guard-registry": "/usr/bin/python3 /usr/local/bin/guard-registry-check.py --write-status >> /root/.guard-registry/cron.log 2>&1",
 "journal-commit": "/usr/local/bin/journal-commit.sh",
 "text-channel-check": "/bin/bash /usr/local/bin/text-channel-check.sh >/dev/null 2>&1",
 "tmpfs-reaper": "mkdir -p /root/tmp-rescue && MIN_FREE_MB=600 TARGET_FREE_MB=1500 RESCUE_ROOT=/root/tmp-rescue /bin/bash /usr/local/bin/tmpfs-reaper.sh >/dev/null 2>&1",
 "tree-integrity-check": "TREE_INTEGRITY_DRY_RUN=1 /bin/bash /usr/local/bin/tree-integrity-check.sh >/dev/null 2>&1",
 "report-offsite-age": "/usr/local/bin/report-offsite-age.sh >> /root/report-offsite-age.log 2>&1",
 "prune-backups": "/usr/local/bin/prune-backups.sh /var/lib/authority-snapshots >> /var/log/authority-backup-prune.log 2>&1",
 "pain-check": "/usr/bin/python3 /usr/local/bin/pain-check.py --write-status >> /root/.pain-check/cron.log 2>&1",
 "db-integrity-check": "SECRETARY_DB=/root/authority.db DB_INTEGRITY_BACKUP_ROOT=/var/lib/authority-snapshots /usr/bin/python3 /usr/local/bin/db-integrity-check.py --write-status >> /root/.db-integrity/cron.log 2>&1",
}
bad = 0
n = 0
for line in open(path, encoding="utf-8"):
    line = line.rstrip("\n")
    if not line.strip() or line.startswith("#") or "=" in line.split(None, 1)[0]:
        continue
    parts = line.split()
    if len(parts) < 7 or "cron-wrap.sh" not in line:
        print("NOT-A-JOB LINE:", line[:80]); bad += 1; continue
    name = parts[-2]; payload = parts[-1]
    n += 1
    try:
        got = base64.b64decode(payload + "=" * (-len(payload) % 4)).decode()
    except Exception as e:
        print("DECODE FAIL", name, e); bad += 1; continue
    want = expect.get(name)
    if want is None:
        print("UNKNOWN JOB", name); bad += 1; continue
    if got != want:
        print("MISMATCH", name); print("   got :", got); print("   want:", want); bad += 1
print("jobs=%d mismatches=%d" % (n, bad))