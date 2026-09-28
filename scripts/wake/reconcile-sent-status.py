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
from datetime import datetime, timezone
from pathlib import Path

INBOX = Path(os.environ.get("SMS_INBOX_DB") or (Path.home() / ".sms-inbox" / "inbox.db"))
UNSETTLED = ("queued", "sending", "accepted", "undefined", "")


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
    rows = conn.execute(
        "SELECT sid, date_sent, status, to_number, body FROM messages "
        "WHERE direction='outbound' AND (status IS NULL OR status IN (%s)) "
        "AND date_sent > datetime('now', ?) ORDER BY rowid DESC LIMIT ?"
        % ",".join("?" * len(UNSETTLED)),
        list(UNSETTLED) + ["-%d hours" % a.hours, a.limit]).fetchall()
    print("unsettled outbound rows in the last %dh: %d" % (a.hours, len(rows)))
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
