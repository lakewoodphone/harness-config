#!/usr/bin/env python3
"""owner_topic.py — "we already told him this", enforced.

WHY THIS EXISTS
---------------
Measured on the authority, 2026-10-19. The owner's thread contained **four separate texts for
one payment**:

    2026-10-05 21:03  ⏰ Reminder: Pay Yisroel Weinberg $597.29 net CASH settlement (owner
                      decided after Sukkot). Sukkot ended Sun 2026-10-04. Record date+amount…
    2026-10-05 21:48  ⏰ Reminder: Pay Yisroel Weinberg $597.29 net CASH settlement (owner
                      decided: after Sukkot). Actionable from Mon 2026-10-05…
    2026-10-05 22:33  ⏰ Reminder: Pay Yisroel Weinberg $597.29 net CASH settlement (owner
                      decided: after Sukkot). Sukkot ends Sun 2026-10-04, so this is
                      actionable today…
    2026-10-08 10:01  ⏰ Reminder: OWNER ACTION: Pay Yisroel Weinberg $597.29 net CASH
                      settlement (owner decided 2026-09-30, due after Sukkot)…

Four wordings, one task. They all got through, and they were SUPPOSED to: every gate in this
estate judges a message by its BODY. `owner_text_relay.policy_hash` dedupes on the normalised
body, `owner_flood_guard.decide` backs off per body-hash, and `textsend.classify_owner_body`
reads one body at a time. Change the wording and every one of them says "first send, allowed".

The channel already RECORDS the thing that would have caught it. `attempt.topic` and
`ask.topic` are columns; producers pass `topic=`. Nothing ever read them back. This module is
the reader.

WHAT IT IS NOT
--------------
It is not a content filter. It never reads the body except to derive an identity, and it has no
opinion about whether the message is good — that is `textsend.classify_owner_body`. It answers
exactly one question: **have we already said this, recently, and is it still open?**

THE THREE ANSWERS
-----------------
    ok              nothing like this has gone out inside the window
    topic_cooldown  an identical topic went out `age` ago; the window has not elapsed
    topic_closed    the topic was answered or closed; say nothing until it reopens

`topic_cooldown` and `topic_closed` are DIFFERENT sentences on purpose (measurement rule): the
first means "later", the second means "not until something changes". Collapsing them is how
"we have not sent this yet" and "we sent it and it is finished" become the same reading.

DERIVING THE TOPIC — the part that took the thought
---------------------------------------------------
A caller may pass `topic=`. Most do not, and the ones that do pass inconsistent things: the
`reason=` values measured in the app on 2026-10-19 include `reminder:52`, `sync_breaker:Gmail`
and the whole English sentence `the 26 minutes; he is still resting`. A topic keyed on a
sentence can never match anything — that is precisely the defect that left the old
`owner_text_suppression` table holding one inert row forever.

So an explicit topic is used only if it LOOKS like a key (`family:identity`). Otherwise the
topic is derived from what the message is ABOUT, strongest signal first:

  1. money       `$597.29` / `597.29`          → `money:597.29`
     The CFO's whole corpus is money. Different wordings of one reminder keep the amount.
  2. a work order / case / ticket id            → `case:WO2602180002`
  3. a task / queue row                         → `task:26089`
  4. an explicit reminder id                    → `reminder:52`
  5. the first five significant words           → `say:<hash>` (weak, last resort)

A `say:` topic is deliberately weak: it collapses restatements of one sentence, which is what
the ten copies of "received your message. i am processing it." needed, and it will not pretend
to understand a paraphrase. Weak and honest beats a clever key that misses.

READ-ONLY UNTIL `record()` — `admit()` writes nothing. Callers that are refused must be able to
ask without the asking changing the answer.

STORE: `/root/.owner-text/relay.db`, table `owner_topic`. One ledger, not a fifth one; the same
file already holds `attempt` and `ask`, and a separate file would be a second truth about the
same conversation.
"""
from __future__ import annotations

import os
import re
import sqlite3
from datetime import datetime, timedelta, timezone

VERSION = 1

DEFAULT_DB = os.environ.get("OWNER_TOPIC_DB", "/root/.owner-text/relay.db")

