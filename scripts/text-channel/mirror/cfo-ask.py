#!/usr/bin/env python3
"""cfo-ask.py — the CFO's mouth: ask the owner about ONE unclear purchase, by text.

WHY THIS EXISTS
---------------
The owner's instruction, 2026-09-30: *"the cfo is constantly working and classifying
behind the scenes ... especially live, it should ask me purchases it's unsure about ...
this way when i still remember the purchase i can give info on what and who it's for,
and it should be very good at documenting this ... which shouldn't be blocked unless
it's way too much."*

Everything needed for this already existed except the mouth. The classifier leaves an
unmatched row `active` with no category and a schema that has no state meaning "waiting
for the owner"; the owner question list was a Python dict printed to stdout and never
written to a table. This is the missing piece: it takes a real unclarified purchase out
of the ledger, turns it into one short question with a recommendation, and sends it —
capped, deduped, and durably recorded.

WHO IT TEXTS
------------
The owner, and only the owner. `textsend.can_send_to` opens for exactly two cases: the
recipient IS an owner number, or third-party sending is explicitly enabled AND the
ledger says `allow=auto`. This script only ever addresses an owner number, so the
third-party gate is never in play. The stop that matters — "nothing outbound without
explicit approval of the exact words" — is about OTHER PEOPLE; the owner is the
recipient of his own system, and he said so plainly.

WHY IT IS CAPPED, AND AT WHAT
-----------------------------
His words: "shouldn't be blocked unless it's way too much". The arithmetic:
263-323 card/bank movements a month is ~10 a day; 65-74% classify; most of the
remainder is repeats of merchants already answered. So the genuine ask rate is one to
three genuinely new, genuinely uncertain purchases a day, and it decays. Hence
MAX_PER_DAY = 3, MIN_GAP_MINUTES = 45, and NEVER THE SAME MERCHANT TWICE
WITHIN THE WINDOW -- a question that went out and was not answered comes back
after REASK_AFTER_HOURS (48 h by default), up to MAX_ASKS_PER_MERCHANT (3),
and then stops. Changed 2026-10-16 at the owner's instruction: "why not, it can
ask a day or 2 later." Before this, `sent = 1` suppressed that merchant for ever
and an unanswered question was simply dead

WHAT IT WILL NOT ASK ABOUT
--------------------------
Transfers, card payments, processor settlements, deposits, payroll and fees are not
questions for a human — they are money movement the rulebook is supposed to handle.
Asking the owner "what was the Stripe payout for?" trains him to ignore the channel.
They are excluded by shape, and the exclusion list is data at the top of this file so
it can be argued with rather than guessed at.

HOW IT IS DOCUMENTED
--------------------
Every ask is written to its own store (`~/.cfo-asks/asks.db`) — a store this script
owns, so a write lock on the 13 GiB app database cannot silently swallow it — with the
transaction id, merchant, amount, the exact body sent, the provider's reply, and the
sid. And a row is written into the ledger's own evidence table when that database is
writable. An answer is matched back by the `#ask-<n>` reference in the body, which is
what makes two outstanding questions safe.

`cfo_clarify.py` (added 2026-10-13) makes that record the DURABLE CLARIFICATION the loop was
missing: one row per question, with the state (`asked` / `answered` / `expired` /
`superseded`), the cluster and the charges it covers, the exact body sent, the outbound
message id, his answer, how the answer was matched, and the rule it produced.
`record_question()` is called BEFORE the sender is called, so a question that is on his phone
is one this record knows about; `cfo_clarify.answer_from_reply()` turns his reply into a
`created_by='owner'` rule that stops the same merchant ever being asked again. Until
2026-10-13 nothing wrote an answer back at all: the `answered_at` / `answer` columns existed
in this file's own schema and not one statement in the whole reachable codebase ever set them.

RESOLVE BEFORE ASKING (added 2026-10-02, after the owner's complaint)
--------------------------------------------------------------------
"you could do a little more research before you ask the questions ... you could've
googled it probably and of course it's shop supplies". Two of the questions he was sent
that day were answerable from our own records: `Data Reclos` IS `$300 Data Recovery`
(25 charges since Apr 2025, receipts, tickets) and the Hangzhou merchant IS the DeepSeek
API that runs this company. So before composing anything, each candidate goes through
`merchant_resolve.resolve()`. A merchant it solves at or above RESOLVE_CONFIDENCE is
recorded with `auto_resolved=1` and `resolution_json`, NO text is sent, and the asker
moves to the next candidate. Nothing is filed into the ledger from here: the sanctioned
writer is the app's own rule engine (`app/services/auto_categorize.py::run_auto_categorize`),
and where it has no rule yet the exact `transaction_categories` row a filer would need is
printed instead of written. `--status` lists those pending filings.

Everything this composes also passes `ask_quality.review()` — one gate, shared with the
other two askers — so an internal instruction, a body naming no card, or a merchant
already put to him cannot leave this process.

USAGE
    cfo-ask.py                     dry run: choose, compose, print, send nothing
    cfo-ask.py --send              send one question if one is due
    cfo-ask.py --status            what has been asked, and what is due next
    cfo-ask.py --why               explain the current choice in detail

EXIT CODE (tri-state, this repo's contract)
    0                 the job did its work: a question was accepted, there was nothing due, or
                      every candidate was answered from our own records;
    CONDITION_EXIT(3) `textsend.py` refused because the OWNER has an unanswered question open
                      (his own one-at-a-time rule). A real finding this asker cannot clear --
                      answering it is HIS act -- so `bin/sources/cron-failures.py` must not file
                      a repair session for a streak of it. The cause is echoed to stderr so
                      ~/.cron-status/runs.tsv carries a reason instead of a blank column;
    1                 a FAULT: textsend crashed, the provider failed, a timeout, or the body was
                      refused by our own gate in a way that needs a look. A fault always wins.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# The campaign modules, imported DEFENSIVELY: a partial deployment (this file copied
# before its siblings) must degrade to the old behaviour, never crash an asker that cron
# is running.
try:
    import merchant_resolve
except ImportError:                                        # pragma: no cover
    merchant_resolve = None
try:
    import ask_quality
except ImportError:                                        # pragma: no cover
    ask_quality = None
try:
    import cfo_clarify
except ImportError:                                        # pragma: no cover
    cfo_clarify = None

HOME = Path.home()
ACCT_DB = Path(os.environ.get("CFO_ACCT_DB", HOME / "accounting-data/live/accounting.db"))
APP_ENV = Path(os.environ.get("CFO_APP_ENV", HOME / "personal-secretary-mvp/.env"))
ASK_DB = Path(os.environ.get("CFO_ASK_DB", HOME / ".cfo-asks/asks.db"))
# The OTHER asker (`~/bin/owner-ask.py`, cron */30) asks the owner about
# owner-decision rows AND about purchases, from the same ledger. Two askers,
# one channel, so the record of "already asked" has to be shared or the owner
# gets one charge twice -- measured 2026-10-02, `P2830`.
OWNER_ASK_DB = Path(os.environ.get("OWNER_ASK_DB", HOME / ".owner-ask/asks.db"))
# Overridable ONLY so this loop can be exercised end to end against a STUB sender that
# writes to a file instead of a phone. The deployed default is unchanged and is the real AI
# line; nothing in production sets CFO_TEXTSEND.
TEXTSEND = Path(os.environ.get("CFO_TEXTSEND", HOME / "bin/textsend.py"))

MAX_PER_DAY = int(os.environ.get("CFO_ASK_MAX_PER_DAY", "3"))

#: How long a question that WENT OUT and was not answered keeps that merchant closed.
#: The owner, 2026-10-16, on being told the design never re-asks: "why not, it can ask a
#: day or 2 later". Two days, and the same number governs how long the waiting
#: clarification stays open, so exactly ONE question per merchant is ever outstanding --
#: two waiting clarifications for one shop would make his single reply ambiguous and
#: could lose the answer instead of resolving it.
REASK_AFTER_HOURS = float(os.environ.get("CFO_ASK_REASK_HOURS", "48"))

#: After this many asks about one merchant, all unanswered, it stops asking -- one ask and
#: one retry. The SHAPE is the ladder `owner-ask.py` has used since 2026-10-11 ("at most 1
#: retry, >=24 h later, then stop"); the window here is 48 h because the owner said "a day or
#: 2 later". Bounded on purpose: an alarm that is permanently true is one he learns to
#: ignore, which is the failure P2926 recorded for the money plane.
MAX_ASKS_PER_MERCHANT = int(os.environ.get("CFO_ASK_MAX_ASKS_PER_MERCHANT", "2"))
MIN_GAP_MINUTES = int(os.environ.get("CFO_ASK_MIN_GAP_MINUTES", "45"))
RECENT_DAYS = int(os.environ.get("CFO_ASK_RECENT_DAYS", "21"))
MIN_AMOUNT_CENTS = int(os.environ.get("CFO_ASK_MIN_AMOUNT_CENTS", "2500"))

# How sure `merchant_resolve` has to be before this asker stays silent instead of asking.
# THE ARITHMETIC (see merchant_resolve.CONF_* for the whole table): an alias the owner
# taught us 0.97 · a small in-file business vendor list 0.93 · an ask he already answered
# 0.92 · >=2 prior categorisations of the merchant in our own ledger 0.90. One prior
# categorisation is 0.80 and a receipt alone is 0.70 — both are evidence, neither is an
# answer, so they ride along in the question instead of replacing it. The threshold sits
# at 0.85: above everything we merely suspect, below everything our own records already
# know. Overridable, because it is a judgement and not a law.
RESOLVE_CONFIDENCE = float(os.environ.get("CFO_RESOLVE_CONFIDENCE", "0.85"))
# Candidates looked at per run: each one may cost a resolve, and the walk stops anyway as
# soon as one genuinely needs a human.
RESOLVE_TRIES = int(os.environ.get("CFO_RESOLVE_TRIES", "5"))

# How long a question that did NOT reach him stops the selector picking it again.
# Item 104 (2026-10-14) made a definite refusal non-suppressing on purpose -- a question
# the sender refused is not an ask, and suppressing it forever meant he was never asked at
# all. The other half of that repair was missing: nothing re-armed it, so the same charge
# was RE-COMPOSED every 30 minutes indefinitely. Measured 2026-10-15 in asks.db:
# `pass` 135.33 was composed ten times between 06:00 and 03:01Z, nine refusals and one
# delivery, 21 hours later. Nine identical composition attempts buy nothing the first one
# did not settle -- the sender's refusal is about the CHANNEL being busy, not about this
# question, so the right response is to wait, not to retry at every tick.
#
# Six hours, chosen from the numbers around it: the sender's own owner floor is 20 minutes
# (`OWNER_TEXT_RELAY_MIN_GAP_MINUTES`), MIN_GAP_MINUTES here is 45, and the longest real
# silence a refused question waited before it finally went out was ~16 h (`sticky brand`
# 12:00:09 -> next day 00:00:45). Six hours is longer than any transient the channel
# produces and short enough that a genuine question still gets asked the same day.
REFUSAL_SILENCE_HOURS = float(os.environ.get("CFO_ASK_REFUSAL_SILENCE_HOURS", "6"))

#: How long the relay keeps a CFO ask open, so his reply can still be matched to it.
#: 72 h is the relay's own default; named here because the two stores must agree about how
#: long a question is answerable, or one of them expires a question the other still honours.
CFO_ASK_TTL_HOURS = float(os.environ.get(
    "CFO_ASK_TTL_HOURS", str(REASK_AFTER_HOURS)))

# Money movement and processor plumbing. Not a question for a human.
NOT_A_QUESTION = (
    "stripe", "gusto", "paypal-transaction", "automatic payment", "payment thank",
    "payment to chase", "atm cash deposit", "atm check deposit", "zelle", "venmo",
    "wire transfer", "internal transfer", "check deposit", "mobile deposit",
    "interest payment", "service charge", "monthly fee", "overdraft", "cash advance",
    "balance transfer", "refund", "reversal", "employee reimbursement", "payroll",
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS ask (
  id                 INTEGER PRIMARY KEY AUTOINCREMENT,
  asked_at           TEXT NOT NULL,
  entity_id          TEXT,
  account_name       TEXT,
  merchant           TEXT NOT NULL,
  merchant_key       TEXT NOT NULL,
  transaction_id     TEXT,
  transaction_date   TEXT,
  amount_cents       INTEGER,
  txn_count          INTEGER,
  total_cents        INTEGER,
  body               TEXT NOT NULL,
  reference          TEXT,
  sent               INTEGER NOT NULL DEFAULT 0,
  provider_ok        INTEGER,
  provider_sid       TEXT,
  provider_detail    TEXT,
  answered_at        TEXT,
  answer             TEXT,
  resolved_at        TEXT,
  -- Added 2026-10-02: `merchant_resolve` answered the question from our own records, so
  -- no text was sent. The row is the record of what we decided and why.
  auto_resolved      INTEGER NOT NULL DEFAULT 0,
  resolution_json    TEXT
);
CREATE INDEX IF NOT EXISTS ix_ask_merchant ON ask(merchant_key);
CREATE INDEX IF NOT EXISTS ix_ask_sent_at  ON ask(asked_at);
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
"""


