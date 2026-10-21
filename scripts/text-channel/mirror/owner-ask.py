#!/usr/bin/env python3
"""owner-ask.py — ask the owner ONE question, in his own terms, and record the answer.

WHY THIS EXISTS
---------------
Eighty-seven of the owner's own turns since March are a request to be asked. Verbatim:

  "prepare a full document of qs for us to go through together and then ask me qs
   one at a time and document my answers"
  "create a full document of things that need my clarification and then we'll go
   through them one at a time with you documenting my answers clearly"
  "What are these assumptions you're making? Why don't you just ask me? I'll tell
   you a lot of stuff."

The system built outbound notifications and never built intake. This is the intake.

HIS SPECIFICATION, and the whole design follows from it (inbound SMS, 2026-09-25):

  "The text you are sending me have way too much information at once. I don't read
   them. You only should text me when you have like a question one at a time for me
   to answer and I'll answer it."

THE MEASUREMENTS THIS IMPLEMENTS (owner-pref/reports/WS1, WS2, WS5, WS8)
  * reply rate is 90.9% at <=40 characters and 15.4% over 800. Target 160.
  * median time for him to reply is 48 seconds. A question is answered fast or not at all.
  * 63.3% of what the system decided to tell him never reached him.
  * ~65% of the queue is engineering faults that are not his. "these are dev questions,
    their not boss qs you do the dev stuff, i do the boss stuff."
  * 31 queue rows asked him for data already sitting in a database he owns.
  * he is unreachable 04:00-10:00 local and all of Saturday; 07:00 is zero turns in 18 days.

THE NINE RULES, ENFORCED HERE
  1 one question, <=160 chars   2 always a recommendation   3 answerable in seconds
  4 nothing that asks nothing   5 never ask what we can read  6 never ask what is not his
  7 never re-ask                8 the non-response ladder stops, it does not escalate
  9 send in his hours

WHAT IT READS
  owner_decision_queue  (the declared single source of truth for what is waiting on him)
  the accounting store   (unclear purchases, via the same selection cfo-ask.py used)

USAGE
  owner-ask.py                 dry run: pick, compose, print, send nothing
  owner-ask.py --send          send one question if one is due
  owner-ask.py --why           explain the pick and everything rejected
  owner-ask.py --status        what has been asked, answered and is due
  owner-ask.py --sitting [N]   print the ordered question document (default 20)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
from datetime import datetime, time as dtime, timedelta, timezone
from pathlib import Path

# The campaign modules, imported DEFENSIVELY: this file may be deployed a tick before its
# siblings, and a partial deployment must degrade to the old behaviour rather than break an
# asker cron is running.
try:
    import ask_quality
except ImportError:                                        # pragma: no cover
    ask_quality = None
try:
    import merchant_resolve
except ImportError:                                        # pragma: no cover
    merchant_resolve = None

HOME = Path.home()
APP_DB = Path(os.environ.get("SECRETARY_DB", Path("/root/authority.db")))
ACCT_DB = Path(os.environ.get("CFO_ACCT_DB", HOME / "accounting-data/live/accounting.db"))
ASK_DB = Path(os.environ.get("OWNER_ASK_DB", HOME / ".owner-ask/asks.db"))
TEXTSEND = HOME / "bin/textsend.py"
APP_ENV = Path(os.environ.get("CFO_APP_ENV", HOME / "personal-secretary-mvp/.env"))

# ── the parameters, each traceable to a measurement ─────────────────────────
MAX_CHARS = int(os.environ.get("OWNER_ASK_MAX_CHARS", "160"))
# A purchase question now has to name the card (the owner: "That does not contain enough
# information or card which card it was come on"), and a charge, a date, a card and a
# recommendation do not always fit in 160 characters. The hard owner ceiling is the
# sender's 320; decisions keep the 160 target, purchases get the room they need.
PURCHASE_MAX_CHARS = int(os.environ.get("OWNER_ASK_PURCHASE_MAX_CHARS", "320"))
# Same threshold and same arithmetic as cfo-ask (merchant_resolve.CONF_*): a merchant our
# own records already identify is not a question for him.
RESOLVE_CONFIDENCE = float(os.environ.get(
    "OWNER_ASK_RESOLVE_CONFIDENCE", os.environ.get("CFO_RESOLVE_CONFIDENCE", "0.85")))


class Refuse(Exception):
    """This cannot be asked as one short question. Say so; do not mangle it."""
       # 90.9% reply at <=40; 15.4% over 800
MAX_PER_DAY = int(os.environ.get("OWNER_ASK_MAX_PER_DAY", "2"))     # WS6 param: max 2 questions/day
TARGET_CHARS = int(os.environ.get("OWNER_ASK_TARGET_CHARS", "120"))  # WS6: 120 target, 160 hard cap
MIN_GAP_MINUTES = int(os.environ.get("OWNER_ASK_MIN_GAP_MINUTES", "90"))
REASK_AFTER_HOURS = float(os.environ.get("OWNER_ASK_REASK_HOURS", "24"))
# 24 h, not 12: WS6 - "at most 1 retry, >=24 h later, then stop". The turn WINDOW
# (12 h) is when an open conversation expires; it is not the retry cadence.
GIVE_UP_AFTER = int(os.environ.get("OWNER_ASK_GIVE_UP_AFTER", "2"))        # ladder stops, never escalates
MIN_AMOUNT_CENTS = int(os.environ.get("OWNER_ASK_MIN_AMOUNT_CENTS", "2500"))
# His hours, from 9,300 of his own turns: peak 12:00-17:00 and 19:00-23:00;
# 07:00 is ZERO turns in 18 days; Saturday is 3 of 1,362 turns.
OPEN_HOURS = ((12, 17), (19, 23))
SATURDAY = 5                                                  # Monday == 0
LOCAL = timezone(timedelta(hours=-4))                         # America/New_York, EDT

# ── what is not his ─────────────────────────────────────────────────────────
# WS8: ~65% of the owner_message_queue is machine state wearing his name. A fault is
# not a question. These markers are the ones actually present in the two queues.
# Multi-word phrases only. A bare "monitoring", "stale", "capture" or "cache" occurs in
# ordinary business sentences and must never reject a question.
NOT_HIS = re.compile(
    r"mesh node|circuit breaker|sync_breaker|lifecycle sweep|consecutive failed|"
    r"needs? (re)?login|work order|agent worker|quarantin|prerequisite|"
    r"lease (expired|held|until)|claimed by|heartbeat|webhook|broker|"
    r"empty roster|deadlock|database is locked|migration|"
    r"monitoring (failure|is blind|has gone blind)|capture is stale|"
    r"token (is about to|has) expir|service (is|was) down|"
    r"\b502\b|\btimeout\b|deploy|restart",
    re.I,
)
# WS8 §3: a question whose answer is already in a system we own is a defect.
ALREADY_READABLE = re.compile(
    r"google business profile|GBP rating|review count|yelp|labs? result|"
    r"portal says|URGENT EMAIL|^From:|^Subj:",
    re.I,
)


# ─────────────────────────────── store ───────────────────────────────
def conn_ask() -> sqlite3.Connection:
    ASK_DB.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(ASK_DB, timeout=10)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA busy_timeout=8000")
    c.executescript(
        """
        CREATE TABLE IF NOT EXISTS ask (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          asked_at TEXT NOT NULL, source TEXT NOT NULL, source_id TEXT NOT NULL,
          subject TEXT NOT NULL, body TEXT NOT NULL, reference TEXT,
          sent INTEGER NOT NULL DEFAULT 0, provider_ok INTEGER,
          provider_sid TEXT, provider_detail TEXT, refused_why TEXT,
          answered_at TEXT, answer TEXT, resolved_at TEXT,
          UNIQUE(source, source_id, body)
        );
        CREATE INDEX IF NOT EXISTS ix_ask_src ON ask(source, source_id);
        CREATE INDEX IF NOT EXISTS ix_ask_sent ON ask(sent, asked_at);
        """
    )
    return c


def in_hours(now: datetime | None = None) -> tuple[bool, str]:
    local = (now or datetime.now(timezone.utc)).astimezone(LOCAL)
    if local.weekday() == SATURDAY:
        return False, "Saturday - 3 turns in 1,362, he is not there"
    if not any(a <= local.hour <= b for a, b in OPEN_HOURS):
        return False, f"{local.hour:02d}:00 local is outside his responsive hours (12-17, 19-23)"
    return True, f"{local.hour:02d}:00 local"


# ─────────────────────────────── sources ───────────────────────────────
def from_decision_queue() -> list[dict]:
    """DECISION ROWS ARE NO LONGER SENT FROM HERE (2026-10-21).

    One queue, one sender. This program and `decision-deliver.py` both read
    `owner_decision_queue WHERE status='pending'`, and each kept its own private send
    ledger, so neither could see the other's sends: the day both ran, one question could
    reach the owner twice in an hour, against his own instruction of "one question at a
    time" (2026-09-25). Reported by a concurrent session as D3 on 2026-10-21, and correct.

    `decision-deliver.py` is the sender that owns these rows: it triages first
    (decision-triage.py decides SEND_NOW / COMPOSE / STALE / SYSTEM / DUPLICATE before
    anything is composed), it paces at 2/day with a 30-minute gap in his hours, it stops the
    ladder at two asks, and it writes the shared `decision_sent` ledger in the authority
    database that this program also reads.

    What this function still does is READ the queue, so `--status` and the sitting remain
    accurate. It no longer returns candidates, which is what stops the double send.
    """
    return []


def _from_decision_queue_unused() -> list[dict]:
    """The previous body, kept for reference; not called.

    It is preserved rather than deleted because its SQL is the record of what the read path
    looked like, and because the composer defect it fed (D2: taking the text before a colon,
    capping at 72 characters and stapling a recommendation on -- producing a statement where
    a question belonged) is worth being able to read. The `deferred_until` predicate added
    below on 2026-10-21 is the one change it still needed."""

    if not APP_DB.exists():
        return []
    c = sqlite3.connect(f"file:{APP_DB}?mode=ro", uri=True, timeout=15)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA busy_timeout=8000")
    try:
        cols = {r[1] for r in c.execute("PRAGMA table_info(owner_decision_queue)")}
        rec = "recommendation" if "recommendation" in cols else "''"
        # A DEFERRED ROW IS NOT PENDING (fixed 2026-10-21). The owner parks decisions in
        # his own words -- "these are decisions about the product for next time i bring it
        # up", "too early - the ones due in November get thought about in November", "put a
        # note that we should look at this in 2 plus years". `owner-queue.py` honours
        # `deferred_until` on every read path, but this sender did not, so seven parked rows
        # were selectable and would have been texted the moment it ran. Filtered in the
        # SELECT, not after ranking, so no fallback can bring one back.
        rows = c.execute(
            f"""SELECT id, question, {rec} AS recommendation, severity, asked_at, status
                FROM owner_decision_queue WHERE status='pending'
                AND (deferred_until IS NULL OR deferred_until <= datetime('now'))
                ORDER BY id"""
        ).fetchall()
    except sqlite3.Error:
        return []
    finally:
        c.close()

    out = []
    for r in rows:
        q = re.sub(r"\s+", " ", str(r["question"] or "")).strip()
        if not q:
            continue
        out.append({
            "source": "decision", "source_id": str(r["id"]),
            "subject": q[:70], "question": q,
            "recommendation": re.sub(r"\s+", " ", str(r["recommendation"] or "")).strip(),
            "severity": str(r["severity"] or "medium"), "asked_at": r["asked_at"],
        })
    return out


def from_purchases() -> list[dict]:
    """Unclear purchases. Money movement is not a question for a human.

    The account_id is carried out of the query as well as the account_name: the card must
    be named by its last four digits (`personal-chase-4258` -> 4258), because two cards here
    genuinely share one account_name and a question that names the account_name is the one
    the owner answered with "which card it was come on" (measured 2026-10-02).
    """
    if not ACCT_DB.exists():
        return []
    c = sqlite3.connect(f"file:{ACCT_DB}?mode=ro", uri=True, timeout=15)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA busy_timeout=8000")
    cutoff = (datetime.now(timezone.utc).date() - timedelta(days=21)).isoformat()
    try:
        rows = c.execute(
            """SELECT t.normalized_merchant m, COUNT(*) n, SUM(t.amount_cents) tot,
                      MAX(t.amount_cents) mx, MAX(t.transaction_date) newest,
                      t.account_name acct, t.account_id acct_id
               FROM transactions t
               WHERE t.duplicate_of_transaction_id IS NULL
                 AND NOT EXISTS (SELECT 1 FROM transaction_categories tc WHERE tc.transaction_id=t.id)
                 AND TRIM(COALESCE(t.normalized_merchant,'')) <> ''
                 AND t.transaction_date >= ?
               GROUP BY 1 ORDER BY 3 DESC""", (cutoff,)).fetchall()
    except sqlite3.Error:
        return []
    finally:
        c.close()

    money = re.compile(r"stripe|gusto|paypal|payment|transfer|deposit|zelle|venmo|fee|payroll|interest|refund", re.I)
    out = []
    for r in rows:
        m = (r["m"] or "").strip()
        if len(m) < 3 or money.search(m) or int(r["tot"] or 0) < MIN_AMOUNT_CENTS:
            continue
        out.append({
            "source": "purchase", "source_id": f"m:{m.lower()[:40]}",
            "subject": m, "merchant": m, "amount": int(r["mx"] or 0),
            "count": r["n"], "total": int(r["tot"] or 0), "newest": r["newest"],
            "acct": r["acct"] or "", "acct_id": r["acct_id"] or "",
            "last4": _card_last4(r["acct_id"] or "", r["acct"] or ""),
            "severity": "medium", "asked_at": None,
        })
    return out


def _card_last4(account_id: str, account_name: str = "") -> str:
    """Last four digits of the charge's card, or "". Prefers merchant_resolve's reader."""
    if merchant_resolve is not None:
        try:
            return merchant_resolve.card_last4(account_id, account_name, ACCT_DB)
        except Exception:  # noqa: BLE001 - fall through to the local copy
            pass
    m = re.search(r"(\d{4,})$", account_id or "")
    if m:
        return m.group(1)[-4:]
    m = re.search(r"\*(\d{4})\b", account_name or "")
    return m.group(1) if m else ""


def _resolved_purchase(rec: dict) -> dict | None:
    """merchant_resolve's answer for a purchase, when it has one worth acting on."""
    if merchant_resolve is None:
        return None
    try:
        res = merchant_resolve.resolve(
            _merchant_key(rec["subject"]), merchant=rec["subject"], acct_db=str(ACCT_DB),
            amount_cents=rec.get("amount"), when=rec.get("newest"))
    except Exception:  # noqa: BLE001 - a resolver fault must not lose the ask
        return None
    if res.get("solved") and float(res.get("confidence") or 0) >= RESOLVE_CONFIDENCE:
        return res
    return None


