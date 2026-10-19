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
  what was checked the resolver's `checked` / `evidence` lists, rendered as ONE
                  clause naming the sources that came back empty. Absent lists
                  produce NO clause: a claim of diligence that did not happen is
                  worse than no claim.
  one ask         one charge, one amount, one date, one card, one evidence line,
                  and a question about what the charge was FOR.

What it deliberately does NOT put in, and why each one is gone (four measured
defects, all quoted from the owner):
  a guess         "My guess: shop supplies. Reply 'yes'" was wrong for the DeepSeek
                  API, for Polka Dot (a holiday dress), for Newegg (a laptop) and
                  for Home Depot. "why do you even have to ask me" (2026-10-02).
                  Guessing at his money and asking him to confirm the guess is the
                  thing he called stupid; no guess is emitted, ever, and no offer to
                  file one.
  siblings        "Also this merchant: 12.00 on 3 Oct, 9.99 on 1 Oct" put a second
                  amount and a second date in a one-charge question.
  email subjects  "part of an email" in a CFO question (2026-10-05). Only an order
                  number from a receipt email survives.
  counts          "(+1 more)" and "3 charges ... total". "what's the plus one more".
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
#: The hard ceiling `render()` enforces on any body it returns.
RENDER_CEILING = 320
#: What `compose()` composes to. textsend's own owner ceiling is 320, and cfo-ask
#: turns the leading "CFO:" into "CFO [ask-1792026036]:" (+11 characters) AFTER this
#: module returns, so the headroom is spent on the reference the owner needs in order
#: to answer. Keeping the two numbers apart is deliberate: the composer aims lower than
#: the ceiling, and the renderer refuses to cross it.
MAX_BODY = 300
#: The question. It asks what the purchase was FOR -- never what the merchant is, which
#: is what the descriptor already says. See THE DESCRIPTOR, in merchant_resolve.
DEFAULT_ASK = "What was this purchase for?"
#: The question when the resolver already knows what the charge is (category/descriptor).
#: "Why can't you figure that out?" (2026-10-18, about PASSNY TOLLBYMAI). It did figure
#: it out, so the only thing left to establish is whether the reading is right.
KNOWN_ASK = "Is that right?"

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


# ── what may go in a body, and what may never go in one ─────────────────────
#
# 1. NO GUESS, AND NO OFFER TO FILE ONE. "My guess: shop supplies. Reply 'yes' - or tell
#    me what it was and I'll file it for good." It was wrong for the DeepSeek API, Polka
#    Dot, Newegg and Home Depot, and the answer path parsed the phrase back out as a
#    category the ledger does not have ("shop supplies" is not an lpt category and never
#    was). He said it twice: "why do you even have to ask me" (2026-10-02) and "you should
#    research your questions before asking them to me for no reason" (2026-10-13). So the
#    guess phrase, and its successor "No guess from me", are both dropped from any body
#    this module returns -- including a body built by an older version of it.
#
# 2. SAY WHAT WAS CHECKED. "exhaust all of the resources for exploring it, and then if you
#    still don't know, give me all the details you found" (2026-10-16). The body gets ONE
#    clause naming the sources that ran and came back empty. It is built from the
#    resolver's own `checked` list, so it can only name a source that really ran; an empty
#    list renders NO clause at all.
#
# 3. ONE QUESTION, ONE THING. "That was confusing why are you mixing a CFO question and
#    part of an email and then what's the plus one more" (2026-10-05). One charge, one
#    amount, one date, one card, at most one supporting line.
#
# 4. FIT THE CEILING WITHOUT CUTTING A WORD. `render()` drops evidence to fit and only
#    then shortens the merchant, at a word boundary, keeping the amount, the date, the
#    card and the question mark -- a body that names no card is refused by ask_quality,
#    and a body with no question is refused by textsend's one-at-a-time rule.

#: A sentence that offers a guess or asks him to confirm one. Dropped wholesale.
_GUESS_SENTENCE = re.compile(
    r"(?:^|(?<=[.!?]))\s*"
    r"(?:my guess|guess:|no guess from me|i'?d file it as)\b[^.!?\n]*[.!?]?", re.I | re.M)