# ─────────────────────────────── store ───────────────────────────────
def _migrate(c: sqlite3.Connection) -> None:
    """Bring an asks store written by an earlier version up to this schema.

    `CREATE TABLE IF NOT EXISTS` does nothing to a table that already exists, so the two
    new columns have to be added explicitly. Idempotent, and it never drops anything.
    """
    try:
        cols = {r["name"] for r in c.execute("PRAGMA table_info(ask)")}
    except sqlite3.Error:
        return
    for col, ddl in (
        ("auto_resolved", "ALTER TABLE ask ADD COLUMN auto_resolved INTEGER NOT NULL DEFAULT 0"),
        ("resolution_json", "ALTER TABLE ask ADD COLUMN resolution_json TEXT"),
    ):
        if col not in cols:
            try:
                c.execute(ddl)
            except sqlite3.Error:
                pass


def ask_conn() -> sqlite3.Connection:
    ASK_DB.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(ASK_DB, timeout=10)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA busy_timeout=8000")
    c.executescript(SCHEMA)
    _migrate(c)
    c.commit()
    return c


def merchant_key(name: str) -> str:
    key = re.sub(r"[^a-z0-9 ]+", " ", (name or "").lower())
    key = re.sub(r"\s+", " ", key).strip()
    # ONE MERCHANT, ONE KEY (item 74, 2026-10-13). A trailing corporate suffix split the
    # same shop into two keys -- measured in asks.db, 'back market' (id 5) and
    # 'back market inc' (ids 6, 7) for the same 357.18 at the same shop. The selector keys
    # its whole skip set on this string, so two spellings are two questions about one shop.
    key = re.sub(r"\s+(inc|llc|ltd|co|corp|incorporated|company|limited)\.?$", "", key)
    return key[:48]


def last_four_map(conn: sqlite3.Connection) -> dict:
    """account_id -> last four digits.

    The transactions.account_name string is NOT a unique card label: measured
    2026-10-01, 'Blue Cash Everyday(R)' is carried by BOTH personal-amex-22005 and
    personal-amex-94045, so a question that names only the account_name cannot say
    which card the owner is being asked about. accounts.last_four is per account_id,
    but it is stored MASKED and five digits long for these cards - measured
    2026-10-01: '94045' for personal-amex-94045, '22005' for personal-amex-22005 -
    so the value is cut to its final four before it is printed.

    AND WHEN accounts.last_four IS NULL, THE DIGITS ARE IN account_id ALREADY.
    Measured 2026-10-02: `personal-chase-4258` has no `last_four` row, so the ask went
    out as "what was 632.00 at esti's world of fashion on 25 Sep (CREDIT CARD)?" - an
    account_name that names no card at all, which is the defect that made the owner
    answer "which card it was come on" the day before. `charge_msg.card_last4` has always
    read the trailing digits out of the account_id; this map did not, and the asker used
    this map.
    """
    out: dict = {}
    for r in conn.execute(
        "SELECT id, last_four FROM accounts "
        "WHERE last_four IS NOT NULL AND TRIM(last_four) <> ''"
    ):
        digits = re.sub(r"[^0-9]", "", str(r["last_four"] or ""))
        if digits:
            out[r["id"]] = digits[-4:]
    return out


