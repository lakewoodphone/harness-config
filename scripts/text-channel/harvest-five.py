#!/usr/bin/env python3
"""harvest-five.py - five learned rows name a category the ledger cannot file. Correct them from
his OWN sentences, with the sentence and the sid on every row.

MEASURED 2026-10-19. The alias store holds 11 rows; 5 carry the category "personal" or "unknown",
neither of which is a row in the ledger's 137 categories, so `category_id_for()` returns "" and the
charge is never filed - while the alias still reads back as an answer. That is the shape of the
whole complaint: something was "learned" and nothing improved.

He had already said what each one was, in writing:

  pass                         -> Parking & Tolls   "It looks like easy pass to me and that's just
                                                     from your text."  (2026-10-18T05:45:28Z,
                                                     sid SM3f52cd409573d2027c060d1438aa73fe)
  american professional        -> Insurance         "it's her yearly liability insurance to be a
                                                     therapist in doctorate school"
                                                     (2026-10-08T00:15:03Z, sid SM303c78ff05...)
  pocono whitewater            -> Travel            "The $107 one by the Poconos was a holiday
                                                     biking trip me and my wife"
                                                     (2026-10-05T01:09:19Z, sid SMf1e9f57a04...)
  aplpay dave busterfreehold nj -> Entertainment    "it looks like it's Dave and Buster's, which is
                                                     an arcade place ... it was probably a date"
                                                     (2026-10-18T14:03:31Z, sid SM60389b3619...)
  color me mine tomstoms river nj -> Entertainment  "I went there on a date with my wife before we
                                                     got married. It's pottery painting."
                                                     (2026-10-19T01:25:37Z, sid SMcb77020642...)

WHY THIS IS NOT MY INFERENCE. A ledger category names the KIND of spend, not whether it is
deductible - the accounting database files personal charges too, and `entity_id` is what carries
personal vs business. A toll is a toll, liability insurance is insurance, a biking trip is travel,
an arcade and a pottery studio are entertainment. Each row quotes the sentence it came from, and
every one of those sentences is his.

Dry-run by default. --apply writes.
"""
from __future__ import annotations

import sqlite3
import sys

ALIASES = "/root/.cfo-asks/aliases.db"
ACCT = "/root/accounting-data/live/accounting.db"

ROWS = [
    ("pass", "Parking & Tolls",
     "owner answered 2026-10-18 (sid SM3f52cd409573d2027c060d1438aa73fe): "
     "\"Are you serious? It looks like easy pass to me and that's just from your text.\" "
     "| merchant_key=pass | entity=E-ZPass | category=Parking & Tolls (he named it: easy pass)"),
    ("american professional", "Insurance",
     "owner answered 2026-10-08 (sid SM303c78ff05d965818538cdefbd5cce12): \"he told me that it's "
     "her yearly liability insurance to be a therapist in doctorate school\" | confirmed "
     "2026-10-15 (sid SM7b00d15c0c41315b58097a9d08d8248a) | merchant_key=american professional "
     "| entity=American Professional | category=Insurance (he named the instrument)"),
    ("pocono whitewater", "Travel",
     "owner answered 2026-10-05 (sid SMf1e9f57a04a1b97d9932f534aef56c7a): \"The $107 one by the "
     "Poconos was a holiday biking trip me and my wife\" | confirmed 2026-10-14 (sid "
     "SMe049294ebe74b45874385cff841c64bf) | merchant_key=pocono whitewater | entity=Pocono "
     "Whitewater | category=Travel (a trip)"),
    ("aplpay dave busterfreehold nj", "Entertainment",
     "owner answered 2026-10-18 (sid SM60389b3619dacb5af71d1192d86050e8): \"it looks like it's "
     "Dave and Buster's, which is an arcade place ... it was probably a date\" | "
     "merchant_key=aplpay dave busterfreehold nj | entity=Dave & Buster's | "
     "category=Entertainment (an arcade)"),
    ("color me mine tomstoms river nj", "Entertainment",
     "owner answered 2026-10-19 (sid SMcb770206429dcdc35472300f3c6771ca): \"I went there on a "
     "date with my wife before we got married. It's pottery painting.\" | merchant_key=color me "
     "mine tomstoms river nj | entity=Color Me Mine | category=Entertainment (pottery painting)"),
]


def main() -> int:
    dry = "--apply" not in sys.argv
    a = sqlite3.connect("file:%s?mode=ro" % ACCT, uri=True)
    known = {(r[0] or "").lower() for r in a.execute("select name from categories")}
    a.close()

    c = sqlite3.connect(ALIASES)
    print("alias store %s" % ALIASES)
    print()
    planned = []
    for key, category, evidence in ROWS:
        row = c.execute("select merchant_key, entity, category from alias where merchant_key=?",
                        (key,)).fetchone()
        if not row:
            print("  SKIP  %-32s no alias row exists (not learned yet)" % key[:32])
            continue
        if category.lower() not in known:
            print("  FAIL  %-32s %r is not a ledger category - refusing" % (key[:32], category))
            return 1
        print("  %-32s %r -> %r" % (key[:32], row[2], category))
        planned.append((key, category, evidence))
    print()
    if dry:
        print("DRY RUN: %d row(s) would be corrected. Re-run with --apply." % len(planned))
        c.close()
        return 0
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        for key, category, evidence in planned:
            c.execute("update alias set category=?, evidence=?, learned_at=? "
                      "where merchant_key=?", (category, evidence, now, key))
        c.commit()
    finally:
        c.close()
    print("APPLIED: %d row(s) corrected" % len(planned))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
