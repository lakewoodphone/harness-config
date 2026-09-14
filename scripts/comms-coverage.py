#!/usr/bin/env python3
"""comms-coverage — prove that the comms index holds every row it claims to.

WHY. `commsindex.py` reports how many rows it *wrote*; that is not the same as how
many rows it *should have written*. The two differ silently in three ways, all of
which were live on 2026-09-14:

  * the source table grew after the last build (a build is a point-in-time snapshot),
  * two source rows share one `ref`, and UNIQUE(source_table, ref) means
    `INSERT OR REPLACE` keeps only the last one,
  * an extractor skips rows by design (no text) and nobody counts the skips.

HOW IT KNOWS WHAT TO EXPECT. It does not re-implement the indexer's queries — it
IMPORTS its extractors and replays them against the source, so the expectation and
the index are produced by the same code. A second copy of the SQL would be a second
thing to drift, and drift is exactly what this tool exists to catch.

It is read-only against both databases and exits non-zero when they disagree, so it
can be wired into a scheduled refresh without ever writing to production.

USAGE
  comms-coverage.py [--source PATH] [--index PATH] [--json]
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import commsindex  # noqa: E402  (the extractors ARE the specification)

DEFAULT_SOURCE = commsindex.DEFAULT_SOURCE
DEFAULT_INDEX = commsindex.DEFAULT_DB


def _table_rows(con: sqlite3.Connection, table: str) -> int:
    try:
        return con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    except sqlite3.Error:
        return 0


def audit(source: str, index: str) -> dict:
    src = sqlite3.connect(f"file:{source}?mode=ro", uri=True, timeout=60)
    src.row_factory = sqlite3.Row
    idx = sqlite3.connect(f"file:{index}?mode=ro", uri=True, timeout=60)

    try:
        meta = {r[0]: r[1] for r in idx.execute("SELECT key, value FROM meta")}
    except sqlite3.Error:
        meta = {}

    expected: dict[str, set] = {}
    yielded: dict[str, int] = {}
    for label, fn in commsindex.EXTRACTORS:
        # Mirror the indexer exactly, INCLUDING its de-duplication key: a collapse the
        # index performed on purpose must not read here as a row it lost. Importing
        # the key function is what keeps the two in step -- the alternative is a
        # second copy of the rule, which is the drift this tool exists to catch.
        by_key: dict[str, dict] = {}
        for rec in fn(src):
            text = rec.get("text")
            if not text or not str(text).strip():
                continue
            table = rec.get("source_table") or label
            yielded[table] = yielded.get(table, 0) + 1
            by_key[commsindex._dedup_key(rec)] = rec
        by_ref: dict[str, dict] = {}
        for rec in by_key.values():
            ref = str(rec.get("ref"))
            prev = by_ref.get(ref)
            if prev is None or commsindex._richness(rec) > commsindex._richness(prev):
                by_ref[ref] = rec
        for rec in by_ref.values():
            table = rec.get("source_table") or label
            expected.setdefault(table, set()).add(str(rec.get("ref")))

    indexed: dict[str, set] = {}
    for table, ref in idx.execute("SELECT source_table, ref FROM comms"):
        indexed.setdefault(table, set()).add(str(ref))

    out = {
        "index": index,
        "source": source,
        "last_index": meta.get("last_index"),
        "age_seconds": commsindex.index_age_seconds(meta),
        "tables": [],
        "ok": True,
    }

    for table in sorted(set(expected) | set(indexed)):
        want = expected.get(table, set())
        have = indexed.get(table, set())
        # An "unkeyed" set is the refs the extractor produced before de-duplication,
        # so the collapse count is visible rather than inferred.
        missing = want - have
        orphan = have - want
        row = {
            "table": table,
            "source_rows": _table_rows(src, table),
            "yielded": yielded.get(table, 0),
            "unique_refs": len(want),
            "collapsed": yielded.get(table, 0) - len(want),
            "indexed": len(have),
            "missing": len(missing),
            "orphan": len(orphan),
        }
        if missing:
            out["ok"] = False
            row["missing_sample"] = sorted(missing)[:5]
        if orphan:
            row["orphan_sample"] = sorted(orphan)[:5]
        out["tables"].append(row)

    src.close()
    idx.close()
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", default=DEFAULT_SOURCE)
    ap.add_argument("--index", default=DEFAULT_INDEX)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    result = audit(a.source, a.index)
    if a.json:
        print(json.dumps(result, indent=1))
        return 0 if result["ok"] else 1

    print(f"index:  {result['index']}")
    print(f"source: {result['source']}")
    age = result.get("age_seconds")
    print("last index: " + (f"{result['last_index']} ({age/3600:.1f}h ago)"
                            if age is not None else "NEVER"))
    print()
    print(f"{'source_table':<30} {'src':>8} {'yield':>8} {'uniq':>8} {'coll':>6} "
          f"{'idx':>8} {'miss':>6} {'orph':>5}")
    for r in result["tables"]:
        print(f"{r['table']:<30} {r['source_rows']:>8,} {r['yielded']:>8,} "
              f"{r['unique_refs']:>8,} {r['collapsed']:>6,} {r['indexed']:>8,} "
              f"{r['missing']:>6,} {r['orphan']:>5,}")
        if r.get("missing_sample"):
            print(f"    missing e.g. {r['missing_sample']}")
    print()
    print("VERDICT: " + ("covered — every row the extractors yield is in the index"
                         if result["ok"] else
                         "INCOMPLETE — the source has rows the index does not hold"))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
