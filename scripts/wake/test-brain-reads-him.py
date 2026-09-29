#!/usr/bin/env python3
"""DOES THE BRAIN ACTUALLY READ HIM? Feed his REAL messages through the REAL decision path with the REAL
context, and see whether the model understands them. This is the test that matters, because the whole complaint
was that a hardcoded thing was answering him instead of a brain.

Nothing is sent and nothing is filed: `choose()` returns a decision; we print it.

Usage: python3 test-brain-reads-him.py
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

MSGS = [
    ("2026-09-29T02:22:39", "OK two different questions one about escape 101 and one about the library so the "
     "library I actually still have the books in my house and simply have to return them to the fees and stuff "
     "get waived after I return them as their point in returning them, what happens if I don't mark that old "
     "down and figure it out and as for a skate 101 I don't use that company anymore. It's basically closed "
     "down for good and done for silence and the reason to keep it Open."),
    ("2026-09-29T02:54:36", "I will pay Weinberg in cash after the holiday\nI already answered the desktop chat "
     "earlier today that he left voluntarily because he wanted more pay"),
    ("2026-09-29T02:57:25", "We have to check back if I paid maybe check the credit card statements because I "
     "thought I paid a few weeks ago"),
    ("2026-09-29T03:10:04", "It's probably a no reply so I don't know why you would reply to it as for the car "
     "after the holiday. Maybe we'll get a proper inspection and the GitHub token depends who uses the token "
     "and what it's for you did not have to bring that to my attention."),
]


def main() -> int:
    spec = importlib.util.spec_from_file_location("resp", "/home/zabz/bin/sms-responder.py")
    resp = importlib.util.module_from_spec(spec)
    sys.modules["resp"] = resp
    spec.loader.exec_module(resp)
    if getattr(resp, "decide_mod", None) is None:
        print("textdecide is not loaded - cannot test the brain")
        return 2

    conv = resp._last_asked_and_open()
    # the same context the live path builds: the ledger view for his number, plus the conversation
    try:
        ctx = resp.safe_resolve(None, "+18483897895")
    except Exception as exc:
        print("could not resolve context (%s) - continuing with a minimal one" % exc)
        ctx = {}
    ctx = dict(ctx or {})
    ctx["phone"] = "+18483897895"
    if conv.get("last_asked"):
        ctx["last_asked"] = conv["last_asked"]
    if conv.get("asked_recently"):
        ctx["asked_recently"] = conv["asked_recently"]
    if conv.get("open_owner_rows"):
        ctx["open_owner_rows"] = conv["open_owner_rows"]

    print("context given to the model:")
    print("  last_asked         : #%s" % (conv.get("last_asked") or {}).get("queue_id"))
    print("  asked_recently     : %s" % [r.get("queue_id") for r in (conv.get("asked_recently") or [])])
    print("  open_owner_rows    : %d" % len(conv.get("open_owner_rows") or []))
    print("  identity           : %s" % json.dumps((ctx.get("identity") or {}), default=str)[:120])
    print()
    for at, body in MSGS:
        d = resp.safe_decide(body, ctx)
        print("=" * 100)
        print("HIS TEXT %s" % at)
        print("  %s" % " ".join(body.split())[:170])
        print("  -> action      : %s" % d.get("action"))
        print("     model used   : %s" % d.get("model"))
        print("     why          : %s" % d.get("why"))
        if d.get("text"):
            print("     would reply  : %s" % " ".join(str(d["text"]).split())[:200])
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
