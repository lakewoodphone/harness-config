#!/usr/bin/env python3
"""test-capture-composer.py — a capture reaches the owner as ONE human sentence.

Measured in the owner's own `sms_log`:

    2026-10-16T15:33:04Z  "Remembered."
    2026-10-18T14:28:09Z  "Captured as a task."

The guard refused both correctly. This test proves the repair is at the composer: the
sentence names the act, the captured fact survives when it is clean, a path or a
credential ask falls back to the plain sentence, and the relay rescues the two bodies
already on the wire with the SAME words the sender would write.

RUN
    python3 test-capture-composer.py
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "mirror"))
import owner_text_relay as relay  # noqa: E402

OWNER = "+18483897895"


def main() -> int:
    failures: list[str] = []

    cases = [
        (("memory", "call the dentist tomorrow"),
         "I saved that to memory: call the dentist tomorrow."),
        (("task", "order the part"),
         "I added that to your task list: order the part."),
        (("memory", ""), "I saved that to memory."),
        (("task", ""), "I added that to your task list."),
        (("memory", "see docs/health/groin.md section 9"), "I saved that to memory."),
        (("task", "Give me the NJ Premier Business Services login"),
         "I added that to your task list."),
    ]
    for args, expect in cases:
        got = relay.compose_capture_reply(*args)
        if got != expect:
            failures.append("compose_capture_reply%r -> %r != %r" % (args, got, expect))
        if relay.internal_prose(got) is not None:
            failures.append("guard still refuses %r: %r"
                            % (got, relay.internal_prose(got)))
        if relay.credential_request(got) is not None:
            failures.append("credential guard refuses %r" % (got,))
        if got.count(".") != 1:
            failures.append("%r is not one sentence" % (got,))

    for raw, expect in (
        ("Remembered.", "I saved that to memory."),
        ("Captured as a task.", "I added that to your task list."),
    ):
        got, note = relay._rescue_reminder(raw, OWNER, "cron")
        if got != expect:
            failures.append("rescue %r -> %r != %r" % (raw, got, expect))
        if relay.internal_prose(got) is not None:
            failures.append("rescue still refused for %r" % (raw,))
        print("  %r -> %r  (%s)" % (raw, got, note))

    untouched = "Pay Yisroel Weinberg $597.29"
    got, note = relay._rescue_reminder(untouched, OWNER, "cron")
    if got != untouched or note is not None:
        failures.append("rescue touched a real message: %r / %r" % (got, note))

    if failures:
        print("RESULT: FAIL")
        for row in failures:
            print("  - %s" % row)
        return 1
    print("RESULT: PASS")
    print("  composer: %s" % relay.compose_capture_reply("memory", "call the dentist tomorrow"))
    print("  guard: internal_prose=None, credential_request=None")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
