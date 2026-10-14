#!/usr/bin/env python3
"""test_card_due_watch.py — the load-bearing parts of card-due-watch.py.

WHAT THIS TEST IS ACTUALLY GUARDING
-----------------------------------
Not "does it run". The failure this tool exists to prevent is a CONFIDENT WRONG ANSWER
that reads as reassurance - and the first version of it emitted exactly that:

    "That covers the minimum."

for card ...9650, whose funding account held 72.47 against a 40.00 minimum - while the
autopay on that card actually took 2,380.06 and emptied the account. So the tests below
pin the three coverage bands with the real numbers from the 2026-10-11 overdraft, and pin
that an absent "Auto-pay enabled" flag is never turned into an autopay claim.

The snippets are verbatim from the Gmail search results read on 2026-10-14, not invented.

    python3 scripts/test_card_due_watch.py
"""

from __future__ import annotations

import importlib.util
import os
import sys
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
MODULE_PATH = os.path.join(HERE, "card-due-watch.py")

spec = importlib.util.spec_from_file_location("card_due_watch", MODULE_PATH)
cdw = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cdw)

FAILURES: list[str] = []


def check(label: str, got, want) -> None:
    if got != want:
        FAILURES.append(f"{label}\n     got: {got!r}\n    want: {want!r}")


# --------------------------------------------------------------- real snippets

S_9650 = ("Statement ready Your credit card statement is available online Account Chase "
          "Credit Card (...9650) Due date 10/11/2026 Minimum payment due $40.00 Statement "
          "balance $2965.33 Visit our Resource Center")

S_7542_AUTOPAY = ("Statement ready Your credit card statement is available Account Chase "
                  "Credit Card (...7542) Due date 10/22/2026 Minimum payment due $246.25 "
                  "Statement balance $5931.22 Auto-pay enabled You're set")

S_DEPOSIT = ("Statement ready Review your latest deposit statement Here are the details: "
             "Account (...9730) Your statement includes your recent transactions and may "
             "include important messages")

# --------------------------------------------------------------- parse tests

p = cdw.parse_statement(S_9650)
check("9650 card", p["card"], "9650")
check("9650 due", p["due"], "10/11/2026")
check("9650 minimum", p["minimum"], 40.00)
check("9650 statement", p["statement"], 2965.33)

p2 = cdw.parse_statement(S_7542_AUTOPAY)
check("7542 autopay flag present", p2["autopay_flag"], True)
check("7542 minimum", p2["minimum"], 246.25)

# The 9650 snippet carries NO autopay flag - and that card DOES have autopay. Absence must
# stay absence, never become "no autopay".
check("9650 autopay flag absent stays False", cdw.parse_statement(S_9650)["autopay_flag"],
      False)

# A deposit statement is not a card payment and must parse to None, not to a guess.
check("deposit statement -> None", cdw.parse_statement(S_DEPOSIT), None)
check("empty -> None", cdw.parse_statement(""), None)

check("due date parsed", cdw.parse_due("10/11/2026"), date(2026, 10, 11))
check("bad due date -> None", cdw.parse_due("not a date"), None)

# --------------------------------------------------------------- the three bands

FUNDING = {"account_id": "personal-checking",
           "label": "Chase checking ...9730 (the account named \"CHASE COLLEGE\")"}
BAL_72 = {"amount": 72.47, "captured_at": "2026-10-14T04:30:13.416339+00:00"}
DUE = date(2026, 10, 11)
INFO_9650 = {"minimum": 40.00, "statement": 2965.33}

# BAND 2 - the band that caused the incident. 72.47 beats the 40.00 minimum, so a naive
# check says "covered"; the real autopay was 2,380.06. It MUST warn.
mid = cdw.compose("9650", INFO_9650, FUNDING, BAL_72, DUE, 2)
check("band2 does not claim coverage", "That covers the minimum." in mid, False)
check("band2 says minimum only", "covers the minimum but NOT the statement balance" in mid,
      True)
check("band2 names the overdraw risk", ("overdraw" in mid) or ("returned" in mid), True)
check("band2 names the source account", "...9730" in mid, True)
check("band2 carries the balance", "72.47" in mid, True)

# BAND 1 - genuinely covered.
covered = cdw.compose("9650", INFO_9650, FUNDING, {"amount": 3000.0,
                                                   "captured_at": "2026-10-14T04:30:13Z"},
                      DUE, 2)
check("band1 covers statement", "covers the full statement balance" in covered, True)

# BAND 3 - short even of the minimum.
short = cdw.compose("9650", INFO_9650, FUNDING, {"amount": 10.0,
                                                 "captured_at": "2026-10-14T04:30:13Z"},
                    DUE, 2)
check("band3 warns", "NOT enough even for the minimum" in short, True)

# UNMAPPED - no funding account must not be answered with a guess.
unmapped = cdw.compose("5578", {"minimum": 273.83, "statement": 4692.89}, None, None, DUE, 2)
check("unmapped admits it", "cannot tell you" in unmapped, True)

# --------------------------------------------------------------- no dollar-sign pairs

# The Web GUI renders a pair of dollar signs in one paragraph as inline maths. Prose here
# is read on a phone, but the same rule applies to anything we write.
for name, body in (("band1", covered), ("band2", mid), ("band3", short),
                   ("unmapped", unmapped)):
    for para in body.splitlines():
        if para.count("$") >= 2:
            FAILURES.append(f"{name}: two dollar signs in one paragraph -> maths render: "
                            f"{para!r}")

# --------------------------------------------------------------- funding map

os.environ["CARD_DUE_FUNDING_MAP"] = os.path.join(HERE, os.pardir,
                                                  "settings", "finance",
                                                  "card-funding-accounts.tsv")
# Re-bind the module constant the reader uses.
cdw.FUNDING_MAP = os.path.abspath(os.environ["CARD_DUE_FUNDING_MAP"])
fmap = cdw.read_funding_map()
check("funding map 9650", fmap.get("9650", {}).get("account_id"), "personal-checking")
check("funding map 3929", fmap.get("3929", {}).get("account_id"), "lpt-boa-checking")
check("funding map 5578", fmap.get("5578", {}).get("account_id"), "lpt-boa-checking")
check("funding map 7542", fmap.get("7542", {}).get("account_id"), "lpt-boa-checking")
# Assert substance, not a row count: a count breaks every time a card is mapped, which
# trains the reader to edit the number instead of reading the failure. The real invariant
# is that a card with NO evidence is absent rather than defaulted to something plausible.
check("funding map does not invent a card", "8512" in fmap, False)
check("funding map only holds known cards",
      sorted(fmap.keys()), ["3929", "5578", "7542", "9650"])
# The label may contain spaces in both directions - the pipe format must survive them.
check("funding map label keeps spaces",
      "CHASE COLLEGE" in fmap.get("9650", {}).get("label", ""), True)

# --------------------------------------------------------------- result

if FAILURES:
    print(f"FAIL - {len(FAILURES)} check(s) failed\n")
    for f in FAILURES:
        print(f"  * {f}")
    sys.exit(1)

print("card-due-watch: all checks passed "
      "(parse 4 snippets, 3 coverage bands, dollar-sign discipline, funding map)")
