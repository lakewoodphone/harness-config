#!/usr/bin/env python3
"""replay-reads-both-ledgers.py - the replay that judged the guards saw a sixth of the channel.

`replay-owner-text.py` built its channel from `sms_log` alone: 282 of the owner's delivered texts.
The AI line's `messages` table holds 1,169 and 887 exist only there, including 40 of the 42 CFO
questions. So `WOULD-LOSE` and `WOULD-SAVE` were computed over a sample that omitted most of the
channel - and the whole point of that harness is that those two numbers decide whether a guard ships.

This adds the AI line's ledger as a second source, normalises its mixed date formats (ISO and
RFC-2822 both live in that table), and reports which sources answered. Deduplicated on the sid, so a
text present in both ledgers is one text.
"""
from __future__ import annotations

import io
import sys

PATH = sys.argv[1] if len(sys.argv) > 1 else "replay-owner-text.py"

LOADER = '''

#: The AI line's ledger. `textsend._record_send` writes it; the app writes `sms_log`. Both are the
#: owner's channel and only one of them was being read.
MESSAGES_DB = os.environ.get("SMS_INBOX_DB", "/root/.sms-inbox/inbox.db")


def load_ai_line(path: Path | None = None) -> list[dict]:
    """Delivered outbound owner texts from the AI line's ledger, shaped like sms_log rows.

    The table mixes ISO stamps from the sender with RFC-2822 stamps from Twilio, so both are parsed
    - a date comparison that silently becomes a string comparison is how a whole store gets dropped
    without anything looking wrong. Returns [] on any failure and says so on stderr.
    """
    db = path or Path(MESSAGES_DB)
    if not db.exists():
        print("  (AI line ledger absent at %s - replay covers sms_log only)" % db, file=sys.stderr)
        return []
    import sqlite3
    try:
        conn = sqlite3.connect("file:%s?mode=ro" % db, uri=True)
        try:
            raw = conn.execute(
                "select sid, direction, coalesce(from_number,''), coalesce(to_number,''), "
                "       body, coalesce(date_sent_utc, date_sent) as sentwhen, status "
                "from messages where direction='outbound' "
                "  and coalesce(status,'') in ('delivered','sent')").fetchall()
        finally:
            conn.close()
    except Exception as exc:                                   # noqa: BLE001
        print("  (AI line ledger unreadable: %s - replay covers sms_log only)" % exc,
              file=sys.stderr)
        return []
    out = []
    for sid, direction, frm, to, body, when, status in raw:
        iso = _to_iso(when)
        if iso is None:
            continue
        out.append({"id": None, "twilio_sid": sid, "direction": direction,
                    "from_number": frm, "to_number": to, "body": body,
                    "status": status, "created_at": iso, "agent_id": "ai-line"})
    return out


def _to_iso(value) -> str | None:
    """An ISO-8601 UTC stamp from either format this estate writes, or None."""
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(
            timezone.utc).isoformat()
    except ValueError:
        pass
    try:
        from email.utils import parsedate_to_datetime
        got = parsedate_to_datetime(text)
        if got.tzinfo is None:
            got = got.replace(tzinfo=timezone.utc)
        return got.astimezone(timezone.utc).isoformat()
    except Exception:                                          # noqa: BLE001
        return None

'''

OLD_MAIN = '''    rows = load_rows(corpus)
    out, inn = build_channel(rows)
    out_raw = len(out)'''

NEW_MAIN = '''    rows = load_rows(corpus)
    # BOTH LEDGERS. sms_log holds what the app sent; the AI line holds what textsend sent, and 887
    # owner texts exist only there - including 40 of the 42 CFO questions. Judging a guard on the
    # smaller store is judging it on the part of the channel that was least in dispute.
    ai = load_ai_line(Path(a.messages_db) if getattr(a, "messages_db", "") else None)
    if ai:
        have = {(r.get("twilio_sid") or "") for r in rows}
        added = [r for r in ai if (r.get("twilio_sid") or "") not in have]
        print("  AI line ledger: %d delivered owner texts, %d not already in the corpus"
              % (len(ai), len(added)))
        rows = list(rows) + added
    out, inn = build_channel(rows)
    out_raw = len(out)'''

ARGPARSE_OLD = '''    ap.add_argument("--corpus", default="data/sms.jsonl")'''
ARGPARSE_NEW = '''    ap.add_argument("--corpus", default="data/sms.jsonl")
    ap.add_argument("--messages-db", default="",
                    help="the AI line's ledger; empty means SMS_INBOX_DB then the default path")'''

ANCHOR = "\ndef load_rows(path: Path)"


def main() -> int:
    dry = "--apply" not in sys.argv
    text = io.open(PATH, encoding="utf-8").read()
    if "def load_ai_line(" in text:
        print("OK    already applied")
        return 0
    for label, anchor in (("load_rows", ANCHOR), ("main", OLD_MAIN), ("argparse", ARGPARSE_OLD)):
        if text.count(anchor) != 1:
            print("FAIL  %s anchor found %d times" % (label, text.count(anchor)))
            return 1
    out = (text.replace(ANCHOR, LOADER + ANCHOR, 1)
               .replace(OLD_MAIN, NEW_MAIN, 1)
               .replace(ARGPARSE_OLD, ARGPARSE_NEW, 1))
    # `timezone` must be imported for _to_iso
    if "from datetime import datetime, timedelta, timezone" not in out:
        out = out.replace("from datetime import datetime, timedelta",
                          "from datetime import datetime, timedelta, timezone", 1)
    import ast
    try:
        ast.parse(out)
    except SyntaxError as exc:
        print("FAIL  does not parse: %s" % exc)
        return 1
    if dry:
        print("DRY   would add the AI line's ledger to the replay")
        return 0
    io.open(PATH, "w", encoding="utf-8", newline="\n").write(out)
    print("APPLIED %s" % PATH)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
