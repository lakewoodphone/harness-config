#!/usr/bin/env bash
# box-health-check.sh - watch the things on lpt-apps-01 that fail silently.
#
# WHY THIS EXISTS. The nightly backup script and /root/backup-status-check.sh both existed, and
# nothing called the checker: a backup that stops running produces no error, no log line anyone reads,
# and no symptom until the day someone needs to restore. Same for a filling disk. This runs from the
# secretary (which can reach the box) and turns a silent failure into a row in the owner decision
# queue - the channel the owner actually reads - plus a line in syslog.
#
# 2026-10-05: THE ALERT WAS DETECTED AND NEVER DELIVERED. The disk on lpt-apps-01 reached 86% and this
# script found it, then reported only:
#     WARN: could not create the owner row - see /home/zabz/bin/owner-queue.py
# because the enqueue's output went to /dev/null and the queue had REFUSED it as a duplicate of row
# #49 - a *resolved* self-test row created with DISK_WARN_PCT=1 when this script was first verified
# (similarity 1.00). So the one channel that reaches the owner silently rejected the alert and threw
# away the reason. The disk then hit 100% during a burst of deploys and every database-touching request
# on the site returned 503, with the container still reporting healthy (its healthcheck is liveness
# only, by design). Three fixes, all below:
#   1. the enqueue's output is now captured and logged, never discarded;
#   2. OWNER_QUEUE_ALLOW_DUPLICATE=1 - a monitor alert is a new event, and a RESOLVED earlier row must
#      not suppress it;
#   3. the timestamp is part of the question, so successive alerts are distinguishable.
#
# Install: cron on the secretary, daily a little after the box's 03:35 backup, e.g.
#   15 5 * * * /home/zabz/bin/box-health-check.sh
# It logs itself to $HOME/box-health-check.log, so cron needs no redirect
# (/var/log is root:syslog 775; a user cron cannot create files there).
set -uo pipefail

LOG="${LOG:-$HOME/box-health-check.log}"
exec >>"$LOG" 2>&1

BOX="${BOX:-lpt-apps-01}"
QUEUE="${QUEUE:-$HOME/bin/owner-queue.py}"
DISK_WARN_PCT="${DISK_WARN_PCT:-85}"
STAMP=$(date -u +%Y-%m-%dT%H:%M:%SZ)
problems=()

note() { echo "[$STAMP] $*"; }

# 1. Is the last restic snapshot recent? (the job also prunes, so staleness means the job died)
if ! out=$(ssh -o ConnectTimeout=20 -o BatchMode=yes "$BOX" 'bash /root/backup-status-check.sh' 2>&1); then
    note "BACKUP PROBLEM: $out"
    problems+=("backup: $out")
else
    note "backup ok: $out"
fi

# 2. Is the rentals database inside the newest snapshot? (proves the SQLite half is still collected)
if ! ssh -o ConnectTimeout=20 -o BatchMode=yes "$BOX" \
        'source /root/.restic-env && restic ls latest 2>/dev/null | grep -q sqlite-lakewood-rentals.db'; then
    note "SQLITE SNAPSHOT MISSING from the newest snapshot"
    problems+=("sqlite snapshot missing from the newest restic snapshot")
fi

# 3. Disk headroom on the box.
disk=$(ssh -o ConnectTimeout=20 -o BatchMode=yes "$BOX" "df -P / | awk 'NR==2{print \$5}' | tr -d '%'" 2>/dev/null || echo "")
if [ -n "$disk" ] && [ "$disk" -ge "$DISK_WARN_PCT" ]; then
    note "DISK ${disk}% on $BOX (threshold ${DISK_WARN_PCT}%)"
    problems+=("disk on $BOX at ${disk}% (threshold ${DISK_WARN_PCT}%)")
fi

# 4. Is the site actually serving? (checks the public URL, which is what a user sees)
code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 https://rentals.lakewoodphoneandtech.com/api/health || echo 000)
if [ "$code" != "200" ]; then
    note "SITE: /api/health returned $code"
    problems+=("rentals /api/health returned $code")
fi

if [ "${#problems[@]}" -eq 0 ]; then
    note "all checks passed"
    exit 0
fi

body=$(printf '%s; ' "${problems[@]}")
note "ENQUEUEING owner row: $body"

# Delivery is the whole point of this script, so its result is captured and SHOWN either way. The
# previous version wrote `>/dev/null 2>&1` and printed one vague line on failure, which is how a
# refused alert went unnoticed on 2026-10-05.
queue_out=$(OWNER_QUEUE_ALLOW_DUPLICATE=1 python3 "$QUEUE" add \
    --question "lpt-apps-01 health check failed ($STAMP): ${body}What do you want done?" \
    --context "Automated check by box-health-check.sh on the secretary at $STAMP. The script watches: backup freshness (restic snapshot age > 26h), the rentals SQLite snapshot being present in the newest snapshot, disk usage on the box (threshold ${DISK_WARN_PCT}%), and the public /api/health. Nothing here is destructive; the fix is almost always on the box (cron, disk, container). Disk at 83% and a 46 GB build cache were the state on 2026-09-15; on 2026-10-05 the disk hit 100% during a burst of deploys and the site's database became unwritable." \
    --options "I fix it|Leave it, I will look|Ignore this check for now" \
    --recommendation "I fix it" \
    --severity high \
    --source "box-health-check.sh $STAMP" 2>&1)
queue_rc=$?

if [ "$queue_rc" -eq 0 ]; then
    note "owner row created: $queue_out"
else
    note "DELIVERY FAILED (queue exit $queue_rc) - the owner was NOT told. Queue said:"
    printf '%s\n' "$queue_out" | sed 's/^/    /'
    note "Fix the delivery path, then re-run this script so the alert actually lands."
fi

exit 1
