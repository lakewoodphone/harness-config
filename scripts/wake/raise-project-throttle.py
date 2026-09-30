#!/usr/bin/env python3
"""Raise the per-project throttle, so a real backlog drains in a day instead of a week.

WHY. The owner's instruction on 2026-09-28, already quoted in this file: "There's no reason to limit how
much you could do per day... obviously we can't have overall more than $70 of spending, let's say, on the
deepseek API daily. But it's not like how many times... The point of stopping you isn't to make you do less
work is to make sure you're not doing stupid work or doing the same work over and over. Or wasting money."

The numbers in force were 3 flags per project per day with a 21600-second cooldown. Measured 2026-09-30:
housekeeping had already used its three by 14:50Z, so ten housekeeping ledger items filed at 15:24Z could
not be woken again until 20:50Z, and the rest of the backlog would take days. That is the wrong limiter:
the measured cost of a shift is 0.036 to 0.068 USD against a 70 USD daily ceiling, so about a thousand
shifts of headroom exist and the throttle was binding at three.

AFTER: 12 flags per project per day and a 1800-second cooldown. The global daily backstop (500) and the
spend ceiling (70 USD) are untouched and remain the real limits. Nothing else changes.

Backs up before writing, updates the recorded reasoning in the same file, and prints the before/after.
"""
import json
import shutil
import sys
import time

PATH = sys.argv[1] if len(sys.argv) > 1 else "/home/zabz/bin/sources/projects.json"
NEW_FLAGS, NEW_COOLDOWN = 12, 1800

doc = json.load(open(PATH))
stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
shutil.copy2(PATH, "%s.bak-throttle-%s" % (PATH, stamp))

changed = []
for p in doc.get("projects", []):
    if not p.get("enabled"):
        continue
    before = (p.get("max_flags_per_day"), p.get("cooldown_seconds"))
    p["max_flags_per_day"] = NEW_FLAGS
    p["cooldown_seconds"] = NEW_COOLDOWN
    p["budget_note"] = (
        "RAISED 2026-09-30 by the dev seat, on the owner's standing instruction that volume is not the "
        "constraint and that the point of stopping is not to do less work but to avoid stupid, repeated or "
        "wasteful work. Was 3/day with a 21600s cooldown, which meant a project that had used its three by "
        "midday could not be woken again until the evening: measured 2026-09-30, ten housekeeping ledger "
        "items filed at 15:24Z were unreachable until 20:50Z and the backlog would have taken days. Now "
        "12/day with a 1800s cooldown. The limits that remain are the ones that mean something: the store's "
        "per-source hourly cap, the 500/day global backstop, and the 70 USD/day spend ceiling against a "
        "measured 0.036-0.068 USD per shift.")
    changed.append((p.get("id"), before, (NEW_FLAGS, NEW_COOLDOWN)))

caps = doc.get("caps") or {}
caps["per_project_raised"] = (
    "2026-09-30: per-project 12 flags/day with a 1800s cooldown (was 3/day and 21600s). The real limits are "
    "the store's max_per_source_per_hour, the 500/day backstop and the 70 USD/day ceiling.")
doc["caps"] = caps

with open(PATH, "w", encoding="utf-8") as fh:
    json.dump(doc, fh, indent=2)
    fh.write("\n")
print("backup %s.bak-throttle-%s" % (PATH, stamp))
for pid, b, a in changed:
    print("  %-20s %s -> %s" % (pid, b, a))
print("projects changed: %d" % len(changed))
