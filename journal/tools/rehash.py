#!/usr/bin/env python3
"""rehash.py -- repair a stored integrity hash that no longer matches its entry.

WHY THIS EXISTS
`journal.py check` verifies that the `sha=` recorded in an entry's metadata line is
`entry_hash(heading, body)`. There was no command to RECOMPUTE it (measured 2026-09-15; the same gap is
recorded in the session that found it), so an edit that changed a body without touching the metadata --
which is exactly what a bulk repair does -- left `check` exiting non-zero with no supported way back.
That is how six entries came to sit in the record with a stale hash: they were repaired by
`fix-encoding.py`, the repair was correct, and the hash was simply never updated. `check` then reported
six errors forever, and an alarm that cannot be cleared is an alarm nobody reads.

WHAT IT DOES
Recomputes the hash from the entry's own heading and body and writes it back. It changes NOTHING else:
not a word of the heading, not a word of the body, not a tag, not a reference. Re-hashing is an
integrity operation, not an edit, so it must be impossible for it to alter the record -- and
`--apply` reports, per file, the old and new value so the change is auditable in the log.

DEFAULT IS REPAIR, NOT BACKFILL. Only an entry that CARRIES a hash and no longer matches it is touched.
An entry with no hash at all is valid to `check` (verification is skipped when nothing is claimed), so
silently adding a field to a hundred entries across a shared append-only log would be a large diff
nobody asked for. `--include-missing` does that deliberately, when someone decides they want every
entry verifiable.

If the BODY is also wrong (double-encoded text and so on), that is `fix-encoding.py`'s job and this will
not hide it: run that first, then this.

Usage:
  python journal/tools/rehash.py                 # report every mismatch
  python journal/tools/rehash.py --apply         # write the corrected hash
  python journal/tools/rehash.py --apply --id L221
  python journal/tools/rehash.py --apply --include-missing
"""
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import journal as J  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--id", action="append", default=[], help="only this id (repeatable)")
    ap.add_argument("--include-missing", action="store_true",
                    help="also give a hash to entries that carry none (large diff; off by default)")
    args = ap.parse_args()

    entries, _paths = J.load_entries()
    wanted = {i.upper() for i in args.id}
    checked = 0
    mismatched = []
    missing = 0
    for e in entries:
        if wanted and e["id_full"].upper() not in wanted:
            continue
        checked += 1
        path = J.entries_dir() / e["kind"] / (e["id_full"] + ".md")
        full = J.parse_entry(path, e["kind"])
        if full is None:
            print("SKIP (unparseable): %s" % J._rel_of(path))
            continue
        expected = J.entry_hash(full["heading"], full["body"])
        stored = full.get("sha") or ""
        if stored == expected:
            continue
        if not stored and not args.include_missing:
            missing += 1
            continue
        mismatched.append((full, path, stored, expected))

    if not mismatched:
        print("scanned %d entries: 0 hash mismatch(es)" % checked)
        if missing:
            print("            %d entr%s carry no hash (valid to check; --include-missing to fill)"
                  % (missing, "y" if missing == 1 else "ies"))
        return 0

    for full, path, stored, expected in mismatched:
        print("%-6s %-58s stored=%s expected=%s" % (
            full["id_full"], J._rel_of(path), stored or "(none)", expected))
        if args.apply:
            full["sha"] = expected
            J.atomic_write(path, J.entry_bytes(full))

    print("-- %d mismatch(es) of %d scanned%s" % (
        len(mismatched), checked, " (written)" if args.apply else "; re-run with --apply"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
