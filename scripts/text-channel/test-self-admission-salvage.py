#!/usr/bin/env python3
"""The promise-salvage must not send the apology it was wrapped in.

WHY THIS TEST EXISTS
--------------------
`textsend.classify_owner_body` drops a promise-only sentence and sends the rest. On
2026-10-18 the rest was:

    "You're right - I was asking you for something I should have found myself.
     Let me actually dig."

The promise was dropped correctly; the apology was then admitted as a RESULT
(`reported_fact`, 58 chars, three words) and reached the owner. It asks nothing and
reports no outcome, so he ignored it -- and the scorecard named its four-word family
`asking something should found` as the worst LIVE family on 2026-10-20. The same defect
delivered two more bodies on 2026-10-12.

WHAT IS PROVEN
--------------
1. An admission-only body is refused WHOLE (no leftover on the phone).
2. A real answer wrapped in the same promise still sends its core.
3. An apology followed by a question sends the question -- the apology is the receipt,
   the question is the message.
4. A result carrying a specific is untouched: "You're right - the $58 ... closed."

Run:
    python3 scripts/text-channel/test-self-admission-salvage.py
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
MIRROR = HERE / "mirror" / "textsend.py"
sys.path.insert(0, str(MIRROR.parent))

_spec = importlib.util.spec_from_file_location("textsend_self_admission_test", MIRROR)
textsend = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(textsend)

CHECKS = []


def check(name, got, want):
    ok = got == want
    CHECKS.append((name, ok, got, want))
    print(("PASS  " if ok else "FAIL  ") + name)
    if not ok:
        print("      got  %r" % (got,))
        print("      want %r" % (want,))


#: The three bodies that reached him and did no work (distinct provider sids,
#: 2026-10-12 13:39Z, 2026-10-12 16:25Z, 2026-10-18 05:46Z).
DEAD = [
    "You're right - I was asking you for something I should have found myself. "
    "Let me actually dig.",
    "You did tell me - and I should have caught it. "
    "Let me verify the actual state instead of re-asking you.",
    "You're right - you told me, and I should have it. "
    "Let me check what's actually recorded before I say anything else.",
]

for i, body in enumerate(DEAD, 1):
    v = textsend.classify_owner_body(body)
    check("dead body %d is refused whole" % i, v["refused"], True)
    check("dead body %d sends nothing" % i, v.get("send_body"), None)
    check("dead body %d is named NOISE" % i, v["cls"], textsend.CLASS_NOISE)

# The already-salvaged row from the scorecard's family, handed over on its own.
v = textsend.classify_owner_body(
    "I was asking you for something I should have found myself.")
check("standalone admission is refused", v["refused"], True)
check("standalone admission sends nothing", v.get("send_body"), None)

# A real answer inside the same promise shape must survive.
v = textsend.classify_owner_body(
    "Got it - that dress purchase is personal, not business. "
    "Let me pull the Amazon card details now.")
check("real answer inside a promise is kept", v.get("send_body"),
      "that dress purchase is personal, not business.")

# A result carrying a specific is not an admission.
body = ("You're right - the $58 Dave & Buster's charge is closed. "
        "Your mom's card, no action.")
v = textsend.classify_owner_body(body)
check("a result with a specific is untouched", v["refused"], False)
check("a result with a specific keeps its body", v.get("send_body"), body)

# An apology before a question: drop the apology, send the question.
v = textsend.classify_owner_body(
    "You're right, I was wrong. Should I cancel the Audible membership?")
check("the apology is dropped", v["refused"], True)
check("the question is what goes out", v.get("send_body"),
      "Should I cancel the Audible membership?")

# An admission followed by a result keeps the result.
v = textsend.classify_owner_body(
    "You're right - I was asking. The $58 charge is closed.")
check("admission + result keeps the result", v.get("send_body"),
      "The $58 charge is closed.")

# A promise alone is still refused.
v = textsend.classify_owner_body("Let me actually dig.")
check("a promise alone is still refused", v.get("send_body"), None)

# A clean result is unchanged.
body = "The $58 charge is closed and the card ending 4258 needs no action."
v = textsend.classify_owner_body(body)
check("a clean result is unchanged", v.get("send_body"), body)

failed = [name for name, ok, _g, _w in CHECKS if not ok]
print()
if failed:
    print("RESULT: FAIL (%d of %d checks failed)" % (len(failed), len(CHECKS)))
    for name in failed:
        print("  - " + name)
    raise SystemExit(1)
print("RESULT: PASS (%d checks)" % len(CHECKS))
