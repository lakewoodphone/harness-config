#!/usr/bin/env python3
"""more-definitional-descriptors.py - three tokens that name their own kind of charge.

Measured 2026-10-19 against the 48 distinct merchants in the unresolved ask tail: 23 are filable,
12 are identified-but-uncategorised, **13 are unsolved**. Three of those 13 say what they are in
the descriptor itself, which is exactly the condition the descriptor rung exists for:

    dda withdraw tw04c379      the descriptor says WITHDRAW   -> Cash Withdrawals
    cdd:crdt rvsd case         "card credit reversed"          -> Fees & Adjustments, a reversal
    ebay commerce              eBay is a marketplace, by name  -> Online Marketplace Purchases

Every target name verified present in the ledger (cash withdrawals 14+2 filings, fees &
adjustments 237, online marketplace purchases 79+5).

NOT added, deliberately, because the token does not name a KIND and the rule would be my guess
about his money: `sel sel ppd` (5,877.19 - unknown), `paypal bilgala` (a person), `tequipment`,
`amp photo`, `betckey labels`, `bais medrash east fifth`, `chemed`, `conduent state local
solutions`, and `adjust membership fee` (ambiguous by construction - still asked on purpose).
"""
from __future__ import annotations

import io
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

PATH = Path(sys.argv[1] if len(sys.argv) > 1 else "/root/bin/merchant_resolve.py")

OLD = '''    {"category": "Fees & Adjustments", "purchase": False, "tokens": (
        "refund", "adjustment", "adjust", "adj")},
)'''

NEW = '''    {"category": "Fees & Adjustments", "purchase": False, "tokens": (
        "refund", "adjustment", "adjust", "adj")},
    # THE DESCRIPTOR NAMES THE KIND OF CHARGE, which is the only condition this rung may fire on.
    # All three were unsolved against the 48-merchant tail measured 2026-10-19; every target name
    # is verified present in the ledger. Tokens are chosen so they cannot appear inside an
    # unrelated word (WITHDRAW, RVSD/CRDT, EBAY), never a brand guessed from context.
    {"category": "Cash Withdrawals", "tokens": ("withdraw", "withdrawal", "withdrawl", "atm")},
    {"category": "Fees & Adjustments", "purchase": False, "tokens": (
        "crdt rvsd", "rvsd", "crdt", "reversal", "reversed", "chargeback")},
    {"category": "Online Marketplace Purchases", "tokens": ("ebay", "etsy", "mercari")},
)'''


def main() -> int:
    dry = "--apply" not in sys.argv
    text = PATH.read_text(encoding="utf-8")
    if "Cash Withdrawals\", \"tokens\"" in text:
        print("OK    already applied")
        return 0
    if text.count(OLD) != 1:
        print("FAIL  descriptor table tail found %d times" % text.count(OLD))
        return 1
    out = text.replace(OLD, NEW, 1)
    import ast
    try:
        ast.parse(out)
    except SyntaxError as exc:
        print("FAIL  does not parse: %s" % exc)
        return 1
    if dry:
        print("DRY   would add Cash Withdrawals, the reversal tokens, and eBay")
        return 0
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    shutil.copy2(PATH, PATH.with_suffix(PATH.suffix + ".bak-moredesc-" + stamp))
    tmp = PATH.with_suffix(PATH.suffix + ".new")
    tmp.write_text(out, encoding="utf-8")
    rc = subprocess.run([sys.executable, "-c",
                         "import ast,sys;ast.parse(open(sys.argv[1],encoding='utf-8').read())",
                         str(tmp)], capture_output=True)
    if rc.returncode != 0:
        print("FAIL  tmp does not parse: %s" % rc.stderr.decode()[:300])
        tmp.unlink(missing_ok=True)
        return 1
    tmp.replace(PATH)
    print("APPLIED %s" % PATH)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
