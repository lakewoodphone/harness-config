#!/usr/bin/env python3
"""cfo358-evidence-type-audit.py -- do the OTHER evidence types corroborate the charge they attach to?

LEDGER ITEM 435, discovered mid-shift from item 358. Item 358 added a product-token corroboration
gate to ``marketplace_order_sync.match_orders()`` for ``marketplace_order`` evidence: a card or
marketplace agreement alone is not a link, the charge line must also share a product token with the
order's item list (or carry no product information at all). 358 could only speak for the type it
owns. ``transaction_evidence`` also carries:

  * ``marketplace_match``  -- 82 rows, ALL confidence ``high``, written by the archived
    ``migrated-from-repo`` enrichment import (``amazon-enriched.json``,
    ``chase-enriched-ebay.json``, ``ebay-payment-orders.json``, ``ebay-reconciled.json``).
  * ``support_order_match`` -- 108 rows (69 at confidence ``high`` / ``0.97``), written by
    ``docs/archive/2026-07-12/personal_apply_support_evidence.py``: a support-only Amazon
    order-history CSV row matched to a financial charge by EXACT AMOUNT and a date window.

Both are the same class item 358 fixed: a link asserted on amount/date coincidence, with no check
that the charge and the referenced order describe the same product. An uncorroborated evidence row
can make a later reader, or ``cfo-resolve``, treat a category as documented.

WHAT THIS PRINTS. For EVERY ``marketplace_match`` and ``support_order_match`` row: the charge
description, the referenced order's items (or why they are unreachable), the product tokens the two
share, and one verdict --

  CORROBORATED        the charge names a product the order's items also name
  UNINFORMATIVE-CHARGE the charge names NO product (only the marketplace/processor/a store id), so
                       it cannot contradict the order -- item 358's explicit allowance
  NO-SHARED-TOKEN     the charge names a product and the order's items do NOT name it. THIS IS THE
                       FALSE-LINK CLASS and is the count the ledger item asks for
  ITEMS-UNRESOLVED    the referenced order's items are not reachable from the ledger at all, so no
                       token comparison is possible and NOTHING is claimed either way -- AND no
                       reason is recorded on the row, so the count is the actionable one
  UNRESOLVED-EXPLAINED the same unreachable case, but ``cfo445-record-unresolved.py`` has written
                       the measured reason into ``transaction_evidence.item_list_status`` (added
                       by that tool). The rows are still listed and still counted; this column is
                       what separates "81 rows nobody has looked at" from "81 rows whose reason is
                       on the row", so the ITEMS-UNRESOLVED count is the OPEN count, not the total

THE TOKEN RULES ARE NOT REIMPLEMENTED. ``charge_tokens``, ``item_tokens`` and
``informative_charge_tokens`` are imported from ``app.services.marketplace_order_sync`` -- the same
functions item 358's gate uses, including ``CHARGE_NOISE_TOKENS`` / ``ITEM_NOISE_TOKENS``. A second
tokenizer would be the defect this program keeps naming.

READ-ONLY. The ledger is opened ``mode=ro``; nothing is written anywhere.

USAGE   python3 /root/bin/cfo358-evidence-type-audit.py
        python3 /root/bin/cfo358-evidence-type-audit.py --type marketplace_match
EXIT    0 = the audit ran and every row carries a verdict (a NO-SHARED-TOKEN row is a FINDING, not an
            error, and does not change the exit code).
        1 = the audit could not complete.
"""
from __future__ import annotations

import argparse
import re
import sqlite3
import sys

sys.path.insert(0, "/root/personal-secretary-mvp")
from app.services.marketplace_order_sync import (  # noqa: E402
    charge_tokens,
    informative_charge_tokens,
    item_tokens,
)

LEDGER = "/root/accounting-data/live/accounting.db"
AUDIT_TYPES = ("marketplace_match", "support_order_match")