def card_for(account_id: str, account_name: str, last4: dict) -> str:
    """The last four of the card a charge is on: accounts.last_four, else account_id.

    Same precedence as `charge_msg.card_last4`, so the asker and the message composer
    cannot disagree about which card is being named.
    """
    digits = re.sub(r"[^0-9]", "", str(last4.get(account_id) or ""))
    if digits:
        return digits[-4:]
    m = re.search(r"(\d{4,})$", account_id or "")
    if m:
        return m.group(1)[-4:]
    m = re.search(r"\*(\d{4})\b", account_name or "")
    return m.group(1) if m else ""


# ─────────────────────────────── the ledger ───────────────────────────────
def _owner_asked_merchants() -> set:
    """Merchants `owner-ask.py` has already put to the owner. Never raises.

    Read-only, and empty on any failure: this is a courtesy to the owner, not a
    safety control, so it must never stop a question he is owed.
    """
    if not OWNER_ASK_DB.exists():
        return set()
    out = set()
    try:
        c = sqlite3.connect(f"file:{OWNER_ASK_DB}?mode=ro", uri=True, timeout=10)
        c.row_factory = sqlite3.Row
        try:
            rows = c.execute(
                "SELECT DISTINCT source_id FROM ask "
                "WHERE sent=1 AND source LIKE 'purchase%'").fetchall()
        finally:
            c.close()
    except Exception:
        return set()
    for r in rows:
        m = str(r["source_id"] or "")
        if m.startswith("m:"):
            m = m[2:]
        k = merchant_key(m)
        if k:
            out.add(k)
    return out


PARK_STORE = os.environ.get("CFO_PARK_STORE", "/root/.cfo/parked.jsonl")
# OFF by default: turning this on changes what the owner receives by text.
INCLUDE_PARKED = os.environ.get("CFO_ASK_INCLUDE_PARKED", "") == "1"
OWNER_REASON_KINDS = ("unknown_vertical", "evidence_missing", "no_merchant_name",
                      "direction_ambiguous")


def parked_candidates(last4: dict, limit: int = 40) -> list[dict]:
    """Parked clusters whose missing fact is the owner's, shaped like a candidate.

    Read-only and never fatal: a missing or unreadable store returns [] and the mouth behaves
    exactly as it did before. It opens its OWN connection on purpose: `candidates()` closes the
    caller's connection before it returns, and reusing it raised
    `sqlite3.ProgrammingError: Cannot operate on a closed database` (measured 2026-10-16).
    """
    if not os.path.exists(PARK_STORE):
        return []
    try:
        c = sqlite3.connect(f"file:{ACCT_DB}?mode=ro", uri=True, timeout=10)
        c.row_factory = sqlite3.Row
    except sqlite3.Error:
        return []
    try:
        with open(PARK_STORE, errors="replace") as fh:
            rows = [json.loads(l) for l in fh if l.strip()]
    except Exception:                                          # noqa: BLE001
        return []
    # the newest row per key wins, exactly as cfo-park.load_index() treats the store
    newest = {}
    for r in rows:
        if r.get("merchant_key"):
            newest[str(r["merchant_key"])] = r
    out = []
    for key, row in newest.items():
        if row.get("reason_kind") not in OWNER_REASON_KINDS:
            continue
        ids = list(row.get("txn_ids") or [])
        if not ids:
            continue
        marks = ",".join("?" * len(ids))
        t = c.execute(
            f"SELECT id, entity_id, account_id, account_name, transaction_date, amount_cents,"
            f" description, merchant_name FROM transactions WHERE id IN ({marks})"
            f" ORDER BY amount_cents DESC LIMIT 1", ids).fetchone()
        if not t:
            continue
        text = str(t["merchant_name"] or "").strip() or key.replace("desc:", "").strip()
        low = text.lower()
        if any(bad in low for bad in NOT_A_QUESTION):
            continue
        total = abs(int(row.get("dollars_cents") or 0))
        if total < MIN_AMOUNT_CENTS:
            continue
        rec = {
            "merchant": text,
            "merchant_key": merchant_key(text),
            "entity_id": t["entity_id"],
            "account_id": t["account_id"],
            "account_name": t["account_name"],
            "last_four": card_for(t["account_id"] or "", t["account_name"] or "", last4),
            "txn_count": len(ids),
            "total_cents": total,
            "max_cents": abs(int(t["amount_cents"] or 0)),
            "newest": t["transaction_date"],
            "dated": t["transaction_date"],
            "oldest": t["transaction_date"],
            "transaction_id": t["id"],
            "merchant_name": t["merchant_name"] or "",
            "description": t["description"] or "",
            "parked_reason_kind": row.get("reason_kind"),
            "parked_reason": str(row.get("reason") or "")[:200],
        }
        # the PARKED key, not a recomputed one: it is the key the filing engine computes
        rec["cluster_key"] = key
        out.append(rec)
        if len(out) >= limit:
            break
    c.close()
    return out


def candidates(reason: bool = False) -> list[dict]:
    """Unclarified purchases worth asking about, best first."""
    if not ACCT_DB.exists():
        raise SystemExit(f"accounting store not found: {ACCT_DB}")
    uri = f"file:{ACCT_DB}?mode=ro"
    c = sqlite3.connect(uri, uri=True, timeout=10)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA busy_timeout=8000")
    cutoff = (datetime.now(timezone.utc).date() - timedelta(days=RECENT_DAYS)).isoformat()
    rows = c.execute(
        """
        SELECT t.normalized_merchant        AS merchant,
               t.entity_id                  AS entity_id,
               t.account_id                 AS account_id,
               t.account_name               AS account_name,
               COUNT(*)                     AS n,
               SUM(t.amount_cents)          AS total_cents,
               MAX(t.amount_cents)          AS max_cents,
               MAX(t.transaction_date)      AS newest,
               -- The window cutoff is repeated INSIDE this subquery on purpose.
               -- Measured 2026-10-02: without it, max_date came from the all-time
               -- max-amount row (Amazon 585.27 on 20 Aug) while max_cents came from
               -- the in-window max (173.55 on 18 Sep), so the owner was texted
               -- "173.55 ... on 20 Aug" - an amount and a date from different rows.
               (SELECT MAX(t2.transaction_date) FROM transactions t2
                 WHERE t2.account_id = t.account_id
                   AND t2.normalized_merchant = t.normalized_merchant
                   AND t2.duplicate_of_transaction_id IS NULL
                   AND t2.transaction_date >= ?
                   AND t2.amount_cents = (SELECT MAX(t3.amount_cents) FROM transactions t3
                                           WHERE t3.account_id = t.account_id
                                             AND t3.normalized_merchant = t.normalized_merchant
                                             AND t3.duplicate_of_transaction_id IS NULL
                                             AND t3.transaction_date >= ?)
               )                            AS max_date,
               MAX(t.id)                    AS any_id,
               MIN(t.transaction_date)      AS oldest,
               -- The canonical cluster key needs the ledger's OWN merchant_name and
               -- statement line: `cfo_rules.cluster_key()` prefers merchant_name over
               -- normalized_merchant, and a rule written under a key the filing engine does
               -- not compute would never cover the charge it was learned from.
               MAX(t.merchant_name)         AS merchant_name,
               MAX(t.description)           AS description
        FROM transactions t
        WHERE t.duplicate_of_transaction_id IS NULL
          AND NOT EXISTS (SELECT 1 FROM transaction_categories tc WHERE tc.transaction_id = t.id)
          AND TRIM(COALESCE(t.normalized_merchant,'')) <> ''
          AND t.transaction_date >= ?
        GROUP BY t.normalized_merchant, t.entity_id, t.account_id
        ORDER BY SUM(t.amount_cents) DESC
        """,
        (cutoff, cutoff, cutoff),
    ).fetchall()
    last4 = last_four_map(c)
    c.close()

    # The other asker's sent merchants, read once. A charge either asker has already
    # put to him is not a question any more.
    owner_asked = _owner_asked_merchants()

    out, dropped = [], []
    for r in rows:
        m = (r["merchant"] or "").strip()
        low = m.lower()
        why = None
        if any(bad in low for bad in NOT_A_QUESTION):
            why = "money movement / processor plumbing, not a question for a human"
        elif len(m) < 3:
            why = "merchant string too short to name"
        elif int(r["total_cents"] or 0) < MIN_AMOUNT_CENTS:
            why = f"below the {MIN_AMOUNT_CENTS/100:.2f} floor"
        elif merchant_key(m) in owner_asked:
            # Measured 2026-10-02 (`P2830`): owner-ask #28 and this asker both put the
            # same Amazon charge to him, sixteen hours apart. One charge, one question.
            why = "already asked by the other asker (owner-ask) - one charge, one question"
        rec = {
            "merchant": m,
            "merchant_key": merchant_key(m),
            "entity_id": r["entity_id"],
            "account_id": r["account_id"],
            "account_name": r["account_name"],
            "last_four": card_for(r["account_id"] or "", r["account_name"] or "", last4),
            "txn_count": r["n"],
            "total_cents": int(r["total_cents"] or 0),
            "max_cents": int(r["max_cents"] or 0),
            "newest": r["newest"],
            "dated": r["max_date"] or r["newest"],
            "oldest": r["oldest"],
            "transaction_id": r["any_id"],
            "merchant_name": r["merchant_name"] or "",
            "description": r["description"] or "",
        }
        rec["cluster_key"] = _cluster_key(rec)
        (out if why is None else dropped).append(rec if why is None else (why, rec))

    # The park store's owner-facing clusters, when the switch is on. Kept OUT of `dropped`:
    # these are candidates the previous pass could not see, not candidates it rejected.
    if INCLUDE_PARKED:
        seen = {r.get("cluster_key") for r in out}
        for rec in parked_candidates(last4):
            if rec["cluster_key"] in seen or rec.get("merchant_key") in owner_asked:
                continue
            out.append(rec)

    return (out, dropped) if reason else out


