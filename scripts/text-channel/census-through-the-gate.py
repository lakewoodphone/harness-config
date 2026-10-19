#!/usr/bin/env python3
"""census-through-the-gate.py - the conformance census measured around the gate.

`owner-text-scorecard.conformance()` asks `internal_prose()` and `credential_request()` about each
delivered body. But the relay now RESCUES a reminder-class body before those guards run, so the
census charges the channel for texts the gate would in fact rewrite and send.

Same mistake I made in `reminders-at-risk.py` and caught there: a probe that measures around the
gate reports the defect it was written to find. The census is the number that decides whether the
overhaul worked, so it has to measure what the gate does, not what one function would do.

This routes each body through `_rescue_reminder()` first, exactly as `submit()` does, and reports
both numbers so the size of the overstatement is visible instead of silently corrected.
"""
from __future__ import annotations

import io
import sys

PATH = sys.argv[1] if len(sys.argv) > 1 else "owner-text-scorecard.py"

OLD = '''        delivered += 1
        body = r.get("body") or ""
        hits = []
        for name in _GUARD_FUNCS:
            fn = getattr(relay, name, None)
            if not callable(fn):
                continue
            try:
                got = fn(body)
            except Exception:
                got = None
            if got:
                hits.append(name)'''

NEW = '''        delivered += 1
        body = r.get("body") or ""
        # THROUGH THE GATE. `submit()` first offers a reminder-class body to `_rescue_reminder()`,
        # which rewrites an instruction-shaped reminder into a sentence and sends the readable
        # remainder. Asking the guards about the RAW body charges the channel for messages the
        # gate would have rewritten and delivered - measured 2026-10-19: 9 of 34 reminder texts,
        # every one of them a real reminder (Weinberg settlement, Fisher SD card, Weitman bench).
        # The rescued text is what the guards actually see, so it is what this census must score.
        rescued = body
        rescue_note = ""
        fn_rescue = getattr(relay, "_rescue_reminder", None)
        if callable(fn_rescue):
            try:
                got_r = fn_rescue(body, OWNER, r.get("subsystem") or "cron")
                if isinstance(got_r, tuple) and len(got_r) == 2:
                    rescued, rescue_note = got_r[0], str(got_r[1] or "")
            except Exception:
                rescued, rescue_note = body, ""
        if rescued != body:
            rewrites += 1
        hits = []
        for name in _GUARD_FUNCS:
            fn = getattr(relay, name, None)
            if not callable(fn):
                continue
            try:
                got = fn(rescued)
            except Exception:
                got = None
            if got:
                hits.append(name)'''

ANCHOR_COUNTER = "    delivered = 0\n    flagged = 0"
ANCHOR_COUNTER_NEW = "    delivered = 0\n    flagged = 0\n    rewrites = 0"

ANCHOR_RETURN = '''    return {"available": True, "delivered": delivered, "would_refuse": flagged,
            "by_class": by_class, "examples": examples,
            "rate": (flagged / delivered) if delivered else None}'''
ANCHOR_RETURN_NEW = '''    return {"available": True, "delivered": delivered, "would_refuse": flagged,
            "rewritten": rewrites, "by_class": by_class, "examples": examples,
            "rate": (flagged / delivered) if delivered else None}'''


def main() -> int:
    dry = "--apply" not in sys.argv
    text = io.open(PATH, encoding="utf-8").read()
    if "_rescue_reminder" in text:
        print("OK    already applied")
        return 0
    for label, anchor in (("the body loop", OLD), ("the counters", ANCHOR_COUNTER),
                          ("the return", ANCHOR_RETURN)):
        if text.count(anchor) != 1:
            print("FAIL  %s found %d times" % (label, text.count(anchor)))
            return 1
    out = (text.replace(OLD, NEW, 1)
               .replace(ANCHOR_COUNTER, ANCHOR_COUNTER_NEW, 1)
               .replace(ANCHOR_RETURN, ANCHOR_RETURN_NEW, 1))
    if "OWNER = " not in out:
        print("FAIL  no OWNER constant in this file - the rescue needs the owner number")
        return 1
    import ast
    try:
        ast.parse(out)
    except SyntaxError as exc:
        print("FAIL  does not parse: %s" % exc)
        return 1
    if dry:
        print("DRY   would measure the census through the gate (rescue included)")
        return 0
    io.open(PATH, "w", encoding="utf-8", newline="\n").write(out)
    print("APPLIED %s" % PATH)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
