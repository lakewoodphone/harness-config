#!/usr/bin/env python3
"""owner-queue-ingest-mail — ordinary email, judged, into the ONE owner queue.

WHY THIS EXISTS

The owner's words (2026-10-18): *"any email or text that you deem worthy of my attention or something I
might want to know should be in the owner queue ... I don't look at my emails, calls or texts at all."*
Google Voice is already reached through its forwarding mail by `owner-queue-ingest-gv.py`. This is the
other half: his actual inboxes.

WHY IT IS A JUDGE AND NOT A FILTER

Measured 2026-10-18 on this mailbox: 814 messages over 14 days across five accounts (~58/day).
`email_catalog` flags 347 of 812 rows `needs_owner=1` and a 25-row sample of those was UGG, Uber Cash,
AAA and newsletters -- the flag is not the signal. The previous session's bridge
(`owner-queue-ingest-mail.py.experimental`) reused `owner_attention.from_email_catalog`, produced 25
items over 3 days and was dominated by marketing, so it was sealed rather than shipped. A regex cannot
answer "would he want to know this"; a wrong DROP is invisible and expensive, a wrong KEEP is visible
and cheap.

So the verdict is made by a model against a written rubric, one call per batch of messages, and
**every verdict is stored with the reason that produced it** (`owner_mail_verdict`). Nothing is
dropped without a recorded why, so a bad rule can be audited instead of guessed at.

Rules this obeys, all measured elsewhere in this estate:

  * The model is NEVER hardcoded. `call_fast_model_simple` resolves provider and model from the live
    registry at call time, and the model that actually served each batch is stored with the verdict.
  * A judge outage is LOUD. If a batch cannot be judged the run exits non-zero and says so; it never
    silently writes nothing and lets the queue look healthy. A dead reader over a live channel is the
    exact defect this queue was built to stop repeating.
  * Google Voice forwards and Dialpad mail are EXCLUDED -- the GV ingest owns the first and the owner
    ruled the second out of his queue by name.
  * Threads collapse to one row (a six-reply thread is one conversation, not six items).
  * Re-running refreshes a pending row and never resurrects a closed one.

  owner-queue-ingest-mail.py --days 2              # normal run (the timer's shape)
  owner-queue-ingest-mail.py --days 7 --explain    # every verdict + why, writes nothing
  owner-queue-ingest-mail.py --days 7 --explain --only-dropped
  owner-queue-ingest-mail.py --rejudge --days 3    # ignore the cache and judge again
"""
from __future__ import annotations

import argparse
import hashlib
import html as _html
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone

APP_ROOT = os.environ.get("PS_APP_ROOT", "/root/personal-secretary-mvp")
DEFAULT_DB = os.environ.get("OWNER_QUEUE_DB", "/root/authority.db")
sys.path.insert(0, APP_ROOT)

# THE CWD IS LOAD-BEARING: gmail_service._tokens_dir defaults to the RELATIVE path `data/gmail_tokens`
# and resolves against the process cwd. From /root every account reports "not authenticated" while
# the tokens sit in the checkout. Measured 2026-10-18; it looks exactly like a credential outage.
if os.path.isdir(APP_ROOT):
    os.chdir(APP_ROOT)

# ── who is not judged here ────────────────────────────────────────────────────────────────────────
# Google Voice forwards belong to owner-queue-ingest-gv.py. Two ingests, one message, one row.
GV_SENDER = re.compile(r"(voice-noreply@google\.com|txt\.voice\.google\.com|voice\.google\.com)", re.I)
# The owner's rule of 2026-10-18: Dialpad is not in his queue. Its voicemail-notification mail is
# Dialpad, and it reached the previous bridge's list on its first run.
SHOP_LINE_SENDER = re.compile(r"(voicemail@dialpad\.com|@dialpad\.com)", re.I)
# The agent/system mailbox is the company talking to itself, not mail addressed to him.
DEFAULT_DENY_ACCOUNTS = ("zabzgpt@gmail.com",)

# Judge batch size. Ten keeps one bad verdict from poisoning a large batch and keeps every call well
# inside the helper's 2048-token reply cap.
BATCH = 10
BODY_CHARS = 1500
# A single run must not spend unbounded money on a first backfill. Unjudged mail stays unjudged and is
# picked up next run; nothing is dropped for being over the cap.
MAX_JUDGE_PER_RUN = 150

#: WHICH MAIL THE JUDGE IS ALLOWED TO SEE.
#:
#: MEASURED 2026-10-18, and it was the largest blind spot in the queue: the query was
#: `in:inbox newer_than:Nd`, and over one week that saw **223 messages while 385 sat outside the
#: inbox** -- 99 on his personal account, 178 on the shop account. Gmail filters auto-archive
#: receipts, invoices and notifications before he ever sees them, so a bill could live entirely in a
#: label and the queue would never have judged it. He asked for "any email ... worthy of my attention
#: or something I might want to know"; a folder boundary is not a judgement about relevance, and the
#: queue's whole job is to make that judgement itself.
#:
#: Spam and trash stay out on purpose: nothing in his bin is news, and judging it spends real money
#: per batch for mail he has already thrown away.
MAIL_QUERY = "newer_than:%dd -in:spam -in:trash"