def _fmt_day(iso: str) -> str:
    try:
        return datetime.fromisoformat(str(iso)[:10]).strftime("%-d %b")
    except Exception:
        return str(iso or "?")


# ─────────────────────────────── compose ───────────────────────────────
def shorten(text: str, budget: int) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    if len(text) <= budget:
        return text
    cut = text[:budget]
    for sep in (". ", "; ", ", "):
        i = cut.rfind(sep)
        if i > budget * 0.5:
            return cut[: i + 1].strip()
    return cut.rsplit(" ", 1)[0].strip()


def compose(rec: dict, ref: str) -> str:
    """One question, one recommendation, <=160 chars. Never a menu without a pick."""
    if rec["source"] == "purchase":
        amt = rec["amount"] / 100.0
        when = _fmt_day(rec.get("newest") or "")
        card = rec.get("last4") or ""
        head = f"{amt:,.2f} at {rec['subject']}"
        if when and when != "?":
            head += f" on {when}"
        if card:
            head += f", card ending {card}"
        elif rec["count"] > 1:
            head += f" ({rec['count']} charges)"
        q = f"{head}? I'd file it as shop supplies - say no or tell me."
    else:
        # The stored question is a PARAGRAPH written for a document, and the stored
        # recommendation is another one. Neither can be pasted into 160 characters.
        # So build a short ask: the subject (the part before a colon, else the first
        # sentence cut at a word boundary) plus the recommendation's own first
        # sentence. If even that will not fit, REFUSE -- never truncate mid-clause and
        # staple punctuation on, which is how the first version produced
        # "...unpaid vacation (he did not come in at all) and. Pay the $597.29 at your con".
        text = re.sub(r"\s+", " ", rec["question"]).strip()
        subject = text.split(":")[0].strip() if ":" in text[:90] else text
        if len(subject) > 72:
            subject = re.split(r"(?<=[.?!])\s+", subject)[0].strip()
        if len(subject) > 72:
            subject = shorten(subject, 72)
        # A fragment must not end on a coordinator or a preposition: "was due about
        # 2026-05-31 and." is not a sentence and reads as a machine talking.
        for _ in range(3):
            subject = subject.rstrip(" .,;:!?")
            subject = re.sub(
                r"[\s,;:]+(and|or|but|nor|with|without|the|a|an|of|to|for|at|in|on|by|is|was|were|are|be|"
                r"still|that|which|he|she|it|they|i|you|we)\s*$", "", subject, flags=re.I).strip()
        subject = subject.rstrip(" .,;:!?")
        raw_rec = re.sub(r"\s+", " ", rec.get("recommendation") or "").strip()
        raw_rec = re.sub(r"^(recommended|recommendation)\s*[:.-]\s*", "", raw_rec, flags=re.I)
        raw_rec = re.sub(r"^(option\s+)?[A-D]\s*[.):-]\s+", "", raw_rec)
        raw_rec = re.sub(r"^(yes|no)\s*[.:-]\s+", "", raw_rec, flags=re.I)
        rec_txt = re.split(r"(?<=[.?!])\s+", raw_rec)[0] if raw_rec else ""
        if len(rec_txt) > 78:
            rec_txt = shorten(rec_txt, 78)
        q = f"{subject}. {rec_txt}".strip() if rec_txt else subject + "?"
        if len(f"[{ref}] {q}") > MAX_CHARS:
            raise Refuse(
                f"cannot be asked in {MAX_CHARS} chars: the stored wording is "
                f"{len(text)} chars of question plus {len(rec.get('recommendation') or '')} "
                f"of recommendation. Rule 1 says one question; this needs rewriting, "
                f"not truncating.")
    body = f"[{ref}] {q}"
    return body[:MAX_CHARS].rstrip()


