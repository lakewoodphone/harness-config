#!/usr/bin/env python3
"""Stop reporting a YEAR as an unresolved owner-queue reference.

MEASURED 2026-10-18, `work.py lint-refs`:

    UNRESOLVED-REF item 522 (housekeeping, blocked) -> title/why names owner-queue #2026,
    which does NOT exist in the queue; not a link - probably a year or a task id
    lint-refs: 1 orphan prose reference(s) across 140 live item(s)

The tool already knows it is "probably a year" and reports it anyway, every 15 minutes, into the
sources log. That is how a log gets ignored: a finding that can never be acted on trains the reader
to stop reading. Same class as the 245-of-245 `loop-stall UNUSABLE` lines retired in doc section 59.

THE FIX: a reference in the year band (1900-2100) is not an owner-queue id. The queue holds ~554
rows, so a real row cannot yet collide with a year, and when it eventually can this line will say so.
Filtering is applied only in the ORPHAN path -- `_stale_oq_refs` needs the row to EXIST before it can
be stale, so a year cannot reach it.

Idempotent, parse-checked.
"""
import ast
import io
import sys

P = "/root/bin/work.py"

OLD = '''        refs = set()
        for field in ("title", "why"):
            if r[field]:
                refs.update(int(m) for m in _OQ_REF_RE.findall(r[field]))'''

NEW = '''        refs = set()
        for field in ("title", "why"):
            if r[field]:
                # A YEAR IS NOT A ROW ID. MEASURED 2026-10-18: item 522 names "#2026" in prose
                # and lint-refs reported it as an unresolved owner-queue reference every 15
                # minutes, while saying in the same breath that it was "probably a year". An
                # unactionable finding trains the reader to ignore the log, so the year band is
                # excluded here. The queue holds ~554 rows, so a real id cannot collide yet.
                refs.update(
                    i for i in (int(m) for m in _OQ_REF_RE.findall(r[field]))
                    if not (1900 <= i <= 2100)
                )'''

src = io.open(P, encoding="utf-8").read()
if "A YEAR IS NOT A ROW ID" in src:
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
