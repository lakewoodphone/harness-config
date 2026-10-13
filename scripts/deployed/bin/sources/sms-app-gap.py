#!/usr/bin/env python3
"""FLAG SOURCE: the app's inbound SMS log has stopped while texts keep arriving.

THE SIGNAL
----------
Two clocks, compared:

  1. `sms_log` in the app's own database
     (~/personal-secretary-mvp/data/secretary.db): the newest row with
     direction='inbound'. This is the app's record of the texts it received.
  2. `messages` in ~/.sms-inbox/inbox.db: every inbound text Twilio holds for
     the AI line, carrying `app_has_it` = 1 when the app's own sms_log has that
     MessageSid and 0 when it does NOT.

The source fires when BOTH halves are true:

  * the app's newest inbound row is older than SMS_STALE_MIN minutes
    (default 15), and
  * the inbox holds an inbound row with app_has_it=0 whose Twilio `date_sent`
    is NEWER than that app row.

WHY THIS IS ABNORMAL
--------------------
Item 483, 2026-10-05: the app's Twilio webhook stopped being called at
02:39:53Z and nothing raised a flag for ~37 hours. 82 inbound texts piled up in
inbox.db with app_has_it=0. The owner-facing path (poller -> responder -> ledger)
stayed healthy, so the only rotted record was the app's sms_log -- and that is
exactly the table the app's owner-conversation, turn and suppression logic reads.
Silence in sms_log is not quiet; it is the app going blind while every other
surface still looks fine.

The near neighbours cover different signals and cannot catch this:

  * txt-lost-webhook    -- a webhook request that returned HTTP 500 (the journal)
  * txt-stranded-inbound -- an inbound text left in state='new' (undecided)
  * comms-freshness     -- the customer-comms pipeline's own verdict file

None of them compares sms_log's newest inbound row against Twilio's record of
what actually arrived.

HOW IT CLEARS BY ITSELF
-----------------------
It is a comparison re-read on every pass, not a latch. When the app records the
missing texts again -- the webhook recovers, or the texts are backfilled through
the app's own writer -- `~/bin/sms-inbox.py sync` re-reads the app's sids and
flips those rows to app_has_it=1 (sms-inbox.py `upsert`: "UPDATE messages SET
app_has_it=1 WHERE sid=?"), and the app's newest inbound row becomes current.
Both halves of the condition then go false and this source returns `quiet`, with
no manual retraction.

MUST NEVER
    - fire while the app is current (sms_log newest within SMS_STALE_MIN)
    - fire on an app_has_it that is NULL (unknown) or 1
    - fire on a quiet line: if the inbox has no row newer than sms_log, the app
      simply having nothing new is the healthy case
    - write anything: both databases are opened read-only (uri mode=ro)
    - report a gap it did not measure: an unreadable database exits 1, never quiet

PRIORITY  high. The app cannot see inbound texts and nothing else can tell.

SUBJECT  sms-app-gap:<UTC day>
    Day-bucketed, so a stall that persists costs at most ONE session per day
    rather than one per 15-minute pass. The store's daily cap bounds every source
    together.

RUN
    python3 sources/sms-app-gap.py [--dry-run]
    SMS_INBOX_APP_DB   the app database (default ~/personal-secretary-mvp/data/secretary.db)
    SMS_INBOX_DB       the inbox store  (default ~/.sms-inbox/inbox.db)
    SMS_STALE_MIN      minutes of silence in sms_log before the age half is met
                       (default 15)
    SMS_APP_GAP_COOLDOWN_SEC  how long a filed subject stays deduped (default 86400)
"""
from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _flag                                                     # noqa: E402
from _flag import Finding, Unreadable                            # noqa: E402

SOURCE = "sms-app-gap"
SCAN_LIMIT = 500


def _stale_minutes() -> float:
    try:
        return float(os.environ.get("SMS_STALE_MIN") or 15)
    except ValueError:
        return 15.0


def _app_newest_inbound() -> datetime:
    """Newest inbound `created_at` in the app's own sms_log, as UTC."""
    path = _flag.app_db()
    conn = _flag.ro_connect(path)
    try:
        if not _flag.table_exists(conn, "sms_log"):
            raise Unreadable(f"no sms_log table in {path}")
        row = conn.execute(
            "SELECT MAX(created_at) AS newest FROM sms_log"
            " WHERE direction='inbound'").fetchone()
    finally:
        conn.close()
    newest = _flag.parse_dt(row["newest"] if row else None)
    if newest is None:
        raise Unreadable(f"no inbound sms_log row with a readable created_at in {path}")
    return newest