# ─────────────────────────────── gate + send ───────────────────────────────
def owner_number() -> str:
    for key in ("OWNER_NOTIFY_NUMBER", "OWNER_PHONE_NUMBER"):
        for line in APP_ENV.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith(key + "="):
                v = line.split("=", 1)[1].strip().strip('"').strip("'")
                if v:
                    return v
    raise SystemExit(f"no OWNER_NOTIFY_NUMBER / OWNER_PHONE_NUMBER in {APP_ENV}")


def provider_accepted(res: dict) -> bool:
    """Did the PROVIDER accept it? Not "did we ask it to send" -- a refusal recorded as a
    send fills the daily cap and silences the system while its log says it spoke."""
    if res.get("rc") != 0:
        return False
    out = res.get("stdout") or ""
    if re.search(r"\bok=False\b", out):
        return False
    return bool(re.search(r"\bok=True\b", out)) or bool(re.search(r"\bSM[0-9a-f]{32}\b", out))


def condition_only(res: dict) -> bool:
    """A refusal that is the owner's own rule, not a fault in this asker.

    ``rate_floor`` ("he was texted 6 minutes ago and asked for one text every 20
    minutes") and ``owner conversation open`` are CONDITIONS: they clear on their
    own and the question is still queued.  They must not be reported as a failed
    systemd service, because a failed unit is indistinguishable from a broken
    deliverer and would train everyone to ignore it.
    """
    blob = "%s\n%s" % (res.get("stdout") or "", res.get("stderr") or "")
    return ("rate_floor" in blob) or ("owner conversation open" in blob)


