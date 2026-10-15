#!/usr/bin/env python3
"""Answer ONE question, read-only: can anything be claimed RIGHT NOW, and if not, when?

EXISTS BECAUSE A WAITING COUNT CANNOT DISTINGUISH TWO STATES. Measured 2026-09-30 on the authority:
seven rows in state `new`, every one gated by a `not_before` days into the future (two of them 28 days
out), while `autonomy-status.sh` printed "7 row(s) waiting and no cap in force - the next cron tick
should claim" and `wake-fanout.sh` started a shift every five minutes for 55 minutes, none of which could
claim, deleting its own staging evidence each time. A healthy gated queue and a stalled one printed the
same sentence, so nobody could tell them apart.

THE SAME DEFECT RETURNED ON 2026-10-13, ONE GATE FURTHER OUT. This file checked only `not_before`, so on a
day whose release-count cap had already been reached it answered `claimable_now: 75` while `wake.py claim`
answered `blocked_by: "daily-cap"`. `wake-fanout.sh` believed it and started a dispatcher EVERY MINUTE for
3h44m - 192 doomed instances moved into `wake-failed`, where they buried the handful of real failures in
the directory that exists to preserve them - and nothing was released until the cap reset at midnight.
A pre-flight that cannot see the gate the claim will honour is worse than no pre-flight, because it makes
"the loop is trying" look like "the loop cannot do anything".

It still does NOT re-implement the claim predicate - a second copy of a predicate is how two readings of
one thing start disagreeing. It reads `caps_in_force`, the list wake.py's OWN release path publishes, and
honours exactly the entries `release_block()` actually refuses on. `spend_unmeasured`, `night_quiet` and
`source_cap` are deliberately NOT treated as blocking here: the first does not stop release_block unless
volume is already high, and the last two are per-row gates that `_candidates` applies, not whole-queue
refusals. Read-only: it never claims, never writes, and exits 0 even when a store cannot be read, saying
so rather than reporting zero.

Usage:
    wake-nextclaim.py            one human line
    wake-nextclaim.py --json     {"ok":true,"waiting":7,"claimable_now":0,"gated":7,"earliest":...}
"""
import argparse
import datetime
import json
import os
import sqlite3
import subprocess
import sys

DEFAULT_DB = os.path.expanduser("~/.sms-inbox/inbox.db")
DEFAULT_WAKE_CLI = os.path.expanduser(os.environ.get("WAKE_CLI") or "~/bin/wake.py")

# The whole-queue guards release_block() actually refuses on, by the token caps_in_force
# uses. Anything else caps_in_force reports (spend_unmeasured, night_quiet, source_cap,
# session_recursion) does not stop a release and must not stop the fan-out here.
BLOCKING = {
    "paused": "paused",
    "daily_cap": "daily-cap",
    "cost_cap": "cost-cap",
}


def release_gate(wake_cli):
    """The whole-queue guard in force right now, or None. Never raises, never claims.

    Returns (blocked_by, detail) - e.g. ("daily-cap", "daily_cap: 150/150 releases today").
    An unreadable answer is None with the reason reported by the caller, because refusing to
    start on a store we simply could not read is the opposite failure: a lock would become a
    stall.
    """
    try:
        p = subprocess.run(["python3", wake_cli, "stats", "--json"],
                           capture_output=True, text=True, timeout=90)
        d = json.loads(p.stdout or "{}")
        if not d.get("ok", True):
            return None
        for entry in d.get("caps_in_force") or []:
            head = str(entry).split(":", 1)[0].strip()
            if head in BLOCKING:
                return BLOCKING[head], str(entry)
    except Exception:
        return None
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--db", default=os.environ.get("WAKE_DB") or DEFAULT_DB)
    ap.add_argument("--wake-cli", default=DEFAULT_WAKE_CLI,
                    help="the CLI whose caps_in_force is authoritative (default ~/bin/wake.py)")
    args = ap.parse_args()

    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")

    # The whole-queue gate FIRST, in the order `wake.py claim` checks it. A cap can be in
    # force with every row perfectly claimable, and that is the reading this file was blind to.
    gate = release_gate(args.wake_cli)

    try:
        con = sqlite3.connect("file:%s?mode=ro" % args.db, uri=True, timeout=10)
        con.execute("pragma busy_timeout=10000")
        rows = con.execute(
            "select id, subject, not_before from wake where state='new'"
        ).fetchall()
        con.close()
    except Exception as exc:
        out = {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)}
        print(json.dumps(out) if args.json
              else "nextclaim: the store could not be read (%s)" % exc)
        return 0

    claimable, gated = [], []
    for rid, subject, not_before in rows:
        if not_before and str(not_before) > now:
            gated.append((str(not_before), rid, subject or ""))
        else:
            claimable.append(rid)
    gated.sort()

    blocked_by, detail = gate if gate else (None, None)
    open_now = [] if blocked_by else claimable

    out = {
        "ok": True,
        "now": now,
        "waiting": len(rows),
        "claimable_now": len(open_now),
        "claimable_ids": open_now,
        # Kept even when a cap is in force, so "how much work is behind this cap" stays
        # readable instead of collapsing into a bare zero.
        "claimable_when_open": len(claimable),
        "gated": len(gated),
        "earliest": gated[0][0] if gated else None,
        "earliest_subject": gated[0][2] if gated else None,
        "gate": blocked_by or "not_before",
        "blocked_by": blocked_by,
        "blocking_detail": detail,
    }
    if args.json:
        print(json.dumps(out))
    elif blocked_by:
        print("nextclaim: NOTHING claimable now - %s in force (%s); %d row(s) would be "
              "claimable the moment it clears" % (blocked_by, detail, len(claimable)))
    elif out["claimable_now"]:
        print("nextclaim: %d claimable NOW (ids %s); %d gated until later"
              % (out["claimable_now"], ",".join(str(i) for i in claimable[:6]), out["gated"]))
    elif out["gated"]:
        print("nextclaim: NOTHING claimable now; %d row(s) gated by not_before, earliest %s (%s)"
              % (out["gated"], out["earliest"], (out["earliest_subject"] or "")[:60]))
    else:
        print("nextclaim: queue EMPTY (no rows in state new)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