# The archived source files the marketplace_match rows name are GONE (measured 2026-10-16:
# /root/accounting-data/migrated-from-repo does not exist), so the reference string is the only
# handle back to the order. These are the shapes actually present in the ledger.
_RE_ITEMID = re.compile(r"itemId\s+(\S+)\s*/\s*([^/]+?)\s*/\s*([0-9.]+)")
_RE_CARD = re.compile(r"card\s+(\S+)\s*/\s*(.+?)\s*/\s*absAmount\s*([0-9.]+)")
_RE_BARE_ID = re.compile(r"^\d{9,18}$")


class _Order:
    """The minimum shape ``item_tokens`` needs: an object with ``.items`` = [{'name': ...}]."""

    def __init__(self, names):
        self.items = [{"name": n} for n in names if n]


def _item_names_from_rows(rows) -> list[str]:
    return [str(r["item_name"] or "") for r in rows if r["item_name"]]


def _marketplace_items_for_external_id(con, ext_id: str) -> tuple[list[str], str]:
    rows = con.execute(
        "SELECT item_name FROM marketplace_order_items WHERE CAST(item_external_id AS TEXT)=?",
        (str(ext_id),)).fetchall()
    return _item_names_from_rows(rows), "marketplace_order_items.item_external_id"


def _marketplace_items_for_seller(con, seller: str) -> tuple[list[str], str]:
    rows = con.execute(
        "SELECT item_name FROM marketplace_order_items WHERE lower(seller)=lower(?)",
        (seller,)).fetchall()
    return _item_names_from_rows(rows), "marketplace_order_items.seller"


def _items_for_order_id(con, order_id: str) -> tuple[list[str], str]:
    """The order tables, by order id: ebay, amazon and the canonical marketplace store."""
    for sql, label in (
        ("SELECT item_name FROM ebay_order_items WHERE CAST(order_id AS TEXT)=?", "ebay_order_items.order_id"),
        ("SELECT item_name FROM amazon_order_items WHERE CAST(order_id AS TEXT)=?", "amazon_order_items.order_id"),
        ("SELECT item_name FROM marketplace_order_items WHERE CAST(order_id AS TEXT)=?", "marketplace_order_items.order_id"),
    ):
        rows = con.execute(sql, (str(order_id),)).fetchall()
        if rows:
            return _item_names_from_rows(rows), label
    # ebay/amazon orders carry a free-text first_item_text even when the item rows were never
    # scraped; it is weaker (one line, not the list) and is labelled as such.
    for sql, label in (
        ("SELECT first_item_text AS item_name FROM ebay_orders WHERE CAST(order_id AS TEXT)=?",
         "ebay_orders.first_item_text"),
        ("SELECT first_item_text AS item_name FROM amazon_orders WHERE CAST(order_id AS TEXT)=?",
         "amazon_orders.first_item_text"),
    ):
        rows = con.execute(sql, (str(order_id),)).fetchall()
        if rows:
            return _item_names_from_rows(rows), label
    return [], ""


def resolve_marketplace_match(con, ref: str) -> tuple[list[str], str]:
    """The referenced order's items for a marketplace_match row, or ([], why-not)."""
    m = _RE_ITEMID.match(ref or "")
    if m:
        ext_id, seller, _amount = m.group(1), m.group(2).strip(), m.group(3)
        names, how = _marketplace_items_for_external_id(con, ext_id)
        if names:
            return names, how
        names, how = _items_for_order_id(con, ext_id)
        if names:
            return names, how
        if seller and not seller.lower().startswith("payment to"):
            names, how = _marketplace_items_for_seller(con, seller)
            if names:
                return names, "%s (seller from the reference)" % how
        return [], ("no order/item row for itemId %s (tried marketplace_order_items."
                    "item_external_id, ebay/amazon/marketplace order ids, seller %r); the "
                    "referenced source file no longer exists" % (ext_id, seller))

    m = _RE_CARD.match(ref or "")
    if m:
        last4, descriptor, amount = m.group(1), m.group(2).strip(), m.group(3)
        for candidate in (descriptor, descriptor.split("*")[-1] if "*" in descriptor else ""):
            candidate = (candidate or "").strip()
            if candidate:
                names, how = _marketplace_items_for_external_id(con, candidate)
                if names:
                    return names, how
                names, how = _items_for_order_id(con, candidate)
                if names:
                    return names, how
        return [], ("reference names card %s / %r / absAmount %s -- no order id, so no item list "
                    "is identified; the referenced source file no longer exists"
                    % (last4, descriptor, amount))

    if _RE_BARE_ID.match((ref or "").strip()):
        bare = ref.strip()
        names, how = _marketplace_items_for_external_id(con, bare)
        if names:
            return names, how
        names, how = _items_for_order_id(con, bare)
        if names:
            return names, how
        return [], ("bare id %s matches no order/item row and the referenced source file no "
                    "longer exists" % bare)

    return [], "reference format not recognised: %r" % (ref or "")


