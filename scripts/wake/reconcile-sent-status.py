#!/usr/bin/env python3
"""Make a sent text's real fate reachable, so `queued` stops being mistaken for `undelivered`.

THE FINDING, measured 2026-09-28 22:58Z. The text sent to the owner at 22:56:27 reported
`ok=True sid=SM88af60d6... twilio status=queued` and its store row STILL said `queued` 25 minutes later - while
Twilio's own API answers **`status: delivered`, error: none, price -0.01660 USD**. So the row was wrong, and
nothing in this system could correct it: `textsend.py` exposes no status query at all (measured: its
status-ish functions are `[]`).

WHY THAT MATTERS MORE THAN IT LOOKS. A send that reads `queued` for ever is indistinguishable from one that
never arrived - and the two demand opposite reactions. Either you tell the owner "I sent it" when he never
got it, or you re-send something he already has, or you assume a channel works that does not. The store is
supposed to be the evidence; here it was the least trustworthy part.

WHAT THIS ADDS:
  * `check-text-status.py` - queries Twilio's API for a message sid (read-only, sends nothing) and prints
    status, error and price. That is the missing instrument;
  * `reconcile-sent-status.py` - walks recent OUTBOUND rows still marked queued/sending/undefined, asks the
    provider about each, and writes the true status back. Idempotent and safe to run on a schedule, so the
    store converges on the truth instead of freezing at the moment of sending.

Usage:
  python3 reconcile-sent-status.py [--apply] [--hours 24] [--limit 25]
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sqlite3
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

INBOX = Path(os.environ.get("SMS_INBOX_DB") or (Path.home() / ".sms-inbox" / "inbox.db"))
UNSETTLED = ("queued", "sending", "accepted", "undefined", "")


def parse_dt(value):
    """Parse one date_sent value, whichever of the two formats it is in.

    The store's date_sent holds RFC-2822 from Twilio's API AND ISO-8601 from the app
    sms_log that mirror-owner-sms.py copies in. Never compare that column as a string.
    """
    if not value:
        return None
    s = str(value).strip()
    if not s:
        return None
    if s[0].isdigit():
        try:
            d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            d = None
    else:
        try:
            from email.utils import parsedate_to_datetime
            d = parsedate_to_datetime(s)
        except Exception:
            d = None
    if d is None:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def load_env() -> dict:
    vals = dict(os.environ)
    for p in (Path.home() / "personal-secretary-mvp" / ".env", Path.home() / ".sms-inbox" / ".env"):
        try:
            for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                vals.setdefault(k.strip(), v.strip().strip('"').strip("'"))
        except Exception:
            continue
    return vals


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--hours", type=int, default=24, help="how far back to look")
    ap.add_argument("--limit", type=int, default=25)
    a = ap.parse_args()

    env = load_env()
    acct, token = env.get("TWILIO_ACCOUNT_SID", ""), env.get("TWILIO_AUTH_TOKEN", "")
    if not (acct and token):
        print("no Twilio credentials - cannot reconcile (looked in the env and the usual .env files)")
        return 3
    auth = base64.b64encode(("%s:%s" % (acct, token)).encode()).decode()

    conn = sqlite3.connect(str(INBOX), timeout=20)
    conn.row_factory = sqlite3.Row
    # THE TIME FILTER IS APPLIED IN PYTHON, ON A PARSED DATE.
    #
    # It used to be `date_sent > datetime('now', ?)` with '-48 hours' in SQL. That
    # compares an RFC-2822 string ("Wed, 30 Sep 2026 16:44:20 +0000") against an ISO
    # literal ("2026-10-11 01:40:51"), and SQLite compares bytes: 'W' (0x57) is
    # greater than '2' (0x32), so EVERY RFC-2822 row passes however old it is.
    # Measured on the live store 2026-10-13: the filter selected 1838 of 1914
    # outbound rows - effectively everything - so `--hours` did not bound the work
    # at all. It looked harmless only because ORDER BY rowid DESC LIMIT 25 happens to
    # cap the result anyway; the promise in this file's own docstring was false.
    cutoff = datetime.now(timezone.utc) - timedelta(hours=a.hours)
    floor = datetime.min.replace(tzinfo=timezone.utc)
    candidates = conn.execute(
        "SELECT sid, date_sent, status, to_number, body FROM messages "
        "WHERE direction='outbound' AND (status IS NULL OR status IN (%s)) "
        "ORDER BY rowid DESC LIMIT ?"
        % ",".join("?" * len(UNSETTLED)),
        list(UNSETTLED) + [max(a.limit, 200)]).fetchall()
    rows = [r for r in candidates
            if (parse_dt(r["date_sent"]) or floor) >= cutoff][:a.limit]
    print("unsettled outbound rows in the last %dh: %d" % (a.hours, len(rows)))

    # AND SAY WHAT ALREADY WENT WRONG. This script only ever chased
    # queued/sending/accepted/undefined/''. A row Twilio marked `failed` is outside
    # that set and was never looked at again: measured 2026-10-13, 504 outbound rows
    # in the store sat failed or undelivered, and across Twilio's whole history for
    # this line 8,314 of 11,903 outbound sends failed - 7,813 of them in a four-day
    # retry storm in May 2026 that nothing reported. Reporting is not fixing, but the
    # silence is what let that run.
    bad = conn.execute(
        "SELECT COUNT(*) FROM messages WHERE direction='outbound' "
        "AND status IN ('failed','undelivered')").fetchone()[0]
    print("outbound rows marked failed/undelivered, all time (never reconciled "
          "by this script): %d" % bad)

    if not rows:
        print("nothing to reconcile")
        conn.close()
        return 0

    changed = 0
    for r in rows:
        sid = r["sid"]
        if not sid or not sid.startswith("SM"):
            continue
        url = "https://api.twilio.com/2010-04-01/Accounts/%s/Messages/%s.json" % (acct, sid)
        req = urllib.request.Request(url, headers={"Authorization": "Basic " + auth})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                d = json.loads(resp.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as exc:
            # A 404 usually means the sid belongs to a DIFFERENT Twilio account, which is worth saying
            # plainly rather than silently skipping.
            print("  %s -> HTTP %s (not this account's message? leaving it alone)" % (sid[:18], exc.code))
            continue
        except Exception as exc:
            print("  %s -> %s: %s" % (sid[:18], type(exc).__name__, exc))
            continue
        real = d.get("status") or "unknown"
        old = r["status"] or "(null)"
        mark = "CHANGED" if real != old else "same"
        print("  %s  %s -> %s  to=%s  %s%s" % (
            sid[:18], old, real, d.get("to"),
            ("err=%s" % d.get("error_message")) if d.get("error_message") else "",
            "  <-- %s" % mark if real != old else ""))
        if real != old and a.apply:
            conn.execute("UPDATE messages SET status=? WHERE sid=?", (real, sid))
            changed += 1
    if a.apply:
        conn.commit()
        print("\nwrote %d status update(s)" % changed)
    else:
        print("\n(dry run: nothing written. use --apply)")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