#: How long a topic stays quiet after it has been sent, in minutes. Chosen from the corpus,
#: not from taste:
#:   reminder 20 h  — one nudge a day. The Weinberg case sent four in 61 h; the owner's words
#:                    on the class (2026-10-09, sms_log 4057): "the reminders fired from
#:                    separate scheduled jobs, each one blind to the others."
#:   ask      72 h  — an unanswered question is not re-asked for three days. His median answer
#:                    latency is 152.8 min (owner-text-audit, 30 d), so 72 h is generous.
#:   alert     1 h  — an alarm that is still true may ring again; one that just rang may not.
#:   status    6 h  — progress narration.
#:   default  12 h  — anything unnamed.
WINDOWS_MIN = {
    "reminder": 20 * 60,
    "ask": 72 * 60,
    "alert": 60,
    "status": 6 * 60,
    "default": 12 * 60,
}

#: subsystem / reason prefixes mapped to a family
_FAMILY_PREFIXES = (
    ("reminder", "reminder"),
    ("ask", "ask"),
    ("cfo", "ask"),
    ("clarify", "ask"),
    ("owner-ask", "ask"),
    ("card-due", "reminder"),
    ("alert", "alert"),
    ("security", "alert"),
    ("balance", "alert"),
    ("escalat", "alert"),
    ("status", "status"),
    ("attention", "status"),
    ("step_budget", "status"),
)

_KEY_RE = re.compile(r"^[a-z][a-z0-9_.\-]{0,40}:[^\s]{1,120}$")
_MONEY_RE = re.compile(r"(?:\$\s?|usd\s?)(\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?)", re.I)
_BARE_MONEY_RE = re.compile(r"\b(\d{1,3}(?:,\d{3})+\.\d{2}|\d+\.\d{2})\b")
# A case id must carry DIGITS. The first version required only "WO" plus four characters,
# and the live ledger immediately recorded the topic `case:WORKING` from an ordinary
# English word -- a false identity that would suppress unrelated messages about it.
# Measured 2026-10-19 15:12:40Z, one minute after deploy.
_CASE_RE = re.compile(
    r"\b(WO[-_ ]?\d{6,}|CASE[-_# ]{0,2}\d{3,}|PP-[A-Z]-[A-Z0-9-]{6,}|TICKET[-_ ]?\d{3,})",
    re.I)
_TASK_RE = re.compile(r"\b(?:task|queue|owner decision|decision)\s*#?\s*(\d{3,})\b", re.I)
_STOP = {
    "the", "a", "an", "and", "or", "but", "to", "of", "in", "on", "at", "for", "from", "with",
    "is", "was", "are", "be", "been", "it", "this", "that", "his", "her", "he", "she", "you",
    "we", "i", "me", "my", "your", "our", "reminder", "note", "update", "please", "now",
}


def _now(moment=None):
    return moment or datetime.now(timezone.utc)


def _iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")


def _parse(value):
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).strip().replace("Z", "+00:00")
    for fmt in (None,):
        try:
            dt = datetime.fromisoformat(text)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text[: len(fmt) + 2], fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def family_of(reason: str | None, subsystem: str | None = None) -> str:
    """Which cooldown family a message belongs to. Never raises."""
    for raw in (reason, subsystem):
        text = str(raw or "").strip().lower()
        if not text:
            continue
        for prefix, family in _FAMILY_PREFIXES:
            if text.startswith(prefix):
                return family
        # `ask-1791862240`, `cfo_ask`, `card due watch` all read as asks/reminders
        for prefix, family in _FAMILY_PREFIXES:
            if prefix in text:
                return family
    return "default"


def window_minutes(family: str) -> int:
    return int(WINDOWS_MIN.get(family, WINDOWS_MIN["default"]))


