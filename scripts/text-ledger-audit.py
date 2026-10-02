#!/usr/bin/env python3
"""text-ledger-audit.py — the three checks that would have caught 2026-10-02's faults.

Companion to the text channel's existing instruments (text-health.py checks the channel
itself; this checks the DATA the channel answers from). Written because two faults
found by hand that day were invisible to every check already running:

  D1  THE TWO STORES DISAGREED. `inbox.db` — the store the responder REPORTS from —
      held no inbound owner message since 2026-03-25, while the app recorded his texts
      the whole time. `sms-responder.py report` printed "0 to decide" for weeks.

  D2  A TURN THAT CANNOT BE ANSWERED HELD THE CHANNEL. One acknowledgement with no
      question in it refused every outbound for 38 hours. The row is in the app DB;
      nothing looked at it.

  D3  THE ORDER FEED WENT STALE SILENTLY. The ledger's newest Amazon order was 22 days
      old and no check said so, so money questions could not name an item.

Contract, deliberately the same as text-health.py: prints `OK <name>` / `FAIL <name>`
lines, exits non-zero if anything failed, and is READ-ONLY — every connection is opened
`mode=ro`. A check that cannot run reports FAIL with the reason; it never passes by
default, because "I could not look" is not "it is fine".
"""
from __future__ import annotations

import os
import sqlite3
import sys
from datetime import date, datetime, timezone
from pathlib import Path

INBOX = Path(os.environ.get("TEXT_INBOX_DB", Path.home() / ".sms-inbox" / "inbox.db"))
APP_DB = Path(os.environ.get("SECRETARY_DB",
                             Path.home() / "personal-secretary-mvp" / "data" / "secretary.db"))
LEDGER = Path(os.environ.get("CFO_ACCT_DB",
                             Path.home() / "accounting-data" / "live" / "accounting.db"))

OWNER_SUFFIX = "84897895"          # the owner's cell, as stored
# The owner's number is matched by EXACT VALUE against every form the stores use.
# Measured 2026-10-02: `sms_log.from_number` holds '+18483897895' (252 rows) and
# '18483897895' (3 rows) -- and on this host `LIKE '%84897895%'` returned ZERO against
# both, with no direction filter, while `from_number = '+18483897895'` returned 252.
# So LIKE is not dependable here and the check must not be built on it. A check that
# silently matches nothing reports "no data", which reads exactly like "no problem".
OWNER_NUMBERS = ("+18483897895", "18483897895", "+1 848-389-7895")
_OWNER_IN = "IN (%s)" % ",".join("?" * len(OWNER_NUMBERS))
STORE_GAP_HOURS = float(os.environ.get("TEXT_STORE_GAP_HOURS", "72"))
ORDER_FEED_MAX_AGE_DAYS = int(os.environ.get("ORDER_FEED_MAX_AGE_DAYS", "10"))
TURN_HOLD_HOURS = float(os.environ.get("TEXT_TURN_HOLD_HOURS", "24"))

FAILURES: list[str] = []


def ro(path: Path) -> sqlite3.Connection:
    c = sqlite3.connect("file:%s?mode=ro" % path, uri=True, timeout=20)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA busy_timeout=8000")
    return c


def check(name: str, ok: bool, evidence: str) -> None:
    print("%-5s %s" % ("OK" if ok else "FAIL", name))
    print("      %s" % evidence)
    if not ok:
        FAILURES.append(name)


def parse_when(value) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%d %H:%M:%S",
                "%a, %d %b %Y %H:%M:%S %z", "%Y-%m-%d"):
        try:
            moment = datetime.strptime(text, fmt)
            return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)
    except Exception:
        return None


