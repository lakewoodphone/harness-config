#!/usr/bin/env python3
"""backfill-owner-history.py — carry the owner's parked texts into the channel store.

WHY
---
`~/.sms-inbox/inbox.db` is the store the AI text line REPORTS from. Its newest owner
message is 2026-03-25, while the app's `sms_log` holds 252 of his inbound texts, the
newest from today. `~/bin/mirror-owner-sms.py` carries only rows newer than 7 days
(`--days 7`, by design), so a row that aged past that window before a mirror run is
parked in the app forever. Measured 2026-10-02: **225 rows parked**, 0 of them lacking a
`twilio_sid`, so all 225 can be inserted without risking a duplicate (the sid is the
mirror's only dedupe key).

THE MARKING, DECIDED BEFORE THE INSERT — this is the whole safety argument
-----------------------------------------------------------------------
A backfilled row must NOT be answered. These are conversations from February to
September; replying to them today would text the owner about months-old questions. The
store already has the precedent: 255 existing inbound rows carry
`state='seen'`, `decided_by='backfill'`, exactly the shape the old reconciler wrote for
historical rows it recovered. The responder only picks up rows in state `new`, so
`seen` + `decided_by='backfill'` is provably inert and consistent with the record.

Read-only on the app. Insert-only on the store. Idempotent via the sid.

USAGE
    backfill-owner-history.py              # dry run: says exactly what it would insert
    backfill-owner-history.py --apply       # insert
    backfill-owner-history.py --apply --days 30   # narrower window
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

STORE = Path(os.environ.get("TEXT_INBOX_DB", Path.home() / ".sms-inbox" / "inbox.db"))
APP = Path(os.environ.get("SECRETARY_DB",
                          Path.home() / "personal-secretary-mvp" / "data" / "secretary.db"))
OWNER_NUMBERS = ("+18483897895", "18483897895")
OWNER_IN = "IN (%s)" % ",".join("?" * len(OWNER_NUMBERS))
MARK_STATE = "seen"
MARK_BY = "backfill"
MARK_REASON = ("historical row recovered from the app by backfill-owner-history.py "
               "2026-10-02: parked past the mirror's 7-day window and deliberately not "
               "answered, because replying to a months-old text is not a service")


def ro(path: Path) -> sqlite3.Connection:
    c = sqlite3.connect("file:%s?mode=ro" % path, uri=True, timeout=20)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA busy_timeout=8000")
    return c


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--days", type=int, default=7,
                    help="insert rows OLDER than this many days (the mirror's cut-off is 7)")
    ap.add_argument("--limit", type=int, default=1000)
    args = ap.parse_args(argv)

    if not STORE.exists():
        raise SystemExit("store not found: %s" % STORE)
    if not APP.exists():
        raise SystemExit("app db not found: %s" % APP)

    app = ro(APP)
    rows = app.execute(
        "SELECT id, twilio_sid, direction, from_number, to_number, body, created_at, status "
        "FROM sms_log WHERE direction='inbound' AND from_number " + OWNER_IN +
        " AND created_at <= datetime('now', ?) ORDER BY id ASC LIMIT ?",
        OWNER_NUMBERS + ("-%d day" % args.days, args.limit),
    ).fetchall()
    app.close()

    store = sqlite3.connect(str(STORE), timeout=30)
    store.row_factory = sqlite3.Row
    store.execute("PRAGMA busy_timeout=15000")
    have = {r[0] for r in store.execute("SELECT sid FROM messages WHERE COALESCE(sid,'') <> ''")}

    to_add, skipped_no_sid = [], 0
    for r in rows:
        sid = (r["twilio_sid"] or "").strip()
        if not sid:
            skipped_no_sid += 1
            continue
        if sid in have:
            continue
        to_add.append(r)

    print("source app      : %s" % APP)
    print("newer than      : %d day(s) old (mirror's cut-off is 7)" % args.days)
    print("owner rows found: %d" % len(rows))
    print("already in store: %d" % (len(rows) - len(to_add) - skipped_no_sid))
    print("no sid (skipped): %d" % skipped_no_sid)
    print("TO INSERT       : %d" % len(to_add))
    if to_add:
        print("\noldest: %s   newest: %s" % (to_add[0]["created_at"][:19], to_add[-1]["created_at"][:19]))
        print("marking: state=%r decided_by=%r  (the responder only sees state='new')"
              % (MARK_STATE, MARK_BY))
        print("\nfirst 3 rows that would be inserted:")
        for r in to_add[:3]:
            print("   %s  %s  %r" % (r["created_at"][:19], r["twilio_sid"], (r["body"] or "")[:60]))

    if not args.apply:
        print("\nDRY RUN — nothing written")
        return 0

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    before_new = store.execute(
        "SELECT COUNT(*) FROM messages WHERE direction='inbound' AND state='new'").fetchone()[0]
    before_all = store.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    inserted = 0
    for r in to_add:
        cur = store.execute(
            """INSERT OR IGNORE INTO messages
                   (sid, direction, from_number, to_number, body, date_sent, status,
                    num_media, first_seen, app_has_it, state, decided_by, decided_at, reason)
               VALUES (?, 'inbound', ?, ?, ?, ?, ?, 0, ?, 1, ?, ?, ?, ?)""",
            (r["twilio_sid"], r["from_number"], r["to_number"], r["body"] or "",
             r["created_at"], r["status"] or "received", now,
             MARK_STATE, MARK_BY, now, MARK_REASON),
        )
        inserted += cur.rowcount
    store.commit()
    after_new = store.execute(
        "SELECT COUNT(*) FROM messages WHERE direction='inbound' AND state='new'").fetchone()[0]
    after_all = store.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    newest = store.execute(
        "SELECT MAX(date_sent) m FROM messages WHERE direction='inbound'").fetchone()[0]
    store.close()

    print("\n== APPLIED ==")
    print("inserted            : %d" % inserted)
    print("store rows          : %d -> %d" % (before_all, after_all))
    print("inbound state='new' : %d -> %d  (must NOT rise: these rows are inert)"
          % (before_new, after_new))
    print("newest inbound now  : %s" % newest)
    if after_new > before_new:
        print("\nSTOP: the pending count rose, which means rows landed as 'new' and the "
              "responder will answer months-old texts. Investigate before running again.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