def resolve_support_order_match(con, ref: str) -> tuple[list[str], str]:
    """The referenced order-history row's own text, for a support_order_match row.

    ``reference`` is a ``transactions.id`` on a support-only Amazon order-history account. That row
    IS the order evidence (its ``description`` is Amazon's own line; ``docs/archive/.../
    personal_apply_support_evidence.py`` matched it to the financial charge by exact amount and a
    date window). Its product text, if any, is what the charge must corroborate. Per-item detail is
    looked for first and honestly reported absent when the tables are empty.
    """
    row = con.execute(
        "SELECT id, description, account_id, source_document_id FROM transactions WHERE id=?",
        (str(ref),)).fetchone()
    if row is None:
        return [], ("reference %s is not a transactions row -- the support-only order-history source "
                    "is not in this ledger" % ref)
    names: list[str] = []
    how = "transactions.description (the support-only order-history row)"
    if row["description"]:
        names.append(str(row["description"]))
    li = con.execute(
        "SELECT * FROM transaction_line_items WHERE transaction_id=?", (str(ref),)).fetchall()
    for r in li:
        d = dict(r)
        for key in ("description", "item_name", "name"):
            if d.get(key):
                names.append(str(d[key]))
                how = "transaction_line_items"
                break
    if row["source_document_id"]:
        ex = con.execute(
            "SELECT line_items_json FROM receipt_extractions WHERE source_document_id=?",
            (str(row["source_document_id"]),)).fetchall()
        for r in ex:
            blob = r["line_items_json"] or ""
            if blob and blob not in ("[]", "null"):
                names.append(blob)
                how = "receipt_extractions.line_items_json"
    return names, how


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--type", default="", help="audit one type only (%s)" % " | ".join(AUDIT_TYPES))
    ap.add_argument("--ledger", default=LEDGER)
    args = ap.parse_args()

    types = (args.type,) if args.type else AUDIT_TYPES
    bad = [t for t in types if t not in AUDIT_TYPES]
    if bad:
        print("unknown --type %s" % ", ".join(bad))
        return 1

    con = sqlite3.connect("file:%s?mode=ro" % args.ledger, uri=True)
    con.row_factory = sqlite3.Row
    con.text_factory = lambda b: b.decode("utf-8", "replace")

    totals: dict[str, int] = {}
    try:
        cols = [r[1] for r in con.execute("PRAGMA table_info(transaction_evidence)")]
        status_col = "e.item_list_status" if "item_list_status" in cols else "NULL"
        for etype in types:
            rows = con.execute(
                """SELECT e.id, e.transaction_id, e.evidence_type, e.source, e.reference,
                          e.confidence, e.notes, %s AS item_list_status,
                          t.description AS charge_desc, t.merchant_name AS charge_merchant,
                          t.amount_cents AS charge_cents, t.transaction_date AS charge_date
                     FROM transaction_evidence e
                     LEFT JOIN transactions t ON t.id = e.transaction_id
                    WHERE e.evidence_type = ?
                    ORDER BY e.confidence DESC, e.id""" % status_col, (etype,)).fetchall()

            print("=" * 100)
            print("EVIDENCE TYPE: %s   (%d rows)" % (etype, len(rows)))
            print("=" * 100)
            counts = {"CORROBORATED": 0, "UNINFORMATIVE-CHARGE": 0, "NO-SHARED-TOKEN": 0,
                      "ITEMS-UNRESOLVED": 0, "UNRESOLVED-EXPLAINED": 0}
            for row in rows:
                charge_blob = " ".join(
                    str(x or "") for x in (row["charge_desc"], row["charge_merchant"])).strip()
                if etype == "marketplace_match":
                    names, how = resolve_marketplace_match(con, row["reference"] or "")
                    marketplace = "ebay" if "itemId" in (row["reference"] or "") else "amazon"
                else:
                    names, how = resolve_support_order_match(con, row["reference"] or "")
                    marketplace = "amazon"

                if not names:
                    # Item 445: the row may already carry its measured reason on
                    # transaction_evidence.item_list_status. That does not make the item
                    # list reachable, so the row is still printed and still counted --
                    # but it is no longer an OPEN unresolved count.
                    recorded = (row["item_list_status"] or "").strip()
                    if recorded:
                        verdict = "UNRESOLVED-EXPLAINED"
                        detail = "%s [recorded: %s]" % (how, recorded)
                    else:
                        verdict = "ITEMS-UNRESOLVED"
                        detail = how
                    shared: set = set()
                else:
                    itoks = item_tokens(_Order(names))
                    informative = informative_charge_tokens(marketplace, charge_blob)
                    shared = itoks & informative
                    if shared:
                        verdict = "CORROBORATED"
                    elif not informative:
                        verdict = "UNINFORMATIVE-CHARGE"
                    else:
                        verdict = "NO-SHARED-TOKEN"
                    detail = ("items from %s: %s" % (how, " | ".join(
                        n[:70] for n in names[:3])))
                    if len(names) > 3:
                        detail += " (+%d more)" % (len(names) - 3)
                counts[verdict] += 1

                print("-" * 100)
                print("row      %s  conf=%s  %s  %s  $%.2f" % (
                    row["id"], row["confidence"], etype, row["charge_date"] or "?",
                    (row["charge_cents"] or 0) / 100.0))
                print("charge   %r" % charge_blob[:150])
                print("ref      %s" % (row["reference"] or "")[:150])
                print("items    %s" % detail[:220])
                print("shared   %s" % (", ".join(sorted(shared)) or "(none)"))
                print("VERDICT  %s" % verdict)

            total = sum(counts.values())
            print("=" * 100)
            print("SUMMARY %s: %d rows audited" % (etype, total))
            for k in ("CORROBORATED", "UNINFORMATIVE-CHARGE", "NO-SHARED-TOKEN", "ITEMS-UNRESOLVED",
                      "UNRESOLVED-EXPLAINED"):
                print("  %-20s %d" % (k, counts[k]))
            print("  %-20s %d" % ("DO NOT SHARE (NO-SHARED-TOKEN)", counts["NO-SHARED-TOKEN"]))
            totals[etype] = counts
    finally:
        con.close()

    print("=" * 100)
    grand = sum(c["NO-SHARED-TOKEN"] for c in totals.values())
    open_unresolved = sum(c["ITEMS-UNRESOLVED"] for c in totals.values())
    explained = sum(c["UNRESOLVED-EXPLAINED"] for c in totals.values())
    print("RESULT: audited %s; rows whose charge and referenced order share NO product token: %d"
          % (", ".join("%s=%d" % (t, sum(c.values())) for t, c in totals.items()), grand))
    print("RESULT: unreachable item lists: %d open (ITEMS-UNRESOLVED) + %d with a recorded reason "
          "(UNRESOLVED-EXPLAINED)" % (open_unresolved, explained))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
