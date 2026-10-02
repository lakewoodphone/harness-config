#!/usr/bin/env python3
"""ingest-order-history.py — put scraped Amazon order history into the accounting ledger.

WHY: the ledger's `amazon_orders`/`amazon_order_items` were a one-off scrape from
2026-07-01 (business orders end 2026-06-30, personal 2026-05-25), while the
scrapers on the owner's desktop produced 136 personal + 42 business orders with
ASINs and prices in 2026-09. Nothing ever moved that JSON into the ledger, so no
Amazon charge can be matched to an order — which is exactly what the owner asked
for on 2026-10-02: "if it's an Amazon order, you have robust Tools and packages to
read my Amazon accounts and get every order detail."

WHAT IT DOES: reads the scrapers' JSON and upserts it into `amazon_orders` and
`amazon_order_items` on the accounting DB. It only ever ADDS or updates rows for
orders it is given; it never deletes, and it never touches `transactions`.

Dedupe key is (account_label, order_id), which is the existing UNIQUE key.

USAGE
    ingest-order-history.py --dry-run                 # report what would change
    ingest-order-history.py --apply                   # write
    ingest-order-history.py --apply --dir ~/accounting-data/amazon-scrape
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_DB = Path(os.path.expanduser("~/accounting-data/live/accounting.db"))
DEFAULT_DIR = Path(os.path.expanduser("~/accounting-data/amazon-scrape"))

ITEM_DDL = """
CREATE TABLE IF NOT EXISTS amazon_order_items (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id      TEXT NOT NULL,
    account_label TEXT NOT NULL,
    item_name     TEXT,
    quantity      INTEGER,
    unit_price    REAL,
    line_total    REAL,
    asin          TEXT,
    condition     TEXT,
    sold_by       TEXT,
    scraped_at    TEXT NOT NULL
)
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_orders(path: Path) -> tuple[str, dict]:
    """-> (account_label, {'orders': [...], 'source': filename})"""
    blob = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(blob, dict):
        rows = blob.get("orders") or blob.get("rows") or []
    else:
        rows = blob
    name = path.name.lower()
    if "business" in name:
        label = "business"
    elif "personal" in name:
        label = "personal"
    else:
        label = "unknown"
    return label, {"orders": rows, "source": path.name}


def normalise(row: dict) -> dict:
    """Accept both scraper shapes.

    archive/amazon_order_scraper.py   -> order_id, order_date, total_amount,
                                         item_count, ship_to, raw_total,
                                         first_item_text
    scrape_amazon_browser.py          -> order_number, order_placed_date,
                                         grand_total, ship_to, placed_by_group,
                                         items[{title, asin, price}]
    """
    order_id = row.get("order_id") or row.get("order_number") or ""
    date = row.get("order_date") or row.get("order_placed_date") or ""
    total = row.get("total_amount")
    if total is None:
        total = row.get("grand_total")
    raw_total = row.get("raw_total")
    if raw_total is None and total is not None:
        raw_total = "$%.2f" % float(total)
    items = row.get("items") or []
    return {
        "order_id": str(order_id).strip(),
        "order_date": (str(date) or "")[:10],
        "total_amount": float(total) if total not in (None, "") else None,
        "item_count": row.get("item_count", len(items)) or 0,
        "ship_to": row.get("ship_to") or "",
        "raw_total": raw_total or "",
        "first_item_text": row.get("first_item_text")
                           or (items[0].get("title") if items else "")
                           or row.get("placed_by_group") or "",
        "items": [
            {
                "item_name": it.get("title") or it.get("item_name") or "",
                "asin": it.get("asin") or "",
                "unit_price": it.get("price") if it.get("price") is not None else it.get("unit_price"),
                "quantity": it.get("quantity", 1),
                "sold_by": it.get("sold_by") or "",
                "condition": it.get("condition") or "",
            }
            for it in items
        ],
    }


