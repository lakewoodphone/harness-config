#!/usr/bin/env python3
"""What is the company's completed work actually about?

Written 2026-09-15 after the first fresh read of the company's output in fifteen rounds.
Throughput said the company was healthy (1,729 tasks completed in 7 days). The samples said it
was mostly watching itself:

    "6 duplicate task clusters detected", "evolution subsystem failed",
    "I'm the MASHGIACH inspecting dep...", "10 agents with 0 tasks",
    "boa_sync (114 fails), spending_report (38 fails)"

P74/P75 measured "95% of activity is self-management" on 2026-09-14 and nothing re-measured it
since. A number asserted once and never re-derived becomes folklore -- and this one decides whether
the company is worth its spend, so it should take one command rather than an improvised query.

Three classes, deliberately crude and stated rather than hidden:
  owner-delegated  the task came from him (`delegated_from` set, or a creator naming the owner)
  business-facing  the title names a shop, customer or money concern
  self             everything else -- the system working on itself

The classes overlap; owner wins, then business, so the `self` share is an upper bound and the
interesting number is how small the first two are.

Run from any machine that can reach the authority:
    python scripts/task-origin-report.py [days]
"""

from __future__ import annotations

import os
import subprocess
import sys

DAYS = int(sys.argv[1]) if len(sys.argv) > 1 else 7

REMOTE_TEMPLATE = r'''
cd ~/personal-secretary-mvp
.venv/bin/python - <<'PY'
import sqlite3

c = sqlite3.connect("data/secretary.db")
c.row_factory = sqlite3.Row
days = __DAYS__

own_q = "(lower(coalesce(agent_id,'')) like '%owner%' or coalesce(delegated_from,'') != '')"
biz_q = ("(lower(title) like '%customer%' or lower(title) like '%case #%'"
         " or lower(title) like '%order%' or lower(title) like '%refund%'"
         " or lower(title) like '%repair%' or lower(title) like '%invoice%'"
         " or lower(title) like '%payment%' or lower(title) like '%payroll%'"
         " or lower(title) like '%billing%' or lower(title) like '%shop%'"
         " or lower(title) like '%supplier%' or lower(title) like '%sourcing%')")
base = "from tasks where status='done' and created_at > datetime('now','-%d days')" % days

rows = [
    ("owner-delegated", c.execute("select count(*) " + base + " and " + own_q).fetchone()[0]),
    ("business-facing", c.execute("select count(*) " + base + " and not " + own_q
                                  + " and " + biz_q).fetchone()[0]),
    ("self", c.execute("select count(*) " + base + " and not " + own_q
                       + " and not " + biz_q).fetchone()[0]),
]
total = sum(n for _, n in rows)
print("completed tasks in the last %d day(s): %d" % (days, total))
for label, n in rows:
    share = (n / total * 100) if total else 0.0
    print("  %-16s %6d  %5.1f%%" % (label, n, share))

print()
print("newest five -- read these before believing the counts:")
for r in c.execute("select id, substr(title,1,72) t " + base + " order by created_at desc limit 5"):
    print("  #%s %s" % (r["id"], r["t"]))
PY
'''


def main() -> int:
    host = os.environ.get("SECRETARY_SSH", "secretary-cf")
    script = REMOTE_TEMPLATE.replace("__DAYS__", str(DAYS))
    try:
        out = subprocess.run(
            ["ssh", host, "tr -d '\r' | bash -s"],
            input=script,
            capture_output=True,
            text=True,
            timeout=180,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        print("cannot reach the authority over ssh %r: %s" % (host, exc))
        return 2
    if out.returncode != 0:
        print("remote command failed (%d): %s" % (out.returncode, (out.stderr or "").strip()[:400]))
        return out.returncode
    print(out.stdout.strip())
    return 0


if __name__ == "__main__":
    sys.exit(main())