#: The tail that came after it: "One line and I'll file it for good."
_FILE_OFFER = re.compile(r"\s*One line and I'?ll file it for good\.?", re.I)
#: The other half of the old offer: "Reply 'yes' - or tell me what it was and I'll file it
#: for good." Left in, it re-asks the identity question the guess was standing in for.
_REPLY_YES = re.compile(r"(?:^|(?<=[.!?]))\s*Reply\s+'?\"?yes'?\"?\b[^.!?\n]*[.!?]?", re.I | re.M)
_SHOP_SUPPLIES = re.compile(r"\bshop supplies\b", re.I)
#: A SECOND merchant, announced or not. "Also this merchant: 12.00 on 3 Oct".
_ALSO_MERCHANT = re.compile(r"(?:^|(?<=[.!?]))\s*also this merchant\b[^.!?\n]*[.!?]?", re.I | re.M)
#: A grouped total: "3 charges, 357.18 total" - a second amount in a one-charge question.
_COUNT_CLAUSE = re.compile(r"(?:^|(?<=[.!?]))\s*\d+\s+charges?,.*?\btotal\b[^.!?\n]*[.!?]?", re.I | re.M)
#: A mail line. The subject is stripped; only an order number survives (see _email_evidence).
#: Matched to the END OF ITS LINE on purpose: an address like "chase.com" carries a dot, and
#: stopping at the first sentence end left "com - Your receipt for the order you placed" in
#: the body -- the exact fragment he called confusing on 2026-10-05.
_EMAIL_CLAUSE = re.compile(r"(?:^|(?<=[.!?]))\s*(?:e-?mail|mail)\s*:[^\n]*", re.I | re.M)
#: "(+1 more)" - a message count, not evidence.
_MORE_COUNT = re.compile(r"\s*\(\s*\+\s*\d+\s+more\s*\)", re.I)
#: An amount as the body prints it. Used to prove ONE amount per body.
_AMOUNT_ONE = re.compile(r"(?:^|[\s(])\$?\s*(\d{1,3}(?:,\d{3})*\.\d{2}|\d+\.\d{2})\b")
_CARD_ONE = re.compile(r"card ending (\d{2,4})", re.I)
#: An order number, in the three shapes the vendors actually use.
_ORDERISH_ID = re.compile(r"#[\w-]{4,}|\b\d{3}-\d{7}-\d{7}\b|\b\d{8,12}\b")

#: Which `checked` line means which source, most specific prefix first. A method that
#: FAILED must never be claimed as checked, so lines saying so are skipped below.
_SOURCE_PREFIXES: tuple[tuple[str, str], ...] = (
    ("records:owner-answer", "your past answers"),
    ("records:owner-text", "your texts"),
    ("records:vendor-list", "our vendor list"),
    ("records:order-match", "our order records"),
    ("records:ledger", "our ledger"),
    ("research:web", "the web"),
    ("research:model", "the web"),
    ("owner_answer", "your past answers"),
    ("aliases", "your past answers"),
    ("receipts", "the receipts"),
    ("orders", "the order mail"),
    ("comms", "our texts and calls"),
    ("docs", "the documents"),
    ("ledger", "our ledger"),
    ("web", "the web"),
)
#: The reading order of those sources in the clause.
_SOURCE_ORDER = ("our ledger", "your past answers", "your texts", "the receipts",
                 "the order mail", "our order records", "our vendor list",
                 "our texts and calls", "the documents", "the web")
#: A `checked` line whose detail says this did NOT run, and so must not be claimed.
_NOT_CHECKED = ("failed", "error", "skipped", "absent", "unavailable", "not configured",
                "no model", "unreadable")


def _tidy(text: str) -> str:
    """Collapse whitespace and the punctuation the strippers leave behind."""
    t = re.sub(r"\s+", " ", text or "").strip()
    t = re.sub(r"\s+([.,;:?!])", r"\1", t)
    t = re.sub(r"([.,])\1+", r"\1", t)
    return t


def _capitalise(text: str) -> str:
    t = (text or "").strip()
    return (t[0].upper() + t[1:]) if t else t


def _amounts_cents(text: str) -> list:
    """Every amount in `text`, as cents."""
    out = []
    for m in _AMOUNT_ONE.finditer(text or ""):
        try:
            out.append(int(round(float(m.group(1).replace(",", "")) * 100)))
        except ValueError:
            continue
    return out