def derive_topic(body: str | None, reason: str | None = None) -> str:
    """A stable identity for what a message is ABOUT, or "" when nothing stable exists.

    Deterministic and cheap: no clock, no store, no model.
    """
    text = str(body or "")
    low = text.lower()

    # 1. money — the CFO's whole vocabulary, and the signal that survives rewording
    m = _MONEY_RE.search(text) or _BARE_MONEY_RE.search(text)
    if m:
        amount = m.group(1).replace(",", "")
        try:
            return "money:%.2f" % float(amount)
        except ValueError:
            pass

    # 2. a case / work order / dispute id
    m = _CASE_RE.search(text)
    if m:
        ident = re.sub(r"[\s_]+", "", m.group(1)).upper()
        # One case must have ONE key: "Case #4485", "case 4485" and "CASE#4485" are the same
        # matter, so the noun is stripped and only the identifier remains.
        for prefix in ("CASE", "TICKET"):
            if ident.startswith(prefix):
                ident = ident[len(prefix):].lstrip("-#")
        return "case:" + ident

    # 3. a task or queue row
    m = _TASK_RE.search(text)
    if m:
        return "task:" + m.group(1)

    # 4. an explicit reminder id carried in the reason
    m = re.search(r"reminder[:\-_ ]?(\d{2,})", str(reason or ""), re.I)
    if m:
        return "reminder:" + m.group(1)

    # 5. last resort: the first five significant words
    words = [w for w in re.findall(r"[a-z0-9']+", low) if w not in _STOP and len(w) > 2]
    if len(words) >= 3:
        return "say:" + "-".join(words[:5])
    return ""


def normalise_topic(body: str | None = None, reason: str | None = None,
                    topic: str | None = None) -> tuple[str, str]:
    """(topic, how) where `how` says which rule produced it — so a refusal can be argued with.

    Argument order matches `admit()`, `record()` and `note_refusal()` on purpose: the first
    version of this function took `(topic, body, reason)` while its siblings took
    `(body, reason, topic)`, and the test called it the sibling way -- which silently treated
    a message body as an explicit topic and turned all four Weinberg reminders into four
    different `say:` keys. Same-order-or-fail is cheaper than remembering.
    """
    raw = str(topic or "").strip().lower()
    if raw and _KEY_RE.match(raw):
        return raw, "given"
    derived = derive_topic(body, reason)
    if derived:
        return derived, "derived"
    if raw:
        # A caller passed a sentence. Keep it as a weak text key rather than trust it.
        slug = re.sub(r"[^a-z0-9]+", "-", raw).strip("-")[:80]
        if slug:
            return "say:" + slug, "given-sentence"
    return "", "none"


# --------------------------------------------------------------------------- #
# Still true? A reminder that names a deadline which has already passed
# --------------------------------------------------------------------------- #
# WHY. Measured in his thread 2026-10-19: "PayPal case PP-R-VHU-644541358: seller response
# deadline is Oct 7, 2026" was DELIVERED on 2026-10-08 -- a day after the deadline it names.
# A reminder fires because it is DUE, and nothing anywhere asked whether it is still TRUE.
# Topic identity (§above) cannot catch this: the amount has not been said before, so it is
# a first message about a fresh topic, and every body-shaped rule passes it.
#
# THE RULE IS DELIBERATELY NARROW. A date only counts when it follows a deadline word, so
# "you paid 2026-10-05, the refund is due 2026-10-20" is judged on the 20th and the earlier
# date is ignored. Only `reminder` and `alert` families are judged: a status line or a reply
# may legitimately talk about the past, and silencing one of those would lose information he
# is owed. Twelve hours of grace, because a reminder generated at 23:50 for "today" is not
# stale at 00:10.
_MONTH = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*"
_DATE = (
    r"(\d{4}-\d{2}-\d{2}"                      # 2026-10-07
    r"|" + _MONTH + r"\.?\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4}"   # Oct 7, 2026
    r"|\d{1,2}(?:st|nd|rd|th)?\s+" + _MONTH + r"\.?,?\s+\d{4}"   # 7 Oct 2026
    r"|\d{1,2}/\d{1,2}/\d{2,4})"                                # 10/07/2026
)
# The real body that motivated this names its deadline "Oct 7, 2026" -- a month NAME. The
# first version of this regex read only numeric dates and therefore allowed the very
# message it was written for. Found by running it against the corpus body, not a fixture.
_DEADLINE_RE = re.compile(
    r"(?:due|deadline|due by|due on|payment is due|expires?|expiring|must be (?:filed|paid|sent|"
    r"returned)|before)[^.\n]{0,50}?" + _DATE,
    re.I)