# ── the rubric ───────────────────────────────────────────────────────────────────────────────────
# Every line here exists because the corpus contains that exact shape of mail. The DROP list is the
# measured majority; the ATTENTION list is what survived reading it.
SYSTEM_PROMPT = """You are the owner's attention filter. He is one man: he runs a phone repair shop \
and an AI company, he has a family, and HE DOES NOT READ HIS EMAIL. You decide what reaches him.

Read each email and give ONE verdict:

"drop" - he would not want to know, or would be annoyed to be told. This is the majority:
  marketing, sales, newsletters, product announcements, promotional digests, webinars,
  social media and app notifications, shipping/tracking/delivery updates, order confirmations,
  receipts with nothing to do, "your statement is ready" with no amount and no deadline,
  one-time passcodes and verification codes, calendar acceptances, satisfaction surveys,
  review requests, recruiting spam, duplicates of something already flagged, and anything
  automated where no human is waiting for anything.

"attention" - he would want to KNOW but nothing is being asked of him: a real person writing to
  him; money charged, refunded, rejected, overdue or at risk; a bank or card notice; account
  security (password, 2FA, new key, login from a new place, account locked); a deadline,
  renewal, expiry, appointment or registration; family, school, camp, medical, tuition;
  a customer, an order, a supplier, a price change; a legal, tax or regulatory notice;
  anything he would be annoyed to have missed a week later.

"decision" - a HUMAN is asking him to choose, approve or commit, and nobody else can answer it:
  an offer, a proposal, an approval someone is waiting on, a choice between two things, a
  commitment of money or time that needs his yes. NOT a decision: a bill that is due, a
  balance that is negative, a delivery that needs rescheduling, a notice that something was
  already done, a routine renewal. Those are "attention" with a deadline -- he does not need to
  CHOOSE, he needs to know, and then pay or act. When in doubt between the two, choose
  "attention": a wrong "decision" asks him a question he never had.

Judge the MESSAGE, not the sender's reputation: a marketing-looking company can send a failed
payment notice, and a person can send a mass mailing. If the body is too thin to judge, then
"attention" only if a person is plainly writing to him, otherwise "drop" with why="too thin".

Return ONLY a JSON array. One object per email, same order, "i" echoing the index given:
{"i":0,"verdict":"drop|attention|decision","tier":"critical|high|medium|low",
 "class":"person|money|security|deadline|notice",
 "title":"<=90 chars, plain, what happened, the way you would say it to him",
 "why":"<=140 chars, why it is in his queue, grounded in this message",
 "ask":true|false,        // is a person waiting on a reply from him
 "deadline":true|false,   // is there a date by which something must happen
 "money":number|null,     // the single most relevant amount in USD
 "party":"who it is from, a person or company",
 "action":"<=60 chars, the one thing he would do, or 'no action'",
 "recommendation":"if verdict is decision: the one option YOU would pick, in <=120 chars, and why.
                    Otherwise empty string."}

The owner knocks this queue out once every couple of days and wants to answer without going and
looking anything up, so a decision without a recommendation is a defect: he would have to work.

class: "person" = a human wrote to him; "money" = a bank/card/payment/invoice/tax notice;
"security" = password, 2FA, key, login, account lock; "deadline" = a registration, renewal,
expiry, appointment or filing date; "notice" = any other automated notice worth knowing.
A notice that is only "routine" (payment scheduled, statement ready, purchase approved) is
medium or low, never high -- the high and critical money notices are the ones where money has
already gone wrong. Use "drop" for class when the verdict is drop.

tier: critical = money already lost or a payment failed, account compromise, a hard deadline inside
48 hours, a family emergency. high = a person waiting on him, money at risk, a deadline inside a
week. medium = worth knowing, no urgency. low = worth knowing, can wait.

TIER IS ABOUT CONSEQUENCE, NOT ABOUT WHO SENT IT. A link from his wife is low. A forwarded
article is low. A newsletter he is subscribed to is drop. A bill that will suspend a service is
critical. A notice that a password or 2FA changed is high. If the message is already a day or
more old when it arrives in the batch, tier does not go up to compensate -- the queue scores age
by itself.

THE RATE IS PART OF THE JUDGEMENT. He receives roughly 30 emails a day and wants to be told
about a handful, not a digest of his own statements. A good day of mail produces about 3 or 4
items. If you are keeping more than one message in eight, you are being generous with his
attention, and he will stop opening the queue."""


def _norm(s: str) -> str:
    return " ".join((s or "").split()).strip()


# ── HTML → text ────────────────────────────────────────────────────────────────────────────────
# MEASURED 2026-10-18, and it was the largest quality defect in the first run. `gmail_service`
# falls back to the raw part when a message has no text/plain, so a Chase notice arrives as 17 KB of
# `<head>`, tracking scripts and inline CSS. Truncating that to 1,500 chars feeds the judge the one
# region of the message that never contains the amount, the date or the ask -- and it said so
# ("body truncated so amount unknown") while still queueing the row. Strip it before judging.
_RE_SCRIPT = re.compile(r"<(script|style|head)\b.*?</\1>", re.I | re.S)
_RE_COMMENT = re.compile(r"<!--.*?-->", re.S)
_RE_BREAK = re.compile(r"<\s*(br|/p|/div|/tr|/li|/h[1-6])\s*/?\s*>", re.I)
_RE_TAG = re.compile(r"<[^>]+>")
_RE_WS = re.compile(r"[ \t\xa0]+")


def html_to_text(raw: str) -> str:
    """The readable words of a message body, whether it arrived as text or as HTML."""
    t = raw or ""
    if "<" not in t:
        return _norm(t)
    t = _RE_COMMENT.sub(" ", t)
    t = _RE_SCRIPT.sub(" ", t)
    t = _RE_BREAK.sub("\n", t)
    t = _RE_TAG.sub(" ", t)
    t = _html.unescape(t)
    lines = [_norm(_RE_WS.sub(" ", ln)) for ln in t.splitlines()]
    out = [ln for ln in lines if ln]
    return "\n".join(out)