def _cluster_key(rec: dict) -> str:
    """The unit of work, computed by the SAME function the filing engine uses.

    `cfo_rules.cluster_key()` is what `cfo-resolve` and `cfo_rules.rule_for()` match against,
    so a rule learned from this asker's answer has to be keyed the way they key it. Falls back
    to this asker's own normaliser when `cfo_rules` is not importable - a partial deployment
    must degrade, never crash an asker that cron is running.
    """
    if cfo_clarify is not None:
        try:
            return cfo_clarify.cluster_key_for(rec["merchant"],
                                              rec.get("merchant_name") or "",
                                              rec.get("description") or "")
        except Exception:                                  # noqa: BLE001
            pass
    return rec["merchant_key"]


def _fresh_reference() -> str:
    """A reference no clarification has used.

    `ask-<epoch seconds>` is the shape every reader in this system already accepts
    (`ask_quality.REF_RE` and `textsend._ASK_TOKEN_RE` both take `ask-\\d{6,}`), so the shape
    is kept. The bump covers two asks inside one second, which would otherwise collide on the
    clarification table's UNIQUE index.
    """
    base = int(datetime.now(timezone.utc).timestamp())
    if cfo_clarify is None:
        return "ask-%d" % base
    for bump in range(0, 120):
        ref = "ask-%d" % (base + bump)
        try:
            if cfo_clarify.find_by_reference(ref) is None:
                return ref
        except Exception:                                  # noqa: BLE001
            return ref
    return "ask-%d" % (base + 121)


def next_question(reason: bool = False, skip: set | None = None):
    """The single best question to ask right now, or why there is none.

    `skip` is the set of merchant keys this run has already dealt with (auto-resolved), so
    the walk can move on without re-resolving the same candidate.
    """
    conn = ask_conn()
    try:
        # WHICH ROWS SUPPRESS A MERCHANT? Item 74 (2026-10-13) set this to EVERY row, to
        # stop the selector re-picking a purchase it had already queued: newegg 362.51
        # composed 03:11:15 and re-asked 03:30:40, polka dot 299.00 at 04:42:27 and
        # 05:00:36, back-market 357.18 at 04:30:09 and re-resolved 04:38:45.
        # BUT A QUESTION THAT NEVER REACHED HIM IS NOT AN ASK (item 104, 2026-10-14). With
        # every row suppressing, a question the GATE or the SENDER refused became
        # permanently unaskable, so he was never asked at all. Measured in asks.db: `pass`
        # 135.33 was composed at 06:00/06:30/07:00/10:00 on 2026-10-13 and every attempt was
        # refused by the sender (owner conversation open, one at a time); the gate does NOT
        # refuse that body (ask_quality.review() returns ok=[]), yet the selector answered
        # "every unclarified merchant has already been asked about".
        # SO two shapes do NOT suppress: a DEFINITE REFUSAL (provider_ok=0 with an rc in its
        # detail -- the only shape written when the question did not go out) and a DRY RUN
        # (provider_ok<>0 with dry_run:true in its detail -- a rehearsal asked nobody). Every
        # other row -- sent, auto-resolved, or an un-stamped/planted row whose provider_ok is
        # NULL -- suppresses. Item 74 stays fixed: cfo74-test.py plants exactly that
        # NULL-provider_ok shape and asserts it is skipped.
        # EXTENDED 2026-10-15: a refusal stops suppressing for REFUSAL_SILENCE_HOURS, because
        # item 104 left nothing to re-arm it and a refused charge was recomposed at every
        # 30-minute tick (`pass` 135.33: ten compositions over 21 hours). The refusal itself
        # still does not suppress forever -- item 104's property is intact.
        _refusal_floor = (
            datetime.now(timezone.utc) - timedelta(hours=REFUSAL_SILENCE_HOURS)
        ).isoformat()
        # A SENT QUESTION IS NOT A PERMANENT SILENCE (owner, 2026-10-16: "why not, it can
        # ask a day or 2 later"). `sent = 1` used to suppress that merchant FOR EVER, so an
        # unanswered question was dead and the ledger stayed wrong. It now suppresses for
        # REASK_AFTER_HOURS and then the question may come back. Everything item 74 and item
        # 104 fixed is preserved: an auto-resolved row still suppresses; a queued/planted row
        # (provider_ok NULL) still suppresses; a DRY RUN still does not suppress; and a
        # definite REFUSAL stops suppressing after REFUSAL_SILENCE_HOURS.
        _reask_floor = (
            datetime.now(timezone.utc) - timedelta(hours=REASK_AFTER_HOURS)
        ).isoformat()
        asked_keys = {r["merchant_key"] for r in conn.execute(
            "SELECT DISTINCT merchant_key FROM ask "
            "WHERE auto_resolved = 1 "
            "   OR provider_ok IS NULL "
            "   OR (sent = 1 "
            "       AND provider_detail NOT LIKE '%\"dry_run\": true%' "
            "       AND asked_at >= ?) "
            "   OR (provider_ok = 0 AND asked_at >= ?)",
            (_reask_floor, _refusal_floor))}
        # The attempt ceiling, read from the same table rather than trusted from memory.
        asked_keys |= {r["merchant_key"] for r in conn.execute(
            "SELECT merchant_key FROM ask WHERE sent = 1 "
            "GROUP BY merchant_key HAVING COUNT(*) >= ?",
            (MAX_ASKS_PER_MERCHANT,))}
    except sqlite3.Error:                                   # pre-migration store
        asked_keys = {r["merchant_key"] for r in conn.execute(
            "SELECT DISTINCT merchant_key FROM ask WHERE sent=1")}
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    sent_today = conn.execute(
        "SELECT COUNT(*) FROM ask WHERE sent=1 AND substr(asked_at,1,10)=?", (today,)
    ).fetchone()[0]
    last = conn.execute(
        "SELECT asked_at FROM ask WHERE sent=1 ORDER BY id DESC LIMIT 1"
    ).fetchone()
    conn.close()
    asked_keys |= set(skip or ())

    # NEVER ASK TWICE WHILE IT IS STILL LIVE (P2926 part 4, re-scoped 2026-10-16). Two
    # independent stops, both re-read from disk every run rather than trusted from memory:
    #   * an OWNER RULE already covers the cluster - he has told us what this merchant is, so
    #     putting it to him again is precisely the defect this whole loop exists to remove;
    #   * a clarification for this cluster is still WAITING - one question per merchant, so a
    #     run of small charges cannot become two texts about the same shop.
    owner_ruled: set = set()
    waiting_clusters: set = set()
    if cfo_clarify is not None:
        try:
            owner_ruled = cfo_clarify.owner_ruled_keys()
            waiting_clusters = cfo_clarify.open_cluster_keys()
        except Exception as exc:                           # noqa: BLE001
            print("cfo_clarify unreadable (%s); the skip sets are empty this run" % exc,
                  file=sys.stderr)

    detail: dict = {"sent_today": sent_today, "max_per_day": MAX_PER_DAY,
                    "asked_merchants": len(asked_keys),
                    "owner_ruled": len(owner_ruled),
                    "waiting_clarifications": len(waiting_clusters)}
    if sent_today >= MAX_PER_DAY:
        return None, f"daily cap reached ({sent_today}/{MAX_PER_DAY})", detail
    if last:
        age = datetime.now(timezone.utc) - datetime.fromisoformat(last["asked_at"])
        detail["minutes_since_last"] = round(age.total_seconds() / 60, 1)
        if age < timedelta(minutes=MIN_GAP_MINUTES):
            return None, (
                f"only {age.total_seconds()/60:.0f} min since the last ask "
                f"(floor is {MIN_GAP_MINUTES})"
            ), detail

    cands, dropped = candidates(reason=True)
    detail["considered"] = len(cands)
    detail["dropped"] = len(dropped)
    if reason:
        detail["dropped_detail"] = [
            {"why": w, "merchant": r["merchant"], "total": r["total_cents"] / 100.0}
            for w, r in dropped[:15]
        ]
    skipped_owner: list = []
    skipped_waiting: list = []
    for rec in cands:
        if rec["merchant_key"] in asked_keys:
            continue
        keys = {rec["merchant_key"], rec.get("cluster_key") or ""}
        if keys & owner_ruled:
            skipped_owner.append(rec["merchant"])
            continue
        if keys & waiting_clusters:
            skipped_waiting.append(rec["merchant"])
            continue
        return rec, None, detail
    if skipped_owner:
        detail["skipped_owner_ruled"] = skipped_owner[:15]
    if skipped_waiting:
        detail["skipped_waiting_clarification"] = skipped_waiting[:15]
    if skipped_owner or skipped_waiting:
        return None, ("%d merchant(s) already carry an owner rule and %d already have a "
                      "question waiting - nothing new to ask"
                      % (len(skipped_owner), len(skipped_waiting))), detail
    return None, "every unclarified merchant has already been asked about", detail


