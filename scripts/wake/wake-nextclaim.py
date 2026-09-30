#!/usr/bin/env python3
"""Answer ONE question, read-only: can anything be claimed RIGHT NOW, and if not, when?

EXISTS BECAUSE A WAITING COUNT CANNOT DISTINGUISH TWO STATES. Measured 2026-09-30 on the authority:
seven rows in state `new`, every one gated by a `not_before` days into the future (two of them 28 days
out), while `autonomy-status.sh` printed "7 row(s) waiting and no cap in force - the next cron tick
should claim" and `wake-fanout.sh` started a shift every five minutes for 55 minutes, none of which could
claim, deleting its own staging evidence each time. A healthy gated queue and a stalled one printed the
same sentence, so nobody could tell them apart.

It reports ONLY the `not_before` gate, which is the one that was invisible. It deliberately does not try
to re-implement the full claim predicate in wake.py - a second copy of a predicate is how two readings of
one thing start disagreeing. Read-only: it never claims, never writes, and exits 0 even when the store
cannot be read, saying so rather than reporting zero.

Usage:
    wake-nextclaim.py            one human line
    wake-nextclaim.py --json     {"ok":true,"waiting":7,"claimable_now":0,"gated":7,"earliest":...}
"""
import argparse
import datetime
import json
import os
import sqlite3
import sys

DEFAULT_DB = os.path.expanduser("~/.sms-inbox/inbox.db")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--db", default=os.environ.get("WAKE_DB") or DEFAULT_DB)
    args = ap.parse_args()

    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
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

    out = {
        "ok": True,
        "now": now,
        "waiting": len(rows),
        "claimable_now": len(claimable),
        "claimable_ids": claimable,
        "gated": len(gated),
        "earliest": gated[0][0] if gated else None,
        "earliest_subject": gated[0][2] if gated else None,
        "gate": "not_before",
    }
    if args.json:
        print(json.dumps(out))
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