def _iso(ts_ms) -> str:
    try:
        return datetime.fromtimestamp(float(ts_ms) / 1000.0, tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        return datetime.now(timezone.utc).isoformat()


def load_settings():
    """The app's settings object. `get_settings` does NOT exist in app.config -- only `settings` --
    so both shapes are tried, same as the GV ingest and owner_attention_sweep."""
    try:
        from app.config import get_settings as fn  # type: ignore

        return fn() if callable(fn) else fn
    except Exception:
        pass
    from app.config import settings as s  # type: ignore

    return s


# ── the verdict cache ────────────────────────────────────────────────────────────────────────────
CACHE_SCHEMA = """
CREATE TABLE IF NOT EXISTS owner_mail_verdict (
  account     TEXT NOT NULL,
  message_id  TEXT NOT NULL,
  thread_id   TEXT NOT NULL DEFAULT '',
  sender      TEXT NOT NULL DEFAULT '',
  subject     TEXT NOT NULL DEFAULT '',
  received_at TEXT NOT NULL DEFAULT '',
  verdict     TEXT NOT NULL,
  tier        TEXT NOT NULL DEFAULT 'low',
  class       TEXT NOT NULL DEFAULT 'notice',
  title       TEXT NOT NULL DEFAULT '',
  why         TEXT NOT NULL DEFAULT '',
  ask         INTEGER NOT NULL DEFAULT 0,
  deadline    INTEGER NOT NULL DEFAULT 0,
  money       REAL,
  party       TEXT NOT NULL DEFAULT '',
  action      TEXT NOT NULL DEFAULT '',
  recommendation TEXT NOT NULL DEFAULT '',
  resolves    INTEGER NOT NULL DEFAULT 0,
  model       TEXT NOT NULL DEFAULT '',
  judged_at   TEXT NOT NULL,
  PRIMARY KEY (account, message_id)
);
CREATE INDEX IF NOT EXISTS idx_omv_received ON owner_mail_verdict(received_at DESC);
"""


def ensure_cache(con) -> None:
    con.executescript(CACHE_SCHEMA)
    # The class column was added after the first run; a cache is a cache, so migrate in place.
    have = {r[1] for r in con.execute("PRAGMA table_info(owner_mail_verdict)")}
    if "class" not in have:
        con.execute("ALTER TABLE owner_mail_verdict ADD COLUMN class TEXT NOT NULL DEFAULT 'notice'")
    if "recommendation" not in have:
        con.execute("ALTER TABLE owner_mail_verdict ADD COLUMN recommendation TEXT NOT NULL DEFAULT ''")
    if "resolves" not in have:
        con.execute("ALTER TABLE owner_mail_verdict ADD COLUMN resolves INTEGER NOT NULL DEFAULT 0")
    con.commit()


def cached(con, account: str, mid: str):
    return con.execute(
        "SELECT verdict, tier, class, title, why, ask, deadline, money, party, action, model,"
        "       thread_id, recommendation"
        "  FROM owner_mail_verdict WHERE account=? AND message_id=?",
        (account, mid)).fetchone()


# ── reading the mailbox ─────────────────────────────────────────────────────────────────────────
def accounts_to_read(settings, requested: str) -> list[str]:
    from app.services import gmail_service  # type: ignore

    if requested and requested != "all":
        wanted = [a.strip() for a in requested.split(",") if a.strip()]
        return [a for a in wanted if a not in DEFAULT_DENY_ACCOUNTS]
    try:
        live = list(gmail_service.list_authenticated_accounts(settings))
    except Exception as exc:  # noqa: BLE001
        print("cannot list authenticated accounts: %s: %s" % (type(exc).__name__, exc),
              file=sys.stderr)
        return []
    return [a for a in live if a not in DEFAULT_DENY_ACCOUNTS]


def fetch(accounts, days: int, verbose: bool):
    """Headers for every message in the window. Bodies are read only for uncached messages."""
    from app.services import gmail_service  # type: ignore

    settings = load_settings()
    out, errors = [], []
    for account in accounts:
        try:
            msgs = gmail_service.search_messages(
                settings, account=account, query=MAIL_QUERY % days,
                max_results=400)
        except Exception as exc:  # noqa: BLE001
            errors.append("%s search: %s: %s" % (account, type(exc).__name__, exc))
            continue
        if verbose:
            print("  %s: %d message(s)" % (account, len(msgs)), file=sys.stderr)
        for m in msgs:
            sender = str(m.get("from") or "")
            if GV_SENDER.search(sender) or SHOP_LINE_SENDER.search(sender):
                continue
            out.append({
                "account": account,
                "message_id": str(m.get("id") or ""),
                "thread_id": str(m.get("thread_id") or ""),
                "sender": _norm(sender),
                "subject": _norm(m.get("subject") or ""),
                "snippet": _norm(m.get("snippet") or ""),
                "received_at": _iso(m.get("internal_ts")),
            })
    return out, errors, settings


def read_body(settings, account: str, mid: str) -> str:
    from app.services import gmail_service  # type: ignore

    full = gmail_service.read_message(settings, account=account, message_id=mid)
    raw = str(full.get("body") or full.get("body_text") or "")
    return html_to_text(raw)[:BODY_CHARS]


# ── the judge ───────────────────────────────────────────────────────────────────────────────────
_VERDICTS = ("drop", "attention", "decision")
_TIERS = ("critical", "high", "medium", "low")
_CLASSES = ("person", "money", "security", "deadline", "notice")


def _coerce(obj: dict, fallback_party: str) -> dict:
    v = str(obj.get("verdict") or "").strip().lower()
    if v not in _VERDICTS:
        v = "attention"  # an unparsable verdict must not silently delete mail
    tier = str(obj.get("tier") or "").strip().lower()
    if tier not in _TIERS:
        tier = "medium" if v != "drop" else "low"
    cls = str(obj.get("class") or "").strip().lower()
    if cls not in _CLASSES:
        cls = "notice" if v != "drop" else "drop"
    money = obj.get("money")
    try:
        money = float(money) if money not in (None, "", "null") else None
    except (TypeError, ValueError):
        money = None
    return {
        "verdict": v,
        "tier": tier,
        "class": cls,
        "title": _norm(str(obj.get("title") or ""))[:140],
        "why": _norm(str(obj.get("why") or ""))[:220],
        "ask": bool(obj.get("ask")),
        "deadline": bool(obj.get("deadline")),
        "money": money,
        "party": _norm(str(obj.get("party") or fallback_party))[:120],
        "action": _norm(str(obj.get("action") or ""))[:90],
        "recommendation": _norm(str(obj.get("recommendation") or ""))[:300],
    }


#: A machine never asks him to CHOOSE. Measured 2026-10-18: the judge returned "decision" for
#: "Walmart: accept free later delivery of 3 items by 7:06pm" and for Telnyx's daily "balance is
#: -$0.01" notice -- both are obligations, not choices, and a decision the owner cannot answer is
#: worse than an attention item he can dismiss. The rubric says so; this enforces it deterministically
#: so one model wobble cannot put a billing notice in front of him as a question.
def demote_machine_decisions(v: dict) -> dict:
    if v.get("verdict") == "decision" and v.get("class") in ("money", "notice"):
        v = dict(v)
        v["verdict"] = "attention"
        v["why"] = (v.get("why") or "billing/notice") + " [machine notice, not a choice]"
        v["action"] = v.get("action") or "pay or let it ride"
        v["recommendation"] = ""
    return v


# ── closing the loop: a sender that says "fixed" closes its own alarm ───────────────────────────
# MEASURED 2026-10-18, and it was the queue's worst remaining behaviour: Telnyx's "balance is -$0.01,
# services will be suspended" sat at CRITICAL and at the top of the queue for two days AFTER Telnyx
# wrote "account re-enabled after payment". Both facts were in the mailbox; nothing connected them, so
# the queue answered yesterday's question with total confidence. That is worse than a missing item.
#
# The rule is deliberately narrow: the resolution must come from the SAME sender identity, be NEWER
# than the alarm, and the alarm row must actually read like an alarm. It only ever closes `attention`
# -- a decision he has not answered stays his, even if the situation moved (the card flags it POSSIBLY
# MOOT instead). Every close is recorded with what closed it, so this can be audited later.
RE_RESOLVED = re.compile(
    r"(re-?enabled|has been restored|(?:service|account|access|line)s? (?:has|have) been restored|"
    r"payment (?:has been )?received|we(?:'ve| have) received your payment|thank you for your payment|"
    r"successfully paid|has been resolved|is now resolved|no longer (?:suspended|overdrawn|past due|"
    r"restricted|locked|negative)|backup (?:has been|was) deleted|auto-?recharged|"
    r"recharged successfully|balance (?:is now|has been) (?:positive|restored)|"
    r"order (?:has been )?delivered|confirmed (?:received|delivered))", re.I)
RE_ALARM = re.compile(
    r"(suspend|overdrawn|negative|declin|failed|past due|will be|expir|final notice|"
    r"action required|used up|quota|is due|payment due|low balance|insufficient)", re.I)


def reconcile(con, apply: bool) -> list[tuple[int, str]]:
    """Close pending attention rows that a later message from the same sender says is over."""
    try:
        cands = con.execute(
            "SELECT account, sender, subject, title, received_at FROM owner_mail_verdict"
            " WHERE resolves=1 AND received_at > datetime('now','-14 day')"
            " ORDER BY received_at DESC LIMIT 200").fetchall()
    except Exception:
        return []
    closed: list[tuple[int, str]] = []
    seen: set[int] = set()
    for c in cands:
        kind, value = _sender_identity(c["sender"])
        if not value:
            continue
        like = ("%%%s%%" % value) if kind == "address" else ("%%@%s%%" % value)
        try:
            rows = con.execute(
                "SELECT id, question, evidence_at FROM owner_decision_queue"
                " WHERE status='pending' AND kind='attention'"
                "   AND source LIKE 'mail-ingest:%'"
                "   AND meta_json LIKE ? AND evidence_at < ?",
                (like, c["received_at"])).fetchall()
        except Exception:
            continue
        for r in rows:
            if r["id"] in seen or not RE_ALARM.search(r["question"] or ""):
                continue
            seen.add(r["id"])
            why = "auto-closed: %s said \"%s\" (%s)" % (
                _norm(str(c["sender"]))[:40], _norm(str(c["title"] or c["subject"]))[:80],
                str(c["received_at"])[:10])
            closed.append((r["id"], why))
            if apply:
                con.execute(
                    "UPDATE owner_decision_queue SET status='resolved', resolved_at=?,"
                    " resolution=? WHERE id=?", (now_iso(), why, r["id"]))
    if apply and closed:
        con.commit()
    return closed


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _learned_profile(con, min_n: int = 6) -> str:
    """What his answers have taught about WHO and WHAT, not just about one item.

    The few-shot examples below teach "this message was not worth it". This block teaches the shape:
    eight notices from one kind of sender dismissed is a statement about that kind, and a judge told
    it will stop re-litigating a taste it can see. Only cells with real evidence are printed, and the
    count is printed with each, so the judge can weigh a 6-close claim differently from a 30-close one.
    """
    try:
        con.commit()
        rows = con.execute(
            "SELECT LOWER(TRIM(COALESCE(sender_domain,''))) k,"
            "  SUM(CASE WHEN action='answered' THEN 1 ELSE 0 END) a,"
            "  SUM(CASE WHEN action='dismissed' THEN 1 ELSE 0 END) d"
            " FROM owner_queue_feedback"
            " WHERE at > datetime('now','-120 day') AND COALESCE(sender_domain,'') <> ''"
            " GROUP BY k HAVING (a+d) >= ? ORDER BY (d*1.0)/(a+d) DESC LIMIT 8",
            (min_n,)).fetchall()
        cls = con.execute(
            "SELECT LOWER(TRIM(COALESCE(cls,''))) k,"
            "  SUM(CASE WHEN action='answered' THEN 1 ELSE 0 END) a,"
            "  SUM(CASE WHEN action='dismissed' THEN 1 ELSE 0 END) d"
            " FROM owner_queue_feedback"
            " WHERE at > datetime('now','-120 day') AND COALESCE(cls,'') <> ''"
            " GROUP BY k HAVING (a+d) >= ?", (min_n,)).fetchall()
    except Exception:
        return ""
    lines = []
    for r in rows:
        n = int(r["a"]) + int(r["d"])
        if int(r["d"]) >= n * 0.6:
            lines.append("  · mail from %s: he dismissed %d of %d" % (r["k"], r["d"], n))
        elif int(r["a"]) >= n * 0.75:
            lines.append("  · mail from %s: he acted on %d of %d" % (r["k"], r["a"], n))
    for r in cls:
        n = int(r["a"]) + int(r["d"])
        if int(r["d"]) >= n * 0.6:
            lines.append("  · class '%s': he dismissed %d of %d" % (r["k"], r["d"], n))
        elif int(r["a"]) >= n * 0.75:
            lines.append("  · class '%s': he acted on %d of %d" % (r["k"], r["a"], n))
    if not lines:
        return ""
    return ("WHAT HIS OWN ANSWERS HAVE TAUGHT ABOUT WHO AND WHAT. Evidence counts are shown; "
            "judge this batch the same way:\n" + "\n".join(lines))


def _learned_examples(con, limit: int = 12) -> str:
    """His own past answers, as few-shot examples for tomorrow's judgement.

    Owner's requirement, 2026-10-18: "the queue needs to learn over time what to put in it ... based
    on my responses". A rubric written by an agent is a guess about his taste; this replaces part of
    the guess with what he actually said. Verbatim, sender included, newest first.
    """
    try:
        rows = con.execute(
            "SELECT f.action, COALESCE(f.answer,'') said, substr(q.question,1,100) t,"
            "       COALESCE(json_extract(q.meta_json,'$.sender'),'') snd"
            "  FROM owner_queue_feedback f"
            "  JOIN owner_decision_queue q ON CAST(q.id AS TEXT) = f.item_id"
            " WHERE f.action IN ('answered','dismissed')"
            " ORDER BY f.at DESC LIMIT ?", (limit,)).fetchall()
    except Exception:
        return ""
    if not rows:
        return ""
    out = ["WHAT HE HAS ALREADY SAID about earlier queue items. Match his taste, not your own:",
           "  - DISMISSED means he judged it not worth his attention; treat that as evidence about",
           "    that kind of mail, not a blanket rule about the sender."]
    for r in rows:
        said = _norm(str(r["said"] or ""))[:90]
        out.append('  · %s "%s"%s%s' % (
            "ANSWERED" if r["action"] == "answered" else "DISMISSED",
            _norm(str(r["t"] or ""))[:90],
            (" from %s" % _norm(str(r["snd"] or ""))[:50]) if r["snd"] else "",
            (' — he said: "%s"' % said) if said else ""))
    return "\n".join(out)


def judge(batch: list[dict], settings, learned: str = "") -> tuple[list[dict], str]:
    """One model call. Returns (verdicts, model_that_served). Raises on failure -- never guesses."""
    from app.assistant_chat import call_fast_model_simple  # type: ignore

    payload = []
    for i, m in enumerate(batch):
        payload.append({
            "i": i,
            "account": m["account"],
            "from": m["sender"],
            "to": m.get("to") or "",
            "subject": m["subject"],
            "when": m["received_at"][:16],
            "body": m.get("body") or m.get("snippet") or "",
        })
    user_text = json.dumps(payload, ensure_ascii=False)[:24000]
    if learned:
        user_text = user_text + "\n\n" + learned[:3000]
    resp = call_fast_model_simple(
        settings=settings, agent_id="owner_queue_mail_judge",
        system_prompt=SYSTEM_PROMPT, user_text=user_text, max_tokens=2048)
    if not resp.get("ok"):
        raise RuntimeError("judge unavailable: %s" % (resp.get("errors") or resp.get("error")))
    raw = str(resp.get("reply") or "")
    start, end = raw.find("["), raw.rfind("]")
    if start < 0 or end <= start:
        raise RuntimeError("judge returned no JSON array: %r" % raw[:200])
    try:
        arr = json.loads(raw[start:end + 1])
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("judge JSON did not parse: %s: %r" % (exc, raw[start:start + 200]))
    if not isinstance(arr, list):
        raise RuntimeError("judge returned %s, not a list" % type(arr).__name__)

    by_i = {}
    for obj in arr:
        if isinstance(obj, dict):
            try:
                by_i[int(obj.get("i"))] = obj
            except (TypeError, ValueError):
                continue
    out = []
    for i, m in enumerate(batch):
        obj = by_i.get(i)
        if obj is None:
            # A message the model skipped is not "no opinion" -- treat as attention and say so.
            out.append(_coerce({"verdict": "attention", "tier": "low",
                                "title": m["subject"] or m["sender"],
                                "why": "judge returned no verdict for this message",
                                "party": m["sender"]}, m["sender"]))
        else:
            out.append(demote_machine_decisions(_coerce(obj, m["sender"])))
    model = "%s/%s" % (resp.get("provider") or "?", resp.get("model") or "?")
    return out, model


# ── writing the one queue ───────────────────────────────────────────────────────────────────────
def _key(account: str, thread_id: str, message_id: str) -> str:
    # A thread is one conversation: the newest message is its state, so the thread is the identity.
    ident = thread_id or message_id
    return "mail:%s" % hashlib.sha1(("%s|%s" % (account, ident)).encode()).hexdigest()[:20]


#: A sentence with the volatile bits removed: dates, amounts, reference numbers, punctuation.
#: MEASURED 2026-10-18 on the first 7-day backfill: Telnyx sent "balance is -$0.01" on four
#: consecutive days and the queue got FOUR critical rows for one fact, and 300DDR's "backup may be
#: deleted today" arrived as three. A recurring machine notice is ONE thing that keeps being true.
_RE_FP_STRIP = re.compile(
    r"(\$?\d[\d,\.]*|\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s*\d{0,2}\b"
    r"|\b\d{1,2}/\d{1,2}(/\d{2,4})?\b|\b(today|tomorrow|tonight|yesterday)\b)", re.I)


def _fp(subject: str, sender: str) -> str:
    """The identity of a FACT, as opposed to the identity of a message."""
    dom = (re.sub(r".*@", "", (sender or "").lower()).split(">")[0] or sender or "").strip()
    s = re.sub(r"^(re|fwd|fw)\s*:\s*", "", str(subject or ""), flags=re.I)
    s = _RE_FP_STRIP.sub(" ", s.lower())
    s = re.sub(r"[^a-z0-9]+", " ", s).strip()
    return hashlib.sha1(("%s|%s" % (dom, s[:70])).encode()).hexdigest()[:20]


def key_for(it: dict) -> str:
    """A person's conversation is one row; a machine's recurring notice is one row, whatever the day.

    Collapsing a person's mail by subject would merge two different people writing about the same
    thing, so `class='person'` keeps the thread identity and everything else keys on the fact.
    """
    if (it.get("class") == "person") and it.get("thread_id"):
        return _key(it["account"], it["thread_id"], it["message_id"])
    return "mail:fact:%s" % _fp(it.get("subject") or it.get("title") or "", it.get("sender") or "")


# ── routine notices fold into one row a day ──────────────────────────────────────────────────────
# MEASURED 2026-10-18 on the first judged run: 33 messages kept 20 rows, and five of them were the
# same thing happening at different banks -- "Amex large purchase approved", "Chase payment
# scheduled", "BofA $1,000 Zelle sent", "Chase money received", "statement available". He asked for
# what he would want to KNOW; he did not ask to be walked through his own statements. So a routine
# money/notice item (medium or low -- never the critical ones) folds into ONE row per class per day.
# Nothing is deleted: the row carries every member and `--explain --only-kept` still lists each.
DIGEST_CLASSES = ("money", "notice")
DIGEST_TIERS = ("medium", "low")
_TIER_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}


