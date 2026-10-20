#!/usr/bin/env python3
"""hours-drift -- turn the hours checker's verdict into ONE repair session when surfaces disagree.

WHY THIS EXISTS
    `bin/hours-drift-check.py` reads every surface that publishes LPT's walk-in hours and
    reports drift. It is read-only, and a finding -- a surface that disagrees, or that cannot
    be read -- is a condition it cannot clear itself, so it exits 3 (CONDITION, not fault).
    `bin/sources/cron-failures.py` deliberately files NO repair session for a streak of rc=3,
    because the condition is supposed to escalate through its own source. THIS is that source:
    without it the drift is silent, which is exactly what happened -- measured 2026-10-09, ten
    consecutive runs found the same Google Maps drift and the finding lived only in
    ~/.hours-drift/last.txt, which nothing read.

WHAT IT READS
    ~/.hours-drift/status.json, written by the checker on every run:
        {"checked_at": "<ISO-8601 UTC>", "ok": bool, "expected": {...},
         "surfaces": [{"surface", "status", "read_at", "source", "detail"}, ...],
         "disagreeing": [surface, ...]}

THRESHOLDS
    fires      ok is false AND the verdict is fresh (age <= 8 h).
    8 h        one missed 6-hourly run (cron `17 */6 * * *`) plus margin. A verdict older than
               that is an unreadable signal, not a healthy one.
    missing or stale status.json is Unreadable (exit 1), never healthy: "we could not tell" and
               "it is correct" are different facts.
    subject    hours-drift:<UTC day>, so an unfixed drift costs at most ONE session per day
               however often the checker runs.

MUST NEVER
    - run the checker itself (the cron does that) or write any surface it checks;
    - treat a missing or stale verdict as health;
    - phrase an UNREADABLE surface as the owner's drift: OUR reader failing is our fault;
    - send anything to anyone.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _flag  # noqa: E402
from _flag import Finding, Unreadable  # noqa: E402

SOURCE = "hours-drift"
STATE = Path(os.environ.get("HOURS_DRIFT_STATE") or (Path.home() / ".hours-drift"))
STATUS = STATE / "status.json"
MAX_AGE_HOURS = float(os.environ.get("HOURS_DRIFT_MAX_AGE_HOURS", "8"))
COOLDOWN_SECONDS = int(os.environ.get("HOURS_DRIFT_COOLDOWN", "43200"))  # 12 h


def collect(args):
    if not STATUS.is_file():
        raise Unreadable("no verdict at %s -- bin/hours-drift-check.py has not written one" % STATUS)
    try:
        doc = json.loads(STATUS.read_text(encoding="utf-8", errors="replace"))
    except Exception as exc:  # noqa: BLE001
        raise Unreadable("could not parse %s: %s" % (STATUS, exc))

    checked = _flag.parse_dt(doc.get("checked_at"))
    if checked is None:
        raise Unreadable("%s carries no readable checked_at" % STATUS)
    age_h = (datetime.now(timezone.utc) - checked).total_seconds() / 3600.0
    if age_h > MAX_AGE_HOURS:
        raise Unreadable(
            "verdict at %s is %.1f h old (ceiling %.1f h) -- the checker is not running, so "
            "nothing is known about the surfaces" % (STATUS, age_h, MAX_AGE_HOURS))

    if doc.get("ok"):
        return []

    surfaces = doc.get("surfaces") or []
    bad = [str(s) for s in (doc.get("disagreeing") or [])]
    if not bad:
        bad = [str(s.get("surface")) for s in surfaces if s.get("status") != "AGREES"]
    rows = "\n".join(
        "    %-24s %-10s %s" % (s.get("surface"), s.get("status"), s.get("detail"))
        for s in surfaces if s.get("status") != "AGREES")
    rows_block = ("\n" + rows) if rows else ""

    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    prompt = (
        "A SURFACE THAT PUBLISHES LPT'S WALK-IN HOURS DOES NOT AGREE WITH THE OWNER'S WEEK,\n"
        "OR COULD NOT BE READ AT ALL -- the status column below says which.\n\n"
        "    checked_at   %s  (%.1f h ago)\n"
        "    not agreeing %s%s\n\n"
        "    full report  ~/.hours-drift/last.txt\n"
        "    verdict      %s\n"
        "    expected     Sunday 12:00-16:00; Monday no walk-in (working day, drop-off only);\n"
        "                 Tuesday 10:30-17:30; Wednesday no walk-in (working day, drop-off only);\n"
        "                 Thursday 10:30-17:30; Friday closed; Saturday Shabbos.\n\n"
        "WHAT TO DO\n"
        "  1. Read the report. `python3 ~/bin/hours-drift-check.py` runs it by hand and names every\n"
        "     surface, with the exact days that differ.\n"
        "  2. Fix what we CAN write. Dialpad's office hours are writable by API and the checker has\n"
        "     the explicit operator action for them: `python3 ~/bin/hours-drift-check.py\n"
        "     --fix-dialpad`, then run the check again. Never wire that into cron -- the owner sets\n"
        "     his own hours, and a job that reverted his change every six hours would fight him.\n"
        "  3. What we CANNOT write is the Google Maps listing. It changes only through the owner's\n"
        "     own Google Business Profile; this estate has no write path for it. A surface that\n"
        "     DISAGREES is therefore HIS action -- but a surface that reads UNREADABLE is OUR\n"
        "     reader's fault and must be fixed HERE, never handed to him. Measured 2026-10-15:\n"
        "     the Google row read UNREADABLE (the shared SerpAPI free plan at 250/250 searches\n"
        "     for the month) while the listing itself was correct on all seven days, and this\n"
        "     prompt still asked for an owner action. Do NOT text or email him without his\n"
        "     explicit yes to the exact message -- file it through the normal one-question owner\n"
        "     channel instead, with a recommendation.\n"
        "  4. This is a CONDITION, not a fault. The checker exits 3 and `cron-failures` files\n"
        "     nothing for it, so THIS session is the escalation. Close the loop by proving the\n"
        "     surface moved: a fresh run with a new rc=0 row in ~/.cron-status/runs.tsv (rc=3\n"
        "     still means the condition is present). If it cannot be cleared tonight, leave it\n"
        "     honestly as it is -- never silence the check or drop it from cron.\n"
        % (doc.get("checked_at"), age_h, ", ".join(bad) or "(none named)", rows_block, STATUS)
    )
    return [Finding(
        subject="hours-drift:%s" % day,
        priority="normal",
        kind="repair",
        cooldown_seconds=COOLDOWN_SECONDS,
        context=json.dumps({"checked_at": doc.get("checked_at"), "disagreeing": bad,
                            "age_h": round(age_h, 2)}),
        prompt=prompt,
    )]


if __name__ == "__main__":
    raise SystemExit(_flag.run(SOURCE, collect))
