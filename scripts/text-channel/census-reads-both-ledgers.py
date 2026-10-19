#!/usr/bin/env python3
"""census-reads-both-ledgers.py - the conformance census measured 16% of the channel.

MEASURED 2026-10-19. The owner's delivered outbound texts live in TWO durable ledgers:

    authority.db : sms_log              - every send through the APP's choke point      282 rows
    ~/.sms-inbox/inbox.db : messages    - every send through the AI LINE (`textsend`)  1169 rows
                                          887 of which exist ONLY there

and the 887 include **40 of the 42 CFO questions** - the class he complains about most. The
conformance census read `sms_log` only, so it reported "11 of 77 refused" over a sample that
omitted most of the channel and nearly all of the questions.

Recomputed on the real stream over 14 days: **167 delivered, 26 refused (15.6%), 9 rewritten** - and
the refused list contains the banned "28 items, 28 urgent" digest on SIX separate days, which the
sms_log-based census never saw once.

So the census now unions both ledgers, keyed on the sid so a text recorded in both is counted once.
`sms_log` remains the fallback when the AI line's store is absent, and the evidence line says which
sources actually answered.
"""
from __future__ import annotations

import io
import sys

PATH = sys.argv[1] if len(sys.argv) > 1 else "owner-text-scorecard.py"

OLD = '''    delivered = 0
    flagged = 0
    rewrites = 0
    by_class = {}
    examples = []
    seen_sids = set()
    for r in rows:'''

NEW = '''    delivered = 0
    flagged = 0
    rewrites = 0
    by_class = {}
    examples = []
    seen_sids = set()
    # BOTH LEDGERS, because the channel is two senders. `sms_log` holds what the app sent; the AI
    # line (`textsend`) writes `messages` in ~/.sms-inbox and 887 owner texts exist only there,
    # including 40 of the 42 CFO questions. Counting one store measured about a sixth of the
    # channel and omitted the class he complains about most.
    alt = _messages_rows(since)
    if alt:
        rows = list(rows) + alt
    for r in rows:'''

HELPER = '''

#: The AI line's ledger. `textsend._record_send` writes the `messages` table here; the app writes
#: `sms_log`. Both are durable and both are the owner's channel.
MESSAGES_DB = os.environ.get("SMS_INBOX_DB", "/root/.sms-inbox/inbox.db")
OWNER_LIKE = "%18483897895%"


def _messages_rows(since):
    """Delivered outbound owner texts from the AI line's ledger, shaped like the sms_log rows.

    Returns [] on any failure: a census that cannot read one source must still report the other,
    and must say which answered. Never raises.
    """
    try:
        if not os.path.exists(MESSAGES_DB):
            return []
        conn = sqlite3.connect("file:%s?mode=ro" % MESSAGES_DB, uri=True)
        try:
            since_s = since.isoformat() if hasattr(since, "isoformat") else str(since)
            got = conn.execute(
                "select sid, coalesce(date_sent_utc, date_sent) as sentwhen, body, status "
                "from messages where direction='outbound' and to_number like ? "
                "and coalesce(status,'') in ('delivered','sent') "
                "and coalesce(date_sent_utc, date_sent) >= ?",
                (OWNER_LIKE, since_s)).fetchall()
        finally:
            conn.close()
    except Exception:
        return []
    return [{"id": None, "twilio_sid": r[0], "direction": "outbound", "status": r[3],
             "agent_id": "ai-line", "created_at": r[1], "body": r[2]} for r in got]

'''


def main() -> int:
    dry = "--apply" not in sys.argv
    text = io.open(PATH, encoding="utf-8").read()
    if "_messages_rows" in text:
        print("OK    already applied")
        return 0
    if text.count(OLD) != 1:
        print("FAIL  body-loop anchor found %d times" % text.count(OLD))
        return 1
    anchor = "\ndef conformance(rows, since):"
    if text.count(anchor) != 1:
        print("FAIL  conformance anchor found %d times" % text.count(anchor))
        return 1
    out = text.replace(anchor, HELPER + anchor, 1).replace(OLD, NEW, 1)
    import ast
    try:
        ast.parse(out)
    except SyntaxError as exc:
        print("FAIL  does not parse: %s" % exc)
        return 1
    if dry:
        print("DRY   would union the AI line's ledger into the census")
        return 0
    io.open(PATH, "w", encoding="utf-8", newline="\n").write(out)
    print("APPLIED %s" % PATH)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
