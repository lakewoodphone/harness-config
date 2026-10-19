#!/usr/bin/env python3
"""dialpad-route-consults-the-relay.py - the one door to his number that skips the guards.

The door inventory (round 19) found exactly one path that can put a text on the owner's phone
without passing `owner_text_relay.submit()`:

    app/main.py  ~6481   dialpad_send_sms_direct(to_numbers=[payload.to], text=payload.body, ...)

`payload.to` is whatever the caller posts. It logs an sms_log row, but it never asks the relay - so
if any caller ever passed the owner's number, quiet hours, credential_request and internal_prose
would not apply. Today the callers are customer-facing, which is why this is a gap and not a live
defect; it is still the only unguarded door, and the whole point of the inventory was to find it.

The fix is the one `sms_service.send_message` already uses: resolve whether the destination is one of
the owner's numbers, and if it is, submit to the relay first and refuse on a non-SEND verdict.

Fails OPEN: a relay that cannot be loaded must not stop a customer text. It says so once on stderr.
"""
from __future__ import annotations

import io
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

PATH = Path(sys.argv[1] if len(sys.argv) > 1 else "/opt/company/app/main.py")

OLD = '''    from app.services.dialpad_service import send_sms as dialpad_send_sms_direct'''

NEW = '''    from app.services.dialpad_service import send_sms as dialpad_send_sms_direct

    # THE ONE DOOR THAT SKIPPED THE GUARDS (found by the round-19 inventory). `payload.to` is
    # whatever the caller posts, and this path never asked `owner_text_relay` - so a caller that
    # passed the owner's number would bypass quiet hours, credential_request and internal_prose.
    # The callers today are customer-facing, which is why this was a gap rather than a live defect,
    # and it is still the only unguarded door to his phone.
    #
    # Same shape `sms_service.send_message` uses: resolve whether the destination is HIS, and if it
    # is, let the relay decide. Fails OPEN - a relay that cannot be loaded must never stop a
    # customer text - and says so once rather than silently.
    try:
        from app.services.owner_notifications import owner_recognized_numbers

        _owner_nums = {str(n) for n in owner_recognized_numbers(settings) if n}
        if str(payload.to or "") in _owner_nums:
            from app import owner_text as _owner_text_mod

            _relay = (_owner_text_mod.owner_text_relay_module()
                      if hasattr(_owner_text_mod, "owner_text_relay_module") else None)
            if _relay is not None and hasattr(_relay, "submit"):
                _v = _relay.submit(door="app.dialpad", subsystem="dialpad_sms_api",
                                   body=str(payload.body or ""), reason="dialpad_sms_api",
                                   to=str(payload.to))
                if str((_v or {}).get("verdict") or "").upper() != "SEND":
                    return {
                        "ok": False,
                        "detail": ("owner_text relay refused this send (%s): %s"
                                   % ((_v or {}).get("verdict"), (_v or {}).get("reason"))),
                    }
    except Exception as _relay_exc:                             # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning(
            "dialpad sms route: owner-relay check unavailable (%s); sending",
            _relay_exc)'''


def main() -> int:
    dry = "--apply" not in sys.argv
    text = PATH.read_text(encoding="utf-8")
    if "app.dialpad\", subsystem=\"dialpad_sms_api" in text:
        print("OK    already applied")
        return 0
    if text.count(OLD) != 1:
        print("FAIL  anchor found %d times" % text.count(OLD))
        return 1
    out = text.replace(OLD, NEW, 1)
    import ast
    try:
        ast.parse(out)
    except SyntaxError as exc:
        print("FAIL  does not parse: %s" % exc)
        return 1
    if dry:
        print("DRY   would make the dialpad SMS route consult the relay for owner-bound sends")
        return 0
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    shutil.copy2(PATH, PATH.with_suffix(PATH.suffix + ".bak-dprout-" + stamp))
    tmp = PATH.with_suffix(PATH.suffix + ".new")
    tmp.write_text(out, encoding="utf-8")
    tmp.replace(PATH)
    print("APPLIED %s" % PATH)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
