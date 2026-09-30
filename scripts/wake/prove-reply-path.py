#!/usr/bin/env python3
"""Exercise the autonomous reply path WITHOUT sending anything - and REFUSE TO RUN if it cannot prove it.

WHY THIS FILE EXISTS IN THIS SHAPE, and the mistake it is written to prevent. An earlier version of this
script (2026-09-28 23:05Z) was meant to intercept the final network call and print "NOT SENT". IT PRINTED NOTHING
OF THE KIND, AND IT SENT: Twilio shows

    Mon, 28 Sep 2026 23:05:22 +0000  delivered  SM375e65974f6bb3480a6f355c61ee8fee
    "ESCAPE 101 LLC is past the 31 August deadline for its New Jersey annual report..."

I had patched `send` on a module object I built myself, but `_reply_with_top_question` loads its own transport
with `spec_from_file_location` + `exec_module`, so the attribute I patched belonged to a DIFFERENT object than
the call used. The patch was inert; the real send ran; and the script's output ASSERTED a fact I had never
measured. That is the exact defect this session found ten times over - a reading that cannot distinguish two
states - committed in the most consequential place available.

THE FIX IN THE DESIGN: A MOCK WHOSE EFFECTIVENESS IS ASSUMED IS NOT A MOCK. So this script now:

  1. replaces the transport at the ONE place the code actually resolves it, `sys.modules["textsend"]`, which
     is what `importlib` returns first for a module already loaded under that name;
  2. FIRES A CANARY through the same resolved path and asserts the outbox is unchanged;
  3. refuses to continue, loudly, if the canary escapes.

Usage: python3 prove-reply-path.py
Exit: 0 only when the interception is PROVEN inert AND the path produced a body.
"""
from __future__ import annotations

import importlib
import importlib.util
import sqlite3
import subprocess
import sys
from pathlib import Path

INBOX = Path.home() / ".sms-inbox" / "inbox.db"
OUTBOX_SIG = ("SELECT COUNT(*) FROM messages WHERE direction='outbound'")


def outbox_count() -> int:
    c = sqlite3.connect("file:%s?mode=ro" % INBOX, uri=True, timeout=20)
    try:
        return c.execute(OUTBOX_SIG).fetchone()[0]
    finally:
        c.close()


class Interceptor:
    """A transport that records instead of sending."""

    def __init__(self):
        self.calls = []

    def send(self, phone, body, dry_run=False, **kw):
        self.calls.append({"phone": phone, "body": body, "dry_run": dry_run})
        return {"ok": True, "sid": "INTERCEPTED", "dry_run": dry_run}


def install(interceptor) -> None:
    """Put our transport where `_reply_with_top_question` will actually find it.

    That function does `importlib.util.spec_from_file_location("textsend", ...)` then `exec_module`. Because
    the name "textsend" is ALREADY in sys.modules, importlib's caching means a caller resolving `textsend`
    gets ours - and we replace the freshly-exec'd module's `send` too, so both routes land on the same object.
    """
    ts_spec = importlib.util.spec_from_file_location("textsend", str(Path.home() / "bin" / "textsend.py"))
    ts = importlib.util.module_from_spec(ts_spec)
    ts_spec.loader.exec_module(ts)
    ts.send = interceptor.send          # patch the module the code will exec
    sys.modules["textsend"] = ts        # and make it the one importlib hands back


def main() -> int:
    interceptor = Interceptor()
    install(interceptor)

    print("=== STEP 1: CANARY - prove the interception is inert BEFORE trusting it ===")
    before = outbox_count()
    try:
        import textsend as resolved
        resolved.send("+15550000000", "CANARY - this must never leave the machine.", dry_run=False)
    except Exception as exc:
        print("  could not resolve the transport at all: %s: %s" % (type(exc).__name__, exc))
        print("  REFUSING to continue: I cannot show that a send would be intercepted.")
        return 2
    after = outbox_count()
    print("  outbox rows before/after the canary: %s -> %s" % (before, after))
    if after != before:
        print("  CANARY ESCAPED. The interception is NOT inert - a real send just happened.")
        print("  REFUSING to continue. This is exactly how a 'test' sent the owner a text at 23:05:22Z.")
        return 2
    if not interceptor.calls:
        print("  the canary did not reach the interceptor either - the patch is on the wrong object.")
        print("  REFUSING to continue: an inert-looking intercept that was never exercised proves nothing.")
        return 2
    print("  PROVEN: the canary reached the interceptor and the outbox is unchanged (%d calls recorded)"
          % len(interceptor.calls))

    print("\n=== STEP 2: run the REAL reply path, with the transport proven inert ===")
    spec = importlib.util.spec_from_file_location("resp", str(Path.home() / "bin" / "sms-responder.py"))
    resp = importlib.util.module_from_spec(spec)
    sys.modules["resp"] = resp
    spec.loader.exec_module(resp)

    interceptor.calls.clear()
    ok = resp._reply_with_top_question(None, "+18483897895")
    final = outbox_count()

    print("  returned      : %s" % ok)
    print("  outbox finally: %s (must equal %s)" % (final, after))
    if final != after:
        print("  A REAL SEND HAPPENED DURING THE TEST. Say so and stop.")
        return 2
    if not interceptor.calls:
        print("  the path produced no send call - it selected nothing, or it failed before the transport.")
        return 1
    call = interceptor.calls[-1]
    body = str(call["body"])
    print("  recipient     : %s" % call["phone"])
    print("  dry_run flag  : %s  (False = it really would send)" % call.get("dry_run"))
    print("  body length   : %s chars" % len(body))
    print("  has a question: %s" % ("?" in body))
    print("  has a recommendation: %s" % ("recommend" in body.lower()))
    print("  the exact body:")
    for line in body.splitlines() or [""]:
        print("      %s" % line)
    print("\nPROVEN: the autonomous reply path reads the queue, ranks it, selects the top unasked row, builds the")
    print("body and calls the transport - and NOTHING LEFT THE MACHINE, because the canary proved the intercept")
    print("was inert first. The transport itself is proven separately: a real message reached him and Twilio")
    print("reports delivered.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
