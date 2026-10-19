#!/usr/bin/env python3
"""ask-person -- the ONE door for a directed 1:1 question to a named person.

WHY THIS FILE EXISTS (incident 2026-10-18, `sms_log` 4284)
    A CFO question about an Audible charge was sent to the owner's wife by a one-off
    script that called `app.family_chat.twilio_client.send_message(...)`. That module's
    mouth is the FAMILY CHAT hub number (+17328009174) -- the number every family
    message arrives from -- so on her phone the question landed inside the family
    thread. She could not answer it, because a reply there looks like it goes to the
    whole family. Meanwhile the CFO asks the OWNER from the AI line (+17324447361).
    One question, two different numbers, and the one that could not be answered was
    the one that got used.

    The deeper fault was not the script: it was that NO door existed for "ask one
    person, privately, from the AI line", so a session reached for the family chat
    transport because it was the only one that would open. This is that door.

WHAT THIS ENFORCES, IN ORDER
    1. The recipient is NOT the family chat hub. A directed question from the hub is
       the incident, so it is refused by name, with the incident cited.
    2. The recipient is NOT the owner. His questions have their own sender and their
       own one-at-a-time ledger (`owner-ask.py`); using this door for him would skip it.
    3. The recipient IS on `AITEXT_PRIVATE_ASK_ALLOW` -- a name-by-name list in `.env`.
       Outbound only: the person's inbound `allow` is untouched, so the assistant does
       not start chatting with them on its own.
    4. The body is a single message with no internal machine reference in it.
    5. `textsend.send()` still has the last word. This door asks it; it does not bypass
       it, and it prints the gate's verdict whether it is open or closed.

USAGE
    ask-person.py --to +18482245096 --body-file /tmp/b.txt            # dry run
    ask-person.py --to +18482245096 --body-file /tmp/b.txt --send     # transmit

    Exit 0 = sent (or a clean dry run). 1 = refused, and the refusal is printed with
    its reason. 2 = bad arguments. Nothing here raises on a refusal.
"""
from __future__ import annotations

import argparse
import datetime
import re
import sqlite3
import sys
from pathlib import Path

BIN = Path(__file__).resolve().parent
if str(BIN) not in sys.path:
    sys.path.insert(0, str(BIN))

import textsend  # noqa: E402  (path is set up above, deliberately)


def _tail(number: str) -> str:
    return textsend._digits(number)[-10:]


def _out(label: str, value) -> None:
    print("%-8s %s" % (label, value))


AUTHORITY_DB_TIMEOUT = 10


def _record_send(cfg, *, sid, to, body, status, reason, error=None):
    """Make a send from this door visible in `sms_log`, so the comms index can find it.

    WHY A DIRECT WRITE. `app.database.log_sms_best_effort()` is the sanctioned writer,
    but it lives in the app and needs the app's interpreter. This is a CLI under the
    system interpreter, on the same host, against the same sqlite file -- so it performs
    the identical INSERT, deduped on the SID, with the same bounded wait, and never
    raises: a failed audit write must not turn a delivered text into an error.

    Without this, a message from this door exists only in `inbox.db`, which the comms
    index does NOT cover -- so months later "what did we ask her" comes back empty. The
    family chat path writes its row for exactly this reason; this door must too.
    """
    url = str(cfg.get("DATABASE_URL") or "")
    path = url.split("sqlite:///", 1)[-1] if url.startswith("sqlite") else ""
    if not sid or not path:
        print("warn: sms_log row skipped (no sid or no sqlite DATABASE_URL)")
        return
    now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    try:
        conn = sqlite3.connect(path, timeout=AUTHORITY_DB_TIMEOUT)
        try:
            if conn.execute("SELECT 1 FROM sms_log WHERE twilio_sid=?",
                            (sid,)).fetchone():
                return
            conn.execute(
                "INSERT INTO sms_log (twilio_sid, direction, from_number, to_number,"
                " body, status, error_message, agent_id, created_at, updated_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)",
                (sid, "outbound", textsend.sender_number(cfg), to, body, status,
                 error, "private_ask.ai_line", now, now))
            conn.commit()
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001 - an audit write never fails a send
        print("warn: sms_log row not written (%s: %s)" % (type(exc).__name__, exc))


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(
        description="Ask one named person one question, privately, from the AI line.")
    ap.add_argument("--to", required=True, help="their number, any format")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--body")
    g.add_argument("--body-file")
    ap.add_argument("--reason", default="private_ask",
                    help="what this message is, for the record")
    ap.add_argument("--send", action="store_true",
                    help="actually transmit; without this it is a dry run")
    a = ap.parse_args(argv)

    body = a.body if a.body is not None else Path(a.body_file).read_text(encoding="utf-8")
    body = body.strip()
    if not body:
        _out("REFUSED", "the body is empty")
        return 2

    cfg = textsend._config(None)
    sender = textsend.sender_number(cfg)
    to = textsend._e164(a.to)

    _out("from", sender)
    _out("to", to)
    _out("chars", len(body))
    _out("mode", "SEND" if a.send else "dry run")

    # 1. never the family hub -- this is the incident, refused by name.
    hub = str(cfg.get("FAMILY_CHAT_HUB_NUMBER") or "")
    if hub and _tail(to) == _tail(hub):
        _out("REFUSED", "the recipient is the FAMILY CHAT hub number (%s), not a "
                        "person. A directed question from that number lands in the "
                        "family thread and cannot be answered privately -- that is "
                        "incident sms_log 4284. Use the person's own number." % hub)
        return 1

    # 2. never the owner -- he has his own sender and his own one-at-a-time ledger.
    owner = str(cfg.get("OWNER_PHONE_NUMBER") or "")
    if owner and _tail(to) == _tail(owner):
        _out("REFUSED", "the recipient is the owner. His questions go through "
                        "owner-ask.py / cfo-ask.py, which hold his one-at-a-time "
                        "ledger and his own outbound gate; this door would skip both.")
        return 1

    # 3. the named list. An absent key is closed, not open.
    ctx = {"allow": textsend._ledger_allow(to, cfg)}
    allowed, why = textsend.can_send_to(to, ctx, cfg)
    _out("ledger", "allow=%s" % ctx["allow"])
    _out("gate", ("OPEN - " if allowed else "CLOSED - ") + why)
    if not allowed:
        _out("REFUSED", "the send gate is closed for this recipient. Add them to "
                        "AITEXT_PRIVATE_ASK_ALLOW in .env if the owner has authorised "
                        "a 1:1 question to them, and say who they are in the note.")
        return 1

    # 4/5. transmit (or dry run) through the same sender everything else uses.
    res = textsend.send(to, body, dry_run=not a.send, reason=a.reason)
    ok = bool(res.get("ok"))
    _out("ok", ok)
    _out("sid", res.get("sid") or "(none)")
    if res.get("error"):
        _out("error", res.get("error"))
    if res.get("detail"):
        _out("detail", str(res.get("detail"))[:400])
    if a.send and res.get("sid"):
        m = re.search(r"twilio status=([a-z_]+)", str(res.get("detail") or ""))
        _record_send(cfg, sid=str(res.get("sid")), to=to, body=body,
                     status=(m.group(1) if m else ("sent" if ok else "failed")),
                     reason=a.reason, error=res.get("error"))

    _out("body", "")
    print(body)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))