def _clause(text: str, limit: int = 72, *, lower: bool = True) -> str:
    """A short fact for the middle of the checked clause: no trailing stop, no cut word."""
    t = re.sub(r"\s+", " ", str(text or "")).strip().rstrip(" .;:,")
    if len(t) > limit:
        t = t[:limit]
        t = t.rsplit(" ", 1)[0] if " " in t else t
        t = t.rstrip(" ,;:.-")
    # "Our ledger..." reads as a claim of its own inside a sentence; "our ledger..." does not.
    # A category name is exempt: "tolls & Travel" is not a name the ledger has.
    if lower and t and t[0].isupper() and not (len(t) > 1 and t[1].isupper()):
        t = t[0].lower() + t[1:]
    if t.count("(") > t.count(")"):
        t = t[:t.rfind(" (")].rstrip(" ,;:.-")
    return t


def _email_evidence(line: str) -> str:
    """The order-bearing fact from a mail line -- NEVER the subject.

    `email_match()` returns "2026-10-05 (+1 more) chase.com - Your receipt for ...", which
    is the thing he called confusing. What is worth a text is the order number.
    """
    ids = _ORDERISH_ID.findall(line or "")
    if ids:
        return "the receipts show order %s" % ids[0].lstrip("#")
    dom = re.search(r"\b([a-z0-9-]+(?:\.[a-z0-9-]+)+)\b", (line or "").lower())
    if dom:
        return "the receipts are from %s" % dom.group(1)
    return ""


def sources_phrase(checked) -> str:
    """The human words for what was consulted: "our ledger, your past answers and the receipts".

    Empty when nothing was really checked. A rung that failed or was skipped names no
    source: "we could not look" and "it is not there" are different sentences, and only
    the second one belongs in a question.
    """
    found: set = set()
    for line in (checked or []):
        low = re.sub(r"\s+", " ", str(line or "")).strip().lower()
        if not low:
            continue
        for prefix, word in _SOURCE_PREFIXES:
            if low.startswith(prefix):
                rest = low[len(prefix):].lstrip(": -")
                if any(bad in rest[:40] for bad in _NOT_CHECKED):
                    break                     # it did not run; do not claim it
                found.add(word)
                break
    words = [w for w in _SOURCE_ORDER if w in found][:3]
    if not words:
        return ""
    if len(words) == 1:
        return words[0]
    return ", ".join(words[:-1]) + " and " + words[-1]


def checked_clause(checked, found: str = "", *,
                   nothing: str = "the descriptor is all I have") -> str:
    """ONE clause: what was consulted, and what came back.

    "" when there is no record of anything being checked -- the empty string is the
    correct answer there, because inventing diligence is worse than showing none.
    """
    src = sources_phrase(checked)
    if not src:
        return ""
    if found:
        return "I checked %s - %s." % (src, _clause(found))
    return "I checked %s - %s." % (src, nothing)


def _strongest(*, order_lines=(), category: str = "", entity: str = "",
               category_source: str = "", extras=(), evidence=()) -> str:
    """The single strongest thing found, phrased as the tail of the checked clause.

    Order is by how much it tells the owner about THIS charge: an item named by the order
    mail beats a category, which beats anything else the resolver read.
    """
    for line in (order_lines or []):
        line = str(line or "").strip()
        if not line:
            continue
        pretty = re.sub(r"\s+[-–—]\s+", " (", line, count=1)
        if pretty != line:
            pretty += ")"
        return "the order mail has " + _clause(pretty, 64)
    known = _clause(category or entity, 40, lower=False)
    if known:
        if "descriptor" in (category_source or "").lower():
            return "the statement descriptor names " + known
        return "our records point to " + known
    for x in (extras or []):
        if str(x or "").strip():
            return _clause(x, 72)
    for e in (evidence or []):
        if str(e or "").strip():
            return _clause(e, 72)
    return ""


def _join(parts) -> str:
    out = ""
    for p in parts:
        p = (p or "").strip()
        if not p:
            continue
        if out:
            out += " "
        out += p
    return out


