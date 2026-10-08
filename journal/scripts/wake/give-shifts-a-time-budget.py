#!/usr/bin/env python3
"""Tell a woken shift its TIME BUDGET, and make it write before the budget runs out.

THE MEASURED DEFECT, 2026-09-28 23:00Z. Ten wake rows have failed; four of them with the same recorded
outcome:

    "the desktop runner hit its own 2100s bound and killed the session (exit 124) after 2103s - that is a
     bound cutting live work, not a lost hop"

The arithmetic is in `wake-dispatch.sh`: `TURN_CAP=1800`, `TIMEOUT=TURN_CAP+360=2160`, and the runner's own
bound is TURN_CAP-anchored, so a session is killed at ~1800s. Durations today are min 4s / median 745s /
**p90 1788s / max 2103s** - i.e. a cluster right at the wall, and 5 of 79 releases at or over it. A session
killed at 1800s that was still working has usually not yet done STEP 4 (the write-back), so the WORK IS LOST:
the item stays `running`, the ledger gets nothing, and the release is charged in full. The dispatcher's own
comment says the same thing happened on 2026-09-20 with a 840s bound ("cut mid-sentence ... 218 KB and 378 KB
of live reasoning").

AND NOTHING TELLS A SESSION ITS BUDGET. The contract names no time limit at all, so a session plans to finish
and is instead stopped. That is the fix: a bounded worker must be TOLD it is bounded, and told what to do when
the bound approaches.

WHAT THIS ADDS TO THE CONTRACT - one short step, placed before the write-back step so it reads in order:
  * the budget, stated in minutes, with the instruction to STOP STARTING NEW WORK at about two thirds of it;
  * write the ledger record EARLY and keep it current, so a killed session leaves evidence;
  * if the budget runs out mid-item, CLOSE IT AS `--state todo` WITH `--left` rather than losing it - an item
    put back with a reason is recoverable, an item left `running` is not.

Usage: python3 give-shifts-a-time-budget.py [--apply]
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

TARGET = Path("/home/zabz/bin/sources/project-keepalive.py")
ANCHOR = '''        "STEP 4 - WRITE BACK BEFORE YOU FINISH. THIS IS THE STEP THAT MAKES THE SYSTEM WORK;",'''
BUDGET_STEP = '''        "STEP 3b - YOU ARE ON A CLOCK, AND NOBODY TOLD YOU UNTIL NOW. Your session is bounded",
        "  at about 30 minutes by the runner that started it, and when the bound lands the session",
        "  is killed where it stands - the work in progress is simply lost, the item stays",
        "  `running`, and the release is charged in full. Measured 2026-09-28: durations clustered",
        "  right at the wall (p90 1788s, max 2103s against a bound of ~1800s) and four wakes died",
        "  with 'the runner hit its own bound and killed the session - a bound cutting live work'.",
        "",
        "  SO PLAN FOR THE KILL:",
        "    * at about TWO THIRDS of the budget (roughly 20 minutes in), STOP STARTING NEW WORK and",
        "      start proving what you already have;",
        "    * do not wait until the item is finished to write anything down. If you have done",
        "      something provable, record it NOW with the `close` call below and `--state todo` plus",
        "      `--left`, then keep going and improve it - a second close overwrites the outcome, and",
        "      an early record that survives the kill is worth more than a perfect one that does not;",
        "    * if the budget runs out mid-item, CLOSE IT AS `--state todo` WITH `--left` naming exactly",
        "      where you stopped. An item put back with a reason is recoverable by the next shift;",
        "      an item left `running` is not - it looks like work in progress that is not happening.",
        "  A killed session that leaves a correct half-finished record has done its job. One that",
        "  leaves nothing has cost money and taught nobody anything.",
        "",'''

OLD_ANCHOR_TAIL = '''        "STEP 4 - WRITE BACK BEFORE YOU FINISH. THIS IS THE STEP THAT MAKES THE SYSTEM WORK;",'''


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    p = TARGET
    src = p.read_text(encoding="utf-8")
    if "STEP 3b - YOU ARE ON A CLOCK" in src:
        print("already present")
        return 0
    if ANCHOR not in src:
        print("ERROR: could not find the STEP 4 anchor")
        return 1
    src = src.replace(ANCHOR, BUDGET_STEP + ANCHOR, 1)
    try:
        compile(src, str(p), "exec")
    except SyntaxError as exc:
        print("ERROR: does not compile: %s" % exc)
        return 1
    if not a.apply:
        print("dry run ok (use --apply)")
        return 0
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    shutil.copy2(p, p.with_name(p.name + ".bak-budget-" + stamp))
    p.write_text(src, encoding="utf-8")
    print("patched %s" % p)

    print("\n=== PROOF: render the contract and confirm a session now reads it ===")
    code = '''
import datetime, importlib.util
spec = importlib.util.spec_from_file_location("pk", "%s")
pk = importlib.util.module_from_spec(spec); spec.loader.exec_module(pk)
_reg, projects = pk.load_registry()
proj = next((p for p in projects if p.get("id") == "housekeeping"), projects[0])
text = pk.standing_contract(proj, pk.load_state(proj), ["(item)"], datetime.datetime.now(datetime.timezone.utc))
print("  rendered: %%d chars" %% len(text))
for m in ("STEP 3b", "TWO THIRDS", "an early record that survives the kill", "CLOSE IT AS `--state todo`"):
    print("    %%-46s %%s" %% (m[:44], "PRESENT" if m in text else "MISSING"))
i = text.find("STEP 3b")
print()
for line in text[i:i+900].splitlines():
    print("    " + line[:104])
''' % p
    out = subprocess.run(["python3", "-c", code], capture_output=True, text=True, timeout=180)
    print(out.stdout or out.stderr[:400])
    return 0


if __name__ == "__main__":
    sys.exit(main())