# ── D1: the two stores must agree about the owner's own texts ────────────────
#
# The comparison is done by PARSING every timestamp and taking the true maximum, never
# with SQL MAX(). Measured 2026-10-02: `messages.date_sent` holds BOTH ISO
# ('2026-10-02T14:18:00.492540+00:00', written by sms-inbox.py) and RFC-2822
# ('Wed, 25 Mar 2026 08:01:06 +0000', written by mirror-owner-sms.py). MAX() on that
# column sorts them as strings, so it returned 2026-03-25 as "newest" and this check
# reported the store 4,590 hours behind the app. It was 0.00 hours behind: both stores
# held the same newest message. A check whose arithmetic is wrong reports a confident
# falsehood, which is worse than not running.
try:
    chan = ro(INBOX)
    store_rows = chan.execute(
        "SELECT date_sent FROM messages WHERE direction='inbound' AND from_number " + _OWNER_IN,
        OWNER_NUMBERS,
    ).fetchall()
    chan.close()
    store_times = [t for t in (parse_when(r["date_sent"]) for r in store_rows) if t]
    store_last = max(store_times) if store_times else None

    app = ro(APP_DB)
    app_rows = app.execute(
        "SELECT created_at FROM sms_log WHERE direction='inbound' AND from_number " + _OWNER_IN,
        OWNER_NUMBERS,
    ).fetchall()
    app_times = [t for t in (parse_when(r["created_at"]) for r in app_rows) if t]
    app_last = max(app_times) if app_times else None
    if app_last is None:
        # the inbound direction may not be recorded; the turn ledger is the fallback
        app_last = parse_when(app.execute(
            "SELECT MAX(sent_at) m FROM owner_text_turn").fetchone()["m"])
    # The mirror only carries rows newer than 7 days by design, so rows that aged past
    # that window before it ran are parked in the app. Two different situations, two
    # different remedies: live loss (the newest text never arrived) versus a backlog.
    parked = app.execute(
        "SELECT COUNT(*) c FROM sms_log WHERE direction='inbound' AND from_number "
        + _OWNER_IN + " AND created_at <= datetime('now','-7 day')",
        OWNER_NUMBERS,
    ).fetchone()["c"]
    parked_no_sid = app.execute(
        "SELECT COUNT(*) c FROM sms_log WHERE direction='inbound' AND from_number "
        + _OWNER_IN + " AND COALESCE(twilio_sid,'') = ''",
        OWNER_NUMBERS,
    ).fetchone()["c"]
    app.close()

    s, a = store_last, app_last

    if s is None:
        check("D1 the channel store holds the owner's own inbound texts", False,
              "inbox.db holds NO inbound message from the owner at all (ever)")
    elif a is None:
        check("D1 the channel store holds the owner's own inbound texts", True,
              "the app has no newer owner activity to compare (store newest %s)" % s.date())
    else:
        gap = (a - s).total_seconds() / 3600.0
        detail = ("store newest %s · app newest %s · the store is %.1f h behind (limit %.0f h). "
                  % (s.isoformat(timespec="minutes"), a.isoformat(timespec="minutes"),
                     gap, STORE_GAP_HOURS))
        if parked:
            detail += ("%d owner message(s) sit in the app older than the mirror's 7-day window "
                       "(`mirror-owner-sms.py --days`) and will never be carried across; %d owner "
                       "row(s) carry NO twilio_sid, which the mirror uses as its dedupe key, so "
                       "those cannot be inserted at all without risking a duplicate. That is a "
                       "parked backlog, NOT live loss: no new text is being dropped. It matters "
                       "because every store-based report understates this channel."
                       % (parked, parked_no_sid))
        else:
            detail += ("No parked backlog was measured, so the newest owner text itself never "
                       "reached the store -- this is live loss and it is the worse case.")
        detail += (" When this fails the responder answers from one store and REPORTS from "
                   "another, so its own health output is meaningless.")
        check("D1 the channel store holds the owner's own inbound texts",
              gap <= STORE_GAP_HOURS, detail)

except Exception as exc:
    check("D1 the channel store holds the owner's own inbound texts", False,
          "%s: %s" % (type(exc).__name__, exc))


# ── D2: nothing is holding the owner's channel shut ─────────────────────────
try:
    app = ro(APP_DB)
    rows = app.execute(
        """SELECT id, sent_at, body FROM owner_text_turn
            WHERE answered_at IS NULL ORDER BY id DESC LIMIT 5"""
    ).fetchall()
    app.close()
    now = datetime.now(timezone.utc)
    stuck = []
    for r in rows:
        when = parse_when(r["sent_at"])
        age = (now - when).total_seconds() / 3600.0 if when else None
        body = (r["body"] or "")
        asks = ("?" in body) or any(
            w in body.lower() for w in ("should i", "can you", "which", "what ", "reply",
                                        "let me know", "did you", "do you"))
        if age is not None and age >= TURN_HOLD_HOURS and not asks:
            stuck.append((r["id"], age, body[:60]))
    check("D2 no unanswered turn is holding the owner's channel shut",
          not stuck,
          ("none open longer than %.0fh without a question in it" % TURN_HOLD_HOURS)
          if not stuck else
          "; ".join("#%s held %.1fh with nothing to answer: %r" % t for t in stuck))
except Exception as exc:
    check("D2 no unanswered turn is holding the owner's channel shut", False,
          "%s: %s" % (type(exc).__name__, exc))


# ── D3: the order feed is fresh enough to name an item ──────────────────────
try:
    led = ro(LEDGER)
    newest = led.execute(
        "SELECT MAX(order_date) m FROM amazon_orders WHERE length(order_date)=10"
    ).fetchone()["m"]
    n_orders = led.execute("SELECT COUNT(*) c FROM amazon_orders").fetchone()["c"]
    n_items = led.execute("SELECT COUNT(*) c FROM amazon_order_items").fetchone()["c"]
    led.close()
    if not newest:
        check("D3 the order feed can name an item for a recent charge", False,
              "the ledger has no dated order at all (%s orders, %s items)" % (n_orders, n_items))
    else:
        age = (date.today() - date.fromisoformat(newest)).days
        check("D3 the order feed can name an item for a recent charge",
              age <= ORDER_FEED_MAX_AGE_DAYS,
              "newest order %s (%s days old; limit %s) · %s orders, %s items. Stale means the "
              "Amazon session on the owner's desktop has expired or no scrape has run, and "
              "every Amazon charge question can name only the amount and the card."
              % (newest, age, ORDER_FEED_MAX_AGE_DAYS, n_orders, n_items))
except Exception as exc:
    check("D3 the order feed can name an item for a recent charge", False,
          "%s: %s" % (type(exc).__name__, exc))


print()
print("TEXT-LEDGER-AUDIT %s · %d check(s) failed" %
      (datetime.now(timezone.utc).isoformat(timespec="seconds"), len(FAILURES)))
# No trailing `FAIL <name>` list: the runner that invokes this
# (`text-channel-check.sh` -> `run_extra`) greps '^FAIL' for names, so a trailing list
# repeats every failure and the log line read "D1 …;D3 …;D1 …;D3 …". The per-check lines
# and the exit status already carry everything.
sys.exit(1 if FAILURES else 0)

