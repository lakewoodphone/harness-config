#!/usr/bin/env python3
"""Family Chat drift watchdog.

Answers one question on a schedule: does our record of the family chat still
match what the carrier actually sent and received?

WHY THIS EXISTS
On 2026-09-15 the recorded conversation had been silently wrong for a month (117
of 140 stored inbound rows were unreadable) and nothing noticed, because nothing
ever compared our database with Twilio. A later reconciliation over
2026-08-15..2026-09-16 found 151 of 1448 carrier messages (10.4%) absent from our
own table, all outbound. Both defects looked exactly like a healthy system.

A record that is never checked is a record that quietly becomes fiction, so this
runs on cron and fails loudly when the two disagree.

WHAT IT CHECKS
  1. drift        — carrier messages in the window with no row in our database
  2. staleness    — how long since the hub last processed an inbound message, and
                    since it last sent anything (a silent hub is a broken hub)
  3. readability  — stored inbound rows whose readable text is missing, which is
                    the exact shape of the 2026-09-15 corruption

USAGE
    python family_chat_watchdog.py                  # last 6 hours, quiet on success
    python family_chat_watchdog.py --hours 24
    python family_chat_watchdog.py --verbose        # always print the numbers
    python family_chat_watchdog.py --json           # machine-readable, for a monitor

Exit codes:  0 healthy · 1 drift or unreadable rows · 2 stale hub · 3 cannot check
A non-zero exit on cron is the alarm. Nothing here ever sends a message or writes
to the database: it is a read-only instrument.
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
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path.home() / "personal-secretary-mvp"
DB_PATH = REPO / "data" / "family_chat.db"

# Silence is NOT evidence of a fault: a family simply not texting for a week is
# normal, and an alarm that fires on a quiet week gets muted, after which the
# real alarm is missed too. The reliable "am I able to receive" signal is the
# Twilio number's configured webhook — the same field the service checks at
# startup. A wrong or empty webhook URL means inbound messages are being lost at
# the carrier, which is exactly the failure this watchdog exists to catch.
EXPECTED_WEBHOOK_PATH = "/webhook/family-chat/sms"
# Long silences are reported only once they are implausible for this family.
QUIET_HUB_WARN_DAYS = 21
# Statuses that mean a message actually reached (or came from) a human.
ARRIVED_STATUSES = ("delivered", "received", "read")
# Report repeated carrier rejections once they are clearly not a one-off.
REJECTION_ALERT_THRESHOLD = 5
# An outbound row still 'queued'/'sent' after this long is stuck: Twilio's status
# callbacks arrive in seconds, and a row with no SID can never be resolved at all.
STUCK_STATUS_MINUTES = 20


def _load() -> tuple[str, str, str]:
    sys.path.insert(0, str(REPO))
    os.chdir(REPO)
    from app.config import settings

    sid = settings.family_chat_twilio_account_sid
    token = settings.family_chat_twilio_auth_token
    hub = settings.family_chat_hub_number
    if not (sid and token and hub):
        raise SystemExit(3)
    return sid, token, hub


def _twilio_window(sid: str, token: str, since: datetime, until: datetime) -> list[dict]:
    auth = base64.b64encode(f"{sid}:{token}".encode()).decode()
    url = (
        f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"
        f"?PageSize=1000&DateSent>={since:%Y-%m-%dT%H:%M:%SZ}"
        f"&DateSent<={until:%Y-%m-%dT%H:%M:%SZ}"
    )
    out: list[dict] = []
    for _ in range(20):
        req = urllib.request.Request(url, headers={"Authorization": f"Basic {auth}"})
        with urllib.request.urlopen(req, timeout=45) as resp:
            payload = json.load(resp)
        out.extend(payload.get("messages", []))
        nxt = payload.get("next_page_uri")
        if not nxt:
            break
        url = ("https://api.twilio.com" + nxt) if nxt.startswith("/") else nxt
    return out


def _number_webhook(sid: str, token: str, hub: str) -> str:
    """The SMS webhook URL currently configured on the hub number at Twilio.

    Empty means the carrier is not forwarding inbound texts to us at all, so the
    family can text the hub and nothing happens — silent from both ends.
    """
    auth = base64.b64encode(f"{sid}:{token}".encode()).decode()
    url = (
        f"https://api.twilio.com/2010-04-01/Accounts/{sid}/IncomingPhoneNumbers.json"
        f"?PhoneNumber={hub}"
    )
    req = urllib.request.Request(url, headers={"Authorization": f"Basic {auth}"})
    with urllib.request.urlopen(req, timeout=45) as resp:
        payload = json.load(resp)
    numbers = payload.get("incoming_phone_numbers") or []
    if not numbers:
        return ""
    return str(numbers[0].get("sms_url") or "")


def _within(message: dict, since: datetime, until: datetime) -> bool:
    """True when the carrier's own timestamp for a message is inside the window.

    Twilio's DateSent filter is only DATE-granular in the request, and a date-only
    upper bound reads as 00:00 of that day, so ">= 2026-09-29 & <= 2026-09-30"
    returns 2026-09-29 and nothing from 2026-09-30. Measured 2026-09-30 05:30:
    the run reported "179 of 179 missing" -- a whole day of carrier messages
    compared against a six-hour window -- a false alarm of exactly the shape that
    gets a watchdog muted, after which the real alarm is missed too. The
    carrier's own date_sent is the authority for membership in the window.
    """
    raw = str(message.get("date_sent") or message.get("date_created") or "")
    if not raw:
        return False
    try:
        ts = datetime.strptime(raw, "%a, %d %b %Y %H:%M:%S %z")
    except ValueError:
        # Unrecognised shape: keep the message rather than silently dropping it.
        return True
    return since <= ts <= until


def check(hours: int) -> dict:
    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=hours)
    result: dict = {
        "checked_at": now.isoformat(),
        "window_hours": hours,
        "problems": [],
        "warnings": [],
    }

    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT twilio_sid, direction, from_number, to_number, body, media_urls, "
            "created_at FROM messages WHERE created_at >= ?",
            (since.strftime("%Y-%m-%d %H:%M:%S"),),
        ).fetchall()
        last_inbound = conn.execute(
            "SELECT value FROM settings WHERE key = 'last_inbound_processed_at'"
        ).fetchone()
        unreadable = conn.execute(
            "SELECT COUNT(*) FROM messages WHERE direction = 'inbound' "
            "AND trim(coalesce(body, '')) = '' AND trim(coalesce(media_urls, '')) <> ''"
        ).fetchone()[0]
        newest_row = conn.execute(
            "SELECT MAX(created_at) FROM messages"
        ).fetchone()[0]
        stuck_cutoff = (now - timedelta(minutes=STUCK_STATUS_MINUTES)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        stuck = conn.execute(
            "SELECT COUNT(*), MIN(created_at) FROM messages WHERE direction = 'outbound' "
            "AND status IN ('queued', 'sent') AND created_at <= ?",
            (stuck_cutoff,),
        ).fetchone()
    finally:
        conn.close()

    have_sids = {r["twilio_sid"] for r in rows if r["twilio_sid"]}
    result["our_rows_in_window"] = len(rows)

    sid, token, hub = _load()
    hub_entries = [
        m
        for m in _twilio_window(sid, token, since, now)
        if (m.get("from") == hub or m.get("to") == hub)
        and _within(m, since, now)
    ]
    # Only entries that actually ARRIVED can be lost. Twilio logs attempts too: a
    # send the carrier rejected (e.g. 21610 unsubscribed recipient, or 11205 media
    # fetch failed) sits in the log with status 'failed' having never reached
    # anyone. Counting those as drift would raise a false alarm every 30 minutes
    # for as long as the rejection stands, and a watchdog that cries wolf gets
    # muted. Rejections are reported separately below instead.
    carrier = [m for m in hub_entries if (m.get("status") or "") in ARRIVED_STATUSES]
    rejected = [m for m in hub_entries if (m.get("status") or "") == "failed"]
    missing = [m for m in carrier if m.get("sid") not in have_sids]
    result["carrier_messages_in_window"] = len(carrier)
    result["carrier_rejected_in_window"] = len(rejected)
    result["missing_from_ours"] = len(missing)
    result["missing_sample"] = [
        {
            "sent": m.get("date_created"),
            "to": m.get("to"),
            "body": (m.get("body") or "")[:70],
        }
        for m in sorted(missing, key=lambda x: x.get("date_created") or "")[:10]
    ]

    stuck_count, stuck_oldest = int(stuck[0] or 0), stuck[1]
    result["stuck_outbound_rows"] = stuck_count
    if stuck_count:
        result["problems"].append(
            f"{stuck_count} outbound row(s) have sat in queued/sent for over "
            f"{STUCK_STATUS_MINUTES} minutes (oldest {stuck_oldest}) - a lost status "
            "callback, or a row with no SID that nothing can ever resolve"
        )

    if missing:
        result["problems"].append(
            f"{len(missing)} of {len(carrier)} messages the carrier DELIVERED in the "
            f"last {hours}h are absent from our database"
        )

    if rejected and len(rejected) >= REJECTION_ALERT_THRESHOLD:
        result["warnings"].append(
            f"{len(rejected)} carrier rejections in the window "
            f"(codes: {sorted({str(m.get('error_code')) for m in rejected})}) — billed "
            "but never delivered; a repeated permanent error usually means a member "
            "should be deactivated"
        )

    if unreadable:
        result["problems"].append(
            f"{unreadable} stored inbound rows have no readable text "
            "(body empty with the text left in media_urls)"
        )
    result["unreadable_inbound_rows"] = unreadable

    if last_inbound:
        raw = str(last_inbound["value"])
        try:
            stamp = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
            age_h = (now - stamp).total_seconds() / 3600.0
            result["hours_since_last_inbound"] = round(age_h, 1)
            if age_h > QUIET_HUB_WARN_DAYS * 24:
                result["warnings"].append(
                    f"no inbound message processed for {age_h / 24:.0f} days "
                    f"(last: {raw}) — normal if the family is quiet, worth a look if "
                    "they have been texting"
                )
        except ValueError:
            result["warnings"].append(f"unparseable last_inbound_processed_at: {raw!r}")

    # Can the hub receive at all? This is the check that catches a lost webhook.
    try:
        webhook = _number_webhook(sid, token, hub)
        result["sms_webhook"] = webhook
        if not webhook or EXPECTED_WEBHOOK_PATH not in webhook:
            result["problems"].append(
                f"the hub number's SMS webhook is {webhook!r}, which does not contain "
                f"{EXPECTED_WEBHOOK_PATH!r} — inbound messages are being lost at the "
                "carrier and no family text will reach the hub"
            )
    except Exception as exc:  # noqa: BLE001
        result["warnings"].append(f"could not read the number's webhook: {exc}")

    result["newest_row_created_at"] = newest_row
    result["hub_number"] = hub
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=int, default=6)
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    try:
        result = check(args.hours)
    except SystemExit:
        raise
    except urllib.error.URLError as exc:
        # Cannot reach the carrier: not evidence of health, and not evidence of
        # a fault either. Say so rather than reporting either.
        print(f"family-chat-watchdog: cannot reach Twilio: {exc}", file=sys.stderr)
        return 3
    except Exception as exc:  # noqa: BLE001
        print(f"family-chat-watchdog: check failed: {exc}", file=sys.stderr)
        return 3

    if args.json:
        print(json.dumps(result, indent=2))
    elif result["problems"] or result["warnings"] or args.verbose:
        print(f"family-chat-watchdog @ {result['checked_at']}")
        print(
            f"  window {result['window_hours']}h: carrier "
            f"{result['carrier_messages_in_window']}, ours "
            f"{result['our_rows_in_window']}, missing {result['missing_from_ours']}"
        )
        for m in result["missing_sample"]:
            print(f"    missing: {m['sent']} -> {m['to']} {m['body']!r}")
        for p in result["problems"]:
            print(f"  PROBLEM: {p}")
        for w in result["warnings"]:
            print(f"  warn: {w}")

    else:
        # Healthy. Say so out loud: a silent log cannot be told apart from a
        # cron that stopped, and this instrument was already muted once.
        print(
            f"family-chat-watchdog @ {result['checked_at']} quiet: carrier "
            f"{result['carrier_messages_in_window']}, ours "
            f"{result['our_rows_in_window']}, missing 0, window "
            f"{result['window_hours']}h, webhook {result['sms_webhook']}"
        )

    if any("webhook is" in p for p in result["problems"]):
        return 2
    if result["problems"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