def _clip_words(text: str, room: int, *, terminator: str = ".") -> str:
    """`text` cut to <= room characters at a WORD boundary, closed as a sentence.

    A cut word is not a shorter sentence, it is a different one: "Hangzhou Deepseek
    Artificial Intellig" is not a merchant. So the cut always backs off to whitespace.
    """
    t = (text or "").strip()
    if room <= 1:
        return terminator
    if len(t) <= room:
        return t if t[-1:] in (".", "?", "!") else t + terminator
    cut = t[:room]
    # mid-word? drop the partial token entirely.
    if room < len(t) and t[room] not in " \n" and cut[-1:] not in (" ", "\n"):
        cut = cut.rsplit(" ", 1)[0] if " " in cut else ""
    cut = cut.rstrip(" ,;:.-")
    if not cut:
        return terminator
    if cut[-1] not in (".", "?", "!"):
        cut += terminator
    return cut


def _shorten_merchant(head: str, room: int) -> str:
    """Shorten the merchant name, whole words at a time, keeping everything else.

    The card and the date are the parts `ask_quality` and the owner both need to identify
    the charge, so they are never what gets cut first.
    """
    m = re.search(r"(\s+at\s+)(.+?)(\s+on\s+)", head or "")
    if not m:
        return _clip_words(head, room)
    words = m.group(2).split()
    out = head
    while len(words) > 1 and len(out) > room:
        words.pop()
        out = re.sub(r"(\s+at\s+)(.+?)(\s+on\s+)",
                     lambda mm, w=" ".join(words): mm.group(1) + w + mm.group(3),
                     head, count=1)
    return _clip_words(out, room)


def render(head: str, *, evidence=None, ask: str = DEFAULT_ASK,
           limit: int = RENDER_CEILING) -> str:
    """Assemble ONE body under a hard ceiling, without ever truncating a word.

    Order of what gives way, and why: evidence first (it is the least load-bearing and the
    thing he said must not push out the question), then the merchant name, word by word.
    The amount, the date, the card and the question mark survive, because a body without
    a card is refused by `ask_quality.review()` and a body without a question never opens
    the owner's one-at-a-time turn in `textsend`.
    """
    head = (head or "").strip()
    ask = (ask or DEFAULT_ASK).strip()
    if ask and ask[-1] not in (".", "?", "!"):
        ask += "?"
    ev = [e.strip() for e in (evidence or []) if e and str(e).strip()]
    while ev and len(_join([head] + ev + [ask])) > limit:
        ev.pop()
    body = _join([head] + ev + [ask])
    if len(body) <= limit:
        return body
    room = max(12, limit - len(ask) - 1)
    body = _join([_shorten_merchant(head, room), ask])
    if len(body) <= limit:
        return body
    return _join([_clip_words(head, room), ask])


def enforce_one_charge(body: str) -> str:
    """ONE charge: one amount, one date, one card, at most one supporting line.

    Structural, not cosmetic -- it takes a body, including one composed by an older version
    of this file, and returns the version that asks about a single charge. Every clause it
    removes has a measured complaint behind it: the guess ("why do you even have to ask
    me"), the email subject and the "+1 more" ("why are you mixing a CFO question and part
    of an email and then what's the plus one more"), and the second merchant ("also this
    merchant: 12.00 on 3 Oct").
    """
    text = re.sub(r"\r", "", body or "")
    mail_fact = ""
    m = _EMAIL_CLAUSE.search(text)
    if m:
        mail_fact = _email_evidence(m.group(0))     # the order number, not the subject
    text = _GUESS_SENTENCE.sub(" ", text)
    text = _SHOP_SUPPLIES.sub(" ", text)
    text = _FILE_OFFER.sub(" ", text)
    text = _REPLY_YES.sub(" ", text)
    text = _ALSO_MERCHANT.sub(" ", text)
    text = _COUNT_CLAUSE.sub(" ", text)
    text = _EMAIL_CLAUSE.sub(" ", text)
    text = _MORE_COUNT.sub("", text)

    parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+|\n+", text) if p.strip()]
    if not parts:
        return _tidy(mail_fact + ".") if mail_fact else ""
    # THE QUESTION IS NOT EVIDENCE, and it is never what gives way. It is the last
    # sentence, and its question mark is the only thing that opens the owner's
    # one-at-a-time turn in `textsend`: a body trimmed past it is a body
    # `textsend` treats as "asks nothing" and lets a second ask through.
    ask = ""
    if len(parts) > 1 and parts[-1].rstrip().endswith("?"):
        ask = parts.pop()
    head, tail = parts[0], parts[1:]
    head_amounts = _amounts_cents(head)
    head_card = (_CARD_ONE.search(head).group(1) if _CARD_ONE.search(head) else "")
    keep: list = []
    for p in tail:
        amounts = _amounts_cents(p)
        # A different amount is a different charge: it does not belong in this question.
        if head_amounts and any(a != head_amounts[0] for a in amounts):
            continue
        c = _CARD_ONE.search(p)
        if c and head_card and c.group(1) != head_card:
            continue
        keep.append(p)
        break                                       # ONE supporting line, never two
    if not keep and not ask and mail_fact:
        keep = [_capitalise(mail_fact) + "."]
    out = _tidy(_join([head] + keep + ([ask] if ask else [])))
    if "?" not in out:
        out = _tidy(_join([out, DEFAULT_ASK]))
    return out


