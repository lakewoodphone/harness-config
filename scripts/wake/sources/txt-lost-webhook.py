#!/usr/bin/env python3
"""FLAG SOURCE: an inbound text the app's webhook REFUSED.

THE SIGNAL
----------
`journalctl -u secretary-api --grep 'Unhandled error on /webhook/twilio/sms'`.
Each matching line is a request from Twilio that the app answered with HTTP 500,
and the accompanying ERROR line names the cause ("database is locked").

WHY THIS IS ABNORMAL, AND WHY THE THRESHOLD IS ONE OCCURRENCE
-------------------------------------------------------------
Twilio does NOT retry an inbound SMS webhook after a 5xx. So each of these lines
is a text dropped at the moment it arrived; the only reason it is visible at all
is that `sms-inbox.py sync` reconciles against Twilio's own API every 5 minutes.

Measured on secratary, 2026-09-18 03:25 UTC, whole journal for the unit
(2026-08-25T18:31 -> now, 1,113,233 lines):

    13 occurrences, on 5 days: 09-04 x1, 09-07 x3, 09-08 x1, 09-09 x2, 09-18 x6

and all 13 map to a real inbound text: for every one of the 13 timestamps there
is a row in ~/.sms-inbox/inbox.db whose Twilio `date_sent` is within 60 seconds
of it, and every one of those rows has app_has_it=0 -- the app never recorded it.
13 for 13, and no occurrence without a text behind it.

So the justification is NOT "the baseline is zero". It is that this signal has no
known false positives and one hundred percent of it is a lost message; there is no
acceptable rate at which a customer's text is silently dropped, and 5 of the 24
days covered here had at least one. The threshold is one occurrence.

PRIORITY  high. A person texted the shop and got silence.

SUBJECT  sms-webhook-lost:<UTC day>
    Bucketed by day on purpose. The subject is the dedup key, so a bad day costs
    AT MOST ONE session rather than one per occurrence -- and 2026-09-18 had six
    occurrences and one text in the same two minutes. The store's own daily cap
    (WAKE_MAX_PER_DAY, default 8) bounds every source together.

MUST NEVER
    - fire when the journal has no such line in the window
    - report a count it did not read: an unreadable journal is exit 1, not quiet
    - read the whole journal and filter in Python (18 MB / 128k lines per 24 h)
    - email, text or call anyone; this source only files a row

RUN
    python3 sources/txt-lost-webhook.py [--dry-run]
    LOST_TXT_HOURS=24        how far back to look (default 24)
    SECRETARY_API_UNIT       the systemd unit (default secretary-api)
    LOST_TXT_SCAN_LIMIT=4000 how many inbound rows to scan for the cross-check
"""
from __future__ import annotations

import os
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _flag                                                     # noqa: E402
from _flag import Finding, Unreadable                            # noqa: E402

SOURCE = "txt-lost-webhook"
PATTERN = "Unhandled error on /webhook/twilio/sms"
# Twilio posts the webhook as the message arrives, so the text's own date_sent is
# the link to the failing request. Measured 2026-09-18: +-60 s links all 13 known
# occurrences to their text, with no occurrence matching more than its own.
TEXT_MATCH = timedelta(seconds=60)


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name) or default)
    except ValueError:
        return default


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name) or default)
    except ValueError:
        return default


def collect(args) -> list[Finding]:
    now = _flag.now_utc()
    since = now - timedelta(hours=_float_env("LOST_TXT_HOURS", 24.0))
    unit = _flag.app_unit()

    events = []
    for line in _flag.journal_grep(unit, since, PATTERN):
        if PATTERN not in line:                        # --grep is a pattern match
            continue
        stamp = _flag.journal_stamp(line)
        if stamp is None or stamp < since or stamp > now:
            continue
        events.append(stamp)
    if not events:
        return []

    texts = _texts_near(events)
    by_day: dict[str, list] = {}
    for stamp in events:
        by_day.setdefault(stamp.strftime("%Y-%m-%d"), []).append(stamp)

    return [
        _finding(unit, day, sorted(by_day[day]),
                 [(s, t) for (s, t) in texts if s.strftime("%Y-%m-%d") == day])
        for day in sorted(by_day)
    ]

