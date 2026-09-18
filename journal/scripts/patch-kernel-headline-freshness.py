"""The badge's waiting line must show what is live, not the loudest stale row.

Verified 2026-09-15 by live probe: an in-app reminder created now reached the owner queue
(held, `reason=reminder:398`), and the badge still showed the same two six-day-old Google
security alerts, because the sample ordering was:

    CASE reason ... END, CASE urgency ... END, created_at DESC

Urgency outranks everything, so two stale `critical` emails take both headline slots for
ever and the live items -- the reminder the owner set, a fresh sync login, a live email --
never appear. That is the same defect the severity fix repaired one level up (a count of
critical rows held the surface red regardless of age), and leaving it here would make the
in-app reminder channel technically wired and practically invisible.

Fix: freshness first (the same 48-hour window and the same observation clock the shelf life
and the severity rule use), then reason class, then urgency, then recency. A fresh critical
email still beats a fresh reminder (second clause), and the stale criticals still appear in
the summary's count with their age -- they just stop owning the one line the owner reads.
"""

from __future__ import annotations

import pathlib
import sys

SENT = pathlib.Path("/home/zabz/ceo-kernel/ck/sentinel.py")

ANCHOR = '''    held_samples = sources.rows(
        "SELECT urgency, reason, body FROM owner_message_queue WHERE status='held' "
        "ORDER BY CASE WHEN reason = 'urgent_email' THEN 0 "
        # A reminder is the owner's own item, so it ranks with the mail he asked to be
        # told about rather than with the briefings; same rank means newest wins.
        "WHEN reason LIKE 'reminder:%' THEN 0 "
        "WHEN reason LIKE 'sync_breaker%' THEN 2 ELSE 1 END, "
        "CASE urgency WHEN 'critical' THEN 0 WHEN 'urgent' THEN 1 "
        "WHEN 'high' THEN 1 ELSE 2 END, created_at DESC LIMIT 4",
        name="held_samples",
    )'''

REPLACE = '''    held_samples = sources.rows(
        "SELECT urgency, reason, body FROM owner_message_queue WHERE status='held' "
        # Freshness first: a row observed inside FRESH_CRITICAL_HOURS is live and belongs on
        # the line; anything older is history that the summary still counts and dates. Two
        # six-day-old critical emails held both headline slots until this was added, which
        # made the in-app reminder channel invisible even after it was wired up.
        "ORDER BY CASE WHEN datetime(COALESCE(last_seen_at, created_at)) "
        ">= datetime('now', ?) THEN 0 ELSE 1 END, "
        "CASE WHEN reason = 'urgent_email' THEN 0 "
        # A reminder is the owner's own item, so it ranks with the mail he asked to be
        # told about rather than with the briefings; same rank means newest wins.
        "WHEN reason LIKE 'reminder:%' THEN 0 "
        "WHEN reason LIKE 'sync_breaker%' THEN 2 ELSE 1 END, "
        "CASE urgency WHEN 'critical' THEN 0 WHEN 'urgent' THEN 1 "
        "WHEN 'high' THEN 1 ELSE 2 END, created_at DESC LIMIT 4",
        ("-%d hours" % int(FRESH_CRITICAL_HOURS),),
        name="held_samples",
    )'''


def main() -> int:
    text = SENT.read_text(encoding="utf-8")
    if text.count(ANCHOR) != 1:
        print(f"REFUSE: anchor count {text.count(ANCHOR)} (expected 1)")
        return 2
    if REPLACE in text:
        print("REFUSE: already applied")
        return 2
    SENT.write_text(text.replace(ANCHOR, REPLACE, 1), encoding="utf-8")
    print(f"WROTE {SENT}")
    print("PATCH OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