def _newer_unrecorded(app_newest: datetime):
    """Inbound inbox rows with app_has_it=0 whose date_sent beats app_newest.

    Ordering and the comparison are both done on parsed datetimes: `date_sent`
    is stored ISO-ish but with mixed offsets, and sms-inbox.py's own header warns
    that sorting it as text puts 2026 rows before 2025 rows. `first_seen` is
    written in one fixed shape, so it is safe as the SQL-side bound.
    """
    path = _flag.inbox_db()
    conn = _flag.ro_connect(path)
    try:
        if not _flag.table_exists(conn, "messages"):
            raise Unreadable(f"no messages table in {path}")
        rows = conn.execute(
            "SELECT sid, from_number, date_sent, first_seen, app_has_it, body"
            "  FROM messages"
            " WHERE direction='inbound' AND app_has_it = 0"
            " ORDER BY first_seen DESC LIMIT ?", (SCAN_LIMIT,)).fetchall()
    finally:
        conn.close()
    newer = []
    for row in rows:
        sent = _flag.parse_dt(row["date_sent"])
        if sent is not None and sent > app_newest:
            newer.append((sent, row))
    newer.sort(key=lambda pair: pair[0])
    return newer


def collect(args) -> list[Finding]:
    now = _flag.now_utc()
    app_newest = _app_newest_inbound()
    age_min = (now - app_newest).total_seconds() / 60.0
    newer = _newer_unrecorded(app_newest)
    if age_min <= _stale_minutes() or not newer:
        return []
    return [_finding(app_newest, age_min, newer, now)]


def _finding(app_newest, age_min, newer, now) -> Finding:
    day = now.strftime("%Y-%m-%d")
    lines = [
        f"The app's inbound SMS log has been silent for {age_min:.0f} minutes: the "
        f"newest sms_log row with direction='inbound' is stamped "
        f"{app_newest.strftime('%Y-%m-%dT%H:%M:%SZ')}, and {len(newer)} inbound "
        f"text(s) in ~/.sms-inbox/inbox.db are NEWER than it with app_has_it=0.",
        "",
        "app_has_it=0 means the app's own sms_log has no row for that MessageSid. "
        "Twilio holds the text; the app never recorded it. The Twilio webhook is "
        "what writes sms_log, so this is the signature of a webhook that stopped "
        "being called (or is failing) while the poller -> responder -> ledger path "
        "kept the line looking healthy.",
        "",
        f"Newest unrecorded texts ({min(len(newer), 10)} of {len(newer)}):",
    ]
    for sent, row in newer[-10:]:
        body = (row["body"] or "").replace("\n", " ")[:120]
        lines.append(
            f"  - {sent.strftime('%Y-%m-%dT%H:%M:%SZ')}  {row['from_number']}  "
            f"app_has_it={row['app_has_it']}  sid={row['sid']}")
        lines.append(f"      {body!r}")
    lines += [
        "",
        "MEASURED: item 483, 2026-10-05 -- the webhook stopped at 02:39:53Z and "
        "nothing flagged it for ~37 h while 82 texts accumulated app_has_it=0.",
        "",
        "WHAT TO DO",
        "1. Measure the same two clocks by hand:",
        "     sqlite3 -line ~/personal-secretary-mvp/data/secretary.db \\",
        "       \"select max(created_at) from sms_log where direction='inbound';\"",
        "     sqlite3 -line ~/.sms-inbox/inbox.db \\",
        "       \"select max(date_sent) from messages where direction='inbound' and app_has_it=0;\"",
        "2. Find out why the webhook stopped. Check the unit, its journal and the",
        "   public route in front of it:",
        "     systemctl status secretary-api",
        "     journalctl -u secretary-api --since '-24h' --grep 'twilio/sms'",
        "3. The texts are already held in inbox.db, so nothing is lost; get the app",
        "   to record them again through the app's own writer. Do not hand-insert",
        "   rows into sms_log behind the app's back.",
        "4. Re-run this source: it must print `quiet`, and the sids must read",
        "   app_has_it=1 after the next `python3 ~/bin/sms-inbox.py sync`.",
        "",
        "DO NOT: send anything to these people (outbound is a separate owner-gated",
        "decision); restart secretary-api without checking what it is doing; or",
        "widen SMS_STALE_MIN to make this source quiet.",
        "",
        "Report: why the webhook stopped, the exact fix, and the sync output showing",
        "app_has_it=1 and this source quiet.",
    ]
    return Finding(
        subject=f"{SOURCE}:{day}",
        prompt="\n".join(lines),
        context=(f"{SOURCE}: sms_log newest inbound {age_min:.0f} min old; "
                 f"{len(newer)} newer inbound text(s) with app_has_it=0"),
        priority="high",
        kind="bug",
        cooldown_seconds=int(os.environ.get("SMS_APP_GAP_COOLDOWN_SEC") or 86400),
    )


if __name__ == "__main__":
    sys.exit(_flag.run(SOURCE, collect))