def fold_routine_notices(rows: list[dict]) -> tuple[list[dict], int]:
    singles, groups = [], {}
    for r in rows:
        if r["verdict"] == "attention" and r["class"] in DIGEST_CLASSES and r["tier"] in DIGEST_TIERS:
            groups.setdefault((r["class"], r["received_at"][:10]), []).append(r)
        else:
            singles.append(r)
    folded = 0
    for (cls, day), members in groups.items():
        if len(members) == 1:
            singles.append(members[0])  # one notice is not a digest, it is one notice
            continue
        folded += len(members) - 1
        members.sort(key=lambda x: x["received_at"], reverse=True)
        top = max(members, key=lambda x: (_TIER_RANK.get(x["tier"], 0), x["received_at"]))
        heads = [m["title"] or m["subject"] for m in members[:3]]
        label = "notices" if cls == "notice" else ("%s notices" % cls)
        title = "%d %s (%s): %s" % (
            len(members), label, day, " · ".join(h[:48] for h in heads))
        singles.append({
            "account": "digest", "message_id": "digest:%s:%s" % (cls, day),
            "thread_id": "digest:%s:%s" % (cls, day),
            "sender": ", ".join(sorted({m["party"] or m["sender"] for m in members})[:4]),
            "subject": title, "received_at": members[0]["received_at"],
            "verdict": "attention", "tier": top["tier"], "class": cls,
            "title": title[:140],
            "why": "; ".join((m["why"] or m["title"])[:60] for m in members)[:220],
            "ask": any(m["ask"] for m in members),
            "deadline": any(m["deadline"] for m in members),
            "money": max([m["money"] for m in members if m["money"]] or [None]) or None,
            "party": "several", "action": "skim",
            "model": ", ".join(sorted({m["model"] for m in members if m["model"]})),
            "_count": len(members),
            "_members": [(m["title"], m["why"], m["party"] or m["sender"]) for m in members][:12],
            "_key": "mail:digest:%s:%s" % (cls, day),
        })
    singles.sort(key=lambda x: x["received_at"], reverse=True)
    return singles, folded