def send(body: str, dry_run: bool) -> dict:
    # `--reason owner_ask` claims the MONEY rank on the owner's one-at-a-time channel,
    # so a question about his own business is not held behind a machine's notice. See
    # app/owner_text.owner_text_priority and textsend.may_supersede_open_turn.
    cmd = [sys.executable, str(TEXTSEND), "send", "--to", owner_number(),
           "--reason", "owner_ask", "--body", body]
    if not dry_run:
        cmd.append("--send")
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    return {"rc": p.returncode, "stdout": (p.stdout or "").strip()[-900:],
            "stderr": (p.stderr or "").strip()[-400:], "dry_run": dry_run}


# ─────────────────────────────── selection ───────────────────────────────
# ── the other asker's record ───────────────────────────────────────────────
# `cfo-ask.py` (cron */30, store ~/.cfo-asks/asks.db) asks the owner about unclarified
# CHARGES by merchant. This module asks about owner-DECISION rows AND about purchases.
# The purchase halves overlap, and on 2026-10-02 the same Amazon charge was asked by
# both -- `owner-ask` #28 at 20:30Z, then `cfo-ask` #13 at 12:30Z the next day. Read the
# other asker's sent merchants and drop them, so one charge is asked about once.
CFO_ASK_DB = Path(os.environ.get("CFO_ASK_DB",
                                 Path.home() / ".cfo-asks" / "asks.db"))