def build_body(amount_cents, merchant: str, when: str, card: str = "", *,
               checked=(), evidence=(), order_lines=(), category: str = "",
               entity: str = "", category_source: str = "", extras=(),
               ask: str | None = None, prefix: str = "CFO: ",
               limit: int = RENDER_CEILING) -> str:
    """The body for ONE charge. Pure: every input is handed in.

    No ledger, no mailbox, no clock, so a test can render the exact body a charge would
    produce -- which is the only way to assert what the owner will actually read.
    """
    merchant = _pretty(merchant or "")
    head = "%s%s at %s on %s" % (prefix, fmt_money(amount_cents), merchant, when or "?")
    if card:
        head += ", card ending %s" % card
    head = head.rstrip(" ,") + "."
    found = _strongest(order_lines=order_lines, category=category, entity=entity,
                       category_source=category_source, extras=extras, evidence=evidence)
    clause = checked_clause(checked, found)
    if not clause and found:
        # A fact with no record of where it came from is stated plainly, not under an
        # "I checked" that would be a claim about work nobody logged.
        clause = _capitalise(found) + "."
    if ask is None:
        ask = KNOWN_ASK if (category or entity) and found else DEFAULT_ASK
    body = render(head, evidence=[clause] if clause else [], ask=ask, limit=limit)
    return enforce_one_charge(body)


def compose(conn, merchant_key: str, *, window_days: int = 21,
            order_lines: list | None = None,
            checked: list | None = None,
            evidence: list | None = None,
            category: str = "",
            entity: str = "",
            category_source: str = "",
            exclude_ids=None,
            limit: int = MAX_BODY) -> str | None:
    """The message body for one merchant, or None if there is nothing to ask.

    `checked` / `evidence` are the resolver's own record of what it read and what it found;
    they are what makes the body say WHY he is being asked. `category` / `entity` are what
    the resolver decided even when it was not sure enough to stop the question -- handed
    in, the body states them instead of asking what the charge was.

    `exclude_ids` are transactions this merchant has already been asked about, so a second
    question about the same shop asks about a DIFFERENT charge (defect: the ask used to be
    suppressed for the merchant for ever, see cfo-ask's charge-keyed suppression).
    """
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
    excluded = {str(x) for x in (exclude_ids or ()) if str(x or "").strip()}
    if excluded:
        fresh = [r for r in rows if str(r["id"]) not in excluded]
        if fresh:
            rows = fresh
    top = rows[0]                      # the biggest charge not already asked about

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
    email = email_match(merchant, top["transaction_date"] or "")

    # The extra facts, strongest first. Each is one short phrase, never a sentence of its
    # own: `render()` has room for one clause and this is the list it chooses from.
    extras = []
    if match:
        extras.append("our order records have %s" % _clause(match, 60))
    mail_fact = _email_evidence(email) if email else ""
    if mail_fact:
        extras.append(mail_fact)
    if bank:
        extras.append("the bank's own line reads %s" % _clause(bank, 40))

    return build_body(
        top["amount_cents"], merchant, when, card,
        checked=checked or (), evidence=evidence or (),
        order_lines=order_lines or (), category=category, entity=entity,
        category_source=category_source, extras=extras, limit=limit)


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