def _title(m: dict, v: dict) -> str:
    t = v["title"] or m["subject"] or m["sender"]
    if v["verdict"] == "decision":
        return t if t.lower().startswith(("approve", "decide", "choose", "pay", "sign")) else t
    return t


#: Mail domains that identify a PERSON's mailbox, not an organisation. Matching history on one of
#: these joins every item from every Gmail user -- measured 2026-10-18: a card for Yocheved's grocery
#: request listed four Telnyx and Chase items as "history with this sender". A false provenance claim
#: is worse than no history, so for these the full address is the identity, never the domain.
FREEMAIL_DOMAINS = frozenset({
    "gmail.com", "googlemail.com", "yahoo.com", "outlook.com", "hotmail.com", "live.com",
    "icloud.com", "me.com", "aol.com", "proton.me", "protonmail.com", "gmx.com", "msn.com",
})


def _sender_identity(sender: str) -> tuple[str, str]:
    """(match_kind, value) for history: the full address for freemail, the domain otherwise."""
    addr = ""
    m = re.search(r"<([^>]+)>", sender or "")
    if m:
        addr = m.group(1).strip().lower()
    else:
        m2 = re.search(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+", sender or "")
        addr = (m2.group(0).lower() if m2 else "")
    dom = addr.split("@")[-1] if "@" in addr else ""
    if dom in FREEMAIL_DOMAINS and addr:
        return "address", addr
    if dom:
        return "domain", dom
    return "", ""


def _history_block(con, it: dict) -> str:
    """What the queue already knows about this sender -- gathered BEFORE the row is written.

    The owner's requirement (2026-10-18): "all information about it must be gathered in case I want
    more info, so only put it in the queue after all info is gathered". A row that lands without the
    last few things this sender wrote, or without how he answered the last one, makes him go and
    look -- which is the thing he asked to stop doing.
    """
    kind, value = _sender_identity(it.get("sender") or "")
    party = (it.get("party") or "").strip()
    clauses, args = [], []
    if kind == "address":
        clauses.append("meta_json LIKE ?")
        args.append("%%%s%%" % value)
    elif kind == "domain":
        clauses.append("meta_json LIKE ?")
        args.append("%%@%s%%" % value)
    # A party match only when the party is a real name, not a section label.
    if party and len(party) >= 5 and party.lower() not in ("several", "unknown", "various"):
        clauses.append("party LIKE ?")
        args.append(party[:12] + "%")
    if not clauses:
        return ""
    try:
        rows = con.execute(
            "SELECT id, status, substr(question,1,90) q,"
            "       COALESCE(NULLIF(answer,''), NULLIF(resolution,''), '') how,"
            "       COALESCE(answered_at, resolved_at, asked_at) t"
            "  FROM owner_decision_queue"
            " WHERE status IN ('answered','resolved','dismissed','dismissed_noise_v1')"
            "   AND (" + " OR ".join(clauses) + ")"
            " ORDER BY t DESC LIMIT 4", args).fetchall()
    except Exception:
        return ""
    if not rows:
        return ""
    out = ["HISTORY WITH THIS SENDER (%d closed item(s), newest first):" % len(rows)]
    for r in rows:
        said = _norm(str(r["how"] or ""))[:100]
        out.append("  · #%s %s %s: %s%s" % (r["id"], str(r["t"])[:10], r["status"],
                                            str(r["q"] or "")[:80],
                                            (" — he said: \"%s\"" % said) if said else ""))
    return "\n".join(out)


def _context(m: dict, v: dict, count: int, history: str = "") -> str:
    lines = [
        "From: %s" % m["sender"],
        "To: %s" % (m.get("account") or ""),
        "When: %s" % m["received_at"][:16].replace("T", " "),
        "Subject: %s" % m["subject"],
        "Why it is in the queue: %s" % v["why"],
    ]
    if v["action"]:
        lines.append("What he would do: %s" % v["action"])
    if history:
        lines += ["", history]
    if count > 1 and not v.get("_members"):
        lines.append("In this thread: %d message(s); this is the newest." % count)
    for title, why, who in (v.get("_members") or []):
        lines.append("  · %s — %s — %s" % (who, title, why))
    body = m.get("body") or m.get("snippet") or ""
    if body and not v.get("_members"):
        lines += ["", body[:1200]]
    return "\n".join(lines)


def write_items(con, items: list[dict]) -> dict:
    """Upsert by dedupe_key; never resurrects a row he already closed."""
    stats = {"new": 0, "refreshed": 0, "left_closed": 0}
    now_iso = datetime.now(timezone.utc).isoformat()
    for it in items:
        key = it.get("_key") or key_for(it)
        existing = con.execute(
            "SELECT id, status FROM owner_decision_queue WHERE dedupe_key=?", (key,)).fetchone()
        meta = json.dumps({
            "ask": bool(it["ask"]), "deadline": bool(it["deadline"]), "money": it["money"],
            "verdict": it["verdict"], "reason": it["why"], "account": it["account"],
            "message_id": it["message_id"], "thread_id": it["thread_id"],
            "sender": it["sender"], "subject": it["subject"], "action": it["action"],
            "class": it.get("class"), "count": it.get("_count"),
            "members": it.get("_members"), "model": it["model"], "judged": "model",
        }, default=str)
        question = _title(it, it)
        history = "" if it.get("_members") else _history_block(con, it)
        context = _context(it, it, it.get("_count") or 1, history)
        if existing:
            if existing[1] == "pending":
                con.execute(
                    "UPDATE owner_decision_queue SET question=?, context=?, severity=?,"
                    " kind=?, recommendation=?, evidence_at=?, meta_json=? WHERE dedupe_key=?",
                    (question, context, it["tier"],
                     "decision" if it["verdict"] == "decision" else "attention",
                     it.get("recommendation") or "", it["received_at"], meta, key))
                stats["refreshed"] += 1
            else:
                stats["left_closed"] += 1
            continue
        con.execute(
            "INSERT INTO owner_decision_queue"
            " (asked_at, question, context, recommendation, severity, source, status, kind,"
            "  channel, party, evidence_at, evidence_ref, dedupe_key, meta_json)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (now_iso, question, context, it.get("recommendation") or "", it["tier"],
             "mail-ingest:%s" % it["verdict"],
             "pending", "decision" if it["verdict"] == "decision" else "attention",
             "email", it["party"] or it["sender"], it["received_at"], it["message_id"],
             key, meta))
        stats["new"] += 1
    con.commit()
    return stats


