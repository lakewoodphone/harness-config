#!/usr/bin/env python3
"""FLAG SOURCE: an inbound text that was recorded and then never decided.

THE SIGNAL
----------
`messages WHERE direction='inbound' AND state='new' AND first_seen < now-6h`
in ~/.sms-inbox/inbox.db.

`state='new'` is the inbox's "nothing has decided this yet" marker. The router,
~/bin/sms-responder.py, moves every inbound text out of it — to `answered`,
`queued`, `ignored` or `woken` — and it is run from cron every 5 minutes with
`--limit 25`, i.e. up to 25 texts decided per run, 300 per hour.

WHY THIS IS ABNORMAL, AND WHY THE THRESHOLD IS 6 HOURS
------------------------------------------------------
Measured on secratary, 2026-09-18 03:15 UTC:

    inbound messages in state='new'                         : 0
    inbound state='new' older than 6 h by first_seen         : 0
    inbound texts that had arrived in the preceding hour     : 4
    ...and all 4 were decided within ~2 minutes of being recorded

So the healthy value is zero, and the margin is enormous: at 25 decisions per
run and 12 runs per hour, a text that is still `new` after SIX HOURS has had
~72 chances to be decided, which is 144 messages of drain capacity for a line
that receives a handful a day. The only ways it happens are (a) the responder is
not running at all, or (b) the message keeps failing to send and the responder
re-records it as `new` with a reason — and both are real, and both mean a person
who texted the shop is waiting in silence with nobody told.

Note the `reason` column: NULL means the responder never saw it (the consumer is
dead); `send failed: ...` means Twilio is rejecting our replies (the sender is
broken). The flag carries that distinction so the session does not have to guess.

This path is unmonitored elsewhere: ~/.lpt-recon/production-comms-freshness.py
watches the app's own Dialpad/SMS tables, not this router.

PRIORITY  high. A customer or family member texted and got nothing.

SUBJECT  sms-stranded:<UTC day>
    Day-bucketed, so a condition that persists costs at most ONE session per day
    rather than one per stuck message. One session per day is enough to fix a
    dead consumer; the store's daily cap bounds all sources together.

MUST NEVER
    - fire on outbound rows, or on inbound rows another state has claimed
    - fire while `state='new'` rows are merely recent (the healthy case)
    - send, reply, or mutate the inbox: this source reads, files a row, and stops

RUN
    python3 sources/txt-stranded-inbound.py [--dry-run]
    STRANDED_HOURS=6     how old a `new` inbound text must be (default 6)
    STRANDED_MAX=25      how many to list in the prompt (default 25)
"""
from __future__ import annotations

import os
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _flag                                                     # noqa: E402
from _flag import Finding, Unreadable                            # noqa: E402

SOURCE = "txt-stranded-inbound"


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
    hours = _float_env("STRANDED_HOURS", 6.0)
    limit = _int_env("STRANDED_MAX", 25)
    now = _flag.now_utc()
    cutoff = now - timedelta(hours=hours)

    conn = _flag.ro_connect(_flag.inbox_db())
    try:
        if not _flag.table_exists(conn, "messages"):
            raise Unreadable(f"no messages table in {_flag.inbox_db()}")
        rows = conn.execute(
            "SELECT sid, from_number, date_sent, first_seen, reason, body"
            "  FROM messages"
            " WHERE direction='inbound' AND state='new' AND first_seen < ?"
            " ORDER BY first_seen ASC LIMIT ?",
            (cutoff.isoformat(timespec="seconds"), limit),
        ).fetchall()
        total = conn.execute(
            "SELECT COUNT(*) FROM messages"
            " WHERE direction='inbound' AND state='new' AND first_seen < ?",
            (cutoff.isoformat(timespec="seconds"),),
        ).fetchone()[0]
        allows = _allows(conn, [r["from_number"] for r in rows])
    finally:
        conn.close()

    if not rows:
        return []
    day = now.strftime("%Y-%m-%d")
    return [_finding(day, hours, rows, total, allows, now)]


def _allows(conn, phones) -> dict:
    if not _flag.table_exists(conn, "permissions"):
        return {}
    out = {}
    for phone in set(phones):
        try:
            row = conn.execute(
                "SELECT allow, name, relationship FROM permissions WHERE phone=?",
                (phone,)).fetchone()
        except Exception:                                      # noqa: BLE001
            return {}
        out[phone] = dict(row) if row else {}
    return out


def _finding(day, hours, rows, total, allows, now) -> Finding:
    lines = [
        f"{total} inbound text(s) have been sitting in ~/.sms-inbox/inbox.db in "
        f"state='new' for more than {hours:g} hour(s) as of "
        f"{now.strftime('%Y-%m-%dT%H:%M:%SZ')}. 'new' means nothing has decided "
        f"them: not answered, not queued for the owner, not ignored.",
        "",
        "~/bin/sms-responder.py is the only thing that moves a text out of 'new', "
        "and cron runs it every 5 minutes with --limit 25. At that rate a text "
        "still undecided after 6 hours means the router is not running, or its "
        "reply keeps failing. Whoever sent these has had no reply and nobody was "
        "told.",
        "",
    ]
    for row in rows:
        age = ""
        seen = _flag.parse_dt(row["first_seen"])
        if seen:
            age = f", {(now - seen).total_seconds() / 3600:.1f}h ago"
        allow = allows.get(row["from_number"]) or {}
        lines.append(
            "  - %s  sent %s  recorded %s%s  allow=%s%s  reason=%s"
            % (row["from_number"], row["date_sent"], str(row["first_seen"])[:19],
               age, allow.get("allow") or "NO LEDGER ROW",
               f" ({allow.get('name')})" if allow.get("name") else "",
               row["reason"] or "NULL — the router never saw it")
        )
        body = (row["body"] or "").replace("\n", " ")[:140]
        lines.append(f"      {body!r}")
    if total > len(rows):
        lines.append(f"  ... and {total - len(rows)} more")
    lines += [
        "",
        "WHAT TO DO",
        "1. Decide which failure this is, from the reason column.",
        "   - reason is NULL  -> the router is not consuming. Check crontab for the",
        "     sms-responder line, run it by hand and read what it prints:",
        "       python3 ~/bin/sms-responder.py run --send --max-sends 2",
        "     and check ~/.sms-inbox/responder.log for the last run.",
        "   - reason is 'send failed: ...' -> our replies are being rejected. Read",
        "     the Twilio error in that reason and fix the send path.",
        "2. Fix the cause, then re-run the router and confirm these rows leave 'new'.",
        "3. Report what each stranded person's text said and what the fix was.",
        "",
        "DO NOT: send anything to these people — the responder owns outbound, and",
        "sending is a separate, owner-gated decision. Do not delete or rewrite inbox",
        "rows. Do not touch cron without saying so explicitly in your report.",
    ]
    return Finding(
        subject=f"sms-stranded:{day}",
        prompt="\n".join(lines),
        context=f"{SOURCE}: {total} inbound text(s) undecided for >{hours:g}h",
        priority="high",
        kind="bug",
        cooldown_seconds=int(os.environ.get("STRANDED_COOLDOWN_SEC") or 86400),
    )


if __name__ == "__main__":
    sys.exit(_flag.run(SOURCE, collect))
