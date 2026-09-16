"""A reminder marked `sent` into a dashboard nobody renders is a reminder nobody got.

Measured 2026-09-15 (P148): `reminders` holds 396 rows, 14 pending, 0 due. The recent ones
carry `status='sent'` with `delivery_channel='dashboard'`. `delivery_channel` defaults to
`dashboard` in the schema, in the create API and in chat scheduling; the only consumer of
that column is `process_due_reminders`, which skips everything that is not `sms`/`both`;
and nothing on any surface renders a delivered reminder. So the system awarded itself
`sent` for work that reached nobody.

The surface the owner actually chose exists already: the owner-message queue, which the
badge renders, which has a shelf life, and which `send_owner_update` already falls back to
when the owner-SMS kill switch is on. So route the in-app channels there, and give them a
one-day horizon because a reminder is time-bound by nature.

Enqueued as `held` on purpose: a reminder must never become an outbound SMS on its own,
whatever happens to the kill switch later. And the kernel's badge sampling now ranks
`reminder:%` beside `urgent_email`, so a fresh reminder reaches the one line the owner reads
instead of competing with briefings.
"""

from __future__ import annotations

import pathlib
import sys

REPO = pathlib.Path.home() / "personal-secretary-mvp"
OPS = REPO / "app" / "services" / "personal_ops.py"
SWEEP = REPO / "app" / "services" / "lifecycle_sweep.py"

OPS_ANCHOR = '''        delivered += 1
        channel = str(reminder.get("delivery_channel") or "dashboard").strip().lower()
        if channel not in ("sms", "both"):
            continue

        try:
            from app.tool_factory import send_owner_update

            msg = str(reminder.get("message") or "Reminder")
            priority = str(reminder.get("priority") or "normal").lower()
            prefix = "🚨 " if priority in ("urgent", "high") else "⏰ "
            result = send_owner_update(f"{prefix}Reminder: {msg}", settings=settings)
            if isinstance(result, dict) and result.get("ok"):
                sms_sent += 1
            else:
                failed += 1
        except Exception:
            failed += 1'''

OPS_REPLACE = '''        delivered += 1
        channel = str(reminder.get("delivery_channel") or "dashboard").strip().lower()
        msg = str(reminder.get("message") or "Reminder")
        priority = str(reminder.get("priority") or "normal").lower()
        prefix = "🚨 " if priority in ("urgent", "high") else "⏰ "

        # The in-app channel had no reader (P148). `delivery_channel` defaults to
        # 'dashboard', the only consumer skipped everything that was not sms/both, and no
        # surface rendered a delivered reminder -- so a due reminder was marked delivered
        # and reached nobody while the row said 'sent'. The surface the owner chose is the
        # owner-message queue the badge renders, which is exactly where the SMS path
        # already falls back when its kill switch is on. Route the in-app channels there.
        #
        # `held`, deliberately: a reminder must never become an outbound SMS on its own,
        # whatever happens to the kill switch later.
        if channel not in ("sms", "both"):
            try:
                from app.database import enqueue_owner_message

                enqueue_owner_message(
                    db_url,
                    body=f"{prefix}Reminder: {msg}",
                    reason=f"reminder:{reminder_id}",
                    urgency="urgent" if priority in ("urgent", "high") else "normal",
                    status="held",
                )
                queued += 1
            except Exception:
                failed += 1
            continue

        try:
            from app.tool_factory import send_owner_update

            result = send_owner_update(f"{prefix}Reminder: {msg}", settings=settings)
            if isinstance(result, dict) and result.get("ok"):
                sms_sent += 1
            else:
                failed += 1
        except Exception:
            failed += 1'''

OPS_COUNTER_ANCHOR = '''    delivered = 0
    sms_sent = 0
    failed = 0'''

OPS_COUNTER_REPLACE = '''    delivered = 0
    sms_sent = 0
    queued = 0
    failed = 0'''

OPS_RETURN_ANCHOR = '''    return {
        "checked": len(due),
        "sent": delivered,
        "delivered": delivered,
        "sms_sent": sms_sent,
        "failed": failed,
    }'''

OPS_RETURN_REPLACE = '''    return {
        "checked": len(due),
        "sent": delivered,
        "delivered": delivered,
        "sms_sent": sms_sent,
        "queued": queued,
        "failed": failed,
    }'''

HORIZON_ANCHOR = '''OWNER_MESSAGE_MAX_AGE_HOURS_PREFIX = (
    ("sync_breaker", 24.0),
    ("sync_needs_login", 168.0),
)'''

HORIZON_REPLACE = '''OWNER_MESSAGE_MAX_AGE_HOURS_PREFIX = (
    ("sync_breaker", 24.0),
    ("sync_needs_login", 168.0),
    # A reminder is time-bound by nature: one the owner has not acted on in a day is a
    # stale nag, and the item itself is still open in `reminders` either way.
    ("reminder", 24.0),
)'''

EDITS = {
    OPS: [
        (OPS_COUNTER_ANCHOR, OPS_COUNTER_REPLACE, "personal_ops: a queued counter"),
        (OPS_ANCHOR, OPS_REPLACE, "personal_ops: in-app reminders reach the owner queue"),
        (OPS_RETURN_ANCHOR, OPS_RETURN_REPLACE, "personal_ops: report it"),
    ],
    SWEEP: [
        (HORIZON_ANCHOR, HORIZON_REPLACE, "lifecycle_sweep: reminders age out in a day"),
    ],
}


def main() -> int:
    plans = []
    for path, edits in EDITS.items():
        text = path.read_text(encoding="utf-8")
        for old, new, label in edits:
            count = text.count(old)
            if count != 1:
                print(f"REFUSE {label}: anchor count {count} (expected 1) in {path.name}")
                return 2
            if new in text:
                print(f"REFUSE {label}: already applied")
                return 2
            text = text.replace(old, new, 1)
            print(f"planned  {label}")
        plans.append((path, text))
    for path, text in plans:
        path.write_text(text, encoding="utf-8")
        print(f"WROTE {path}")
    print("PATCH OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
