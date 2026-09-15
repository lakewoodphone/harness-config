"""Write the reminder-poll function the scheduler has been calling since February.

agent_bus.py:482 imports `_run_reminder_poll` from app.autopilot and calls it every
5 minutes in a thread. The name has never existed (added in 533267d6, 2026-02-25 --
`git log -S` finds it only there and never in autopilot.py), so the loop has logged
"cannot import name '_run_reminder_poll' from 'app.autopilot'" every 5 minutes for
six and a half months into a log nobody read, and no reminder was ever delivered by
that path.

The implementation exists: app.services.personal_ops.process_due_reminders. This
adds the thin name the scheduler already calls, in autopilot.py rather than in
agent_bus.py -- agent_bus.py is being edited by another live session right now, and
satisfying an existing import is additive in a file only I am touching.

Safety: process_due_reminders marks reminders delivered and defaults to the
"dashboard" channel, which does not send anything; only a reminder whose own
delivery_channel is sms/both calls send_owner_update, which passes the owner-SMS
kill switch. So re-enabling the poll cannot produce an outbound message while the
switch exists.
"""

from __future__ import annotations

import pathlib
import sys

AUTO = pathlib.Path.home() / "personal-secretary-mvp" / "app" / "autopilot.py"

ANCHOR = '''def _utc_now_iso() -> str:'''
BLOCK = '''def _run_reminder_poll(settings):
    """Deliver due personal reminders. The name agent_bus has always called.

    agent_bus.py has imported this name every 5 minutes since 2026-02-25 and it was
    never written, so the scheduled check failed with an ImportError every time and
    no reminder was delivered on that path. The implementation is
    app.services.personal_ops.process_due_reminders; this wrapper exists so the
    scheduler's existing call site names something real.

    Delivery is safe to run with owner SMS off: the default channel is the
    dashboard (mark, no send), and only a reminder marked sms/both reaches
    send_owner_update, which is subject to the owner-SMS kill switch.
    """
    from app.services.personal_ops import process_due_reminders

    return process_due_reminders(settings)


'''


def main() -> int:
    text = AUTO.read_text(encoding="utf-8")
    if text.count(ANCHOR) != 1:
        print(f"REFUSE: anchor count {text.count(ANCHOR)} (expected 1)")
        return 2
    if BLOCK in text:
        print("REFUSE: already applied")
        return 2
    AUTO.write_text(text.replace(ANCHOR, BLOCK + ANCHOR, 1), encoding="utf-8")
    print("WROTE autopilot.py")
    print("PATCH OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
