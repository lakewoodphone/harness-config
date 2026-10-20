#!/usr/bin/env python3
"""test-credential-ask-composer.py - a credential ask becomes one human question.

The gate refuses a body that asks the owner for a credential (rule 1g). For a
reminder that is a deletion: the NJ tax returns and the library count were real
work, and suppressing the ask removed the reminder with it. This test pins the
composer repair on the three measured bodies:

  * 2026-10-08 library  "Send me the barcode and password ..."
  * 2026-10-16 NJ payroll "Give me the NJ Premier Business Services login ..."
  * 2026-10-17 NJ sales   "Give me the NJ Premier Business Services login ..."

BEFORE: the guard refuses all three, and the pager either forwards the ask or
drops the item because it carries no question.
AFTER: the relay and the pager both write one sentence that keeps the subject
and asks him to restore access - no credential noun, no path, no task id, no
agent instruction.

Read-only. Imports the LIVE files, so a pass is evidence about what is running.
"""
from __future__ import annotations

import importlib.util
import os
import sys

RELAY = os.environ.get("OWNER_TEXT_RELAY", "/root/bin/owner_text_relay.py")
PAGER = os.environ.get("OWNER_TEXT_PAGER", "/opt/company/scripts/owner_attention.py")
OWNER = os.environ.get("OWNER_PHONE_NUMBER", "+18483897895")

MEASURED = [
    ("2026-10-08 library",
     "The collector's letter has no item list in it \u2014 just the one lump $487.32 "
     "\u2014 and nothing in our files has a count either. The count is on your library "
     "account under Fines & Fees, or the branch can read it off when you drop them. "
     "Send me the barcode and password and I'll pull the exact list and count.\n\n- Daniel"),
    ("2026-10-16 NJ payroll",
     "NJ payroll returns have no filer since Gusto was cancelled on 8 October \u2014 "
     "Give me the NJ Premier Business Services login and I will file 06/2026 now and "
     "09/2026 before 30 October, and settle the employer account number first so the "
     "right number goes on the return. Yes?"),
    ("2026-10-17 NJ sales tax",
     "The NJ sales tax return for Q3 2026, form ST-50 \u2014 Give me the NJ Premier "
     "Business Services login (user id TU01100696163) and I will file the Q3 2026 "
     "ST-50 as a 25,671.84 gross-receipts return with 1,700.76 of tax, then read the "
     "confirmation back to you. Yes?"),
]

#: A delivered sentence must not contain any of these. They are the exact shapes
#: the guards refuse plus the machine debris the measured bodies carried.
FORBIDDEN = ("login", "password", "passcode", "user id", "userid", "api key",
             "one-time code", "otp", "2fa", "data/owner-attention", "full:",
             "task #", " wo", "branch ", "- daniel", "execute:", "do not",
             "present one")


def load(name: str, path: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def main() -> int:
    relay = load("relay_live", RELAY)
    pager = load("pager_live", PAGER)
    checks = 0

    def check(ok, msg):
        nonlocal checks
        checks += 1
        if not ok:
            raise AssertionError(msg)

    refused_before = 0
    pager_before = 0
    for label, body in MEASURED:
        # What the live guards say about the body that was actually delivered.
        before = relay.internal_prose(body) or relay.credential_request(body)
        if before:
            refused_before += 1
        # What the old pager would have produced from the same digest item.
        budget = pager.OWNER_SMS_MAX - len(pager.PAGER_INSTRUCTION) - 1
        question = pager._first_question(body, budget)
        old_body = ((question + "\n" + pager.PAGER_INSTRUCTION)[:pager.OWNER_SMS_MAX]
                    if "?" in question else "")
        if not old_body or relay.internal_prose(old_body) or relay.credential_request(old_body):
            pager_before += 1

        new, note = relay._rescue_reminder(body, OWNER, "cron")
        check(new != body, "%s: relay did not rewrite the body" % label)
        check("credential" in (note or "").lower(),
              "%s: rescue note does not name the credential class" % label)
        check(relay.credential_request(new) is None,
              "%s: rewrite still asks for a credential" % label)
        check(relay.internal_prose(new) is None,
              "%s: rewrite still reads as internal prose" % label)
        check(new.rstrip().endswith("?"), "%s: rewrite does not end in a question" % label)
        check(new.count("?") == 1, "%s: rewrite is not exactly one question" % label)
        check(12 <= len(new) <= relay.MAX_CHARS, "%s: rewrite length %d" % (label, len(new)))
        for bad in FORBIDDEN:
            check(bad not in new.lower(), "%s: rewrite contains %r" % (label, bad))

        # The pager must SEND the reminder, not skip it before the gate sees it.
        out = pager._compose_one("  1. [high] " + body)
        check(bool(out), "%s: pager dropped the reminder" % label)
        check(out.count("?") == 1, "%s: pager body is not one question" % label)
        check(pager.PAGER_INSTRUCTION in out, "%s: pager body lost the reply instruction" % label)
        check(relay.credential_request(out) is None, "%s: pager body asks for a credential" % label)
        check(relay.internal_prose(out) is None, "%s: pager body reads as internal prose" % label)
        for bad in FORBIDDEN:
            check(bad not in out.lower(), "%s: pager body contains %r" % (label, bad))
        print("OK  %-22s -> %s" % (label, new))

    # A status report, a statement that PROVIDES a secret, and a task for us are
    # not asks. Rewriting any of them would lose a real message.
    for control in ("The login page is broken and I cannot file the return.",
                    "Your password is on the desk.",
                    "Can you reset the password?"):
        out, _note = relay._rescue_reminder(control, OWNER, "cron")
        check(out == control, "control was rewritten: %r" % control)
        check(relay.credential_request(control) is None,
              "control was misclassified as a credential ask: %r" % control)

    question = "Should the company's agent work move out of DeepSeek's peak-price window?"
    out, _note = relay._rescue_reminder(question, OWNER, "cron")
    check(out == question, "a real question was rewritten")

    print("BEFORE  %d/3 measured bodies refused by the guards; pager would skip or "
          "the gate refuse %d/3" % (refused_before, pager_before))
    print("AFTER   0/3 refused; 3/3 delivered as one question, no credential, no path")
    print("RESULT: PASS (%d checks)" % checks)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
