"""Test: mirror freshness must come from the provenance line, never from mtime.

The defect being tested, measured 2026-10-13: the always-read page printed
"(mirror age 38 min)" over `state/owner-questions.md` whose own provenance line said it was
generated 2026-09-17, listing 19 pending while the authority held 161. Its mtime was minutes
old because a checkout had rewritten the file.
"""
import importlib.util
import os
import sys
import tempfile
import time
from pathlib import Path

JOURNAL = Path(os.path.expanduser("~/code/harness-config/journal/tools/journal.py"))
spec = importlib.util.spec_from_file_location("j", str(JOURNAL))
j = importlib.util.module_from_spec(spec)
try:
    spec.loader.exec_module(j)
except SystemExit:
    pass

tmp = Path(tempfile.mkdtemp())


def mk(name, provenance, mtime_age_days):
    """Write a mirror in the REAL format.

    The writer emits (journal.py `cmd_questions`):
        Provenance: 488 row(s) read, 162 pending, generated 2026-10-13 13:35 UTC on ZABZ-YOGA.
    The first version of this test wrote "generated <ts> on ZABZ-YOGA." with no `UTC`, so the
    regex correctly refused to parse it and every case returned infinity. The test was wrong,
    not the code -- a reminder that a regex that refuses is doing its job.
    """
    p = tmp / name
    body = "# OWNER QUESTIONS — open only\n\nUpdated: 2026-10-13\n\n"
    if provenance:
        body += ("Provenance: 488 row(s) read, 19 pending, generated %s on ZABZ-YOGA.\n"
                 % provenance)
    p.write_text(body, encoding="utf-8")
    old = time.time() - mtime_age_days * 86400
    os.utime(p, (old, old))
    return p


failures = []


def check(label, got, expect):
    ok = expect(got)
    print("%-34s %12.0f min   %s" % (label, got, "OK" if ok else "FAIL"))
    if not ok:
        failures.append(label)


p1 = mk("old-content-fresh-mtime.md", "2026-09-17 04:40 UTC", 0.0)
check("old content + fresh mtime", j._mirror_age_minutes(p1), lambda v: v > 10000)

p2 = mk("fresh.md", time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()), 3.0)
check("fresh content + old mtime", j._mirror_age_minutes(p2), lambda v: v < 60)

p3 = mk("noprov.md", None, 0.0)
check("no provenance at all", j._mirror_age_minutes(p3), lambda v: v == float("inf"))

print()
print("the OLD rule would have said, for the first case: %.0f min"
      % ((time.time() - p1.stat().st_mtime) / 60.0))
print("and for the second:                              %.0f min"
      % ((time.time() - p2.stat().st_mtime) / 60.0))
print()
print("RESULT:", "all checks passed" if not failures else "FAILED: " + ", ".join(failures))
sys.exit(1 if failures else 0)
