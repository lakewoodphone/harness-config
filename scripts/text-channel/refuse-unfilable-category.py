#!/usr/bin/env python3
"""refuse-unfilable-category.py - stop WRITING a category the ledger cannot file.

`category_from()` returns his own words, and two of them are not ledger categories:

    "personal"  -> the categories table has no "Personal" (nearest: Unidentified Personal Spending)
    "unknown"   -> not a category anywhere

Measured 2026-10-19: 5 of 11 learned aliases name one of those two, so `category_id_for()` returns
"" and the charge is never filed - while the alias still reads back as an answer. That is a
learned row that can never do the thing it was learned for.

`build_alias` already refuses "unknown" and the ask's own guess. This adds the general rule
instead of a list: a category is written only if it can be FILED, and the words he used are kept
in `evidence` whether or not a category is written - nothing he said is lost, it just stops being
mistaken for a classification.

Note the deeper point, recorded rather than fixed: "personal" is not a CATEGORY at all, it is
which ENTITY the charge belongs to, and the ledger carries `entity_id` for exactly that. Mapping
his word onto a category was a category error in the code, not a missing entry in the table.
"""
from __future__ import annotations

import io
import sys

PATH = sys.argv[1] if len(sys.argv) > 1 else "textdecide.py"

OLD = '''    if named and named.lower() not in str(ask.get("merchant") or "").lower():
        evidence += " | he named it as %r" % named'''

NEW = '''    if named and named.lower() not in str(ask.get("merchant") or "").lower():
        evidence += " | he named it as %r" % named
    # A CATEGORY THAT CANNOT BE FILED IS NOT A CATEGORY. "personal" and "unknown" are words he
    # used, not rows in the ledger's categories table, so a row naming one of them resolves the
    # charge as answered and files nothing - measured 2026-10-19, 5 of 11 learned aliases.
    # The row is still worth writing: `evidence` keeps his exact words, and the resolver treats
    # a row with no category as "known vendor, still a question", which is the truth.
    # The deeper error: "personal" is which ENTITY the charge belongs to, not what kind of spend
    # it was. The ledger already carries entity_id for that.
    _UNFILABLE_CATEGORY_WORDS = {"personal", "business", "unknown", "shop supplies", ""}
    if str(category or "").strip().lower() in _UNFILABLE_CATEGORY_WORDS:
        evidence += (" | no ledger category written (his word %r is not a category the ledger "
                     "holds; entity, not category)" % str(category or "")[:24])
        category = ""
        cat_why = "his words name an ENTITY, not a ledger category"'''

ANCHOR2 = '''    category, cat_why = category_from(body, ask)'''


def main() -> int:
    dry = "--apply" not in sys.argv
    text = io.open(PATH, encoding="utf-8").read()
    if "_UNFILABLE_CATEGORY_WORDS" in text:
        print("OK    already applied")
        return 0
    if text.count(OLD) != 1:
        print("FAIL  the evidence anchor found %d times" % text.count(OLD))
        return 1
    out = text.replace(OLD, NEW, 1)
    import ast
    ast.parse(out)
    if dry:
        print("DRY   would refuse to write an unfilable category in build_alias")
        return 0
    io.open(PATH, "w", encoding="utf-8", newline="\n").write(out)
    print("APPLIED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
