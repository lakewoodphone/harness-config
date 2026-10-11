#!/usr/bin/env python3
"""lpt-audit-freshness.py - is the weekly hygiene pass still running?

WHY THIS EXISTS. A scheduled job that stops is silent, and the only thing that could notice is the
thing that stopped. Measured 2026-10-07: `lpt-audit-weekly.sh` was installed in the authority's
crontab at `0 6 * * 1`, had never fired, and **no component anywhere could have said so** - there was
no log, no state older than the one manual run, and nothing watching either.

That failure mode is already recorded twice in this system: a stopped feed read green because the
reader measured its own heartbeat (`production-comms-freshness.py`, the DEAD-FEED GUARD), and the
Dialpad call harvester logged `ok` while production held 828 newer rows. So this asks the opposite
question from the audit: **not "what is wrong with production", but "is the thing that looks for
what is wrong still alive".**

It therefore runs DAILY and the audit runs WEEKLY. A guard inside the weekly job cannot report that
the weekly job never ran.

WHAT IT DOES
  * reads the newest audit state (`~/.lpt-ops/audit/state.json`)
  * fresh  -> clears any staleness marker, prints the age, exits 0
  * stale  -> queues ONE row in the owner decision queue, remembers which stale reading it reported
              so it does not repeat itself every day, and exits 1

A missing state file is stale, not unknown: the job has never produced state, which is the condition
this exists to detect.

Exit codes: 0 fresh (or a stale reading already reported), 1 stale and reported or unreadable.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import subprocess
import sys

STATE = pathlib.Path.home() / ".lpt-ops" / "audit" / "state.json"
MARKER = pathlib.Path.home() / ".lpt-ops" / "audit" / "stale-reported.txt"
QUEUE = pathlib.Path.home() / "bin" / "owner-queue.py"
STAMP_FMT = "%Y%m%dT%H%M%SZ"

DEFAULT_MAX_AGE_DAYS = 9.0  # a weekly job, plus a day of slack for a missed Monday


def read_state(state: pathlib.Path) -> tuple[str | None, dt.datetime | None, bool]:
    """`(stamp, timestamp, readable)` from the audit state.

    `readable` is False when the file is absent, unreadable, or carries a stamp we cannot parse.
    That distinction is the whole point: an unreadable state must never fall back to something that
    *looks* like a recent run. MEASURED by this module's own test on writing it - the first version
    fell back to the file's mtime, so a state file that had just been written with unparseable
    contents reported **fresh (0.00 days old)**. A guard that reports green on rubbish is worse than
    no guard, so there is no fallback here at all.
    """
    try:
        d = json.loads(state.read_text())
    except Exception:
        return None, None, False
    raw = str(d.get("at") or "").strip()
    if not raw:
        return None, None, False
    try:
        return raw, dt.datetime.strptime(raw, STAMP_FMT).replace(tzinfo=dt.timezone.utc), True
    except ValueError:
        return raw, None, False


def queue_row(age: float | None, raw: str | None, now: dt.datetime, dry_run: bool) -> str:
    if age is None:
        question = ("The weekly production hygiene pass has produced no readable state at all - "
                    "is it running?")
        context = ("`lpt-audit-weekly.sh` is installed in the authority's crontab at `0 6 * * 1` and "
                   "writes `~/.lpt-ops/audit/state.json`. That file is missing or unreadable, so "
                   "either the job has never run or it cannot write. Until it runs, the 300+ ranked "
                   "work-order findings it produces reach nobody, and no reading can be trusted "
                   "about whether production is clean.")
    else:
        question = ("The weekly production hygiene pass has not run for %.1f days - re-arm it?" % age)
        context = ("`lpt-audit-weekly.sh` runs Mondays 06:00 on the authority and its newest state "
                   "reads `%s`. %.1f days have passed, so a Monday has been missed. The script itself "
                   "cannot report this - a stopped job cannot complain - which is why this daily check "
                   "exists. Last known reading was taken from %s."
                   % (raw or "unknown", age, raw or "the state file's mtime"))
    row = {
        "question": question,
        "context": context + " Nothing here writes to production; this is a liveness check only.",
        "options": ("Re-arm the weekly job now and run it once by hand (Recommended) | "
                    "Leave it and tell me when it matters | Turn the weekly pass off and audit on demand"),
        "recommendation": ("Re-arm and run it once by hand. The audit is read-only, so running it is "
                           "free, and the only cost of the check running is the cost of knowing."),
        "severity": "low",
        "blocks": "Nothing - the hygiene findings are a standing review, not a blocker",
        "source": "lpt-audit-freshness %s" % now.strftime(STAMP_FMT),
    }
    tmp = pathlib.Path("/tmp/lpt-audit-freshness.json")
    tmp.write_text(json.dumps(row))
    try:
        if dry_run or not QUEUE.exists():
            return ("would queue (dry-run)" if dry_run else "no owner-queue.py at %s" % QUEUE)
        r = subprocess.run(["python3", str(QUEUE), "add", "--from-json", str(tmp)],
                           capture_output=True, text=True)
        return (r.stdout or r.stderr or "").strip()[:200] or "queued"
    finally:
        if tmp.exists():
            tmp.unlink()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Is the weekly LPT hygiene audit still running?")
    p.add_argument("--state", default=str(STATE))
    p.add_argument("--marker", default=str(MARKER))
    p.add_argument("--max-age-days", type=float, default=DEFAULT_MAX_AGE_DAYS)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--json", action="store_true")
    a = p.parse_args(argv)

    state, marker = pathlib.Path(a.state), pathlib.Path(a.marker)
    now = dt.datetime.now(tz=dt.timezone.utc)
    raw, when, readable = read_state(state)
    age = ((now - when).total_seconds() / 86400.0) if (readable and when) else None
    fresh = readable and age is not None and age <= a.max_age_days

    result = {"at": now.strftime(STAMP_FMT), "state": str(state), "stamp": raw,
              "age_days": None if age is None else round(age, 2),
              "max_age_days": a.max_age_days, "fresh": fresh, "action": "none"}

    if fresh:
        # Recovery is a fact worth clearing the marker for, so the NEXT episode reports again.
        if marker.exists() and not a.dry_run:
            marker.unlink()
        result["action"] = "fresh"
        print(json.dumps(result, indent=1) if a.json else
              "lpt-audit-freshness: fresh (state %s, %.2f day(s) old)" % (raw, age))
        return 0

    # A reading we cannot read is its own key, so a corrupt state and an absent one are not
    # silently treated as the same episode.
    key = raw if readable else ("NO-STATE" if not state.exists() else "UNREADABLE")
    if marker.exists() and marker.read_text().strip() == key:
        result["action"] = "already-reported"
        print(json.dumps(result, indent=1) if a.json else
              "lpt-audit-freshness: STALE (%s) but already reported" % key)
        return 1

    detail = queue_row(age, raw, now, a.dry_run)
    result["action"] = "reported"
    result["queue"] = detail
    if not a.dry_run:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(key)
    print(json.dumps(result, indent=1) if a.json else
          "lpt-audit-freshness: STALE - %s" % detail)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
