#!/usr/bin/env bash
# Schedule the evolution verification loop on the authority.
# Additive only: a NEW file in /etc/cron.d. The existing crontab is not read or
# rewritten. The job is a handful of SQLite statements, not heavy work.
set -uo pipefail

cat > /root/bin/evolution-loop.py <<'PY'
#!/usr/bin/env python3
"""Hourly: backfill missing verification rows and advance open ones to a verdict.

Deployed from personal-secretary-mvp/app/services/evolution_loop.py. Kept as a
thin runner so the schedule does not depend on the API process being up.
"""
import sys

sys.path.insert(0, "/opt/company")

from app.services.evolution_loop import close_the_loop  # noqa: E402

res = close_the_loop("sqlite:////root/authority.db")
print(
    "evolution-loop: backfilled=%(backfilled)s measured=%(measured)s "
    "passed=%(passed)s failed=%(failed)s" % res
)
PY
chmod 755 /root/bin/evolution-loop.py

cat > /etc/cron.d/evolution-loop <<'CRON'
# Evolution verification loop (2026-10-26, round 3).
# Closes the loop the anti-stagnation engine never closed: applied changes get a
# verification row and are graded after 3 measurements. Hourly at :17 so it does
# not collide with the :23 transcript archive or the */5 serving probe.
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
17 * * * * root /opt/company/.venv/bin/python /root/bin/evolution-loop.py >> /var/log/evolution-loop.log 2>&1
CRON
chmod 644 /etc/cron.d/evolution-loop

echo "=== installed ==="
ls -l /etc/cron.d/evolution-loop /root/bin/evolution-loop.py
echo
echo "=== dry run through the exact cron command line ==="
/opt/company/.venv/bin/python /root/bin/evolution-loop.py 2>&1 | tail -3
echo
echo "=== is the cron daemon running? ==="
systemctl is-active cron 2>/dev/null || systemctl is-active crond 2>/dev/null