def _insert_items(conn, label: str, order_id: str, items: list[dict], stamp: str) -> int:
    """Insert items, tolerating the ledger's hidden unique index.

    Returns how many rows the index refused (0 in the normal case). A refusal is
    never an error: the same line twice on one order is a real Amazon shape, and
    the ledger's index -- not this script -- decides what counts as a duplicate.
    """
    refused = 0
    for it in items:
        before = conn.total_changes
        try:
            conn.execute(
                """INSERT OR IGNORE INTO amazon_order_items (order_id, account_label,
                       item_name, quantity, unit_price, line_total, asin, condition,
                       sold_by, scraped_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (order_id, label, it["item_name"], it["quantity"], it["unit_price"],
                 None, it["asin"], it["condition"], it["sold_by"], stamp),
            )
        except sqlite3.IntegrityError:
            refused += 1
            continue
        if conn.total_changes == before:
            refused += 1
    return refused


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--dir", default=str(DEFAULT_DIR))
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    apply = bool(args.apply)

    db = Path(args.db)
    if not db.exists():
        raise SystemExit("ledger not found: %s" % db)
    src_dir = Path(args.dir)
    files = sorted(p for p in src_dir.glob("amazon-*.json") if "browser" in p.name or "2026" in p.name)
    if not files:
        raise SystemExit("no amazon-*.json in %s" % src_dir)

    conn = sqlite3.connect(str(db), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=15000")
    conn.executescript(ITEM_DDL)

    stamp = now_iso()
    stats = {"files": 0, "orders_new": 0, "orders_updated": 0, "items_new": 0,
             "items_rejected": 0, "items_unstored": 0, "orders_shrank": 0,
             "orders_gained_items": 0, "skipped_no_id": 0, "unchanged": 0,
             "blank_rows_left_alone": 0}

    for path in files:
        label, payload = read_orders(path)
        orders = payload["orders"]
        print("\n== %s -> account_label=%s, %d order(s) ==" % (path.name, label, len(orders)))
        stats["files"] += 1
        for raw in orders:
            o = normalise(raw)
            if not o["order_id"]:
                stats["skipped_no_id"] += 1
                continue
            existing = conn.execute(
                "SELECT id, total_amount, order_date FROM amazon_orders"
                " WHERE account_label=? AND order_id=?",
                (label, o["order_id"]),
            ).fetchone()
            if existing is None:
                stats["orders_new"] += 1
                if apply:
                    conn.execute(
                        """INSERT INTO amazon_orders (account_label, order_id, order_date,
                               total_amount, item_count, ship_to, raw_total,
                               first_item_text, scraped_at)
                           VALUES (?,?,?,?,?,?,?,?,?)""",
                        (label, o["order_id"], o["order_date"], o["total_amount"],
                         o["item_count"], o["ship_to"], o["raw_total"],
                         o["first_item_text"], stamp),
                    )
            else:
                # MEASURED 2026-10-02: an incoming record with no date and no total
                # (the browser scraper emits `total_amount: null` for some rows)
                # overwrote a good stored row with '' and 0.0. Empty is not news.
                # A row that carries neither a date nor a total is left alone; its
                # items are still ingested below, which is the only thing it can add.
                if not (o["order_date"] or "").strip() and o["total_amount"] in (None, 0, 0.0):
                    stats["unchanged"] += 1
                    stats["blank_rows_left_alone"] += 1
                else:
                    # Only a real difference is a write. The first version marked a row
                    # "updated" whenever the file carried items, so every run rewrote
                    # 172 rows and refreshed `scraped_at` on all of them -- which made
                    # "orders_updated: 172" on a second identical run, and made
                    # `scraped_at` useless as a freshness signal.
                    fields_differ = (
                        (existing["total_amount"] is None and o["total_amount"] is not None)
                        or (existing["total_amount"] is not None and o["total_amount"] is not None
                            and abs(existing["total_amount"] - o["total_amount"]) > 0.005)
                        or (existing["order_date"] or "") != (o["order_date"] or "")
                    )
                    if not fields_differ:
                        stats["unchanged"] += 1
                    else:
                        stats["orders_updated"] += 1
                        if apply:
                            conn.execute(
                                """UPDATE amazon_orders SET order_date=?, total_amount=?,
                                       item_count=?, ship_to=?, raw_total=?,
                                       first_item_text=?, scraped_at=?
                                   WHERE id=?""",
                                (o["order_date"] or existing["order_date"],
                                 o["total_amount"] if o["total_amount"] is not None else existing["total_amount"],
                                 o["item_count"], o["ship_to"], o["raw_total"],
                                 o["first_item_text"], stamp, existing["id"]),
                            )
            if o["items"]:
                have = conn.execute(
                    "SELECT COUNT(*) FROM amazon_order_items WHERE order_id=? AND account_label=?",
                    (o["order_id"], label),
                ).fetchone()[0]
                if have == 0:
                    stats["items_new"] += len(o["items"])
                    if apply:
                        stats["items_rejected"] += _insert_items(
                            conn, label, o["order_id"], o["items"], stamp)
                else:
                    # The ledger carries a UNIQUE index on
                    # (order_id, item_name, unit_price) that is not in the DDL this
                    # script can see, so a delete-and-reinsert loses rows the moment
                    # an order contains the same line twice (measured 2026-10-02:
                    # IntegrityError on the personal account after 42 business orders
                    # had already been written). ADD-ONLY is the honest rule: keep
                    # every row already stored and insert only what is genuinely
                    # missing. An order whose covered item count falls is counted, not
                    # hidden.
                    add = [it for it in o["items"]
                           if not conn.execute(
                               """SELECT 1 FROM amazon_order_items
                                   WHERE order_id=? AND account_label=? AND item_name=?
                                     AND COALESCE(unit_price,-1)=COALESCE(?,-1)
                                   LIMIT 1""",
                               (o["order_id"], label, it["item_name"], it["unit_price"]),
                           ).fetchone()]
                    if add:
                        stats["items_new"] += len(add)
                        stats["orders_gained_items"] += 1
                        if apply:
                            stats["items_rejected"] += _insert_items(
                                conn, label, o["order_id"], add, stamp)
                    elif len(o["items"]) > have:
                        stats["items_unstored"] += len(o["items"]) - have
                        stats["orders_shrank"] += 1

    if apply:
        conn.commit()

    print("\n== %s ==" % ("APPLIED" if apply else "DRY RUN (nothing written)"))
    for k, v in sorted(stats.items()):
        print("  %-18s %s" % (k, v))

    print("\n-- ledger coverage now --")
    for r in conn.execute("""SELECT account_label, COUNT(*) n, MIN(order_date) lo,
                                    MAX(order_date) hi, MAX(scraped_at) newest
                               FROM amazon_orders GROUP BY 1 ORDER BY 1"""):
        print("  %-10s orders=%-4s %s .. %s  scraped=%s" % (
            r["account_label"], r["n"], r["lo"], r["hi"], (r["newest"] or "")[:19]))
    n_items = conn.execute("SELECT COUNT(*) FROM amazon_order_items").fetchone()[0]
    print("  items total: %s" % n_items)

    # FRESHNESS. The order feed going stale is silent otherwise: the scrapers live on
    # the owner's desktop, and on 2026-10-02 the saved Amazon session had expired, so
    # every run returned zero orders and said nothing. Measured then: the ledger's
    # newest order was 2026-09-10 while charges kept arriving, so charge questions about
    # anything newer could not name an item. A stale feed is now a stated fact and a
    # non-zero exit, so a cron wrapper can raise ONE owner question instead of silence.
    newest_order = conn.execute(
        "SELECT MAX(order_date) FROM amazon_orders WHERE length(order_date)=10").fetchone()[0]
    age_days = None
    if newest_order:
        from datetime import date as _date
        try:
            age_days = (_date.today() - _date.fromisoformat(newest_order)).days
        except Exception:
            age_days = None
    limit = int(os.environ.get("ORDER_FEED_MAX_AGE_DAYS", "10"))
    stale = age_days is not None and age_days > limit
    print("\n-- freshness --")
    print("  newest order in the ledger: %s (%s days old; limit %s)"
          % (newest_order, age_days, limit))
    print("  %s" % ("STALE - the Amazon session has probably expired on the desktop, "
                    "or no scrape has run" if stale
                    else "fresh enough: charge questions can name an item"))
    conn.close()
    return 3 if stale else 0


if __name__ == "__main__":
    sys.exit(main())
