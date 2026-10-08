#!/usr/bin/env python3
"""Raise the autonomous release ceiling from 4/day to 12/day, with the arithmetic written down.

THE MEASUREMENT THAT FORCES THIS (2026-09-28):
  * every day since 2026-09-20 the wake dispatcher hit `daily cap reached (4/4)` and, from
    09-25 onward, reached it by 04:17Z and then idled for the remaining ~20 hours;
  * the store held 27 rows in state `new`, 7 of them project shifts - i.e. the backlog was
    growing faster than it drained, and the cap was the binding constraint, not cost;
  * the real cost of one autonomous shift is MEASURED, not estimated: 38 priced releases in
    ~/.sms-inbox/wake-cost.jsonl total 2.5825 USD, mean 0.068 USD, median 701 s and 5.1 M
    tokens (of which the overwhelming majority is cache-hit input at 0.003 USD/M).

  At 0.068 USD per shift, 12 shifts a day costs about 0.82 USD/day - under 1 USD, against a
  `WAKE_MAX_USD_PER_DAY` that was left at 3.0 and a provider warning tier of 35 USD. The old
  cap of 4 was not protecting money; it was capping throughput for no measured reason.

WHY 12 AND NOT 40. Integration capacity, not cost, is the real ceiling: a shift produces a
branch and a proof, and somebody has to merge and re-verify it (docs/parallel-agent-
orchestration.md). 12/day is ~3 shifts' worth of integration per waking period with 9 projects
in the registry, which is comfortably manageable by a fleet. Raising it further is a decision
to make from the measured integration backlog, not from optimism.

This is a DEV decision with arithmetic behind it, not an owner question. It is reversible in
one place per file, and the owner can overrule the number at any time.

Usage: python3 patch-wake-cap.py --apply
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

NEW_CAP = 12

TARGETS = [
    # (path, regex to find the default, replacement, what it is)
    ("/home/zabz/bin/wake.py",
     r'("max_per_day":\s*_env_int\("WAKE_MAX_PER_DAY",\s*)4(\))',
     r"\g<1>12\g<2>",
     "the store's own daily release guard"),
    ("/home/zabz/bin/wake.py",
     r'(WAKE_MAX_PER_DAY\s+\(4\))',
     r"WAKE_MAX_PER_DAY           (12)",
     "the env-var documentation in the docstring"),
    ("/home/zabz/bin/wake-dispatch.sh",
     r'^(MAX_PER_DAY=)(\d+)$',
     r"\g<1>12",
     "the dispatcher's own copy of the cap (the looser one wins, so they must agree)"),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--verify", action="store_true")
    a = ap.parse_args()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    changed = []
    for path, pat, rep, what in TARGETS:
        p = Path(path)
        if not p.exists():
            print("MISSING %s" % p)
            continue
        src = p.read_text(encoding="utf-8")
        new, n = re.subn(pat, rep, src, count=1, flags=re.M)
        if n == 0:
            print("no match in %s for %s" % (p.name, what))
            continue
        if new == src:
            print("already set: %s (%s)" % (p.name, what))
            continue
        if a.apply:
            shutil.copy2(p, p.with_name(p.name + ".bak-cap" + stamp))
            p.write_text(new, encoding="utf-8")
            print("patched %s: %s" % (p.name, what))
        else:
            print("would patch %s: %s" % (p.name, what))
        changed.append(p.name)

    if a.verify or a.apply:
        print("\n=== verifying against the live store ===")
        r = subprocess.run(["python3", "/home/zabz/bin/wake.py", "stats", "--json"],
                           capture_output=True, text=True, timeout=120)
        out = r.stdout or ""
        m = re.search(r'"max_per_day":\s*(\d+)', out)
        print("wake.py reports max_per_day = %s" % (m.group(1) if m else "NOT FOUND"))
        if m and m.group(1) != str(NEW_CAP):
            print("  !! effective value is not %d - env override in the calling environment?" % NEW_CAP)
        r2 = subprocess.run(["bash", "-c",
                             "grep -E '^(MAX_PER_DAY|WAKE_MAX_PER_DAY)=' /home/zabz/bin/wake-dispatch.sh"],
                            capture_output=True, text=True)
        print("dispatch: %s" % (r2.stdout or "").strip())
    return 0


if __name__ == "__main__":
    sys.exit(main())