def _merchant_key(text: str) -> str:
    r"""BYTE-IDENTICAL to `cfo-ask.py::merchant_key`.

    That function is:
        key = re.sub(r"[^a-z0-9 ]+", " ", name.lower())
        key = re.sub(r"\s+", " ", key).strip()[:48]

    A first attempt here stripped every non-alphanumeric, so "newegg" -> "newegg" but
    "newegg.com" -> "neweggcom": two keys for one merchant, which is exactly the miss
    this dedupe exists to prevent. Keep the space rule.
    """
    key = re.sub(r"[^a-z0-9 ]+", " ", (text or "").lower())
    key = re.sub(r"\s+", " ", key).strip()
    return key[:48]


#: A question that went out and was not answered comes back after this long. The owner,
#: 2026-10-16: "why not, it can ask a day or 2 later". Read from the SAME env var
#: `cfo-ask.py` uses, so the two askers cannot drift apart about what "already asked" means.
CFO_REASK_AFTER_HOURS = float(os.environ.get("CFO_ASK_REASK_HOURS", "48"))


def _cfo_asked_merchants() -> set:
    """Merchants `cfo-ask.py` has put to the owner RECENTLY. Never raises.

    Time-bounded since 2026-10-16. It used to be `WHERE sent=1` with no clock, which made
    one sent question a permanent silence: the merchant could never be asked about again by
    this asker either. An unanswered charge is exactly the thing that should come back.
    """
    if not CFO_ASK_DB.exists():
        return set()
    try:
        floor = (datetime.now(timezone.utc)
                 - timedelta(hours=CFO_REASK_AFTER_HOURS)).isoformat()
        c = sqlite3.connect(f"file:{CFO_ASK_DB}?mode=ro", uri=True, timeout=10)
        try:
            rows = c.execute(
                "SELECT merchant_key FROM ask WHERE sent=1 AND asked_at >= ?",
                (floor,)).fetchall()
        finally:
            c.close()
    except Exception:
        return set()
    out = set()
    for (m,) in rows:
        k = _merchant_key(m)
        if k:
            out.add(k)
    return out


