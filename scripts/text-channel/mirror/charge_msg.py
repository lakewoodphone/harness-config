"""charge_msg.py — compose an owner money-question that carries the evidence.

Prototype for the replacement of cfo-ask.compose(). Read-only: it takes a merchant
key + the ledger and returns a message body. No network, no writes, no sends.

What it puts in, and where each piece comes from:
  card            accounts.last_four, else the digits already inside account_id
                  (personal-amex-22005 -> 2005). NEVER the account_name: two
                  different cards both read "Blue Cash Everyday(R)".
  the exact charge  the real row: amount_cents + transaction_date + id, not a
                  MAX() aggregate taken from a different row.
  bank's words    raw_payload_json.raw_name, e.g. "THE HOME DEPOHOWELL" - the
                  location is real information; the amount restated is not, so
                  noise is stripped and the line is dropped when nothing is left.
  siblings        the other charges for the same merchant in the window, listed
                  as "amount on date", so a grouped total is never mistaken for a
                  single charge.
  order match     amazon_orders by exact amount then +/- 5 days (only useful once
                  the Amazon feed is fresh; silent when it cannot know).
  one ask         a guess plus 'yes', or a free-text answer.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

LEDGER = 'file:/home/zabz/accounting-data/live/accounting.db?mode=ro'
MAX_BODY = 300          # textsend's owner ceiling is 320; leave headroom

_SMALL = {"of", "the", "and", "at", "for", "to", "a", "an", "on", "in", "by"}
_NOISE = re.compile(r"^(aplpay|amazon order|total|purchase|payment|pos|debit|pending)\b[\s:—\-]*", re.I)
_AMOUNT = re.compile(r"\$?\s*\d[\d,]*\.?\d{0,2}\s*")
_SIGNAL = re.compile(r"[A-Z]{5,}|STORE|WHSE|#\d|\(\d{3}\)")


def _c(ledger: str = LEDGER) -> sqlite3.Connection:
    c = sqlite3.connect(ledger, uri=True)
    c.row_factory = sqlite3.Row
    return c


def connect(ledger: str = LEDGER) -> sqlite3.Connection:
    """A read-only connection with Row rows — for callers that own the ledger path.

    The caller must use this rather than `sqlite3.connect` itself: rows without a
    row_factory are tuples, and every accessor here is a named column (measured
    2026-10-02 — the first deployment fell back to the bare body with
    "tuple indices must be integers or slices, not str").
    """
    path = ledger
    if not path.startswith("file:"):
        path = "file:%s?mode=ro" % path
    return _c(path)


def _pretty(name: str) -> str:
    """Title-case a merchant without mangling "Esti's" into "Esti'S"."""
    out = []
    for w in (name or "").split():
        if w.lower() in _SMALL:
            out.append(w.lower())
        elif "'" in w:
            head, _, tail = w.partition("'")
            out.append(head[:1].upper() + head[1:].lower() + "'" + tail.lower())
        else:
            out.append(w[:1].upper() + w[1:].lower())
    return " ".join(out)


def fmt_money(cents) -> str:
    return "{:,.2f}".format((cents or 0) / 100.0)


def fmt_day(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).strftime("%-d %b")
    except Exception:
        try:
            return datetime.strptime((iso or "")[:10], "%Y-%m-%d").strftime("%-d %b")
        except Exception:
            return iso or "?"


def card_last4(row, conn) -> str:
    """Last four for a charge's card. account_id first - accounts.last_four is
    NULL for most rows, and account_name is shared by two different cards."""
    aid = row["account_id"] or ""
    m = re.search(r"(\d{4,})$", aid)
    if m and len(m.group(1)) >= 4:
        return m.group(1)[-4:]
    r = conn.execute("SELECT last_four FROM accounts WHERE id = ?", (aid,)).fetchone()
    if r and r[0]:
        d = re.sub(r"[^0-9]", "", str(r[0]))
        if d:
            return d[-4:]
    m = re.search(r"\*(\d{4})\b", row["account_name"] or "")
    return m.group(1) if m else ""


def bank_words(row) -> str:
    """`raw_name` from the bank, only if it still carries information after the
    amount and the filler are removed. Measured 2026-10-02: without this filter
    the owner gets "Statement says: 320.00" - the amount he was already told."""
    raw = row["raw_payload_json"] or ""
    try:
        blob = json.loads(raw)
    except Exception:
        return ""
    txt = str(blob.get("raw_name") or blob.get("name") or blob.get("Description") or "")
    txt = re.sub(r"\s+", " ", txt).strip()
    if not txt:
        return ""
    # Strip the Apple Pay marker, the restated amount and the filler words, then
    # look at what is LEFT: if nothing but the merchant's own name survives, the
    # line adds nothing and is dropped. "Data Reclos Angeles" keeps its city;
    # "Amazon Order - TOTAL" and "Esti's World of Fashion I." do not survive.
    cleaned = re.sub(r"^AplPay\s+", "", txt, flags=re.I)
    cleaned = _AMOUNT.sub(" ", cleaned)
    cleaned = _NOISE.sub("", cleaned).strip(" —-:,.`'")
    merchant = (row["normalized_merchant"] or "").lower()
    probe = cleaned
    for w in [w for w in re.split(r"[^a-z0-9]+", merchant) if len(w) > 2]:
        probe = re.sub(re.escape(w), " ", probe, flags=re.I)
    probe = re.sub(r"[^A-Za-z0-9]+", " ", probe).strip()
    # Keep it only when a city, a store location or a store number survives - so
    # the owner never reads "Statement says: Amazon Order — TOTAL." The amount
    # restated, or the merchant's own name, is not evidence.
    return cleaned if len(probe) >= 6 else ""


def order_match(conn, cents: int, when: str) -> str:
    """An Amazon order with the same total within +/- 5 days, if we hold one."""
    try:
        if not conn.execute("SELECT 1 FROM amazon_orders LIMIT 1").fetchone():
            return ""
        lo = (date.fromisoformat(when[:10]) - timedelta(days=5)).isoformat()
        hi = (date.fromisoformat(when[:10]) + timedelta(days=5)).isoformat()
        r = conn.execute(
            """SELECT order_id, order_date FROM amazon_orders
                WHERE ABS(COALESCE(total_amount,0) - ?) < 0.02
                  AND order_date BETWEEN ? AND ?
                ORDER BY order_date DESC LIMIT 1""",
            (cents / 100.0, lo, hi),
        ).fetchone()
        if not r:
            return ""
        first = conn.execute(
            "SELECT item_name FROM amazon_order_items WHERE order_id = ? LIMIT 1",
            (r["order_id"],),
        ).fetchone()
        what = ""
        if first and first[0]:
            what = first[0]
            what = (what[:40] + "...") if len(what) > 43 else what
        return "Amazon order %s (%s)%s" % (r["order_id"], r["order_date"],
                                           " - " + what if what else "")
    except Exception:
        return ""


def email_match(merchant: str, when: str, *, days: int = 6) -> str:
    """The vendor email nearest this charge — the owner's own ask, mechanised.

    "Maybe match it up against emails, if you can find anything." (2026-10-02)

    Vendor mail lives in the app's `email_triage_log` and is reachable read-only.
    Verified against real data: `data reclos` finds `Jotform <noreply@jotform.com>`
    "Receipt for $300 DATA RECOVERY - SECURE PAYMENT FORM"; `the home depot` finds
    `HomeDepotPro@order.homedepot.com`; `newegg` finds "Delivered: Newegg order
    #419077624 (1 item)" — an ORDER NUMBER, which is the useful part.

    Matching is deliberately crude and says so: the merchant's words against the
    sender and the subject, nearest in date within a few days. It returns what it
    found verbatim rather than a conclusion, because a false "matched" is worse than
    "no email".
    """
    db = Path(os.environ.get("SECRETARY_DB",
                             Path.home() / "personal-secretary-mvp" / "data" / "secretary.db"))
    if not db.exists():
        return ""
    words = [w for w in re.split(r"[^a-z0-9]+", (merchant or "").lower()) if len(w) > 3]
    if not words:
        return ""
    try:
        c = sqlite3.connect("file:%s?mode=ro" % db, uri=True, timeout=15)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA busy_timeout=8000")
        # The most distinctive single word keeps this a cheap, indexed-ish scan on a
        # 16 GB database; more words only add false negatives.
        needle = max(words, key=len)
        try:
            day = datetime.fromisoformat(when[:10]).date()
        except Exception:
            return ""
        rows = c.execute(
            """SELECT created_at, sender, subject FROM email_triage_log
                WHERE (lower(sender) LIKE ? OR lower(subject) LIKE ?)
                  AND created_at >= ? AND created_at <= ?
                ORDER BY created_at DESC LIMIT 4""",
            ("%" + needle + "%", "%" + needle + "%",
             (day - timedelta(days=days)).isoformat(),
             (day + timedelta(days=days)).isoformat() + "T23:59:59"),
        ).fetchall()
        # NO any-date fallback. Measured 2026-10-02: with one, a charge on 24 Sep cited
        # a Home Depot email from 27 Sep under the label "Email:" -- plausible, and
        # potentially a different order. A question that names the wrong order is worse
        # than one that names none, so an out-of-window hit is reported as none.
        if not rows:
            c.close()
            return ""
        c.close()
    except Exception:
        return ""
    if not rows:
        return ""
    r = rows[0]
    subj = re.sub(r"\s+", " ", str(r["subject"] or ""))[:78]
    order = re.search(r"(#[\w-]{4,}|\b\d{6,12}\b|\b[\d]{3}-[\d]{7}-[\d]{7}\b)", subj)
    who = str(r["sender"] or "")
    dom = re.search(r"@([\w.-]+)", who)
    label = dom.group(1) if dom else who[:28]
    stamp = str(r["created_at"] or "")[:10]
    extra = (" order %s" % order.group(1)) if order else ""
    n = int(len(rows))
    return "%s%s: %s%s" % (stamp, (" (+%d more)" % (n - 1)) if n > 1 else "", label, extra or (" - " + subj))


# ── the email-backed Amazon fallback ───────────────────────────────────────
APP_PY = Path(os.environ.get("SECRETARY_APP", Path.home() / "personal-secretary-mvp"))
AMAZON_MAIL_ACCOUNTS = tuple(
    a for a in os.environ.get(
        "AMAZON_MAIL_ACCOUNTS",
        "lakewoodphoneandtech@gmail.com,eliyahuzabrowsky@gmail.com,ezabz68@gmail.com",
    ).split(",") if a.strip())

_ORDER_ID = re.compile(r"\b\d{3}-\d{7}-\d{7}\b")
_ORDERISH = re.compile(r"ordered|shipped|delivered|arriving|out for delivery", re.I)


# ── the lookup cache ───────────────────────────────────────────────────────
# The Gmail lookup costs 2.5-7 s and answers a fact that changes once a day. Measured
# 2026-10-02: `compose('amazon')` took 2.55 s of pure lookup time, on the send path.
_EMAIL_CACHE_DIR = Path(os.environ.get(
    "CHARGE_MSG_CACHE", Path.home() / ".cache" / "charge-msg"))
_EMAIL_CACHE_TTL_DAYS = float(os.environ.get("CHARGE_MSG_CACHE_TTL_DAYS", "3"))
_EMAIL_CACHE_TTL_RECENT_HOURS = float(os.environ.get("CHARGE_MSG_CACHE_TTL_RECENT_HOURS", "2"))


def _email_cache_path(when: str):
    try:
        day = datetime.fromisoformat(str(when)[:10]).date().isoformat()
    except Exception:
        return None
    return _EMAIL_CACHE_DIR / ("amazon-orders-%s.json" % day)


def _email_cache_get(when: str) -> str | None:
    """The cached answer, or None. Never raises."""
    p = _email_cache_path(when)
    if p is None:
        return None
    try:
        if not p.exists():
            return None
        blob = json.loads(p.read_text(encoding="utf-8"))
        saved = datetime.fromisoformat(blob["at"])
        age_h = (datetime.now(timezone.utc) - saved).total_seconds() / 3600.0
        # A window ending within the last few days can still gain an order, so it expires
        # faster than one from weeks ago.
        try:
            day = datetime.fromisoformat(str(when)[:10]).date()
            recent = (datetime.now(timezone.utc).date() - day).days <= 3
        except Exception:
            recent = True
        ttl = _EMAIL_CACHE_TTL_RECENT_HOURS if recent else _EMAIL_CACHE_TTL_DAYS * 24.0
        if age_h <= ttl:
            return str(blob.get("value") or "")
    except Exception:
        return None
    return None


def _email_cache_put(when: str, value: str) -> None:
    """Best-effort. Never raises, never blocks an answer."""
    p = _email_cache_path(when)
    if p is None:
        return
    try:
        _EMAIL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps({
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "when": str(when)[:10],
            "value": value,
        }), encoding="utf-8")
        tmp.replace(p)          # atomic: a reader never sees a half-written file
    except Exception as exc:
        # LOUD. A bare pass here made a real write failure look like "no cache", and
        # the only symptom was every lookup paying 2.5-7 s forever.
        import traceback as _tb
        if os.environ.get("_EMAIL_ORDER_DEBUG"):
            _tb.print_exc(file=sys.stderr)
        else:
            print("charge_msg: cannot write the cache at %s (%s)" % (p, exc),
                  file=sys.stderr)


def _email_order_match(when: str, *, days: int = 4, accounts=None, limit: int = 12) -> str:
    """An Amazon ORDER ID from the owner's own mail, for a charge on `when`.

    Independent of the ledger and of every scraper: it reads Gmail. Returns "" unless it
    finds a real order id inside the date window, and it never guesses an order for a
    charge it cannot tie to one. Weak by construction — no amount, no items — so it is a
    fallback, and its output says "via email" so a reader knows which source spoke.
    """
    if not APP_PY.exists():
        return ""
    try:
        day = datetime.fromisoformat(str(when)[:10]).date()
    except Exception:
        return ""
    cached = _email_cache_get(when)
    if cached is not None:
        return cached
    lo = (day - timedelta(days=days)).strftime("%Y/%m/%d")
    hi = (day + timedelta(days=days)).strftime("%Y/%m/%d")
    query = "from:amazon.com after:%s before:%s" % (lo, hi)
    seen: dict = {}
    if str(APP_PY) not in sys.path:
        sys.path.insert(0, str(APP_PY))
    # `settings.gmail_tokens_dir` is RELATIVE ('data/gmail_tokens'), so the service resolves
    # it against the process cwd. Measured 2026-10-02: from the app directory 4 accounts are
    # authenticated, from $HOME 0 are -- and `cfo-ask.py` runs from $HOME, so every lookup
    # raised "not authenticated" and the fallback returned "" as if there were no mail.
    # Anchor the cwd for the lookup only; the app itself is untouched.
    _app_cwd = None
    try:
        _app_cwd = os.getcwd()
        os.chdir(str(APP_PY))
    except Exception:
        _app_cwd = None
    try:
        for acct in (accounts or AMAZON_MAIL_ACCOUNTS):
            try:
                from app.config import settings
                from app.services import gmail_service as gs
                found = gs.search_messages(settings, account=acct, query=query, max_results=limit)
            except Exception as exc:
                # Never silent. A bare `continue` made a real failure look exactly like "no
                # order mail in this window", which is how this path returned nothing for
                # every charge without anyone being able to say why.
                if os.environ.get("_EMAIL_ORDER_DEBUG"):
                    print("_email_order_match: %s -> %s: %s"
                          % (acct, type(exc).__name__, str(exc)[:160]), file=sys.stderr)
                continue
            if os.environ.get("_EMAIL_ORDER_DEBUG"):
                print("_email_order_match: %s -> %d message(s) for %r"
                      % (acct, len(found or []), query), file=sys.stderr)
            for m in (found or []):
                if not isinstance(m, dict):
                    continue
                subj = str(m.get("subject") or "")
                if not _ORDERISH.search(subj):
                    continue
                text = subj + " " + str(m.get("snippet") or "")
                mid = m.get("id") or m.get("message_id")
                ids = _ORDER_ID.findall(text)
                if not ids and mid:
                    try:
                        full = gs.read_message(settings, message_id=mid, account=acct)
                        ids = _ORDER_ID.findall(json.dumps(full)[:20000])
                    except Exception:
                        ids = []
                if ids:
                    stamp = str(m.get("date") or "")[:19]
                    what = re.sub(r"^\s*\d+\s*", "", subj).strip()
                    seen.setdefault(ids[0], (stamp, what))
    finally:
        if _app_cwd:
            try:
                os.chdir(_app_cwd)
            except Exception:
                pass
    if seen:
        # Several orders on one day is normal (three on 2026-09-28). Report all of them
        # with the limitation stated, rather than one id as though it were the answer:
        # the mail carries no price, so the amount cannot pick between them.
        if seen:
            items = sorted(seen.items(), key=lambda kv: kv[1][0])
            first_id, (first_stamp, first_what) = items[0]
            what = re.sub(r"^\s*\d+\s*", "", first_what or "").strip()
            # Trim the item hint to its first comma-clause: "Delivered 2 items: Plumbing,
            # Bathroom Fixtures" -> "Plumbing". The category is the useful part.
            if ":" in what:
                what = what.split(":", 1)[1]
            what = what.split(",")[0].strip()[:22]
            line = "order %s" % first_id
            if what:
                line += " (%s)" % what
            if len(items) > 1:
                # Cannot choose, so do not pretend to. The count is the honest answer.
                result = ("%d Amazon orders in this window - cannot tell which from mail"
                          % len(items))
                _email_cache_put(when, result)
                return result
            result = "%s (via email)" % line
            _email_cache_put(when, result)
            return result
    _email_cache_put(when, "")
    return ""


def _is_amazon_merchant(merchant: str) -> bool:
    """Is this charge an Amazon one? The mail fallback is Amazon-only by construction."""
    low = (merchant or "").lower()
    return "amazon" in low or "amzn" in low or "amz " in low


def compose(conn, merchant_key: str, *, window_days: int = 21,
            order_lines: list | None = None) -> str | None:
    """The message body for one merchant, or None if there is nothing to ask."""
    since = (date.today() - timedelta(days=window_days)).isoformat()
    rows = conn.execute(
        """SELECT id, transaction_date, amount_cents, account_id, account_name,
                  raw_payload_json, normalized_merchant
             FROM transactions
            WHERE normalized_merchant = ?
              AND duplicate_of_transaction_id IS NULL
              AND transaction_date >= ?
            ORDER BY amount_cents DESC""",
        (merchant_key, since),
    ).fetchall()
    if not rows:
        return None
    top = rows[0]                      # the biggest single charge - that is the ask
    others = rows[1:]

    card = card_last4(top, conn)
    bank = bank_words(top)
    when = fmt_day(top["transaction_date"])
    merchant = _pretty(top["normalized_merchant"] or "")
    match = order_match(conn, top["amount_cents"], top["transaction_date"] or "")
    if not match and _is_amazon_merchant(merchant):
        # The ledger's order feed is stale (measured 2026-10-02: nothing after 2026-09-10
        # while charges kept arriving). For an AMAZON charge the owner's own mail still has
        # an order id, so ask it before giving up -- and label it, because it is weaker
        # evidence. Gated on the merchant: this searches `from:amazon.com`, so it can only
        # speak about an Amazon charge. Without the gate it put "5 Amazon orders that day"
        # on a Data Reclos question.
        try:
            match = _email_order_match(top["transaction_date"] or "")
        except Exception:
            match = ""

    head = "CFO: %s at %s on %s" % (fmt_money(top["amount_cents"]), merchant, when)
    if card:
        head += ", card ending %s" % card
    head += "."

    # THE QUESTION MARK IS LOAD-BEARING, not punctuation. `textsend` opens the owner's
    # one-at-a-time turn only when the body actually asks something. Its own record on the
    # 2026-10-15 asks: "no turn opened: the body asks nothing (no question mark), so the
    # one-at-a-time rule does not apply". So every CFO ask was EXEMPT from the single-ask
    # protection, and the daily cap of 3 was the only brake left -- three charge questions
    # went to him at 00:00, 01:00 and 02:00 on 2026-10-15, and his reply to one of them was
    # "Didn't we already go through that...". Measured before this change, in asks.db:
    # `pass` 135.33 composed TEN times over 21 hours, and five of the last twenty charges
    # were composed twice. Ending in "?" is what lets the one-at-a-time rule engage.
    #
    # AND IT SAYS WHY HE IS BEING ASKED. The old close ("No guess from me - say what it was
    # and I'll file it for good.") tells him there was no guess but not that the ledger, his
    # mail and his earlier answers were consulted first. What it must NOT do is claim a rung
    # ran: this composer has no view of the resolver, so it states only what is true here --
    # no guess was reachable.
    ask = "No guess from me - what was it? One line and I'll file it for good."
    detail = []
    # The order mail that NAMES THE ITEM (ledger item 114). It goes first because it is the most
    # load-bearing detail: the ceiling loop below drops from the end, and "order #419077624 - Dell
    # Latitude 7430" is what lets the owner answer at a glance instead of being asked what his own
    # mailbox already says.
    for line in (order_lines or [])[:2]:
        detail.append(line if line.endswith(".") else line + ".")
    email = email_match(merchant, top["transaction_date"] or "")
    if email:
        detail.append("Email: %s" % email)
    if bank:
        detail.append("Statement says: %s." % bank)
    if match:
        detail.append(match + ".")
    if others:
        sib = ", ".join("%s on %s" % (fmt_money(r["amount_cents"]), fmt_day(r["transaction_date"]))
                        for r in others[:3])
        detail.append("Also this merchant: %s." % sib)

    # Fit the ceiling by dropping the least load-bearing detail first.
    for keep in (len(detail), 2, 1, 0):
        body = "\n".join([head] + detail[:keep] + [ask])
        if len(body) <= MAX_BODY:
            return body
    return "\n".join([head, ask])


if __name__ == "__main__":
    import sys
    conn = _c()
    keys = sys.argv[1:] or ["data reclos", "the home depot", "amazon order total",
                            "esti's world of fashion", "newegg", "polka dot"]
    for k in keys:
        body = compose(conn, k)
        print("=" * 72)
        print("merchant: %r   chars: %s" % (k, len(body) if body else 0))
        print("-" * 72)
        print(body or "(nothing to ask)")
    conn.close()

