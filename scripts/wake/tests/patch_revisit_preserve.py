#!/usr/bin/env python3
"""A blocked item must not have its revisit date pushed out by recording an observation.

MEASURED 2026-10-18, on a throwaway copy of the live ledger, item 337:

    before:  blocked  "MEASURED 2026-10-16: no human decider ex..."  revisit 2026-10-19T06:54:04Z
    $ work.py attempt 337 --by tester --did "recorded an observation only"
    after :  blocked  "MEASURED 2026-10-16: no human decider ex..."  revisit 2026-10-25T04:52:55Z

The state and the blocker survive (that was the previous patch), but `revisit_at` is recomputed:

    revisit_at = ((parse_revisit(getattr(a, "revisit", None)) or revisit_default())
                  if state == "blocked" else None)

so with no `--revisit` given it falls back to `revisit_default()` (+7 days) and OVERWRITES the date
that was already recorded. Every diagnostic note on a blocked item therefore delays the moment it is
looked at again by a week -- the block gets quieter each time somebody looks at it, which is the
opposite of what a revisit date is for.

THE FIX: when the item is blocked and no `--revisit` is supplied, keep the date it already had (and
fall back to the default only when it had none). An explicit `--revisit` still wins.

Idempotent, parse-checked.
"""
import ast
import io
import sys

P = "/root/bin/work.py"

OLD = '''    revisit_at = ((parse_revisit(getattr(a, "revisit", None)) or revisit_default())
                  if state == "blocked" else None)'''

NEW = '''    # MEASURED 2026-10-18: with no --revisit supplied this fell back to revisit_default() and
    # OVERWROTE the date already recorded, so every diagnostic note pushed a blocked item a week
    # further from being looked at again. Keep what the row already had; an explicit --revisit wins.
    if state == "blocked":
        revisit_at = (parse_revisit(getattr(a, "revisit", None))
                      or r["revisit_at"]
                      or revisit_default())
    else:
        revisit_at = None'''

src = io.open(P, encoding="utf-8").read()
if "pushed a blocked item a week" in src:
    print("ALREADY-PATCHED: nothing written")
    sys.exit(0)
if src.count(OLD) != 1:
    print("REFUSED: anchor found %d times" % src.count(OLD))
    sys.exit(2)
out = src.replace(OLD, NEW, 1)
try:
    ast.parse(out)
except SyntaxError as exc:
    print("REFUSED: would not parse: %s" % exc)
    sys.exit(3)
io.open(P, "w", encoding="utf-8").write(out)
print("WROTE %s  %d -> %d chars" % (P, len(src), len(out)))