def migrate_keys(con, apply: bool) -> int:
    """Re-key rows written by an earlier scheme, without deleting any.

    The dedupe key changed from "this thread" to "this fact" on 2026-10-18, because Telnyx's daily
    balance notice had produced four critical rows. Re-ingesting under the new key would have left
    the old rows pending beside the new ones, so they are re-keyed in place; where two old rows now
    collapse to one identity, the older is marked `superseded` with a note -- status, never deletion.
    """
    rows = con.execute(
        "SELECT id, dedupe_key, evidence_at, meta_json FROM owner_decision_queue"
        " WHERE status='pending' AND source LIKE 'mail-ingest:%' ORDER BY evidence_at DESC").fetchall()
    changed = collide = 0
    seen = {}
    for r in rows:
        meta = {}
        try:
            meta = json.loads(r["meta_json"] or "{}")
        except Exception:
            meta = {}
        want = key_for({"class": meta.get("class"), "thread_id": meta.get("thread_id"),
                        "account": meta.get("account") or "", "message_id": meta.get("message_id"),
                        "subject": meta.get("subject"), "sender": meta.get("sender")})
        if want in seen:
            collide += 1
            print("  #%s superseded by #%s (same fact)" % (r["id"], seen[want]))
            if apply:
                con.execute("UPDATE owner_decision_queue SET status='superseded',"
                            " meta_json=? WHERE id=?",
                            (json.dumps(dict(meta, superseded_by=seen[want]), default=str), r["id"]))
            continue
        seen[want] = r["id"]
        if want != r["dedupe_key"]:
            changed += 1
            if apply:
                con.execute("UPDATE owner_decision_queue SET dedupe_key=? WHERE id=?", (want, r["id"]))
    if apply:
        con.commit()
    print("mail keys: %d re-keyed, %d folded into an existing fact, %d pending row(s) read%s"
          % (changed, collide, len(rows), "" if apply else "  (dry run; --migrate-keys-apply writes)"))
    return 0


