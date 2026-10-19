#!/usr/bin/env python3
"""what-is-gate-error.py - 2,780 of 9,279 gate decisions are 'gate_error' and nobody has looked.

Found in round 1 of this programme and never explained: `owner_text_decision` holds ~2,780 rows with
code `gate_error` and allowed=0. A gate that ERRORS is supposed to fail open - so either these are
harmless refusals of the wrong shape, or a third of the gate's decisions have been made by an
exception path.

This reads the actual rows: when they happened, what `why`/`reason` they carry, and whether the
pattern is one bug or many.
"""
import sqlite3
from collections import Counter

c = sqlite3.connect("file:/root/authority.db?mode=ro", uri=True)
c.row_factory = sqlite3.Row

print("== every decision code, all time")
for r in c.execute("""select code, allowed, count(*) n from owner_text_decision
                      group by 1,2 order by n desc limit 12"""):
    print("   %-22s allowed=%s  %d" % (r["code"], r["allowed"], r["n"]))

print()
print("== gate_error: when?")
for r in c.execute("""select substr(created_at,1,7) m, count(*) n from owner_text_decision
                      where code='gate_error' group by 1 order by 1"""):
    print("   %s  %5d %s" % (r["m"], r["n"], "=" * min(r["n"], 40)))

print()
print("== gate_error: what do they say?")
for r in c.execute("""select coalesce(why,'(null)') w, coalesce(reason,'(null)') rn, count(*) n
                      from owner_text_decision where code='gate_error'
                      group by 1,2 order by n desc limit 8"""):
    print("   %-40s | %-30s %d" % (str(r["w"])[:40], str(r["rn"])[:30], r["n"]))

print()
print("== newest five gate_error rows in full")
for r in c.execute("""select created_at, why, reason, urgency, chars, body_head
                      from owner_text_decision where code='gate_error'
                      order by created_at desc limit 5"""):
    print("   %s why=%r reason=%r" % (r["created_at"][:19], r["why"], r["reason"]))
    print("      head: %s" % (r["body_head"] or "")[:80])