STALE_FAMILIES = ("reminder", "alert")


def _parse_date(raw: str):
    """A date from ISO or M/D/YYYY. None when it cannot be read with confidence."""
    text = re.sub(r"(?<=\d)(st|nd|rd|th)\b", "", str(raw or "").strip())
    text = text.replace(",", " ")
    text = re.sub(r"\s+", " ", text)
    try:
        return datetime.fromisoformat(text[:10]).date()
    except ValueError:
        pass
    for fmt in ("%b %d %Y", "%B %d %Y", "%d %b %Y", "%d %B %Y", "%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def stale_reference(body: str | None, *, subsystem: str | None = None,
                    reason: str | None = None, now=None, grace_hours: float = 12.0) -> dict | None:
    """None when the message may go, or a refusal dict when it names a deadline gone by."""
    fam = family_of(reason, subsystem)
    if fam not in STALE_FAMILIES:
        return None
    text = str(body or "")
    m = _DEADLINE_RE.search(text)
    if not m:
        return None
    when = _parse_date(m.group(1))
    if when is None:
        return None
    moment = _now(now)
    deadline_end = datetime.combine(when, datetime.max.time(), tzinfo=timezone.utc)
    overdue_hours = (moment - deadline_end).total_seconds() / 3600.0
    if overdue_hours <= grace_hours:
        return None
    return {
        "code": "stale_reference",
        "date": when.isoformat(),
        "overdue_hours": round(overdue_hours, 1),
        "detail": ("the deadline it names (%s) passed %.0f hour(s) ago - re-measure before "
                   "reminding him; %r" % (when.isoformat(), overdue_hours, text[:70])),
    }


# --------------------------------------------------------------------------- #
# The store
# --------------------------------------------------------------------------- #
SCHEMA = """
CREATE TABLE IF NOT EXISTS owner_topic (
    topic        TEXT NOT NULL,
    family       TEXT NOT NULL DEFAULT 'default',
    first_at     TEXT NOT NULL,
    last_at      TEXT NOT NULL,
    sends        INTEGER NOT NULL DEFAULT 0,
    refused      INTEGER NOT NULL DEFAULT 0,
    state        TEXT NOT NULL DEFAULT 'open',   -- open | answered | closed
    state_at     TEXT,
    last_body    TEXT NOT NULL DEFAULT '',
    last_reason  TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (topic, family)
);
CREATE INDEX IF NOT EXISTS owner_topic_last ON owner_topic(last_at);
CREATE INDEX IF NOT EXISTS owner_topic_topic ON owner_topic(topic);
"""