# ── main ───────────────────────────────────────────────────────────────────────────────────────
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=2)
    ap.add_argument("--accounts", default="all",
                    help="'all' (default, every authenticated account minus the system mailbox) "
                         "or a comma-separated list")
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--explain", action="store_true", help="print every verdict, write nothing")
    ap.add_argument("--only-dropped", action="store_true")
    ap.add_argument("--only-kept", action="store_true")
    ap.add_argument("--rejudge", action="store_true", help="ignore the verdict cache")
    ap.add_argument("--max-judge", type=int, default=MAX_JUDGE_PER_RUN)
    ap.add_argument("--migrate-keys", action="store_true",
                    help="re-key rows written under an earlier dedupe scheme (dry run)")
    ap.add_argument("--migrate-keys-apply", action="store_true", help="...and write it")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args(argv)

    try:
        settings = load_settings()
    except Exception as exc:  # noqa: BLE001
        print("mail ingest FAILED: cannot load app settings: %s: %s" % (type(exc).__name__, exc))
        return 3
    accounts = accounts_to_read(settings, a.accounts)
    if not accounts:
        print("mail ingest FAILED: no authenticated account to read (tokens?)")
        return 3

    con = sqlite3.connect(a.db, timeout=180)
    con.row_factory = sqlite3.Row
    ensure_cache(con)

    if a.migrate_keys or a.migrate_keys_apply:
        return migrate_keys(con, apply=a.migrate_keys_apply)

    msgs, errors, settings = fetch(accounts, a.days, a.verbose or a.explain)
    if not msgs:
        print("mail ingest: 0 message(s) in %d day(s) across %d account(s)%s"
              % (a.days, len(accounts), ("; errors: %s" % errors) if errors else ""))
        return 1 if errors else 0

    # ── judge what is not cached ──
    pending, verdicts = [], {}
    for m in msgs:
        row = None if a.rejudge else cached(con, m["account"], m["message_id"])
        if row:
            verdicts[(m["account"], m["message_id"])] = dict(row)
            continue
        pending.append(m)
    pending.sort(key=lambda m: m["received_at"], reverse=True)
    over_cap = max(0, len(pending) - a.max_judge)
    pending = pending[: a.max_judge]

    judged_n, models, judge_errors = 0, set(), []
    # Two learning blocks, and they teach different things: the examples teach "this message was not
    # worth it", the profile teaches the shape across messages ("he has dismissed 8 of 10 from this
    # sender"). A judge given only examples overfits to the last dozen items.
    learned = "\n\n".join(x for x in (_learned_profile(con), _learned_examples(con)) if x)
    for i in range(0, len(pending), BATCH):
        batch = pending[i:i + BATCH]
        for m in batch:
            try:
                m["body"] = read_body(settings, m["account"], m["message_id"])
            except Exception as exc:  # noqa: BLE001
                m["body"] = m.get("snippet") or ""
                errors.append("body %s: %s" % (m["message_id"], exc))
        try:
            out, model = judge(batch, settings, learned)
        except Exception as exc:  # noqa: BLE001
            judge_errors.append("%s: %s" % (type(exc).__name__, exc))
            break
        models.add(model)
        # NOT `now_iso` -- that is the module-level function, and shadowing it here made the run
        # arithmetic fail with "str object is not callable" on the first real run (2026-10-18).
        judged_ts = datetime.now(timezone.utc).isoformat()
        for m, v in zip(batch, out):
            con.execute(
                "INSERT OR REPLACE INTO owner_mail_verdict"
                " (account, message_id, thread_id, sender, subject, received_at, verdict, tier,"
                "  class, title, why, ask, deadline, money, party, action, recommendation,"
                "  resolves, model, judged_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (m["account"], m["message_id"], m["thread_id"], m["sender"], m["subject"],
                 m["received_at"], v["verdict"], v["tier"], v["class"], v["title"], v["why"],
                 int(v["ask"]), int(v["deadline"]), v["money"], v["party"], v["action"],
                 v.get("recommendation") or "",
                 1 if RE_RESOLVED.search(m.get("body") or "") else 0,
                 model, judged_ts))
            verdicts[(m["account"], m["message_id"])] = {
                "verdict": v["verdict"], "tier": v["tier"], "class": v["class"],
                "title": v["title"], "why": v["why"],
                "ask": v["ask"], "deadline": v["deadline"], "money": v["money"],
                "party": v["party"], "action": v["action"],
                "recommendation": v.get("recommendation") or "",
                "model": model, "thread_id": m["thread_id"]}
            judged_n += 1
        con.commit()
        if a.verbose:
            print("  judged %d/%d" % (judged_n, len(pending)), file=sys.stderr)

    # ── collapse threads, build the rows worth writing ──
    keep, tally = [], {"drop": 0, "attention": 0, "decision": 0}
    for m in msgs:
        v = verdicts.get((m["account"], m["message_id"]))
        if not v:
            continue
        tally[str(v["verdict"])] = tally.get(str(v["verdict"]), 0) + 1
        if v["verdict"] not in ("attention", "decision"):
            continue
        item = dict(m)
        item.update({
            "verdict": v["verdict"], "tier": v["tier"], "class": v["class"],
            "title": v["title"], "why": v["why"],
            "ask": bool(v["ask"]), "deadline": bool(v["deadline"]), "money": v["money"],
            "party": v["party"], "action": v["action"], "model": v["model"] or "",
            "recommendation": v.get("recommendation") or "",
            "thread_id": v["thread_id"] or m["thread_id"],
        })
        keep.append(item)

    # One row per conversation (people) or per fact (machines): the newest is the current state.
    by_key, collapsed = {}, 0
    for it in sorted(keep, key=lambda x: x["received_at"]):
        k = key_for(it)
        if k in by_key:
            collapsed += 1
            it["_count"] = (by_key[k].get("_count") or 1) + 1
        by_key[k] = it
    rows = list(by_key.values())
    rows.sort(key=lambda x: x["received_at"], reverse=True)

    rows, folded = fold_routine_notices(rows)

    if a.explain:
        closed = reconcile(con, apply=False)
        sel = rows
        if a.only_dropped:
            sel = [m for m in msgs
                   if (verdicts.get((m["account"], m["message_id"])) or {}).get("verdict") == "drop"]
        elif a.only_kept:
            sel = rows
        print("mail: %d message(s) in %d day(s); verdicts: %d drop, %d attention, %d decision"
              % (len(msgs), a.days, tally.get("drop", 0), tally.get("attention", 0),
                 tally.get("decision", 0)))
        print("      %d thread(s) after collapse (%d folded); %d routine notice(s) folded into "
              "%d digest row(s); %d newly judged this run"
              % (len(rows), collapsed, folded, sum(1 for r in rows if r.get("_members")), judged_n))
        if over_cap:
            print("      %d message(s) over the per-run judge cap, left for the next run" % over_cap)
        if models:
            print("      judged by: %s" % ", ".join(sorted(models)))
        for m in sel[:400]:
            v = verdicts.get((m["account"], m["message_id"])) or m
            print("  [%-9s %-8s] %-28s %s" % (v.get("verdict", "?"), v.get("tier", ""),
                                              str(m.get("sender") or "")[:28],
                                              str(v.get("title") or m.get("subject"))[:88]))
            if v.get("why"):
                print("       why: %s" % v["why"][:130])
        if judge_errors:
            print("\nJUDGE FAILED: %s" % "; ".join(judge_errors))
            return 4
        if closed:
            print("\nWOULD CLOSE %d stale row(s) — a later message from the same sender resolves them:"
                  % len(closed))
            for cid, why in closed[:20]:
                print("  #%-5s %s" % (cid, why))
        return 0

    stats = write_items(con, rows)
    closed = reconcile(con, apply=True)
    # The arithmetic of a COMPLETE read, in one row health can check: every message fetched either
    # got a verdict or is named as over the cap. A judge that silently stops seeing a folder looks
    # identical to a quiet week from the outside, and this is the row that tells them apart.
    try:
        con.execute(
            "CREATE TABLE IF NOT EXISTS owner_queue_ingest_run ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT NOT NULL, ran_at TEXT NOT NULL,"
            " days INTEGER, fetched INTEGER, queued INTEGER, dropped INTEGER,"
            " new INTEGER, refreshed INTEGER, errors INTEGER, note TEXT)")
        con.execute(
            "INSERT INTO owner_queue_ingest_run (source, ran_at, days, fetched, queued, dropped,"
            " new, refreshed, errors, note) VALUES (?,?,?,?,?,?,?,?,?,?)",
            ("mail", now_iso(), a.days, len(msgs), len(rows), tally.get("drop", 0),
             stats["new"], stats["refreshed"], len(errors) + len(judge_errors),
             ("over cap: %d" % over_cap) if over_cap else ""))
        con.commit()
    except Exception as exc:  # noqa: BLE001
        print("  (run arithmetic not recorded: %s: %s)" % (type(exc).__name__, exc))
    print("mail ingest: read=%d judged=%d new=%d refreshed=%d left_closed=%d "
          "threads=%d dropped=%d closed_stale=%d"
          % (len(msgs), judged_n, stats["new"], stats["refreshed"],
             stats["left_closed"], len(rows), tally.get("drop", 0), len(closed)))
    for cid, why in closed[:20]:
        print("  CLOSED #%-5s %s" % (cid, why))
    if models:
        print("  judged by: %s" % ", ".join(sorted(models)))
    if over_cap:
        print("  NOTE %d message(s) past the per-run judge cap wait for the next run" % over_cap)
    if errors:
        print("  %d read/body error(s); first: %s" % (len(errors), errors[0]))
    if judge_errors:
        # A judge outage is an open item, not an event: non-zero, with the provider's own words.
        print("JUDGE FAILED: %s" % "; ".join(judge_errors))
        print("  nothing was invented; unjudged mail stays queued for the next run")
        return 4
    return 0


if __name__ == "__main__":
    sys.exit(main())