# ─────────────────────────────── the message ───────────────────────────────
def compose(rec: dict, ref: str, order_lines: list | None = None) -> str:
    """One question, naming the card and dating the charge it is actually asking about.

    Two measured defects fixed 2026-10-01 (cfo #317): the amount printed was
    MAX(amount_cents) while the date printed was MAX(transaction_date) - different
    rows - so 299.29 on 2026-09-24 went out as "on 26 Sep"; and the card label was
    account_name, which two different cards share, so the owner could not tell which
    card was meant. The date now comes from the same row as the amount, and the card
    is named by the last four digits of accounts.last_four.
    """
    amount = rec["max_cents"] / 100.0
    when = rec.get("dated") or rec["newest"] or "?"
    try:
        when = datetime.fromisoformat(when).strftime("%-d %b")
    except Exception:
        pass
    card = ""
    if rec.get("last_four"):
        card = f"ending {rec['last_four']}"
    elif (rec.get("account_name") or "").strip():
        card = (rec["account_name"] or "").strip()
    # THE EVIDENCE BODY. Measured 2026-10-02, after the owner replied to a bare
    # question with "That does not contain enough information or card which card it
    # was come on": the ledger already held the bank's own description and the real
    # single charge row, and the vendor's receipt emails were already in the
    # mailbox -- none of it reached him. charge_msg.compose() puts the card, the
    # exact charge, the statement line, the sibling charges and any order match into
    # the body, inside textsend's 320-character owner ceiling.
    try:
        # cfo-ask.py already defines HOME at module level; reuse it rather than
        # introducing a name that does not exist in that file (measured
        # 2026-10-02: `BIN` was undefined, the wrapper fell back and the operator
        # saw the bare body again -- a silent fallback that looks like success).
        bin_dir = str(HOME / "bin")
        if bin_dir not in sys.path:
            sys.path.insert(0, bin_dir)
        import charge_msg

        # charge_msg.connect() sets row_factory — sqlite3.connect directly gives
        # tuples and every accessor here is a named column.
        conn = charge_msg.connect(str(ACCT_DB))
        try:
            # The LEDGER'S OWN normalised_merchant string, not the asker's dedupe key.
            # They differ wherever the name has punctuation: "esti's world of fashion"
            # (the ledger) vs "esti s world of fashion" (merchant_key), and charge_msg
            # matches the column exactly -- so the key found nothing and the evidence-rich
            # body silently fell back to the bare question (measured 2026-10-02).
            evidence = charge_msg.compose(conn, rec["merchant"], order_lines=order_lines) or None
            if evidence is None and rec["merchant"] != rec["merchant_key"]:
                evidence = charge_msg.compose(conn, rec["merchant_key"], order_lines=order_lines)
        finally:
            conn.close()
        if evidence:
            # Keep the reference so an answer can still be matched to this ask.
            return evidence.replace("CFO:", f"CFO [{ref}]:", 1)
    except Exception as exc:  # noqa: BLE001 -- never lose the ask because a nicer
        print("charge_msg unavailable (%s); falling back to the bare body" % exc,
              file=sys.stderr)

    lines = [f"CFO [{ref}]: what was {amount:,.2f} at {rec['merchant']} on {when}" + (f" ({card})?" if card else "?")]
    if rec["txn_count"] > 1:
        lines.append(f"{rec['txn_count']} charges, {rec['total_cents']/100.0:,.2f} total.")
    # NEVER ASSERT A CATEGORY THE LEDGER CANNOT FILE (fixed 2026-10-13). This line used to read
    # "My guess: shop supplies. Reply 'yes' ..." - and the answer path then parsed that phrase
    # back out as `suggest_category`, so when the owner agreed, `cfo_clarify.category_from_answer`
    # answered "he agreed with the suggestion 'shop supplies', but entity lpt holds no such
    # category, so the cluster is marked answered with NO RULE". The ledger's lpt categories are
    # "Business, Industrial, & Scientific Supplies Basic" and "Office & Shipping Supplies"; there
    # is no "shop supplies" and never was. So the guess invited an answer that could not be filed,
    # and the question he was actually sent at 03:30 carries it.
    #
    # This is the BARE-BODY fallback, used only when `charge_msg` cannot compose, and `charge_msg`
    # now declines to guess rather than inventing one ("No guess from me"). The fallback should do
    # the same: ask, and say plainly that there is no guess, instead of naming a category that will
    # be thrown away when he agrees with it.
    lines.append("No guess from me - what was it? One line and I'll file it for good.")
    return "\n".join(lines)


# ─────────────────────────────── sending ───────────────────────────────
def owner_number() -> str:
    """The owner's own number, read from the app's .env. Never anyone else's."""
    if not APP_ENV.exists():
        raise SystemExit(f"app env not found: {APP_ENV}")
    keys = ("OWNER_NOTIFY_NUMBER", "OWNER_PHONE_NUMBER")
    wanted: list[str] = []
    for line in APP_ENV.read_text(encoding="utf-8", errors="replace").splitlines():
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        if k.strip().upper() in keys:
            v = v.strip().strip('"').strip("'")
            if v:
                wanted.append(v)
    if not wanted:
        raise SystemExit("no OWNER_NOTIFY_NUMBER / OWNER_PHONE_NUMBER in the app .env")
    return wanted[0]