def connect(path=None, *, create: bool = True) -> sqlite3.Connection:
    target = str(path or DEFAULT_DB)
    if create:
        parent = os.path.dirname(target)
        if parent:
            os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(target, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    return conn


def _ro(path=None):
    target = str(path or DEFAULT_DB)
    if not os.path.exists(target):
        return None
    try:
        conn = sqlite3.connect("file:%s?mode=ro" % target, uri=True, timeout=2.0)
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.Error:
        return None


def row_for(topic: str, family: str = "default", conn=None) -> dict | None:
    own = conn is None
    c = conn or _ro()
    if c is None:
        return None
    try:
        row = c.execute(
            "SELECT * FROM owner_topic WHERE topic=? AND family=?",
            (str(topic), str(family)),
        ).fetchone()
        return dict(row) if row else None
    except sqlite3.Error:
        return None
    finally:
        if own:
            c.close()


def admit(body: str | None, *, reason: str | None = None, subsystem: str | None = None,
          topic: str | None = None, now=None, conn=None, window_min=None) -> dict:
    """May this message go out, given what we have already said about this topic?

    Read-only. Returns a dict, always, including on every failure — a brake that raises is a
    brake that does nothing.
    """
    moment = _now(now)
    fam = family_of(reason, subsystem)
    key, how = normalise_topic(body, reason, topic)
    out = {
        "allow": True,
        "code": "ok",
        "topic": key,
        "topic_source": how,
        "family": fam,
        "window_minutes": int(window_min or window_minutes(fam)),
        "age_minutes": None,
        "sends": 0,
        "detail": "",
    }
    if not key:
        out["code"] = "no_topic"
        out["detail"] = "no stable identity could be derived; nothing to cooldown on"
        return out

    row = row_for(key, fam, conn)
    if not row:
        out["detail"] = "first message about %s" % key
        return out

    out["sends"] = int(row.get("sends") or 0)
    state = str(row.get("state") or "open")
    if state in ("answered", "closed"):
        out["allow"] = False
        out["code"] = "topic_closed"
        out["detail"] = (
            "%s is %s since %s — nothing may be said about it until it reopens"
            % (key, state, row.get("state_at") or row.get("last_at")))
        return out

    last = _parse(row.get("last_at"))
    if last is not None:
        age = (moment - last).total_seconds() / 60.0
        out["age_minutes"] = round(age, 1)
        if age < out["window_minutes"]:
            out["allow"] = False
            out["code"] = "topic_cooldown"
            out["detail"] = (
                "%s went out %.0f min ago (#%d for this topic) and the %s window is %d min"
                % (key, age, out["sends"], fam, out["window_minutes"]))
            return out
        out["detail"] = ("%s last went out %.0f min ago; the %s window (%d min) has elapsed"
                         % (key, age, fam, out["window_minutes"]))
        return out

    out["detail"] = "%s has no readable last_at; allowed" % key
    return out


def record(body: str | None, *, reason: str | None = None, subsystem: str | None = None,
           topic: str | None = None, now=None, conn=None, sent: bool = True) -> dict:
    """Write the admission. Call this ONLY after the decision to send, never before."""
    moment = _now(now)
    fam = family_of(reason, subsystem)
    key, how = normalise_topic(body, reason, topic)
    if not key:
        return {"ok": False, "code": "no_topic", "topic": ""}
    own = conn is None
    c = conn or connect()
    try:
        head = re.sub(r"\s+", " ", str(body or ""))[:200]
        with c:
            c.execute(
                """INSERT INTO owner_topic
                       (topic, family, first_at, last_at, sends, refused, state, last_body, last_reason)
                   VALUES (?,?,?,?,?,0,'open',?,?)
                   ON CONFLICT(topic, family) DO UPDATE SET
                       last_at=excluded.last_at,
                       sends=sends + ?,
                       last_body=excluded.last_body,
                       last_reason=excluded.last_reason,
                       family=excluded.family""",
                (key, fam, _iso(moment), _iso(moment), 1 if sent else 0, head,
                 str(reason or ""), 1 if sent else 0),
            )
        return {"ok": True, "code": "recorded", "topic": key, "topic_source": how}
    except sqlite3.Error as exc:
        return {"ok": False, "code": "store_error", "topic": key, "error": str(exc)}
    finally:
        if own:
            c.close()


def note_refusal(body: str | None, *, reason=None, subsystem=None, topic=None, now=None,
                 conn=None) -> dict:
    """Count a refusal against the topic without moving `last_at`.

    A refusal must not refresh the window — otherwise a producer that retries every five
    minutes would push the next legitimate send out forever, which is a brake that brakes
    the wrong thing.
    """
    fam = family_of(reason, subsystem)
    key, _how = normalise_topic(body, reason, topic)
    if not key:
        return {"ok": False, "code": "no_topic"}
    own = conn is None
    c = conn or connect()
    try:
        with c:
            c.execute(
                """INSERT INTO owner_topic (topic, family, first_at, last_at, sends, refused,
                                            state, last_body, last_reason)
                   VALUES (?,?,?,?,0,1,'open',?,?)
                   ON CONFLICT(topic, family) DO UPDATE SET
                       refused = refused + 1,
                       last_reason = excluded.last_reason""",
                (key, fam, _iso(_now(now)), _iso(_now(now)),
                 re.sub(r"\s+", " ", str(body or ""))[:200], str(reason or "")),
            )
        return {"ok": True, "code": "refusal_noted", "topic": key}
    except sqlite3.Error as exc:
        return {"ok": False, "code": "store_error", "error": str(exc)}
    finally:
        if own:
            c.close()


def close_topic(topic: str, state: str = "closed", *, now=None, conn=None) -> dict:
    """Mark a topic answered or closed. Nothing about it may be sent until it reopens."""
    if state not in ("answered", "closed", "open"):
        return {"ok": False, "code": "bad_state"}
    key = str(topic or "").strip().lower()
    if not key:
        return {"ok": False, "code": "no_topic"}
    own = conn is None
    c = conn or connect()
    try:
        with c:
            c.execute(
                "INSERT INTO owner_topic (topic, family, first_at, last_at, sends, state, state_at)"
                " VALUES (?,?,?,?,0,?,?)"
                " ON CONFLICT(topic, family) DO UPDATE SET state=excluded.state,"
                " state_at=excluded.state_at",
                (key, family_of(key), _iso(_now(now)), _iso(_now(now)), state, _iso(_now(now))),
            )
        # A topic is settled as a THING, not in one family: closing a payment must silence
        # the reminder AND the status line about the same payment.
        with c:
            c.execute("UPDATE owner_topic SET state=?, state_at=? WHERE topic=?",
                      (state, _iso(_now(now)), key))
        return {"ok": True, "code": "state_set", "topic": key, "state": state}
    except sqlite3.Error as exc:
        return {"ok": False, "code": "store_error", "error": str(exc)}
    finally:
        if own:
            c.close()


def report(limit: int = 20, conn=None) -> dict:
    """What the ledger knows: open topics, the noisiest, and what has been refused."""
    own = conn is None
    c = conn or _ro()
    if c is None:
        return {"ok": False, "reason": "store missing"}
    try:
        rows = c.execute(
            "SELECT topic, family, sends, refused, state, last_at FROM owner_topic"
            " ORDER BY sends DESC, last_at DESC LIMIT ?", (int(limit),)
        ).fetchall()
        total = c.execute("SELECT COUNT(*) FROM owner_topic").fetchone()[0]
        return {"ok": True, "topics": total, "rows": [dict(r) for r in rows]}
    except sqlite3.Error as exc:
        return {"ok": False, "reason": str(exc)}
    finally:
        if own:
            c.close()


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _main(argv=None) -> int:
    import argparse
    import json

    p = argparse.ArgumentParser(description="topic identity for owner-bound messages")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("admit", help="would this go out? (read-only)")
    a.add_argument("--body", required=True)
    a.add_argument("--reason", default="")
    a.add_argument("--subsystem", default="")
    a.add_argument("--topic", default="")
    a.add_argument("--now", default="")
    a.add_argument("--db", default="")
    a.add_argument("--json", action="store_true")

    r = sub.add_parser("record", help="write an admission (after deciding to send)")
    r.add_argument("--body", required=True)
    r.add_argument("--reason", default="")
    r.add_argument("--subsystem", default="")
    r.add_argument("--topic", default="")
    r.add_argument("--db", default="")

    cl = sub.add_parser("close", help="mark a topic answered or closed")
    cl.add_argument("--topic", required=True)
    cl.add_argument("--state", default="closed", choices=("answered", "closed", "open"))
    cl.add_argument("--db", default="")

    rp = sub.add_parser("report", help="what the ledger knows")
    rp.add_argument("--limit", type=int, default=20)
    rp.add_argument("--db", default="")

    args = p.parse_args(argv)
    db = getattr(args, "db", "") or None

    if args.cmd == "admit":
        res = admit(args.body, reason=args.reason, subsystem=args.subsystem,
                    topic=args.topic, now=_parse(args.now) if args.now else None,
                    conn=connect(db))
    elif args.cmd == "record":
        res = record(args.body, reason=args.reason, subsystem=args.subsystem,
                     topic=args.topic, conn=connect(db))
    elif args.cmd == "close":
        res = close_topic(args.topic, args.state, conn=connect(db))
    else:
        res = report(args.limit, conn=_ro(db))

    print(json.dumps(res, indent=2, default=str))
    if args.cmd == "admit":
        return 0 if res.get("allow") else 1
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(_main())
