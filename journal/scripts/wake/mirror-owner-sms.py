#!/usr/bin/env python3
"""Mirror the owner's inbound texts from the app's sms_log into the store the responder reads.

THE FAULT THIS FIXES, measured 2026-09-28 20:07Z: the owner's texts ARRIVE (the Twilio webhook writes 982
rows into the app's `sms_log`, 228 of them from his iPhone, the newest TODAY) but the responder reads
`~/.sms-inbox/inbox.db`, whose newest inbound row is **2026-04-29**. So every responder tick prints
`0 to decide` - not because the responder is broken, but because its input is empty. It has been looking in
the wrong place for months.

WHY A MIRROR AND NOT A CHANGE TO THE RESPONDER. The responder runs LIVE every five minutes with
`--send`. Editing its worklist would put new code directly in the path that sends texts to a human being.
A mirror is a new, separate process: the responder keeps its own proven path and its own store, and this
only fills that store from the source where the texts actually live. If the mirror is wrong, the worst case
is that no new rows appear - the responder behaves exactly as it does today. Containment first; the
responder itself is not touched.

WHAT IT DOES, idempotently:
  * reads `sms_log` READ-ONLY from the app database (the same `mode=ro` discipline the rest of this
    codebase uses);
  * takes only `direction='inbound'` rows;
  * maps the schema: twilio_sid->sid, direction, from_number, to_number, body, created_at->date_sent,
    status, and state='new' for anything not already present;
  * DEDUPES on sid, so a row seen once is never inserted twice - re-running is safe;
  * never touches a row that already exists, and never updates one;
  * prints what it did and why, and refuses to guess if the schema does not match.

WHAT IT DELIBERATELY DOES NOT DO: send anything, decide anything, or write to the app database. It is a
one-way, read-only-from-the-app, insert-only-to-the-inbox copy.

Usage:  python3 mirror-owner-sms.py [--apply]  (default is a dry run)
        SQLite path overrides: SMS_MIRROR_APP_DB, SMS_INBOX_DB
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

HOME = Path.home()
APP_DB = Path(os.environ.get("SMS_MIRROR_APP_DB")
              or (HOME / "personal-secretary-mvp" / "data" / "secretary.db"))
INBOX_DB = Path(os.environ.get("SMS_INBOX_DB") or (HOME / ".sms-inbox" / "inbox.db"))

# THE SCHEMA MAPPING, written out so it can be checked rather than trusted.
MAPPING = [
    ("twilio_sid", "sid", "the dedupe key; may be null on some rows"),
    ("direction", "direction", "'inbound' only - this mirror is one-way"),
    ("from_number", "from_number", ""),
    ("to_number", "to_number", ""),
    ("body", "body", ""),
    ("created_at", "date_sent", "renamed: the inbox column is date_sent"),
    ("status", "status", ""),
]


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--limit", type=int, default=500, help="max rows to consider in one run")
    ap.add_argument("--days", type=int, default=7,
                    help="only mirror rows newer than this many days (0 = no limit). DEFAULT 7 ON PURPOSE: "
                         "the responder decides about NEW texts, not about archaeology - measured "
                         "2026-09-28, an unbounded first run would have mirrored 27 rows from as far back "
                         "as 2026-03-23, including 'Public ingress probe' test messages, and every one "
                         "would have become a ledger item.")
    a = ap.parse_args()

    if not APP_DB.exists():
        print("error: no app database at %s" % APP_DB)
        return 2
    if not INBOX_DB.exists():
        print("error: no inbox store at %s" % INBOX_DB)
        return 2

    # --- read the source READ-ONLY -------------------------------------------------------------
    src = sqlite3.connect("file:%s?mode=ro" % APP_DB, uri=True, timeout=20)
    src.row_factory = sqlite3.Row
    cols = {r[1] for r in src.execute("PRAGMA table_info(sms_log)")}
    needed = {src_name for src_name, _, _ in MAPPING}
    missing = needed - cols
    if missing:
        print("error: sms_log is missing expected column(s) %s - refusing to guess (found: %s)"
              % (sorted(missing), sorted(cols)))
        return 2
    rows = src.execute(
        "SELECT id, twilio_sid, direction, from_number, to_number, body, created_at, status "
        "FROM sms_log WHERE direction='inbound' ORDER BY id DESC LIMIT ?", (a.limit,)).fetchall()
    src.close()
    print("source: %s" % APP_DB)
    print("  inbound rows considered: %d (of %d total)" % (
        len(rows), sqlite3.connect("file:%s?mode=ro" % APP_DB, uri=True)
        .execute("select count(*) from sms_log").fetchone()[0]))

    # --- compare against the destination --------------------------------------------------------
    dst = sqlite3.connect(str(INBOX_DB), timeout=20)
    dst.row_factory = sqlite3.Row
    have = {r[0] for r in dst.execute("SELECT sid FROM messages")}
    print("destination: %s" % INBOX_DB)
    print("  rows already present: %d" % len(have))

    to_add, skipped_null, dupes, too_old = [], 0, 0, 0
    cutoff = None
    if a.days:
        cutoff = datetime.now(timezone.utc).timestamp() - a.days * 86400
    for r in rows:
        sid = (r["twilio_sid"] or "").strip()
        if not sid:
            # A row with no sid cannot be deduped safely, and guessing a key would risk double-handling a
            # real message. Count it and report it rather than inventing an identifier.
            skipped_null += 1
            continue
        if sid in have:
            dupes += 1
            continue
        if cutoff is not None:
            try:
                ts = datetime.fromisoformat(str(r["created_at"] or "").replace("Z", "+00:00")).timestamp()
            except Exception:
                ts = 0
            if ts < cutoff:
                too_old += 1
                continue
        to_add.append(r)

    print("\nplan:")
    print("  to insert      : %d" % len(to_add))
    print("  already present: %d" % dupes)
    if too_old:
        print("  too old        : %d row(s) older than %d day(s), left where they are (the responder "
              "decides about new texts, not history)" % (too_old, a.days))
    if skipped_null:
        print("  SKIPPED        : %d row(s) with no twilio_sid - cannot dedupe them safely" % skipped_null)
    for r in to_add[:8]:
        print("    + %s  %s -> %s  %s" % (
            (r["created_at"] or "")[:19], r["from_number"], r["to_number"],
            " ".join((r["body"] or "").split())[:56]))
    if len(to_add) > 8:
        print("    ... and %d more" % (len(to_add) - 8))

    if not a.apply:
        print("\n(dry run: nothing written. use --apply)")
        return 0

    # --- insert ---------------------------------------------------------------------------------
    # COUNT HONESTLY. `dst.total_changes` is cumulative for the CONNECTION, so using it inside the loop
    # would report a growing number rather than the rows inserted. These sids were each proven absent by
    # the dedupe above, and INSERT OR IGNORE still protects against a race, so count the attempts and
    # then read the store back as the authoritative number.
    before = dst.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    for r in to_add:
        dst.execute(
            "INSERT OR IGNORE INTO messages (sid, direction, from_number, to_number, body, date_sent, "
            "status, num_media, state, first_seen) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (r["twilio_sid"], "inbound", r["from_number"], r["to_number"], r["body"] or "",
             r["created_at"], r["status"], 0, "new", now()))
    dst.commit()
    after = dst.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    inserted = after - before
    got = dst.execute("SELECT COUNT(*) FROM messages WHERE direction='inbound' AND state='new'").fetchone()[0]
    dst.close()
    print("\ninserted %d row(s) (%d attempted, %d already present despite the dedupe); the inbox now holds "
          "%d inbound row(s) awaiting a decision" % (inserted, len(to_add), len(to_add) - inserted, got))
    print("THE RESPONDER WILL SEE THEM ON ITS NEXT TICK (cron runs it every 5 minutes).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
