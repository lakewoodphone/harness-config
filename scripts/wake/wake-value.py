#!/usr/bin/env python3
"""One line that answers: is the company producing value, and what is it costing.

WHY. The system reported releases, dollars and backlog counts, but never the two together, and never the
only number that matters: dollars per item actually closed with a proof. `wake.py stats` itself warns that a
release is a session started and not work done - measured 2026-09-29: 133 releases over 41 distinct ids.
Without this line no change in the backlog can be judged: a rise in releases with a flat closed-count would
read as progress when it is churn.

ALSO RECONCILES THE BUDGET. The harness spend guard and the wake daily ceiling were two different numbers
for one wallet. This prints the wake ceiling read from wake.py itself - one source - beside the spend it
measures, so a reader cannot be shown a cap that no process enforces.

Read-only. Exit 0 always. An unreadable store is reported as unreadable, never as zero.
"""
import os
import sqlite3
import sys
import datetime

LEDGER = os.environ.get("WORK_DB") or os.path.expanduser("~/work/work.db")
WAKE_DB = os.environ.get("WAKE_DB") or os.path.expanduser("~/.sms-inbox/inbox.db")


def ceiling():
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import wake
        return float(os.environ.get("WAKE_MAX_USD_PER_DAY") or wake.DEFAULT_MAX_USD_PER_DAY)
    except Exception:
        return None


def main():
    today = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")

    # --- ledger: what the machine actually finished, and what it owes
    try:
        con = sqlite3.connect("file:%s?mode=ro" % LEDGER, uri=True, timeout=10)
        con.execute("pragma busy_timeout=10000")
        states = dict(con.execute("select state, count(*) from work_item group by state").fetchall())
        closed = con.execute("select count(*) from work_item where state='done' and done_at >= ?",
                             (today,)).fetchone()[0]
        oldest = con.execute("select min(created_at) from work_item where state='blocked'").fetchone()[0]
        con.close()
        blocked_age = "?"
        if oldest:
            try:
                d = datetime.datetime.fromisoformat(oldest.replace("Z", "+00:00"))
                if d.tzinfo is None:
                    d = d.replace(tzinfo=datetime.timezone.utc)
                days = (datetime.datetime.now(datetime.timezone.utc) - d).total_seconds() / 86400.0
                blocked_age = "%.0fd" % days
            except Exception:
                blocked_age = "?"
    except Exception as exc:
        print("  VALUE         : the ledger could not be read (%s: %s)" % (type(exc).__name__, exc))
        return 0

    # --- money. READ IT FROM THE ONE PLACE THAT OWNS IT. The first version of this tool summed the
    # `cost_usd` column and printed 0.00 while `wake.py stats` said 0.64499 on the same day: the dispatcher
    # logs "cost: not reported by this harness surface", so that column is mostly empty and the real figure
    # comes from the priced records wake-cost.py writes. A reading that contradicts the system's own number
    # is worse than no reading - so ask the owner of the number, and take the ceiling from the same answer.
    spend = cap = None
    try:
        import json as _json
        import subprocess as _sp
        wake_cli = os.environ.get("WAKE_CLI", "/home/zabz/bin/wake.py")
        raw = _sp.run(["python3", wake_cli, "stats", "--json"], capture_output=True, text=True,
                      timeout=60).stdout
        d = _json.loads(raw)
        if d.get("ok", True):
            spend = float(d.get("spend_today_usd") or 0.0)
            cap = float((d.get("caps") or {}).get("max_usd_per_day") or 0.0) or None
    except Exception:
        spend = cap = None
    if cap is None:
        cap = ceiling()

    money = "unmeasured"
    if spend is not None:
        money = "%.2f spent" % spend
        if cap is not None:
            money += " of the %.2f daily ceiling" % cap
    per_item = ""
    if spend is not None and closed:
        per_item = " | %.3f USD per closed item" % (spend / closed)

    print("  VALUE         : %d item(s) closed today%s | todo %s running %s blocked %s (oldest blocked %s)"
          % (closed, per_item,
             states.get("todo", 0), states.get("running", 0), states.get("blocked", 0), blocked_age))
    print("  BUDGET        : %s | harness guard is separate - see the digest" % money)
    return 0


if __name__ == "__main__":
    sys.exit(main())