#: This repo's word for "CONDITION, not fault" (`bin/sources/cron-failures.py` honours it for
#: EVERY job; see CONDITION_EXIT in ai-gateway-health.py and text-ledger-audit.py, and the same
#: tri-state repair in lpt-deploy-drift.py and supplier-delivery-watch.py). ONE refusal this asker
#: gets from `textsend.py` is a CONDITION, not a fault: the owner's own one-at-a-time rule. He has
#: an unanswered question open, so the AI line refuses a second one before any network call.
#: Clearing it is HIS act (answering), not a repair of this code, and the question is already on
#: his phone -- there is nothing for a repair session to escalate.
#: MEASURED 2026-10-07: ten consecutive cron runs exited 1 this way (the 07:30:01Z run was the
#: tenth), every one with an EMPTY stderr column in ~/.cron-status/runs.tsv, so
#: `sources/cron-failures.py` filed "A SCHEDULED JOB HAS FAILED 10 TIMES IN A ROW" for a job that
#: was working exactly as designed. All 148 `error:` lines in ~/.cfo-asks/cron.log carry this one
#: signature. rc=1 stays a FAULT here (a textsend crash, a provider error, a timeout): a fault
#: always wins and still fires.
CONDITION_EXIT = 3

#: The stable fragment of textsend.py's one-at-a-time refusal (textsend.py:1657). Matched on the
#: error TEXT it returns, never on the exit code: textsend uses rc=1 for every policy refusal and
#: for a real provider failure alike, and this asker must keep the two apart.
_ONE_AT_A_TIME = "owner conversation open"


def send_exit_code(res: dict) -> int:
    """The exit code for ONE send attempt.

    0 accepted; CONDITION_EXIT (3) the owner's own one-at-a-time refusal, which only he can
    clear; 1 anything else, which is a FAULT in this asker or its sender and must still fire.
    """
    if res.get("rc") == 0:
        return 0
    blob = "%s\n%s" % (res.get("stdout") or "", res.get("stderr") or "")
    if _ONE_AT_A_TIME in blob:
        return CONDITION_EXIT
    return 1


def condition_reason(res: dict) -> str:
    """The refusal, named for the runs.tsv cause column.

    `bin/cron-wrap.sh` records the first 160 chars of stderr in ~/.cron-status/runs.tsv, so this
    is what turns an empty cause column into a readable one. Falls back to a fixed sentence so
    the reason is never blank when the refusal took an unexpected shape.
    """
    for line in (res.get("stdout") or "").splitlines():
        if line.startswith("error:"):
            return line.split(":", 1)[1].strip()
    return "the owner has an open unanswered question (one text at a time)"


def send(body: str, dry_run: bool) -> dict:
    """Send through the AI line's own gate. A refusal is a returned value, never a raise."""
    to = owner_number()
    # `--reason cfo_ask` is not decoration: it is how this question claims the MONEY
    # rank on the owner's one-at-a-time channel, so it takes the floor from a machine
    # notice that would otherwise hold it. Measured 2026-10-05/06, before this flag
    # existed: 17 consecutive asks refused with "owner conversation open ... (turn
    # #54)" while an email-triage notice sat in the turn. Stated explicitly rather
    # than inferred from the body, because money is the class this asker always is.
    cmd = [sys.executable, str(TEXTSEND), "send", "--to", to,
           "--reason", "cfo_ask", "--body", body]
    if not dry_run:
        cmd.append("--send")
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    return {
        "to": to,
        "dry_run": dry_run,
        "rc": p.returncode,
        "stdout": (p.stdout or "").strip()[-1200:],
        "stderr": (p.stderr or "").strip()[-600:],
    }


def provider_accepted(res: dict) -> bool:
    """Did the PROVIDER accept the message? Not "did we ask it to send".

    Measured 2026-09-30: `--send` with the AI line's owner-turn gate closed returns
    `ok=False ... refused before any network call` and exit 1. Recording that as a send
    fills the daily cap with refusals, so after three closed gates the CFO believes it has
    already asked three questions and stops -- silent while its own log says it spoke.
    """
    # A DRY RUN IS NEVER A SEND. Measured 2026-10-02: `--why` returns ok=True with
    # dry_run=True, and this function passed it, so the ask was recorded sent=1 for a
    # message nobody received -- consuming the daily cap, permanently claiming the
    # merchant as "asked", and telling the store the owner had been informed.
    if res.get("dry_run"):
        return False
    if res.get("rc") != 0:
        return False
    out = (res.get("stdout") or "")
    if re.search(r"\bok=False\b", out):
        return False
    return bool(re.search(r"\bok=True\b", out)) or bool(re.search(r"\bSM[0-9a-f]{32}\b", out))


def find_pending(merchant_key: str):
    """An ask already composed for this merchant that never went out, if any."""
    conn = ask_conn()
    row = conn.execute(
        "SELECT id, asked_at FROM ask WHERE merchant_key=? AND sent=0 ORDER BY id DESC LIMIT 1",
        (merchant_key,),
    ).fetchone()
    conn.close()
    return row


def update_pending(row_id: int, body: str, ref: str, res: dict) -> int:
    """Reuse the row instead of filing a second one for the same merchant."""
    conn = ask_conn()
    conn.execute(
        """UPDATE ask SET asked_at=?, body=?, reference=?, provider_ok=?, provider_detail=?
           WHERE id=?""",
        (datetime.now(timezone.utc).isoformat(), body, ref,
         1 if res.get("rc") == 0 else 0, json.dumps(res)[:2000], row_id),
    )
    conn.commit()
    conn.close()
    return row_id