def pick(reason: bool = False):
    """The single best question to ask now, or the reason there is none."""
    c = conn_ask()
    sent_global = {r["key"] for r in c.execute(
        "SELECT source||':'||source_id AS key FROM ask WHERE sent=1")}
    attempts = {r["key"]: r["n"] for r in c.execute(
        "SELECT source||':'||source_id AS key, COUNT(*) n FROM ask GROUP BY 1")}
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    sent_today = c.execute(
        "SELECT COUNT(*) FROM ask WHERE sent=1 AND substr(asked_at,1,10)=?", (today,)).fetchone()[0]
    last = c.execute("SELECT asked_at FROM ask WHERE sent=1 ORDER BY id DESC LIMIT 1").fetchone()
    c.close()

    detail = {"sent_today": sent_today, "max_per_day": MAX_PER_DAY}
    ok, why_hours = in_hours()
    detail["hours"] = why_hours
    if not ok:
        return None, why_hours, detail
    if sent_today >= MAX_PER_DAY:
        return None, f"daily cap reached ({sent_today}/{MAX_PER_DAY})", detail
    if last:
        age = datetime.now(timezone.utc) - datetime.fromisoformat(last["asked_at"])
        detail["minutes_since_last"] = round(age.total_seconds() / 60)
        if age < timedelta(minutes=MIN_GAP_MINUTES):
            return None, f"{age.total_seconds()/60:.0f} min since the last ask", detail

    cands = from_decision_queue() + from_purchases()
    detail["candidates"] = len(cands)
    rejected, keep = [], []
    _cfo_asked = _cfo_asked_merchants()
    detail["cfo_asked_merchants"] = len(_cfo_asked)
    for r in cands:
        key = f"{r['source']}:{r['source_id']}"
        if key in sent_global:
            rejected.append((r, "already answered/asked - rule 7"))
        elif attempts.get(key, 0) >= GIVE_UP_AFTER:
            rejected.append((r, f"asked {attempts[key]}x unanswered - rule 8, the ladder stops"))
        elif r["source"] == "decision" and NOT_HIS.search(r["question"]):
            rejected.append((r, "machine state, not his - rule 6"))
        elif r["source"] == "decision" and ALREADY_READABLE.search(r["question"]):
            rejected.append((r, "answer is already readable - rule 5"))
        elif r["source"] == "purchase" and _merchant_key(r["source_id"]) in _cfo_asked:
            # The OTHER asker has already put this charge to him. Measured 2026-10-02:
            # owner-ask #28 and cfo-ask #13 asked the same amazon charge five words
            # apart, hours apart. One charge, one question.
            rejected.append((r, "already asked by the CFO's asker - one charge, one question"))
        elif r["source"] == "purchase" and (rr := _resolved_purchase(r)):
            # OUR OWN RECORDS already answer it. The owner, 2026-10-02: "that sounds like
            # $300 data recovery we do business with them all the time you should have that
            # on record already" - and it was. Asking him again is the defect.
            rejected.append((r, "already answered by our own records (%s): %s"
                             % (rr.get("source") or "?", (rr.get("evidence") or [""])[0][:80])))
        else:
            keep.append(r)
    detail["kept"] = len(keep)
    if reason:
        detail["rejected"] = [{"id": f"{r['source']}:{r['source_id']}",
                               "subject": r["subject"][:60], "why": w} for r, w in rejected[:25]]
    if not keep:
        return None, ("nothing to ask from this program's own sources -- decision rows are sent by decision-deliver.py now (one queue, one sender, 2026-10-21)"), detail
    # order: severity, then oldest first - a stale blocking item outranks a fresh idea
    rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    keep.sort(key=lambda r: (rank.get(r["severity"], 2),
                             -r["total"] if r["source"] == "purchase" else 0,
                             r["asked_at"] or ""))
    detail["next"] = f"{keep[0]['source']}:{keep[0]['source_id']}"
    return keep[0], None, detail


