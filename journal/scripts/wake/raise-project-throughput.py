#!/usr/bin/env python3
"""Let a project advance more than once a day, on measurement.

THE THROTTLE, measured 2026-09-28 19:42Z:

    every one of the 9 projects: max_flags_per_day = 1, cooldown_seconds = 43200 (12 h)
    30 todo items across 5 projects; the slowest project (lpt-website, 11 items) would take
    ABOUT 11 DAYS to drain at one item per day.

Meanwhile the owner said exactly what he wants, twice:
  * "There's no reason to limit how much you could do per day."
  * "I want to be really powerful and autonomous and able to actually finish projects really fast
     and move on and evolve and do the next thing."
and the measured cost says the ceiling is nowhere near binding: 0.0361 USD per release today, so the
70 USD/day ceiling is about **1,940 releases** of headroom. Nine projects at 3/day is 27 releases and
about 0.97 USD.

WHY 3 AND NOT 20: the binding guard is the STORE's `max_per_source_per_hour = 3`. The sources that
file project shifts are `project-keepalive` and `ledger-keepalive`; at 3 filings per source per hour,
the sustainable rate is roughly 3-6 shifts/hour = 24-48/day, and raising a per-project number past
that would only produce flags the store refuses. So the per-project cap goes to 3 and the cooldown to
6 h, which together mean "a project may be advanced again after a few hours if the previous shift
finished" - and the store's own hourly and daily guards remain the real backstop.

WHAT STAYS: the dedup on subject (so a day still cannot file the same project twice under one subject
key), the cooldown, the store's per-source hourly cap, the 500/day backstop, the 70 USD ceiling and the
pause file. This raises a planning number, it does not remove a guard.

Usage: python3 raise-project-throughput.py [--apply] [--per-day N] [--cooldown S]
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

REG = Path("/home/zabz/bin/sources/projects.json")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--per-day", type=int, default=3)
    ap.add_argument("--cooldown", type=int, default=21600, help="seconds (default 6 h)")
    a = ap.parse_args()
    doc = json.loads(REG.read_text(encoding="utf-8"))
    changed = []
    for row in doc.get("projects", []):
        if not row.get("enabled"):
            continue
        old_pd, old_cd = row.get("max_flags_per_day"), row.get("cooldown_seconds")
        if old_pd == a.per_day and old_cd == a.cooldown:
            continue
        row["max_flags_per_day"] = a.per_day
        row["cooldown_seconds"] = a.cooldown
        row["budget_note"] = (
            "RAISED 2026-09-28 on measurement. Was 1/day with a 12 h cooldown, which would take about "
            "11 days to drain the slowest project's backlog. Owner: 'There's no reason to limit how "
            "much you could do per day' and 'finish projects really fast and move on'. The measured "
            "cost is 0.0361 USD per release (today: 0.469 USD for 13), so the 70 USD/day ceiling is "
            "about 1,940 releases of headroom. The BINDING guard is the store's own "
            "max_per_source_per_hour=3, which is why this is %d/day and not 20 - planning past it "
            "would only file flags the store refuses." % a.per_day)
        changed.append((row["id"], old_pd, a.per_day, old_cd, a.cooldown))
    if not changed:
        print("already at %d/day, %ds cooldown" % (a.per_day, a.cooldown))
        return 0
    for pid, opd, npd, ocd, ncd in changed:
        print("  %-20s per_day %s -> %s | cooldown %ss -> %ss" % (pid, opd, npd, ocd, ncd))
    if not a.apply:
        print("\ndry run: %d project(s) would change (use --apply)" % len(changed))
        return 0
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    shutil.copy2(REG, REG.with_name("projects.json.bak-throughput-" + stamp))
    caps = doc.setdefault("caps", {})
    caps["per_project_raised"] = (
        "2026-09-28: per-project max_flags_per_day %d, cooldown %ds. The binding guard is the store's "
        "max_per_source_per_hour=3; the daily backstop is 500 and the spend ceiling 70 USD/day."
        % (a.per_day, a.cooldown))
    REG.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    print("\nwrote %s (%d project(s))" % (REG, len(changed)))

    # PROVE it: the source's own dry run must now plan more than one flag per project.
    import subprocess
    r = subprocess.run([sys.executable, "/home/zabz/bin/sources/project-keepalive.py", "--dry-run"],
                       cwd="/home/zabz/bin/sources", capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=300)
    out = (r.stdout or "") + (r.stderr or "")
    for line in out.splitlines():
        if "flag(s)" in line or "suppressed" in line:
            print("  " + line.strip()[:120])
    return 0


if __name__ == "__main__":
    sys.exit(main())
