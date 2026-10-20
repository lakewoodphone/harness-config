#!/usr/bin/env python3
"""test-reminder-composer.py — a reminder reaches the owner as ONE human sentence.

The measured body is in the owner's own `sms_log` (2026-10-10 07:02:16Z, sid
SM4ccdef6b41dc8a83a72a07871ac4f48d):

    ⏰ Reminder: VS Code session: present ONE numbered owner-approval ask — (1) #27836 ...

The guard refused it correctly. This test proves the repair is at the composer: the
substance survives, the paths/ids/agent imperatives do not, and the result is one
sentence that the guard accepts.

RUN
    python3 test-reminder-composer.py
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "mirror"))
import owner_text_relay as relay  # noqa: E402

RAW = (
    "VS Code session: present ONE numbered owner-approval ask \u2014 "
    "(1) #27836 SD-card SMS, (2) #27745 Rubin SMS, "
    "(3) #27907 Global Direct Parts email (dispute window closes 2026-10-16), "
    "(4) #27888 Seedr. Owner answers numbered lists, not digests."
)
OWNER = "+18483897895"


def main() -> int:
    failures: list[str] = []

    body, note = relay.compose_reminder_sentence(RAW)
    expect = ("Four things need your approval: SD-card SMS, Rubin SMS, "
              "Global Direct Parts email (dispute window closes 2026-10-16) and Seedr.")
    if body != expect:
        failures.append("composer body %r != %r" % (body, expect))
    for banned in ("#27836", "#27745", "#27907", "#27888", "present ONE numbered",
                   "VS Code session", "Owner answers numbered lists"):
        if banned in body:
            failures.append("composer kept %r" % banned)
    if body.count(".") != 1:
        failures.append("composer emitted %d sentences: %r" % (body.count("."), body))
    if relay.internal_prose(body) is not None:
        failures.append("guard still refuses the composed body: %r"
                        % relay.internal_prose(body))

    rescued, rescue_note = relay._rescue_reminder("\u23f0 Reminder: " + RAW, OWNER, "app.reminder")
    if rescued != expect:
        failures.append("rescue body %r != %r" % (rescued, expect))
    if relay.internal_prose(rescued) is not None:
        failures.append("guard still refuses the rescued body: %r"
                        % relay.internal_prose(rescued))

    plain = "Pay Yisroel Weinberg $597.29 net CASH settlement"
    kept, _ = relay.compose_reminder_sentence(plain)
    if kept != plain + ".":
        failures.append("a plain reminder was mangled: %r" % (kept,))

    if failures:
        print("RESULT: FAIL")
        for row in failures:
            print("  - %s" % row)
        return 1
    print("RESULT: PASS")
    print("  composer: %s" % body)
    print("  note: %s" % note)
    print("  rescue: %s" % rescue_note)
    print("  guard: internal_prose=None, credential_request=%r"
          % (relay.credential_request(body),))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