def record(rec: dict, body: str, ref: str, sent: bool, res: dict) -> int:
    conn = ask_conn()
    cur = conn.execute(
        """INSERT INTO ask (asked_at, entity_id, account_name, merchant, merchant_key,
                            transaction_id, transaction_date, amount_cents, txn_count,
                            total_cents, body, reference, sent, provider_ok, provider_sid,
                            provider_detail)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            datetime.now(timezone.utc).isoformat(), rec["entity_id"], rec["account_name"],
            rec["merchant"], rec["merchant_key"], str(rec["transaction_id"]), rec["newest"],
            rec["max_cents"], rec["txn_count"], rec["total_cents"], body, ref,
            1 if sent else 0, 1 if res.get("rc") == 0 else 0,
            _sid(res.get("stdout", "")), json.dumps(res)[:2000],
        ),
    )
    conn.commit()
    rid = cur.lastrowid
    conn.close()
    return rid


def _sid(out: str) -> str:
    m = re.search(r"\bSM[0-9a-f]{32}\b", out or "")
    return m.group(0) if m else ""


# ──────────────────── resolve before asking a human ────────────────────
def try_resolve(rec: dict) -> dict | None:
    """Ask `merchant_resolve` what this merchant is. None when the module is absent.

    Never raises: a resolver fault must not stop an ask the owner is owed. It prints
    loudly instead, because a silent fallback is how the last one hid for a week.
    """
    if merchant_resolve is None:
        print("merchant_resolve not importable; asking without resolving", file=sys.stderr)
        return None
    try:
        return merchant_resolve.resolve(
            rec["merchant_key"], merchant=rec["merchant"], acct_db=str(ACCT_DB),
            amount_cents=rec.get("max_cents"), when=rec.get("dated") or rec.get("newest"))
    except Exception as exc:  # noqa: BLE001
        print(f"merchant_resolve failed ({exc}); asking without resolving", file=sys.stderr)
        return None


def resolved_enough(res: dict | None) -> bool:
    return bool(res and res.get("solved") and float(res.get("confidence") or 0) >= RESOLVE_CONFIDENCE)


def record_auto_resolved(rec: dict, res: dict) -> int:
    """Record that OUR OWN RECORDS answered this merchant, and that no text was sent.

    `sent=0` on purpose: nothing left this machine, and the daily cap must not be spent on
    a question nobody received.
    """
    conn = ask_conn()
    now = datetime.now(timezone.utc).isoformat()
    keep = {k: res.get(k) for k in (
        "solved", "entity", "category", "category_id", "confidence", "source", "method",
        "evidence", "merchant_key", "charges_on_record", "uncategorised", "planned_rows",
        "checked", "order_evidence")}
    cur = conn.execute(
        """INSERT INTO ask (asked_at, entity_id, account_name, merchant, merchant_key,
                            transaction_id, transaction_date, amount_cents, txn_count,
                            total_cents, body, reference, sent, provider_ok, provider_sid,
                            provider_detail, auto_resolved, resolution_json)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,0,NULL,'',?,1,?)""",
        (now, rec["entity_id"], rec["account_name"], rec["merchant"], rec["merchant_key"],
         str(rec["transaction_id"]), rec["newest"], rec["max_cents"], rec["txn_count"],
         rec["total_cents"], "", "resolved-%d" % int(datetime.now(timezone.utc).timestamp()),
         json.dumps({"why": "merchant_resolve", "at": now})[:500],
         json.dumps(keep, default=str)[:6000]),
    )
    conn.commit()
    rid = cur.lastrowid
    conn.close()
    return rid


def print_resolution(rec: dict, res: dict, rid: int, verbose: bool) -> None:
    print(f"auto-resolved (no text): {rec['merchant']} = {res['entity']}"
          f" -> {res['category'] or '(no category in the answer)'}"
          f"  confidence={res['confidence']:.2f} method={res['method']}")
    for e in (res.get("evidence") or [])[:3]:
        print(f"   evidence: {e[:200]}")
    if verbose:
        for c in (res.get("checked") or []):
            print(f"   checked : {c[:200]}")
    rows = res.get("planned_rows") or []
    if rows:
        print(f"   the ledger still carries {res.get('uncategorised')} uncategorised charge(s) "
              f"for this merchant; the sanctioned writer is the app's own rule engine "
              f"(app/services/auto_categorize.py). The row a filer would need:")
        for s in rows:
            print(f"     {s}")
    print(f"   recorded as ask #{rid} with auto_resolved=1 in {ASK_DB}")


def gate(body: str, rec: dict, evidence: list) -> tuple[bool, list]:
    """The one gate all three mouths pass through. Absent module never blocks an ask."""
    if ask_quality is None:
        print("ask_quality not importable; sending without the gate", file=sys.stderr)
        return True, []
    try:
        return ask_quality.review(
            body, kind="charge", merchant=rec.get("merchant"),
            evidence=evidence or [],
            amount_cents=rec.get("max_cents"), card=rec.get("last_four") or "",
            account=rec.get("account") or rec.get("account_id") or "",
            when=rec.get("dated") or rec.get("newest"))
    except Exception as exc:  # noqa: BLE001
        print(f"ask_quality failed ({exc}); sending without the gate", file=sys.stderr)
        return True, []


# ─────────────────────────────── commands ───────────────────────────────
def pending_filings() -> list[dict]:
    """Auto-resolved merchants the ledger has not actually filed yet.

    This module deliberately does not write the ledger, so a resolution that no rule in
    `auto_categorize` covers would otherwise sit in the asks store looking like progress.
    Saying it out loud is the difference between a record and a claim.
    """
    if not ASK_DB.exists():
        return []
    try:
        conn = ask_conn()
    except Exception:
        return []
    out: list[dict] = []
    try:
        rows = conn.execute(
            "SELECT id, asked_at, merchant, resolution_json FROM ask "
            "WHERE auto_resolved=1 ORDER BY id DESC LIMIT 40").fetchall()
    except sqlite3.Error:
        rows = []
    finally:
        conn.close()
    for r in rows:
        try:
            blob = json.loads(r["resolution_json"] or "{}")
        except Exception:
            blob = {}
        if int(blob.get("uncategorised") or 0) > 0:
            out.append({"id": r["id"], "asked_at": r["asked_at"], "merchant": r["merchant"],
                        "category": blob.get("category") or "", "confidence": blob.get("confidence"),
                        "uncategorised": blob.get("uncategorised"), "rows": blob.get("planned_rows") or []})
    return out


def cmd_status() -> int:
    if not ASK_DB.exists():
        print(f"no asks yet ({ASK_DB} does not exist)")
        return 0
    conn = ask_conn()
    n = conn.execute("SELECT COUNT(*) FROM ask").fetchone()[0]
    sent = conn.execute("SELECT COUNT(*) FROM ask WHERE sent=1").fetchone()[0]
    auto = conn.execute("SELECT COUNT(*) FROM ask WHERE auto_resolved=1").fetchone()[0]
    print(f"asks recorded: {n} · sent: {sent} · auto-resolved (no text): {auto} · store: {ASK_DB}")
    for r in conn.execute(
        "SELECT id, asked_at, merchant, amount_cents, sent, provider_sid, answered_at, auto_resolved "
        "FROM ask ORDER BY id DESC LIMIT 12"
    ):
        mark = "SENT" if r["sent"] else ("auto" if r["auto_resolved"] else "dry ")
        ans = r["answered_at"] or "-"
        sid = (r["provider_sid"] or "")[:12]
        print(f"  #{r['id']:<4} {mark} {r['asked_at'][:16]}  {r['merchant'][:26]:26s} "
              f"{(r['amount_cents'] or 0)/100:>9,.2f}  {sid:12s} answered={ans}")
    pend = pending_filings()
    if pend:
        print(f"\npending filings ({len(pend)} auto-resolved merchant(s) the ledger has not "
              f"categorised yet) - nothing here was filed by this script:")
        for p in pend:
            print(f"  #{p['id']} {p['merchant'][:34]:34s} -> {p['category'] or '?'} "
                  f"({p['uncategorised']} uncategorised)")
    if cfo_clarify is not None:
        try:
            n = cfo_clarify.counts()
            print("\nclarifications: " + " ".join(
                "%s=%d" % (s, n[s]) for s in ("asked", "answered", "expired", "superseded"))
                + "  owner rules in force: %d" % len(cfo_clarify.owner_ruled_keys()))
        except Exception as exc:                           # noqa: BLE001
            print("\nclarifications unreadable: %s" % exc)
    _, why, detail = next_question()
    print(f"\nnext: {why or 'a question is due'}")
    print(f"      {json.dumps(detail, default=str)}")
    conn.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Ask the owner about one unclear purchase, by text.")
    ap.add_argument("--send", action="store_true", help="actually send (default is a dry run)")
    ap.add_argument("--status", action="store_true", help="what has been asked, and what is due")
    ap.add_argument("--why", action="store_true", help="explain the choice in detail")
    ap.add_argument("--force", action="store_true", help="ignore the caps (still never repeats a merchant)")
    args = ap.parse_args(argv)

    if args.status:
        return cmd_status()

    rec, why, detail = next_question(reason=args.why)
    print(f"gate: sent_today={detail.get('sent_today')}/{MAX_PER_DAY} "
          f"asked_merchants={detail.get('asked_merchants')} "
          f"considered={detail.get('considered')} dropped={detail.get('dropped')}")

    # RESOLVE FIRST. Walk up to RESOLVE_TRIES candidates: any merchant our own records
    # already identify is recorded and skipped, and the walk continues; the first merchant
    # we genuinely cannot identify is the one that gets composed.
    resolution: dict | None = None
    walked: set = set()
    while rec is not None and len(walked) < RESOLVE_TRIES:
        walked.add(rec["merchant_key"])
        resolution = try_resolve(rec)
        if not resolved_enough(resolution):
            break
        rid = record_auto_resolved(rec, resolution)
        print_resolution(rec, resolution, rid, verbose=args.why)
        rec, why, detail = next_question(reason=args.why, skip=walked)
        if rec is not None:
            print(f"\nnext candidate after resolving {len(walked)}: {rec['merchant']}")

    if rec is None:
        print(f"nothing to ask right now: {why}")
        if args.why and detail.get("dropped_detail"):
            print("dropped candidates:")
            for d in detail["dropped_detail"]:
                print(f"   - {d['merchant'][:34]:34s} {d['total']:>9,.2f}  {d['why']}")
        if walked:
            print(f"{len(walked)} candidate(s) answered from our own records this run - "
                  f"no text sent.")
        return 0

    ref = _fresh_reference()
    body = compose(rec, ref, order_lines=(resolution or {}).get("order_evidence"))
    if ref not in body:
        # The reference MUST be on the body or his reply cannot name it. `compose()` only
        # rewrites an evidence body that carries the literal "CFO:" prefix; when charge_msg
        # returns a body without it, that replace is a no-op and the ask would go out with no
        # token to answer with - the exact half-defect P2926 part 5 records for the queue path.
        body = "CFO [%s]: %s" % (ref, body)
    print(f"chosen: {rec['merchant']}  {rec['max_cents']/100:,.2f} on {rec.get('dated') or rec['newest']}  "
          f"{rec['txn_count']} charge(s), {rec['total_cents']/100:,.2f} total, "
          f"account={rec.get('account_id')} {('ending ' + rec['last_four']) if rec.get('last_four') else '(no last four on file)'}")
    if resolution and resolution.get("evidence"):
        print("what our records DO say about it (unsolved, so the ask carries it):")
        for e in resolution["evidence"][:3]:
            print(f"   + {e[:200]}")
    if args.why and resolution and resolution.get("checked"):
        print("what was checked (an unchecked method never looks like a checked one):")
        for c in resolution["checked"]:
            print(f"   - {c[:200]}")
    print("--- body ---")
    print(body)
    print("--- end ---")

    ok, reasons = gate(body, rec, (resolution or {}).get("evidence") if (resolution or {}).get("solved") else [])
    if not ok:
        print("\nGATE REFUSED this body - nothing was sent:")
        for r in reasons:
            print(f"   - {r}")
        conn = ask_conn()
        existing = conn.execute(
            "SELECT id FROM ask WHERE merchant_key=? AND sent=0 AND auto_resolved=0 "
            "ORDER BY id DESC LIMIT 1", (rec["merchant_key"],)).fetchone()
        if existing:
            conn.execute("UPDATE ask SET asked_at=?, body=?, provider_detail=? WHERE id=?",
                         (datetime.now(timezone.utc).isoformat(), body,
                          json.dumps({"refused_by": "ask_quality", "reasons": reasons})[:2000],
                          existing["id"]))
            rid = existing["id"]
        else:
            rid = record(rec, body, ref, sent=False,
                         res={"rc": 1, "refused_by": "ask_quality", "reasons": reasons})
        conn.commit()
        conn.close()
        print(f"   recorded ask #{rid} (sent=0, refused by the gate) in {ASK_DB}")
        return 0

    # A QUESTION IS NOT SENT UNTIL ITS RECORD EXISTS. Written before the sender is called,
    # so there can never be a question on his phone that this record does not know about --
    # and stamped with the provider's own message id the moment the sender answers.
    #
    # ONLY WHEN WE ARE ACTUALLY GOING TO SEND. A dry run (`--why`) asks him nothing, so it
    # files no clarification: a record of a question nobody was asked is not a record, and it
    # would make the open-question count -- the number the fallback reports -- a lie.
    clar_id = None
    if not args.send:
        print("dry run - no clarification recorded (nothing was asked)")
    elif cfo_clarify is not None:
        guess = ""
        gm = re.search(r"My guess:\s*([^.\n]+)", body)
        if gm:
            guess = gm.group(1).strip()
        try:
            clar_id = cfo_clarify.record_question(
                reference=ref, cluster_key=rec.get("cluster_key") or rec["merchant_key"],
                merchant=rec["merchant"], merchant_name=rec.get("merchant_name") or "",
                description=rec.get("description") or "", question=body,
                entity_id=rec.get("entity_id") or "", account_id=rec.get("account_id") or "",
                account_name=rec.get("account_name") or "",
                last_four=rec.get("last_four") or "",
                transaction_ids=[rec.get("transaction_id")],
                txn_count=rec.get("txn_count") or 0, max_cents=rec.get("max_cents") or 0,
                total_cents=rec.get("total_cents") or 0, suggest_category=guess,
                asker="cfo-ask", channel="sms")
            print(f"clarification #{clar_id} recorded for cluster {rec['merchant_key']!r} with "
                  f"reference {ref} (before the sender was called)")
        except Exception as exc:                           # noqa: BLE001
            print("CLARIFICATION NOT RECORDED (%s) - his answer to this question will not be "
                  "matchable" % exc, file=sys.stderr)

        # AND FILE THE SAME ASK WITH THE RELAY (added 2026-10-15).
        #
        # Until today the CFO's question lived ONLY in /root/.cfo-asks/asks.db, while the
        # component that answers the owner's reply -- /root/bin/sms-responder.py -- looks the
        # reference up in /root/bin/owner_text_relay.py's own `ask` table. The two never met,
        # and the responder said so, six times, in its own log:
        #
        #     relay: ask ask-1792026036 -> missing
        #
        # `ask-1792026036` was the American Professional charge. So a reply to a CFO question
        # could not be resolved against the question it answered by the one component that
        # claims to be "the single policy brain for every text that reaches the owner". That is
        # the owner's "your unified brain is not working", at the level of code.
        #
        # The relay is the right store for this and not the app: it is the one place every door
        # already submits to and the only one that can say what is outstanding across askers.
        # Its `ask` table is idempotent on `ref`, so re-recording is safe.
        #
        # FAIL-SOFT, like every other relay caller: an outage in the policy component must not
        # cost the owner a question he is owed. It says so out loud rather than swallowing it.
        try:
            import owner_text_relay as _relay  # noqa: PLC0415 - optional by design
            _relay.record_ask(
                ref, "cfo_ask", str(rec.get("merchant") or rec["merchant_key"]), body,
                ttl_hours=CFO_ASK_TTL_HOURS)
            print("relay: ask %s filed (subsystem=cfo_ask, topic=%r, ttl=%.0fh)"
                  % (ref, rec.get("merchant") or rec["merchant_key"], CFO_ASK_TTL_HOURS))
        except Exception as exc:                           # noqa: BLE001
            print("RELAY ASK NOT FILED (%s) - his reply to %s will not resolve against the relay"
                  % (exc, ref), file=sys.stderr)

    res = send(body, dry_run=not args.send)
    accepted = provider_accepted(res)

    if clar_id is not None:
        try:
            cfo_clarify.stamp_outbound(clar_id, ok=accepted,
                                       sid=_sid(res.get("stdout", "") or ""),
                                       detail=json.dumps(res)[:1200])
        except Exception as exc:                           # noqa: BLE001
            print("clarification #%d was NOT stamped with the provider result (%s)"
                  % (clar_id, exc), file=sys.stderr)
    pending = find_pending(rec["merchant_key"])
    if pending and not accepted:
        rid = update_pending(pending["id"], body, ref, res)
        how = f"updated the open ask #{rid} for this merchant (still not sent)"
    else:
        rid = record(rec, body, ref, sent=accepted, res=res)
        how = f"recorded ask #{rid}" + ("" if accepted else " (NOT sent - the provider refused)")
    print(f"\n{how} in {ASK_DB}")
    print(f"dry_run={res['dry_run']} rc={res['rc']} to={res['to']} provider_accepted={accepted}")
    for label in ("stdout", "stderr"):
        if res[label]:
            print(f"  {label}: {res[label][:600]}")
    if args.send and res["rc"] != 0:
        code = send_exit_code(res)
        if code == CONDITION_EXIT:
            # Name the condition on stderr: bin/cron-wrap.sh records the first 160 chars in
            # ~/.cron-status/runs.tsv, so the row says WHY instead of leaving the cause column
            # empty -- an empty column beside a non-zero rc is what made ten healthy runs read
            # as a dead job (2026-10-07).
            sys.stderr.write(
                "cfo-ask: rc=%d CONDITION, not fault -- %s\n"
                % (CONDITION_EXIT, condition_reason(res)))
        return code
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
