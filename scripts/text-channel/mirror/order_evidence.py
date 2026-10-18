#!/usr/bin/env python3
"""order_evidence.py — "does an order email already describe this charge?"

WHY THIS EXISTS (ledger item 114, filed from the owner's 2026-10-13 text)

  "you should check my emails and you should be able to see research your questions
   before asking them to me for no reason"

On 2026-10-13 the asker sent `ask-1791862240` about 362.51 at Newegg and GUESSED shop
supplies, while the mailbox held the entire trail: order #419077624 confirmed 09-22,
shipped 09-23, delivered 09-27, return label created 10-06. `merchant_resolve.resolve()`
already ran before asking, but it identifies a VENDOR, not an ITEM — and Newegg sells
everything, so it resolved nothing.

THE REASON IT COULD NOT SEE THE ANSWER, MEASURED 2026-10-14 (wake-cfo, item 114)

  * `/root/authority.db` `email_catalog` (723 rows) and `email_triage_log` (4182 rows)
    carry SUBJECT LINES ONLY: no body column exists on either. "Order confirmed: Newegg
    order #419077624 (1 item)" is all they hold — never the item.
  * `/root/accounting-data/live/accounting.db` `marketplace_orders` covers only amazon
    (467) and ebay (204); it has 0 newegg rows, so Newegg order mail is parsed by nothing.
  * The body-bearing store is the mail archive: `/root/mail-archive/<account>/archive.db`,
    `messages` (39099 rows: subject, body_text, from_addr, internal_date) with FTS5 over
    it in `msg_fts`. That store answers the question in one indexed query.

WHAT THIS DOES

Given a merchant, an amount and a window, it searches every archived mailbox for ORDER
mail and returns the order number, the item name(s) and the amounts, with the evidence
lines that justify each. It is the primitive `merchant_resolve.resolve()` needs to stop
guessing at item level.

READ-ONLY BY CONSTRUCTION. Every store is opened `mode=ro`. This writes nothing.

USAGE
    order_evidence.py --merchant Newegg --amount 362.51 --window-days 60 --why
    order_evidence.py --merchant Newegg --order 419077624 --window-days 400 --json
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sqlite3
import sys
import time

ARCHIVE_GLOB = os.environ.get("MAIL_ARCHIVE_GLOB", "/root/mail-archive/*/archive.db")

# An order mail is one whose SUBJECT is about an order/receipt/return. The subject is what
# decides candidacy, because the owner's complaint is precisely that we asked about a charge
# whose order mail was sitting there under an obvious subject.
#
# EXTENDED 2026-10-15 with `order\s+<CODE>\s+confirm`. The Shopify-family subject is
# `Order W009615 confirmed` -- the code sits BETWEEN the two words, so neither
# `order\s*(is\s*)?(confirm|#)` nor `order confirmed` could match it, and a charge whose
# order mail was already in the archive read as having no order at all. Measured on the
# live case: `order_evidence.py --merchant "VisionTek Systems" --amount 31.73 --why`
# returned solved=False with 0 candidates while `purchases` row 8281 held the same order.
ORDER_SUBJECT_RE = re.compile(
    r"order\s*(is\s*)?(confirm|#)|your order|order confirmed|your (amazon|ebay|newegg|walmart)?\s*"
    r"(\.com\s*)?order|shipped:|delivered:|delivery update|order update|"
    r"return shipping label|your .*return|return (request|confirmed)|receipt|invoice|"
    r"purchase (confirm|receipt)|thanks for your order|we'?ve got your (return|order)|"
    r"order\s+[A-Z0-9][A-Z0-9\-]{3,}\s+confirm",
    re.I,
)

# Order-number shapes seen in the archive: Newegg 419077624 (9 digits), Amazon
# 111-0032200-9576275, eBay 21-15155-16873, and generic "Order #: 123456".
ORDER_NO_RES = (
    re.compile(r"Sales Order Number:\s*([0-9][0-9\-]{5,})", re.I),
    re.compile(r"Order\s*#?\s*:?\s*([0-9]{3}-[0-9]{7}-[0-9]{7})"),
    re.compile(r"Order\s*#?\s*:?\s*([0-9]{2}-[0-9]{5}-[0-9]{5})"),
    re.compile(r"Order\s*#?\s*:?\s*([0-9]{7,})"),
)

# Item lines. `... Qty: 1` is the Newegg shape and is the most reliable; the `1 × ($x) SKU ... $x`
# shape is the Newegg return-label table; `Item(s) In This Shipment` is the return email.
ITEM_TAIL_RE = re.compile(r"(?m)^\s*(.{15,400}?)\s*Qty:\s*(\d+)\s*$")
ITEM_TIMES_RE = re.compile(r"(?m)^\s*(\d+)\s*[x×]\s*(?:\(\$([\d,]+\.\d{2})\))?\s*(.{5,300}?)\s*\$([\d,]+\.\d{2})\s*$")
AMOUNT_RE = re.compile(r"\$\s?([\d,]+\.\d{2})")
TOTAL_RE = re.compile(r"(?:Order Total|Total|Grand Total)\s*:?\s*\n?\s*\$\s?([\d,]+\.\d{2})", re.I)

# Lines that are clearly not the item even though they end the same way.
ITEM_STOPWORDS = (
    "save $", "shop newegg", "customer service", "policy & agreement", "privacy policy",
    "looking forward", "questions?", "visit our", "get order status", "important info",
    "save packaging", "have questions", "click here", "new egg", "© 2000",
)


def _ro(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect("file:%s?mode=ro" % path, uri=True, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def archives() -> list[str]:
    return sorted(glob.glob(ARCHIVE_GLOB))


def _cutoff(internal_date_max: int, window_days: int) -> int:
    """internal_date is Gmail epoch. Detect ms vs s from the observed maximum, never assume."""
    unit = 1000 if (internal_date_max or 0) > 1e11 else 1
    return int((time.time() - window_days * 86400) * unit)


def _item_lines(body: str) -> list[dict]:
    out: list[dict] = []
    for m in ITEM_TAIL_RE.finditer(body or ""):
        name = re.sub(r"\s+", " ", m.group(1)).strip(" |.-")
        low = name.lower()
        if len(name) < 15 or any(s in low for s in ITEM_STOPWORDS):
            continue
        out.append({"item_name": name, "quantity": int(m.group(2)), "shape": "name...Qty"})
    for m in ITEM_TIMES_RE.finditer(body or ""):
        name = re.sub(r"\s+", " ", m.group(3)).strip(" |.-")
        low = name.lower()
        if len(name) < 5 or any(s in low for s in ITEM_STOPWORDS):
            continue
        out.append({
            "item_name": name,
            "quantity": int(m.group(1)),
            "line_total": float(m.group(4).replace(",", "")),
            "shape": "n x (price) name price",
        })
    # de-dup on name, keeping the longest variant (the archive truncates with "...")
    best: dict[str, dict] = {}
    for it in out:
        k = it["item_name"].lower()[:40]
        if k not in best or len(it["item_name"]) > len(best[k]["item_name"]):
            best[k] = it
    return list(best.values())


def _order_numbers(text: str) -> list[str]:
    seen: list[str] = []
    for rx in ORDER_NO_RES:
        for m in rx.finditer(text or ""):
            v = m.group(1)
            if v not in seen:
                seen.append(v)
    return seen


def search_archive(db: str, term: str, window_days: int, limit: int) -> list[dict]:
    conn = _ro(db)
    try:
        if not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='messages'"
        ).fetchone():
            return []
        mx = conn.execute("SELECT COALESCE(MAX(internal_date),0) FROM messages").fetchone()[0]
        cutoff = _cutoff(mx, window_days)
        rows = list(conn.execute(
            "SELECT m.id, m.internal_date, m.date_hdr, m.from_addr, m.subject, m.body_text "
            "FROM messages m "
            "WHERE m.internal_date >= ? "
            "  AND m.id IN (SELECT id FROM msg_fts WHERE msg_fts MATCH ?) "
            "ORDER BY m.internal_date DESC LIMIT ?",
            (cutoff, term, limit * 8),
        ))
    except sqlite3.Error:
        return []
    finally:
        conn.close()

    hits: list[dict] = []
    for r in rows:
        subj = r["subject"] or ""
        if not ORDER_SUBJECT_RE.search(subj):
            continue
        body = r["body_text"] or ""
        amts = sorted({float(a.replace(",", "")) for a in AMOUNT_RE.findall(body)})
        tot = TOTAL_RE.search(body)
        items = _item_lines(body)
        nums = _order_numbers(subj + "\n" + body)
        hits.append({
            "archive": db,
            "message_id": r["id"],
            "date": r["date_hdr"],
            "internal_date": r["internal_date"],
            "from_addr": r["from_addr"],
            "subject": subj,
            "order_numbers": nums,
            "order_number": nums[0] if nums else None,
            "order_total": float(tot.group(1).replace(",", "")) if tot else None,
            "amounts": amts,
            "items": items,
        })
        if len(hits) >= limit:
            break
    return hits


def find(merchant: str, amount: float | None = None, order: str | None = None,
         window_days: int = 90, limit: int = 25, tolerance: float = 0.02) -> dict:
    # FTS term: the merchant's first meaningful word, so "Newegg.com" searches "Newegg".
    word = re.sub(r"[^A-Za-z0-9 ]", " ", merchant or "").split()
    term = max(word, key=len) if word else (merchant or "")
    checked: list[str] = ["term=%r window_days=%d" % (term, window_days)]
    evidence: list[str] = []
    every: list[dict] = []
    for db in archives():
        rows = search_archive(db, term, window_days, limit)
        if rows:
            checked.append("%s: %d order-mail candidate(s)" % (db, len(rows)))
        every.extend(rows)

    if order:
        every = [h for h in every if any(order in n or n in order for n in h["order_numbers"])
                 or order in (h["subject"] or "")]

    matched: list[dict] = []
    for h in every:
        why_ok = []
        if h["order_number"]:
            why_ok.append("order #%s" % h["order_number"])
        if h["items"]:
            why_ok.append("item %r" % h["items"][0]["item_name"][:80])
        amt_ok = None
        if amount is not None:
            pool = list(h["amounts"])
            if h["order_total"] is not None:
                pool.append(h["order_total"])
            for it in h["items"]:
                if it.get("line_total") is not None:
                    pool.append(it["line_total"])
            for a in pool:
                if abs(a - amount) <= max(tolerance, amount * 0.005):
                    amt_ok = a
                    break
            if amt_ok is None:
                continue
            why_ok.insert(0, "amount $%.2f present" % amt_ok)
        if not why_ok:
            continue
        h = dict(h, amount_matched=amt_ok)
        matched.append(h)
        evidence.append("%s | %s | %s" % (h["date"], h["subject"][:90],
                                          (h["items"][0]["item_name"][:120] if h["items"] else "(no item line)")))

    return {
        "solved": bool(matched),
        "merchant": merchant,
        "amount": amount,
        "order": order,
        "window_days": window_days,
        "matched": matched,
        "evidence": evidence,
        "checked": checked,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="find order mail that describes a charge")
    ap.add_argument("--merchant", required=True)
    ap.add_argument("--amount", type=float, default=None, help="dollars, e.g. 362.51")
    ap.add_argument("--order", default=None, help="order number, if already known")
    ap.add_argument("--window-days", type=int, default=90)
    ap.add_argument("--limit", type=int, default=25)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--why", action="store_true")
    a = ap.parse_args(argv)
    res = find(a.merchant, a.amount, a.order, a.window_days, a.limit)
    if a.json:
        print(json.dumps(res, indent=2, default=str))
        return 0 if res["solved"] else 5
    print("merchant=%s amount=%s window=%dd solved=%s" % (a.merchant, a.amount, a.window_days, res["solved"]))
    if a.why:
        for c in res["checked"]:
            print("  checked: %s" % c)
    for line in res["evidence"]:
        print("  evidence: %s" % line)
    for h in res["matched"]:
        print("  ORDER #%s total=%s" % (h["order_number"], h["order_total"]))
        for it in h["items"]:
            print("    ITEM %s qty=%s" % (it["item_name"], it.get("quantity")))
    if not res["solved"]:
        print("  order_evidence: no order mail matched merchant+amount in the window", file=sys.stderr)
    return 0 if res["solved"] else 5


if __name__ == "__main__":
    raise SystemExit(main())
