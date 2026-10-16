#!/usr/bin/env python3
"""cfo445-record-unresolved.py -- give every unreachable-item-list evidence row a recorded reason.

LEDGER ITEM 445 (discovered mid-shift from 435, which came from 358).
  ``transaction_evidence`` holds 82 ``marketplace_match`` rows and 108
  ``support_order_match`` rows that attach a financial charge to a marketplace order.
  Item 358's gate can only speak for ``marketplace_order``. Item 435 audited the OTHER
  two types and published the counts, but a COUNT IS NOT A RECORD: it tells a reader
  that 81 rows cannot be checked and says nothing about WHY, so the next shift (or a
  human) must re-derive it from the archived JSON names that no longer resolve.

WHAT THIS DOES
  For every row whose referenced order's item list is NOT reachable, it writes a durable
  one-line reason into ``transaction_evidence.item_list_status`` (added on first run by
  ``ALTER TABLE ... ADD COLUMN``, the same additive-migration shape storage.ts uses for
  ``transactions.counterparty``). Inserts in this program name their columns explicitly,
  and every reader names the columns it selects, so the new column breaks neither.

  Rows whose item list IS reachable are deliberately left NULL: they are checkable by
  item 435's audit and must keep being checked. This tool never claims a link is wrong;
  it records that a link CANNOT BE CHECKED, which is the honest verdict for a reference
  whose order is gone.

WHY EACH CLASS CANNOT RESOLVE (measured 2026-10-16 against the live ledger)
  marketplace_match (68 of 82):
    49 x ref is ``card <last4> / <descriptor> / absAmount <n>`` -- a card-side descriptor
         with NO order id; nothing identifies an order, and the archived
         ``~/accounting-data/migrated-from-repo/{amazon-enriched,chase-enriched-ebay}.json``
         rows it came from no longer exist on the authority.
    15 x ref is a bare eBay item id that matches no row in marketplace_order_items
         (by item_external_id or order_id), no ebay/amazon order id, and whose source
         export is gone.
     2 x ref is a bare ``itemId <n> / <seller> / <amount>`` whose seller column exists but
         holds only ``eBay Money Back Guarantee`` boilerplate (not a product), and whose
         item id resolves nowhere.
     2 x ref is ``<id> / <id>`` payment-pair text that names no order id at all.
  support_order_match (13 of 108): the reference is a ``transactions.id`` on a support-only
     order-history account, and that row is not in the live ledger -- the support source
     was pruned, so neither its description nor its line items can be read.

READ-ONLY EXCEPT for the additive column and the status cells it fills. It never touches
``notes`` (that carries the original import provenance) and never edits a charge.

USAGE  python3 /root/bin/cfo445-record-unresolved.py --check     # report only
       python3 /root/bin/cfo445-record-unresolved.py --dry-run   # show what it would write
       python3 /root/bin/cfo445-record-unresolved.py             # apply
       python3 /root/bin/cfo445-record-unresolved.py --db <copy> # rehearse against a copy
EXIT   0 = the record is complete (or --check/--dry-run completed); 1 = it could not complete.
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import re
import sqlite3
import sys

LEDGER = "/root/accounting-data/live/accounting.db"
AUDIT_SCRIPT = "/root/bin/cfo358-evidence-type-audit.py"
COLUMN = "item_list_status"
TYPES = ("marketplace_match", "support_order_match")


def load_audit(path=AUDIT_SCRIPT):
    """Import item 435's resolver so the token rules and lookups are NOT reimplemented."""
    spec = importlib.util.spec_from_file_location("cfo358_audit", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def classify_reference(etype, ref):
    ref = ref or ""
    if etype == "support_order_match":
        return "support-reference-missing"
    if ref.startswith("itemId"):
        return "marketplace-itemId"
    if ref.startswith("card"):
        return "marketplace-card-descriptor"
    if re.fullmatch(r"[0-9]+", ref.strip()):
        return "marketplace-bare-id"
    return "marketplace-unparsed-reference"


def reason_for(etype, ref, why_no):
    kind = classify_reference(etype, ref)
    return "%s: %s" % (kind, (why_no or "").strip().rstrip("."))


def ensure_column(con):
    cols = [r[1] for r in con.execute("PRAGMA table_info(transaction_evidence)")]
    if COLUMN in cols:
        return False
    con.execute("ALTER TABLE transaction_evidence ADD COLUMN %s TEXT" % COLUMN)
    return True


def resolve_all(con, audit, read_only):
    """Yield (row_id, etype, ref, reason_or_None) for every row of both types."""
    for etype in TYPES:
        rows = con.execute(
            "SELECT id, reference FROM transaction_evidence WHERE evidence_type=?", (etype,)
        ).fetchall()
        for row in rows:
            ref = row["reference"] or ""
            if etype == "marketplace_match":
                names, why = audit.resolve_marketplace_match(con, ref)
            else:
                names, why = audit.resolve_support_order_match(con, ref)
            if names:
                yield row["id"], etype, ref, None
            else:
                yield row["id"], etype, ref, reason_for(etype, ref, why)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", default=LEDGER)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    if not os.path.exists(args.db):
        print("MISSING ledger %s" % args.db)
        return 1
    try:
        audit = load_audit()
    except Exception as exc:  # noqa: BLE001
        print("cannot import %s: %s: %s" % (AUDIT_SCRIPT, type(exc).__name__, exc))
        return 1

    read_only = args.check
    if read_only:
        con = sqlite3.connect("file:%s?mode=ro" % args.db, uri=True)
    else:
        con = sqlite3.connect(args.db, timeout=60)
    con.row_factory = sqlite3.Row
    con.text_factory = lambda b: b.decode("utf-8", "replace")
    con.execute("PRAGMA busy_timeout=60000")

    added = False
    if not read_only:
        try:
            added = ensure_column(con)
        except sqlite3.OperationalError as exc:
            print("cannot add column %s: %s" % (COLUMN, exc))
            con.close()
            return 1

    have_col = COLUMN in [r[1] for r in con.execute("PRAGMA table_info(transaction_evidence)")]
    if args.check and not have_col:
        print("CHECK: column %s absent -- nothing recorded yet" % COLUMN)
        con.close()
        return 0

    stats = {t: {"resolved": 0, "unresolved": 0, "written": 0, "already": 0} for t in TYPES}
    pending = []
    for row_id, etype, ref, reason in resolve_all(con, audit, read_only):
        if reason is None:
            stats[etype]["resolved"] += 1
            continue
        stats[etype]["unresolved"] += 1
        if not read_only and not args.dry_run:
            cur = con.execute(
                "SELECT %s AS status FROM transaction_evidence WHERE id=?" % COLUMN, (row_id,)
            ).fetchone()
            if (cur["status"] or "") == reason:
                stats[etype]["already"] += 1
            else:
                con.execute(
                    "UPDATE transaction_evidence SET %s=? WHERE id=?" % COLUMN, (reason, row_id)
                )
                stats[etype]["written"] += 1
        pending.append((row_id, etype, ref, reason))

    if not read_only and not args.dry_run:
        con.commit()
    con.close()

    total_unresolved = sum(s["unresolved"] for s in stats.values())
    total_resolved = sum(s["resolved"] for s in stats.values())
    if args.json:
        import json
        print(json.dumps({"added_column": added, "stats": stats,
                          "unresolved": total_unresolved, "resolved": total_resolved},
                         indent=2))
    else:
        mode = " (check)" if args.check else " (dry-run)" if args.dry_run else ""
        print("ITEM 445 RECORD%s" % mode)
        print("  column %s %s" % (COLUMN, "ADDED" if added else
                                  ("present" if have_col else "absent")))
        for etype in TYPES:
            s = stats[etype]
            print("  %-20s resolved=%-4d unresolved=%-4d written=%-4d already=%-4d"
                  % (etype, s["resolved"], s["unresolved"], s["written"], s["already"]))
        print("  TOTAL resolved=%d unresolved=%d" % (total_resolved, total_unresolved))
        if args.dry_run or args.check or added:
            for rid, etype, ref, reason in pending[:6]:
                print("    %s  %s" % (rid[:8], reason[:150]))
            if len(pending) > 6:
                print("    ... and %d more" % (len(pending) - 6))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