def cmd_sitting(n: int) -> int:
    """The sitting: the document of questions, ordered, for one walk-through."""
    cands = from_decision_queue() + from_purchases()
    c = conn_ask()
    done = {r["key"] for r in c.execute("SELECT source||':'||source_id AS key FROM ask WHERE sent=1")}
    c.close()
    _cfo_asked = _cfo_asked_merchants()
    print(f"# Questions for Eli - {len(cands)} found, top {n} shown")
    print("# answer one at a time; each reply is recorded and becomes a rule\n")
    i = 0
    for r in cands:
        if f"{r['source']}:{r['source_id']}" in done:
            continue
        if r["source"] == "decision" and (NOT_HIS.search(r["question"]) or ALREADY_READABLE.search(r["question"])):
            continue
        if r["source"] == "purchase" and _merchant_key(r["source_id"]) in _cfo_asked:
            continue
        if r["source"] == "purchase" and _resolved_purchase(r):
            # A merchant our own records identify is not a question for the sitting either.
            continue
        i += 1
        if i > n:
            break
        print(f"[{i}] {r['subject']}")
        if r.get("recommendation"):
            print(f"     -> {shorten(r['recommendation'], 220)}")
        print()
    return 0


def cmd_status() -> int:
    if not ASK_DB.exists():
        print("no asks yet")
        return 0
    c = conn_ask()
    for r in c.execute("SELECT * FROM ask ORDER BY id DESC LIMIT 15"):
        mark = "SENT" if r["sent"] else ("ref " if r["refused_why"] else "dry ")
        print(f"#{r['id']:<4} {mark} {r['asked_at'][:16]} {r['source']:9s} "
              f"{(r['provider_sid'] or '')[:12]:12s} {r['subject'][:44]}")
    _, why, detail = pick()
    print(f"\nnext: {why or detail.get('next')}")
    print(f"      {json.dumps(detail, default=str)}")
    c.close()
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Ask the owner one question, his way.")
    ap.add_argument("--send", action="store_true")
    ap.add_argument("--why", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--sitting", nargs="?", const=20, type=int, metavar="N")
    a = ap.parse_args(argv)

    if a.status:
        return cmd_status()
    if a.sitting is not None:
        return cmd_sitting(a.sitting)

    rec, why, detail = pick(reason=a.why)
    print(f"gate: sent_today={detail.get('sent_today')}/{MAX_PER_DAY} hours={detail.get('hours')} "
          f"candidates={detail.get('candidates')} kept={detail.get('kept')}")
    if a.why:
        for r in detail.get("rejected", []):
            print(f"   refused: {r['id']:22s} {r['subject'][:52]:52s} {r['why']}")
    if rec is None:
        print(f"nothing to ask: {why}")
        return 0

    ref = "q%d" % int(datetime.now(timezone.utc).timestamp())
    try:
        body = compose(rec, ref)
    except Refuse as exc:
        print(f"REFUSED {rec['source']}:{rec['source_id']} - {exc}")
        return 0
    print(f"chosen: {rec['source']}:{rec['source_id']}  {rec['subject'][:70]}")
    cap = PURCHASE_MAX_CHARS if rec["source"] == "purchase" else MAX_CHARS
    over = "" if len(body) <= TARGET_CHARS else (
        f"  <-- over the {TARGET_CHARS}-char TARGET (within the {cap} ceiling); "
        f"the stored wording, not the asker, is what needs shortening")
    print(f"--- body ({len(body)} chars, ceiling {cap}) ---{over}")
    print(body)
    print("--- end ---")

    if len(body) > cap:
        print(f"REFUSING: {len(body)} chars over the {cap} ceiling - rule 1")
        return 1

    # THE ONE GATE. A decision row's body comes out of `owner_decision_queue`, which is
    # raw machine text often enough that `[q1790960402] Amazon order history in the ledger
    # is stale ... On the desktop (ZABZ-YOGA) run` reached his phone on 2026-10-02; a
    # purchase body has to name the charge, its date and its card.
    if ask_quality is not None:
        try:
            ok, reasons = ask_quality.review(
                body, kind="charge" if rec["source"] == "purchase" else "decision",
                merchant=rec.get("merchant") if rec["source"] == "purchase" else None,
                evidence=[], ceiling=cap)
        except Exception as exc:  # noqa: BLE001
            ok, reasons = True, [f"ask_quality failed ({exc}) - not blocking the ask"]
    else:
        ok, reasons = True, ["ask_quality not importable - the gate did not run"]
    if not ok:
        print("\nGATE REFUSED this body - nothing was sent, nothing recorded:")
        for r in reasons:
            print(f"   - {r}")
        return 0

    res = send(body, dry_run=not a.send)
    accepted = provider_accepted(res)
    if not a.send:
        print(f"\nDRY RUN - nothing recorded, nothing sent. body would be {len(body)} chars.")
        for k in ("stdout", "stderr"):
            if res.get(k):
                print(f"  {k}: {res[k][:300]}")
        return 0
    c = conn_ask()
    cur = c.execute(
        """INSERT OR IGNORE INTO ask (asked_at, source, source_id, subject, body, reference,
                                      sent, provider_ok, provider_sid, provider_detail, refused_why)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (datetime.now(timezone.utc).isoformat(), rec["source"], rec["source_id"], rec["subject"],
         body, ref, 1 if accepted else 0, 1 if res.get("rc") == 0 else 0,
         (re.search(r"\bSM[0-9a-f]{32}\b", res.get("stdout") or "") or [""])[0]
         if re.search(r"\bSM[0-9a-f]{32}\b", res.get("stdout") or "") else "",
         json.dumps(res)[:1500], "" if accepted else (res.get("stdout") or "")[:300]))
    c.commit()
    rid = cur.lastrowid
    c.close()
    print(f"\nrecorded #{rid} (provider_accepted={accepted}) in {ASK_DB}")
    for k in ("stdout", "stderr"):
        if res.get(k):
            print(f"  {k}: {res[k][:400]}")
    if accepted or res["dry_run"] or condition_only(res):
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
