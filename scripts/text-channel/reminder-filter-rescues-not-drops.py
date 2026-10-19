#!/usr/bin/env python3
"""reminder-filter-rescues-not-drops.py - two defences, one of which deletes.

`tool_factory.send_due_reminders` keeps a reminder PENDING instead of texting it when the message
names a path, a file or a task row:

    if re.search(r"(?:lpt-hub|docs/|/home/|~/|\\.md\\b|\\.py\\b|\\btask\\s*#?\\d{3,})", msg):
        remaining.append(r); continue

That was the lesser evil before the relay could rewrite anything. Since 2026-10-19 the relay
RESCUES a reminder-class body - strips the scaffolding, sends the readable remainder - so the
filter now deletes what the gate would have delivered.

MEASURED on five real reminder bodies: the filter drops the Weinberg settlement reminder
("Pay Yisroel Weinberg 597.29 net CASH settlement ... Record date+amount in
lpt-hub/docs/operations/payroll/..."), which the rescue turns into a clean 188-character reminder.
A real money reminder kept pending forever, for a reason the gate already solves.

So the filter is replaced by the same decision the gate makes, using the same code, computed
before the send rather than after it:

    rescue the body -> if what remains still reads as internal prose, keep it pending
                    -> otherwise send the rescued text

One defence, at the layer that can REPAIR rather than only REJECT. Falls back to the old regex if
the relay cannot be loaded, so a missing relay cannot start texting work orders.

A REFUSED SEND STILL LOOPS, which is why this cannot be "just send it and let the gate refuse":
`send_owner_update` marks a reminder sent only when the result is ok, so a body the gate refuses
stays pending and retries - the documented 840-refusal storm of one 321-character reminder.
"""
from __future__ import annotations

import io
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

PATH = Path(sys.argv[1] if len(sys.argv) > 1 else "/opt/company/app/tool_factory.py")

OLD = '''            msg = r.get("message", "Reminder")
            # A reminder naming a repo path, a file or a task row is a work order,
            # not a message: keep it pending for the dashboard instead of texting
            # it. (Measurement: personal_ops.process_due_reminders, 2026-10-06.)
            if re.search(r"(?:lpt-hub|docs/|/home/|~/|\\.md\\b|\\.py\\b|\\btask\\s*#?\\d{3,})", str(msg or ""), re.I):
                remaining.append(r)
                continue'''

NEW = '''            msg = r.get("message", "Reminder")
            body = f"\\u23f0 Reminder: {msg}"
            # ONE DEFENCE, AT THE LAYER THAT CAN REPAIR. Until 2026-10-19 the only option was to
            # keep a work-order-shaped reminder pending instead of texting it - which is what this
            # regex did, and it DELETED the Weinberg settlement reminder ("... Record date+amount
            # in lpt-hub/docs/operations/payroll/..."), a real money reminder kept pending forever.
            # The relay now RESCUES such a body: it strips the paths, task ids and instruction
            # verbs and sends the readable remainder. So ask the same code the gate will ask, and
            # only keep the reminder pending when nothing readable survives.
            _work_order = re.search(
                r"(?:lpt-hub|docs/|/home/|~/|\\.md\\b|\\.py\\b|\\btask\\s*#?\\d{3,})",
                str(msg or ""), re.I)
            _send_body = body
            _rescued = False
            try:
                from app import owner_text as _ot

                _relay = (_ot.owner_text_relay_module()
                          if hasattr(_ot, "owner_text_relay_module") else None)
                if _relay is not None and hasattr(_relay, "_rescue_reminder"):
                    from app.services.owner_notifications import owner_recognized_numbers

                    _nums = [n for n in owner_recognized_numbers(settings) if n]
                    _out = _relay._rescue_reminder(body, _nums[0] if _nums else "",
                                                   "app.reminder")
                    if isinstance(_out, tuple) and len(_out) == 2:
                        _send_body = _out[0] or body
                        _rescued = _send_body != body
                    if _relay.internal_prose(_send_body):
                        remaining.append(r)
                        continue
                    _work_order = None          # the gate's own judgement supersedes the regex
            except Exception:              # noqa: BLE001 - a rescue that fails must not send garbage
                pass
            if _work_order is not None:
                # No relay to ask, or it could not decide: keep the old, safe behaviour.
                remaining.append(r)
                continue'''

OLD_SEND = '''            result = send_owner_update(
                f"\u23f0 Reminder: {msg}",
                settings=settings,
                reason="reminder",
            )'''
NEW_SEND = '''            result = send_owner_update(
                _send_body,
                settings=settings,
                reason="reminder",
            )'''


def main() -> int:
    dry = "--apply" not in sys.argv
    text = PATH.read_text(encoding="utf-8")
    if "_rescue_reminder" in text:
        print("OK    already applied")
        return 0
    for label, anchor in (("the filter block", OLD), ("the send call", OLD_SEND)):
        if text.count(anchor) != 1:
            print("FAIL  %s found %d times" % (label, text.count(anchor)))
            return 1
    out = text.replace(OLD, NEW, 1).replace(OLD_SEND, NEW_SEND, 1)
    import ast
    try:
        ast.parse(out)
    except SyntaxError as exc:
        print("FAIL  does not parse: %s" % exc)
        return 1
    if dry:
        print("DRY   would replace the drop-filter with the gate's own rescue")
        return 0
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    shutil.copy2(PATH, PATH.with_suffix(PATH.suffix + ".bak-rescuefilter-" + stamp))
    tmp = PATH.with_suffix(PATH.suffix + ".new")
    tmp.write_text(out, encoding="utf-8")
    tmp.replace(PATH)
    print("APPLIED %s" % PATH)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
