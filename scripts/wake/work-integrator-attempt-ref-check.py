#!/usr/bin/env python3
"""Regression check for work-integrator.py attempt-ref classification (ledger item 1110).

Run: python3 /root/bin/work-integrator-attempt-ref-check.py
Exit 0 only when the measured cases and the neighbouring shapes all classify correctly.
"""
import importlib.util
import sys

PATH = "/root/bin/work-integrator.py"
spec = importlib.util.spec_from_file_location("work_integrator", PATH)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

rentals_93_94_skipped = m.is_attempt_ref("rental-system", "origin/integrate/rentals-93-94-20261022")
master_32_286_skipped = m.is_attempt_ref("rental-system", "origin/integrate/master-32-286")
print("rentals_93_94_skipped=%s" % rentals_93_94_skipped)
print("master_32_286_skipped=%s" % master_32_286_skipped)

CASES = [
    ("rental-system", "origin/integrate/rentals-93-94-20261022", False, "real PR93/94 landing branch (item 1110)"),
    ("rental-system", "origin/integrate/master-32-286", True, "attempt snapshot stays skipped"),
    ("rental-system", "origin/integrate/main-156", True, "single-number attempt stays skipped"),
    ("rental-system", "origin/integrate/rentals-next-15526-20261019", False, "dated branch is not an attempt"),
    ("prod-db-sync", "origin/integrate/test-27", True, "fleet test-<item> attempt stays skipped"),
    ("lpt-website", "origin/integrate/test-5", False, "lpt-website test-<n> is real promotion debt"),
    ("lpt-sync", "origin/integrate/main-29", False, "lpt-sync main-<n> is real integration debt"),
    ("rental-system", "origin/integrate/master", False, "bare integrate/<base> is real"),
]

failed = 0
for project, ref, expected, label in CASES:
    got = m.is_attempt_ref(project, ref)
    ok = got == expected
    failed += 0 if ok else 1
    print("%-5s %-18s %-52s skipped=%-5s expected=%-5s  %s" % (
        "OK" if ok else "FAIL", project, ref, got, expected, label))
print("regression_failures=%d" % failed)
sys.exit(1 if failed else 0)
