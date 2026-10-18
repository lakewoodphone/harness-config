#!/usr/bin/env python3
"""Carry a SETTLED SMS status from the capture mirror into the store tools read.

WHY (pain P7307, docs/mesh/178 section 53). `reconcile-sent-status.py` asks Twilio for the
truth and writes it into `messages` in ~/.sms-inbox/inbox.db. The owner's texts -- the rows
`owner_attention`, the ps_* MCP tools and every report query read -- live in
/root/authority.db -> `sms_log`. Nothing propagates between them, so a message that Twilio
says was DELIVERED stays `queued` in the store that gets asked.

Measured on the authority 2026-10-18: of 65 outbound `sms_log` rows that are `queued`, carry
a real SID and are older than 48 h, 50 already hold a settled status in the mirror. One SID
(SM8dea23086e7e9f203aadb4134ecaf70c) read `queued` in sms_log and `delivered` in the mirror
at the same moment.

WHAT IT DOES, AND WHAT IT REFUSES
  * Only rows whose SID is present in BOTH stores, direction=outbound.
  * Only settles into a TERMINAL status: delivered / failed / undelivered / sent.
  * Never overwrites one settled status with a DIFFERENT settled status -- that is two stores
    disagreeing, which is reported as a conflict for a human, not guessed. (A stale `queued`
    or empty status is not a disagreement; it is an absence, and it is filled.)
  * Idempotent: a second run changes nothing.
  * Prints the raw counts on both sides before and after, because a number that cannot be
    re-derived is not a measurement.

Dry run by default. `--apply` is the only way it writes. `--db`/`--mirror` exist so the test
can point at a throwaway store; production defaults are the real paths.
"""
import argparse
import os
import sqlite3
import sys
from datetime import datetime, timezone

TERMINAL = ("delivered", "failed", "undelivered", "sent")
APP_DB = os.environ.get("SMART_DB") or "/root/authority.db"
MIRROR_DB = os.environ.get("SMS_INBOX_DB") or os.path.expanduser("~/.sms-inbox/inbox.db")


def now():
    return datetime.now(timezone.utc).isoformat()


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--apply", action="store_true", help="write; without this it is a dry run")
    ap.add_argument("--db", default=APP_DB, help="the app store holding sms_log")
    ap.add_argument("--mirror", default=MIRROR_DB, help="the capture store holding messages")
    ap.add_argument("--limit", type=int, default=100000)
    a = ap.parse_args()

    if not os.path.exists(a.db) or not os.path.exists(a.mirror):
        print("REFUSED: missing store  db=%s mirror=%s" % (a.db, a.mirror))
        return 2

    app = sqlite3.connect(a.db, timeout=20)
    app.row_factory = sqlite3.Row
    mir = sqlite3.connect("file:%s?mode=ro" % a.mirror, uri=True, timeout=20)
    mir.row_factory = sqlite3.Row

    before = app.execute(
        "SELECT status, COUNT(*) c FROM sms_log WHERE direction='outbound' GROUP BY status"
        " ORDER BY c DESC").fetchall()
    print("sms_log outbound BEFORE: " + ", ".join("%s=%d" % (r["status"] or "NULL", r["c"])
                                                  for r in before))

    rows = app.execute(
        "SELECT id, twilio_sid, status FROM sms_log "
        "WHERE direction='outbound' AND twilio_sid IS NOT NULL AND twilio_sid<>'' "
        "LIMIT ?", (a.limit,)).fetchall()

    changed, conflict, absent, same, notterm = [], [], 0, 0, 0
    for r in rows:
        m = mir.execute("SELECT status FROM messages WHERE sid=? LIMIT 1",
                        (r["twilio_sid"],)).fetchone()
        if m is None:
            absent += 1
            continue
        want = (m["status"] or "").strip().lower()
        have = (r["status"] or "").strip().lower()
        if want not in TERMINAL:
            notterm += 1
            continue
        if want == have:
            same += 1
            continue
        if have in TERMINAL and have != want:
            conflict.append((r["id"], r["twilio_sid"], have, want))
            continue
        changed.append((r["id"], r["twilio_sid"], have or "(empty)", want))

    print("scanned=%d  to_change=%d  conflicts=%d  already_same=%d  no_mirror_row=%d"
          "  mirror_not_terminal=%d" % (len(rows), len(changed), len(conflict),
                                        same, absent, notterm))
    for i, sid, have, want in changed[:10]:
        print("  %-6d %-34s %s -> %s" % (i, sid, have, want))
    if len(changed) > 10:
        print("  ... and %d more" % (len(changed) - 10))
    for i, sid, have, want in conflict[:10]:
        print("  CONFLICT id=%d %s: sms_log=%s mirror=%s (left alone)" % (i, sid, have, want))

    if not a.apply:
        print("\n(dry run: nothing written. use --apply)")
        return 0

    t = now()
    for i, sid, have, want in changed:
        app.execute("UPDATE sms_log SET status=?, updated_at=? WHERE id=?",
                    (want, t, i))
    app.commit()

    after = app.execute(
        "SELECT status, COUNT(*) c FROM sms_log WHERE direction='outbound' GROUP BY status"
        " ORDER BY c DESC").fetchall()
    print("sms_log outbound AFTER : " + ", ".join("%s=%d" % (r["status"] or "NULL", r["c"])
                                                  for r in after))
    print("RESULT: wrote %d status update(s); %d conflict(s) left for a human"
          % (len(changed), len(conflict)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