def _texts_near(events):
    """Inbound texts linked to a failure, ONE line per text.

    A text is linked when its Twilio `date_sent` is within TEXT_MATCH of a
    failing webhook, and it is reported against the CLOSEST such failure. The
    de-duplication by sid matters: 2026-09-18 03:02-03:03 had four failures AND
    four texts inside the same minute, so a naive pairwise match reported sixteen
    lines for four messages.
    """
    by_sid: dict[str, tuple] = {}
    limit = _int_env("LOST_TXT_SCAN_LIMIT", 4000)
    try:
        conn = _flag.ro_connect(_flag.inbox_db())
    except Unreadable as exc:
        print(f"{SOURCE}: cross-check unavailable ({exc})", file=sys.stderr)
        return []
    try:
        if not _flag.table_exists(conn, "messages"):
            return []
        rows = conn.execute(
            "SELECT sid, from_number, date_sent, first_seen, app_has_it, body"
            "  FROM messages WHERE direction='inbound'"
            " ORDER BY first_seen DESC LIMIT ?", (limit,)).fetchall()
    finally:
        conn.close()

    for row in rows:
        sent = _flag.parse_dt(row["date_sent"])
        if sent is None:
            continue
        best = None
        for event in events:
            gap = abs((sent - event).total_seconds())
            if gap <= TEXT_MATCH.total_seconds() and (best is None or gap < best[0]):
                best = (gap, event)
        if best is not None:
            by_sid[row["sid"]] = (best[1], row)
    return sorted(by_sid.values(), key=lambda pair: pair[0])


def _finding(unit, day, stamps, mine) -> Finding:
    when = ", ".join(s.strftime("%H:%M:%SZ") for s in stamps)
    lines = [
        f"The app's own journal shows {len(stamps)} inbound SMS webhook request(s) "
        f"from Twilio answered with HTTP 500 on {day} (UTC), all with the cause "
        f"'Unhandled error on /webhook/twilio/sms: database is locked'. "
        f"Times: {when}.",
        "",
        "Twilio does not retry an inbound SMS webhook after a 5xx, so each of these "
        "is a text that was dropped the moment it arrived. They are in our store "
        "only because ~/bin/sms-inbox.py reconciles against Twilio's API every 5 "
        "minutes and backfilled them; the app's own sms_log never got them.",
    ]
    if mine:
        lines += ["", f"Texts these failures account for ({len(mine)}), matched on "
                      f"Twilio's own date_sent within 60 s:"]
        for stamp, row in mine:
            body = (row["body"] or "").replace("\n", " ")[:120]
            lines.append(
                f"  - {stamp.strftime('%H:%M:%SZ')}  {row['from_number']}  "
                f"sent {row['date_sent']}  recorded {str(row['first_seen'])[:19]}Z  "
                f"app_has_it={row['app_has_it']}  sid={row['sid']}"
            )
            lines.append(f"      {body!r}")
    else:
        lines += ["",
                  "No inbound text in the store lines up with those timestamps, so "
                  "either the payload was not a text, or the message was lost before "
                  "Twilio's API could return it. Determine which before concluding "
                  "anything about impact."]
    lines += [
        "",
        "MEASURED HISTORY (2026-08-25 .. 2026-09-18, whole journal for the unit)",
        "  13 occurrences on 5 days: 09-04 x1, 09-07 x3, 09-08 x1, 09-09 x2,",
        "  09-18 x6. Every one of the 13 has an inbound row with date_sent within",
        "  60 s and app_has_it=0. This is not transient contention noise; each",
        "  occurrence is a customer text that would have been lost.",
        "",
        "WHAT TO DO",
        "1. Reproduce and read the traceback:",
        f"     journalctl -u {unit} --since '{day} 00:00:00' -o short-iso "
        f"--grep '{PATTERN}'",
        "   then find the exact write that loses the race for the SQLite write lock.",
        "2. Make the loss impossible rather than rarer. The webhook must not depend",
        "   on a contended write succeeding to keep the text. The smallest correct",
        "   fix is a bounded retry on SQLITE_BUSY plus a durable spool of the raw",
        "   payload that a worker drains. Change as little as possible; the app tree",
        "   has uncommitted edits and its own deploy story.",
        "3. Prove it: hold a write transaction on",
        "   ~/personal-secretary-mvp/data/secretary.db from another shell, post to",
        "   the webhook, and show the text is still kept. A fix you did not watch",
        "   work under contention is not a fix.",
        "4. Confirm the signal goes quiet afterwards:",
        f"     journalctl -u {unit} -o short-iso --grep '{PATTERN}'",
        "",
        "DO NOT: send anything to any of these people (outbound is a separate",
        "owner-gated decision); restart secretary-api without checking what it is",
        "currently doing; touch cron; or widen the journal window to make this look",
        "better.",
        "",
        "Report: the root cause in one sentence, the exact change, and the command",
        "output that proves the text survives contention.",
    ]
    return Finding(
        subject=f"sms-webhook-lost:{day}",
        prompt="\n".join(lines),
        context=(f"{SOURCE}: {len(stamps)} webhook 5xx on {day} in {unit}; "
                 f"{len(mine)} matching text(s)"),
        priority="high",
        kind="bug",
        cooldown_seconds=int(os.environ.get("LOST_TXT_COOLDOWN_SEC") or 86400),
    )


if __name__ == "__main__":
    sys.exit(_flag.run(SOURCE, collect))
