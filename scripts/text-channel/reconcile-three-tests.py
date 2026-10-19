#!/usr/bin/env python3
"""reconcile-three-tests.py - three assertions that encode the OLD contract.

The behaviour change is deliberate, so the tests that pin the old behaviour must move with it,
and each must be moved to pin the NEW contract exactly rather than simply relaxed:

1. test-merchant-honesty case 13: "every descriptor category is a real ledger category". The guard
   holds a hardcoded set of the categories it believes the ledger has. Two new rules emit
   "Cash Withdrawals" and "Online Marketplace Purchases", which ARE in the ledger (14+2 and 79+5
   filings, verified) - so the guard's set gains them. The guard stays exactly as strict.

2. test-cfo-question "a reversal reading is never enough": `resolved_enough` used to refuse any
   `purchase is False`. It now refuses `provisional` instead, because a DEFINITE reversal is a
   complete answer and asking about it is the complaint. The assertion becomes: a definite
   reversal (provisional False) IS enough, and a PROVISIONAL reading is NOT - which is stricter
   where it matters and looser exactly where the behaviour changed.

3. test-ladder-end-to-end "a reversal is never resolved enough": same change, same correction.
"""
from __future__ import annotations

import io
import sys

BASE = "."


def patch(path, old, new, label):
    text = io.open(path, encoding="utf-8").read()
    if new in text:
        print("OK    %s already updated" % label)
        return 0
    if text.count(old) != 1:
        print("SKIP  %s: anchor found %d times" % (label, text.count(old)))
        return 1
    io.open(path, "w", encoding="utf-8", newline="\n").write(text.replace(old, new, 1))
    print("PATCHED %s" % label)
    return 0


if __name__ == "__main__":
    dry = "--apply" not in sys.argv
    if dry:
        print("DRY: would patch three test expectations")
        raise SystemExit(0)

    rc = patch(
        "test-merchant-honesty.py",
        '        "Groceries", "Insurance", "Fees & Adjustments"}',
        '        "Groceries", "Insurance", "Fees & Adjustments",\n'
        '        # verified present in the ledger 2026-10-19: 14+2 and 79+5 filings\n'
        '        "Cash Withdrawals", "Online Marketplace Purchases"}',
        "test-merchant-honesty case 13 (two real category names)")

    rc |= patch(
        "test-cfo-question.py",
        '    check("a reversal reading is never enough", not ca.resolved_enough(rev), rev)',
        '    # A DEFINITE reversal IS an answer: "crdt rvsd" says card credit reversed, there is\n'
        '    # nothing to ask, and asking about a refund he already explained is the complaint.\n'
        '    # What must still block is AMBIGUITY, which is what `provisional` means now.\n'
        '    check("a definite reversal is enough", ca.resolved_enough(rev), rev)\n'
        '    check("a provisional reading is never enough",\n'
        '          not ca.resolved_enough(dict(rev, provisional=True)), rev)',
        "test-cfo-question reversal check")

    rc |= patch(
        "test-ladder-end-to-end.py",
        '    check("a reversal is never \'resolved enough\'", CA.resolved_enough(rev), False)',
        '    check("a definite reversal IS enough (asking about a refund is the complaint)",\n'
        '          CA.resolved_enough(rev), True)',
        "test-ladder reversal check")
    raise SystemExit(rc)
