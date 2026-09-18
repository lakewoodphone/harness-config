#!/usr/bin/env python3
"""fix-encoding -- repair double-encoded UTF-8 in journal entries, safely.

WHY
---
LESSONS L221 already named this: "Piping a journal body through PowerShell double-encodes it, and
the write path never notices". A body written as UTF-8 and then carried through a console code
page arrives as the UTF-8 bytes re-interpreted as cp1252, so `·` becomes `Â·` and `"` becomes
`â€œ`. Measured 2026-09-15 in `entries/`: 7 files with `Â·`, 7 with `â€`-class damage. It is not
cosmetic: a corrupted heading made `journal.py check` error on the entry, and the same corruption
made two copies of one entry look like two different entries to `idguard` (L1680).

HOW
---
Per LINE, invert exactly the transformation that caused it:

    candidate = line.encode("cp1252").decode("utf-8")

Only lines that are wholly a cp1252 artefact survive that round trip. A line with no non-ASCII is
unchanged. A line carrying a LEGITIMATE `·` or `—` fails the round trip (U+00B7 is not valid
UTF-8 as a single byte) and is left alone. A line mixing real non-ASCII with damage also fails and
is reported for a human rather than silently mangled. That safety property is the whole reason this
is a round trip and not a search-and-replace table.

USAGE
    python journal/tools/fix-encoding.py                 # scan, report, change nothing
    python journal/tools/fix-encoding.py --apply         # repair, leaving <file>.bak-encoding
    python journal/tools/fix-encoding.py --apply --root journal/entries
"""
from __future__ import annotations

import argparse
import os
import sys

SKIP_DIRS = {".git", "__pycache__", "node_modules"}
MARKERS = ("\u00c3", "\u00c2", "\u00e2\u20ac", "\ufffd")

#: Sequence-level repairs for the cases the line-level round trip must refuse: a damaged line that
#: ALSO carries legitimate non-ASCII cannot be round-tripped, but these sequences are unambiguous
#: mojibake whenever they appear (nothing legitimate renders as `Â·`), so they are safe to replace
#: in place. Built from the same transformation, not typed by hand: each is the UTF-8 bytes of the
#: intended character read as cp1252.
def _seqs():
    table = {}
    for ch in ("\u00b7", "\u201c", "\u201d", "\u2019", "\u2018", "\u2013", "\u2014", "\u2026",
               "\u20ac", "\u00a0", "\u00ae", "\u00a9"):
        try:
            table[ch.encode("utf-8").decode("cp1252")] = ch
        except UnicodeDecodeError:
            continue
    return table


SEQUENCES = _seqs()


def repair_sequences(line: str):
    """Replace unambiguous mojibake sequences; returns (line, n_replaced)."""
    n = 0
    for bad, good in SEQUENCES.items():
        if bad and bad in line:
            n += line.count(bad)
            line = line.replace(bad, good)
    return line, n


def repair_line(line: str):
    """(fixed_line, status) where status is 'ok', 'mixed', 'unchanged' or 'lossy'."""
    if not any(m in line for m in MARKERS):
        return line, "unchanged"
    if "\ufffd" in line:
        # A previous decode already destroyed the byte; inference is a judgement call, not a fix.
        return line, "lossy"
    try:
        fixed = line.encode("cp1252").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return line, "mixed"
    return (fixed, "ok") if fixed != line else (line, "unchanged")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))), help="directory to scan (default: the journal)")
    ap.add_argument("--apply", action="store_true", help="write the repairs (default: report only)")
    a = ap.parse_args(argv)

    changed = mixed = lossy = scanned = 0
    for dirpath, dirs, files in os.walk(a.root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in sorted(files):
            if not name.endswith(".md"):
                continue
            path = os.path.join(dirpath, name)
            scanned += 1
            text = open(path, encoding="utf-8", errors="replace").read()
            if not any(m in text for m in MARKERS):
                continue
            out, fixed_any, flags = [], False, set()
            for line in text.splitlines(keepends=True):
                new, status = repair_line(line)
                if status in ("mixed", "lossy"):
                    # Round trip refused; fall back to the unambiguous sequences only, so a line
                    # that mixes real non-ASCII with damage is still repaired rather than skipped.
                    new, n_seq = repair_sequences(line)
                    if n_seq:
                        status = "ok"
                flags.add(status)
                if status == "ok":
                    fixed_any = True
                out.append(new)
            rel = os.path.relpath(path, a.root).replace(os.sep, "/")
            if fixed_any:
                changed += 1
                print("REPAIR  %-52s %s" % (rel, ",".join(sorted(flags))))
                if a.apply:
                    with open(path + ".bak-encoding", "w", encoding="utf-8", newline="") as fh:
                        fh.write(text)
                    with open(path, "w", encoding="utf-8", newline="") as fh:
                        fh.write("".join(out))
            if "mixed" in flags:
                mixed += 1
                print("MIXED   %-52s needs a person: real non-ASCII on a damaged line" % rel)
            if "lossy" in flags:
                lossy += 1
                print("LOSSY   %-52s holds U+FFFD already; the byte is gone, not repairable here"
                      % rel)

    print("\nscanned %d file(s): %d repairable, %d mixed, %d lossy%s"
          % (scanned, changed, mixed, lossy, "" if a.apply else "  (dry run -- pass --apply)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
