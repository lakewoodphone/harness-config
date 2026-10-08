#!/usr/bin/env python3
"""`textctx` - "who is this, and what is going on?"

One module that answers that question for a phone number by reading every source
that already knows something, and by writing down where each answer came from.

WHY IT EXISTS
-------------
Two measured findings (docs/ai-text-line-audit-2026-09-20.md):

* **B8 - identity had exactly one source.** Only `permissions.phone` was consulted.
  `contacts` (630 rows), `dialpad_sms_cache` (132k rows) and `dialpad_call_full`
  (12.8k rows) all knew who these people are and none of them was asked, so three
  AI-line numbers stayed `?`.
* **B7 - the decision saw no business context.** The reply was chosen with the
  thread, a name and the ledger - never the owner's availability, the owner queue,
  or whether this person is one of the shop's customers. `GET /owner/state` and
  `GET /owner/profile` answer over HTTP on the authority and cost nothing to read.

Three rules hold the module together:

1. **`resolve()` never raises.** A dead source is a line in `sources` and a line in
   `warnings`; it is never the loss of the other seven sources. `permissions` is
   queried FIRST for exactly that reason - it is authoritative for `allow`, and it
   must not be lost because a later source blew up.
2. **Provenance is mandatory** (`journal P12`). Every reading carries the source it
   came from and when it was read. There is no code path here that puts a fact in
   the returned dict without a `sources` entry that says where it came from.
3. **Pure reader.** No INSERT, UPDATE or DELETE exists in this file. The app DB is
   opened `mode=ro`; the store is opened read-only in spirit and only ever SELECTed.

The one deliberate subtlety: **`comms` is not identity.** `dialpad_*` is the shop's
customer line. This is the owner's PERSONAL line (audit, "What the system is").
A customer who has the personal number is an exception worth a `warnings` line, not
a person to greet by their Dialpad customer name - so `comms` contributes counts and
at most a low-confidence *alias*, never the name we call them by.

CLI
    python3 textctx.py who +18482102477      # the resolved dict, as JSON
    python3 textctx.py render +18482102477   # just the prompt block
    python3 textctx.py owner                 # owner_state + owner_profile
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# `textstore` owns the store's schema and its connection settings; this module only
# reads through it, so the two can never disagree about which file the store is.
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import textstore  # type: ignore
except Exception:  # pragma: no cover - deployment without the sibling module
    textstore = None

# `sources` in the tuple is not a source - it is where the provenance ends up. The
# contract in docs/ai-text-line-contracts.md froze this tuple verbatim and other
# agents may key off it, so it is reproduced unchanged rather than corrected.
DATA_SOURCES = ("contacts", "permissions", "person", "sources", "memory", "owner_state", "queue")

DEFAULT_API_BASE = "http://127.0.0.1:8002"
DEFAULT_APP_DB = "/home/zabz/personal-secretary-mvp/data/secretary.db"
IDENTITY_SOURCES = ("permissions", "person", "contact", "memory", "comms", "guess")
RELATIONSHIPS = ("owner", "family", "friend", "customer", "vendor", "machine", "unknown")

# How much of one message body is worth putting in a prompt. A body is data, and a
# 1,500-character one would spend the whole budget on a single turn.
BODY_CAP = 300
THREAD_TURNS = 8


def now() -> str:
    """The timestamp shape every entry in `sources` carries."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def digits(value) -> str:
    return re.sub(r"\D", "", str(value or ""))


def norm(phone) -> str:
    """Last 10 digits: `+1 845 555-0100` and `8455550100` are the same person.

    The same normalisation the sensor uses (`sms-inbox.py:norm`), deliberately - if
    the two ever disagreed, `permissions` would match a phone that `messages` did not.
    """
    d = digits(phone)
    return d[-10:] if len(d) >= 10 else d


def e164(phone) -> str:
    """"Best effort" E.164, exactly as the contract words it: a bare 10-digit US
    number gets `+1`, anything already prefixed with `+` is left alone."""
    raw = str(phone or "").strip()
    if raw.startswith("+"):
        return "+" + digits(raw)
    d = digits(raw)
    if len(d) == 10:
        return "+1" + d
    if len(d) == 11 and d.startswith("1"):
        return "+" + d
    return "+" + d if d else ""


def e164_ok(phone) -> bool:
    """True only for a number that is recognisably a complete US number."""
    d = digits(phone)
    return len(d) == 10 or (len(d) == 11 and d.startswith("1"))


def parse_ts(value):
    """A datetime from any of the shapes the three databases actually store.

    Twilio hands back RFC 2822 (`Fri, 18 Sep 2026 03:29:39 +0000`), the store holds
    ISO, and Dialpad stores epoch milliseconds. An unparseable value returns None
    rather than a guess - a wrong timestamp is worse than no timestamp.
    """
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        try:
            n = float(value)
            return datetime.fromtimestamp(n / 1000.0 if n > 1e11 else n, timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    text = str(value).strip()
    try:
        n = float(text)
        return datetime.fromtimestamp(n / 1000.0 if n > 1e11 else n, timezone.utc)
    except ValueError:
        pass
    iso = text.replace("Z", "+00:00")
    # A trailing offset without a colon (`+0000`) is valid RFC 2822 and invalid ISO.
    iso = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", iso)
    for candidate in (iso, iso.replace(" ", "T", 1)):
        try:
            dt = datetime.fromisoformat(candidate)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S",
                "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(text, fmt)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _epoch(value):
    dt = parse_ts(value)
    return dt.timestamp() if dt else None


def _api_base() -> str:
    return (os.environ.get("SECRETARY_API_BASE") or DEFAULT_API_BASE).rstrip("/")


def _app_db_path(path=None) -> Path:
    return Path(path or os.environ.get("SECRETARY_DB") or DEFAULT_APP_DB)


def _open_ro(path, timeout=20) -> sqlite3.Connection:
    """Open a database read-only. Never creates, never migrates, never writes.

    `uri=True` with `mode=ro` is the enforcement, not a promise: a stray UPDATE in
    this module would raise `attempt to write a readonly database` rather than
    damage the shop's data.
    """
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"no such file: {p}")
    conn = sqlite3.connect(f"file:{p}?mode=ro&immutable=0", uri=True, timeout=timeout)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute(f"PRAGMA busy_timeout={int(max(1, timeout) * 1000)}")
    except sqlite3.Error:
        pass
    return conn


def _q(conn, sql, params=()):
    """Run one SELECT and hand back the cursor. Raises on a real SQL error so the
    caller can record *which* source failed and why - swallowing it here is how a
    source silently reports `ok: True` with zero rows."""
    assert sql.lstrip()[:6].upper() == "SELECT", "textctx is a reader: SELECT only"
    return conn.execute(sql, params)


def _clean_name(value) -> str | None:
    """`Weinberg soldering guy` is a note about a customer, not what we call him."""
    text = str(value or "").strip()
    if not text:
        return None
    for sep in (" | ", "|", " - ", " (", " (", ","):
        if sep in text:
            head = text.split(sep, 1)[0].strip()
            if head:
                return head
    return re.sub(r"\s+", " ", text)[:80]


def _same_digits(a, b) -> bool:
    a, b = digits(a), digits(b)
    return bool(a) and bool(b) and a[-10:] == b[-10:]


# --------------------------------------------------------------------------- #
# The sources. Each one returns `(data, provenance_entry, warnings)` and none of
# them is allowed to raise past its own boundary.
# --------------------------------------------------------------------------- #
def _src_permissions(conn, key: str) -> tuple[dict, dict, list]:
    """The ledger. Authoritative for `allow` and, when present, for the name.

    Queried first, on purpose: everything else is enrichment, this is the answer to
    "may the system speak to them at all".
    """
    at = now()
    try:
        rows = _q(conn, "SELECT * FROM permissions").fetchall()
    except sqlite3.Error as exc:
        return {}, {"ok": False, "at": at, "error": f"{type(exc).__name__}: {exc}"}, \
            [f"permissions unreadable: {exc}"]
    for row in rows:
        if norm(row["phone"]) == key:
            return dict(row), {"ok": True, "at": at, "rows": len(rows)}, []
    return {}, {"ok": True, "at": at, "rows": len(rows), "matched": False}, []


def _src_person(conn, key: str) -> tuple[dict, dict, list]:
    """The store's own learned identity (`textstore.person`).

    A missing table is `ok: False`, not a crash - on 2026-09-20 the live store had
    no `person` table yet, and `textstore.ensure_schema` creates it. Reporting that
    as a *source that answered* would be a lie of exactly the kind P12 is about.
    """
    at = now()
    if textstore is not None:
        try:
            got = textstore.get_person(conn, key)
        except Exception as exc:
            return {}, {"ok": False, "at": at, "error": f"{type(exc).__name__}: {exc}"}, \
                [f"person lookup failed: {exc}"]
        if got is None:
            # get_person swallows sqlite errors and returns None, so ask the schema
            # directly whether the table is there - "no row" and "no table" are
            # different facts and only one of them is a fault.
            try:
                exists = _q(conn, "SELECT name FROM sqlite_master WHERE type='table' AND name='person'")
            except sqlite3.Error as exc:
                return {}, {"ok": False, "at": at, "error": f"{type(exc).__name__}: {exc}"}, \
                    [f"person lookup failed: {exc}"]
            if not exists:
                return {}, {"ok": False, "at": at, "error": "no person table in store"}, []
            return {}, {"ok": True, "at": at, "matched": False}, []
        return dict(got), {"ok": True, "at": at, "matched": True}, []
    try:
        row = _q(
            conn,
            "SELECT * FROM person WHERE substr(replace(replace(phone,'+',''),'-',''),-10)=?",
            (key,)).fetchone()
    except sqlite3.Error as exc:
        msg = f"no person table in store" if "no such table" in str(exc).lower() else f"person: {exc}"
        return {}, {"ok": False, "at": at, "error": msg}, ([] if "no such table" in str(exc).lower() else [f"person lookup failed: {exc}"])
    if row is None:
        return {}, {"ok": True, "at": at, "matched": False}, []
    return dict(row), {"ok": True, "at": at, "matched": True}, []


def _src_contacts(app, timeout: int, key: str) -> tuple[dict, dict, list]:
    """`contacts` in the app DB, matched on the last 10 digits.

    The app stores both `+1845…` and `845…` shapes, so the WHERE clause normalises
    instead of assuming one: `addressbook_comparison` says ~630 rows live here and
    a bare `phone = ?` lookup silently misses half of them.
    """
    at = now()
    if app is None:
        return {}, {"ok": False, "at": at, "error": "app DB has no contacts table"}, []
    try:
        row = _q(
            app,
            """SELECT id, name, phone, relationship, company, tags_json, notes, last_interaction
               FROM contacts
               WHERE substr(replace(replace(phone,'+',''),'-',''),-10)=?
                  OR substr(replace(replace(phone,'+',''),'-',''),-11)=?
               LIMIT 1""",
            (key, key)).fetchone()
    except sqlite3.Error as exc:
        msg = "app DB has no contacts table" if "no such table" in str(exc).lower() else f"contacts: {exc}"
        return {}, {"ok": False, "at": at, "error": msg}, []
    if row is None:
        return {}, {"ok": True, "at": at, "matched": False}, []
    return dict(row), {"ok": True, "at": at, "matched": True}, []


def _src_comms(app, timeout: int, key: str) -> tuple[dict, dict, list]:
    """How much this person deals with the *business*, and what Dialpad calls them.

    Kept OUT of identity on purpose (contract requirement, and the audit's own
    framing: the AI line is personal, Dialpad is the customer line). If they turn up
    here, that is a fact worth a warning - a customer holding the personal number is
    an exception - not a reason to greet them by their ticket name.
    """
    at = now()
    if app is None:
        return {}, {"ok": False, "at": at, "error": "app DB has no dialpad tables"}, []
    out: dict = {"sms": 0, "calls": 0, "sms_last": None, "calls_last": None,
                 "customer_name": None, "sms_names": [], "call_names": []}
    errors = []
    try:
        for r in _q(
                app,
                """SELECT customer_name, COUNT(*) n, MAX(created_at) last
                   FROM dialpad_sms_cache
                   WHERE substr(replace(replace(phone_normalized,'+',''),'-',''),-10)=?
                   GROUP BY customer_name""",
                (key,)):
            out["sms"] += int(r["n"] or 0)
            if r["last"] and (_epoch(r["last"]) or 0) > (_epoch(out["sms_last"]) or 0):
                out["sms_last"] = r["last"]
            name = _clean_name(r["customer_name"])
            if name and name not in out["sms_names"]:
                out["sms_names"].append(name)
    except sqlite3.Error as exc:
        errors.append("dialpad_sms_cache: %s" % exc)
    try:
        for r in _q(
                app,
                """SELECT contact_name, COUNT(*) n, MAX(event_timestamp_ms) last
                   FROM dialpad_call_full
                   WHERE substr(replace(replace(COALESCE(contact_phone, external_number, ''),'+',''),'-',''),-10)=?
                   GROUP BY contact_name""",
                (key,)):
            out["calls"] += int(r["n"] or 0)
            if r["last"] and (_epoch(r["last"]) or 0) > (_epoch(out["calls_last"]) or 0):
                out["calls_last"] = r["last"]
            name = _clean_name(r["contact_name"])
            if name and name not in out["call_names"]:
                out["call_names"].append(name)
    except sqlite3.Error as exc:
        errors.append("dialpad_call_full: %s" % exc)

    if not out["sms"] and not out["calls"] and errors:
        return {}, {"ok": False, "at": at, "error": "; ".join(errors)}, \
            ["comms lookup failed: %s" % "; ".join(errors)]
    out["customer_name"] = (out["sms_names"] or out["call_names"] or [None])[0]
    prov = {"ok": True, "at": at, "sms": out["sms"], "calls": out["calls"]}
    if errors:
        prov["error"] = "; ".join(errors)
    return out, prov, []


def _src_store_messages(conn, key: str) -> tuple[dict, dict, list]:
    """The correspondence itself: history counts, the thread, and whether we have
    ever exchanged a text with them (`known`).

    One query, normalised in Python for consistency with the store's own `norm`
    (`sqlite3` has no `regexp`), so the direction split, the last-seen timestamps
    and the thread can never disagree with each other.
    """
    at = now()
    try:
        rows = _q(
            conn,
            """SELECT sid, direction, from_number, to_number, body, date_sent, state
               FROM messages""").fetchall()
    except sqlite3.Error as exc:
        return {}, {"ok": False, "at": at, "error": f"messages: {exc}"}, \
            [f"messages unreadable: {exc}"]
    rows = [r for r in rows if norm(r["from_number"]) == key or norm(r["to_number"]) == key]
    mine = [r for r in rows if r["direction"] == "inbound" and norm(r["from_number"]) == key]
    # Chronological, and it has to be this explicit: `date_sent` mixes Twilio's RFC
    # 2822 with the app's ISO, so SQLite's ORDER BY on the text is not time order, and
    # the live store interleaves the two. Without this the "last 8 turns" slice was
    # whatever 8 rows SQLite happened to return last (measured on the real store,
    # 2026-09-20: Weinberg's thread came back oldest-last and three turns missing).
    rows.sort(key=lambda r: (_epoch(r["date_sent"]) or 0.0, str(r["sid"] or "")))
    mine.sort(key=lambda r: (_epoch(r["date_sent"]) or 0.0, str(r["sid"] or "")))
    data = {
        "inbound": len(mine),
        "outbound": sum(1 for r in rows if r["direction"] == "outbound"),
        "last_inbound": (mine[-1]["date_sent"] if mine else None),
        "last_outbound": next((r["date_sent"] for r in reversed(rows)
                               if r["direction"] == "outbound"), None),
        "first_seen": (mine[0]["date_sent"] if mine else None),
        "answered_share": (sum(1 for r in mine
                               if any(o["direction"] == "outbound"
                                      and (_epoch(o["date_sent"]) or 0.0) > (_epoch(r["date_sent"]) or 0.0)
                                      for o in rows)) / len(mine)) if mine else None,
        "thread": [
            {"who": "them" if r["direction"] == "inbound" else "us",
             "body": str(r["body"] or "")[:BODY_CAP],
             "at": r["date_sent"],
             "sid": r["sid"]}
            for r in rows[-THREAD_TURNS:]],
    }
    return data, {"ok": True, "at": at, "rows": len(rows)}, []


def _src_message_clock(conn) -> tuple[dict, dict, list]:
    """The newest `date_sent` anywhere in the store, and how far behind the wall clock
    it is.

    This is *freshness*, not the staleness of one person's thread. Measured on the
    live store 2026-09-20: the system texts the owner constantly, so the store's
    high-water mark is nearly always "a moment ago" - and a `days_since_contact`
    measured against it came back `0.0` for Weinberg (3 days unanswered), Shabsi
    (12 days) and Radzik Sruly (5 months) alike. A metric that reads the same for
    everyone answers nothing, so it is not used for that: it is reported instead, as
    the honest measure of whether the sensor is still running.
    """
    at = now()
    try:
        rows = _q(conn, "SELECT date_sent FROM messages").fetchall()
    except sqlite3.Error as exc:
        return {}, {"ok": False, "at": at, "error": f"clock: {exc}"}, []
    # NOT `MAX(date_sent)`. `date_sent` is TEXT holding two shapes, and Twilio's is
    # RFC 2822, so SQL's text max sorts by weekday NAME: measured on the live store
    # 2026-09-20, `MAX(date_sent)` returned `Wed, 29 Jul 2026` while the true newest
    # message was `Fri, 18 Sep 2026` - the store looked 53 days stale when it was 2.
    # The max has to be taken over parsed values.
    stamps = [(_epoch(r["date_sent"]), r["date_sent"]) for r in rows]
    stamps = [s for s in stamps if s[0] is not None]
    newest = max(stamps)[1] if stamps else None
    lag = None
    if stamps:
        lag = round((datetime.now(timezone.utc).timestamp() - max(stamps)[0]) / 86400.0, 2)
    return {"newest": newest, "lag_days": lag}, {"ok": True, "at": at}, []


def _src_queue(app, timeout: int, key: str) -> tuple[list, dict, list]:
    """Rows in the owner's decision queue that are ABOUT this person.

    `owner_decision_queue.question` is free text, so the match is on the 10-digit
    number appearing in the question (the live queue does exactly this: row #116 is
    "Customer Levi (732-575-4823) asked whether we repair old Sony Video 8…").
    Knowing a question about them is already open is what stops the assistant
    raising a duplicate for the same person.
    """
    at = now()
    if app is None:
        return [], {"ok": False, "at": at, "error": "app DB has no owner_decision_queue table"}, []
    try:
        rows = _q(
            app,
            """SELECT id, question, asked_at, severity, status
               FROM owner_decision_queue
               WHERE status='pending' AND question LIKE ?
               ORDER BY asked_at DESC""",
            (f"%{key}%",)).fetchall()
    except sqlite3.Error as exc:
        msg = ("app DB has no owner_decision_queue table"
               if "no such table" in str(exc).lower() else f"owner_decision_queue: {exc}")
        return [], {"ok": False, "at": at, "error": msg}, []
    return ([{"id": r["id"], "question": r["question"], "asked_at": r["asked_at"],
              "severity": r["severity"]} for r in rows],
            {"ok": True, "at": at, "matched": len(rows)}, [])


def _owner_get(path: str, timeout) -> tuple[dict, dict]:
    """GET one owner endpoint. Returns `(useful_part, provenance)`; never raises.

    Both are verified-live and both return `{"ok": true, ...}`; the useful part is
    unwrapped (as the contract says) but the wrapper is kept for `/owner/state`,
    where `value` is nested one level deeper.
    """
    at = now()
    url = f"{_api_base()}{path}"
    try:
        req = urllib.request.Request(url)
        req.add_header("Accept", "application/json")
        with urllib.request.urlopen(req, timeout=_http_timeout(timeout)) as resp:
            payload = json.loads(resp.read().decode("utf-8", "replace") or "{}")
    except Exception as exc:
        # One line, with the exception's own name: "unreachable" and "404" are
        # different diagnoses and the reader has to be able to tell them apart.
        return {}, {"ok": False, "at": at, "url": url,
                    "error": f"{type(exc).__name__}: {exc}"}
    if not isinstance(payload, dict):
        return {}, {"ok": False, "at": at, "url": url, "error": "non-object JSON"}
    if payload.get("ok") is False:
        return payload, {"ok": False, "at": at, "url": url,
                         "error": str(payload.get("error") or "ok=false")}
    if "value" in payload and isinstance(payload["value"], dict):
        part = dict(payload["value"])
        part["updated_at"] = payload.get("updated_at")
    elif "profile" in payload and isinstance(payload["profile"], dict):
        part = payload["profile"]
    else:
        part = {k: v for k, v in payload.items() if k != "ok"}
    return part, {"ok": True, "at": at, "url": url, "keys": len(part)}


def _http_timeout(timeout) -> float:
    """A single read must never be able to hang a 5-minute cron tick, so a caller's
    `timeout` is a ceiling, not a suggestion, and the default is seconds."""
    try:
        value = float(timeout)
    except (TypeError, ValueError):
        value = 15.0
    return max(1.0, min(value, 60.0))


def owner_state(timeout=15) -> dict:
    """The owner's own state: availability, calendar, presence. `{}` when unreachable."""
    return _owner_get("/owner/state", timeout)[0]


def owner_profile(timeout=15) -> dict:
    """What the system has learned about the owner, with confidence. `{}` when unreachable."""
    return _owner_get("/owner/profile", timeout)[0]


# --------------------------------------------------------------------------- #
# resolve()
# --------------------------------------------------------------------------- #
def _empty_result(phone: str) -> dict:
    """The shape the contract froze, with every field present and unknown.

    Used as the base so a total failure still returns a dict a caller can read
    fields off - `resolve()` "never raises" includes never returning half a dict.
    """
    return {
        "phone": e164(phone),
        "e164_ok": e164_ok(phone),
        "identity": {"name": None, "relationship": "unknown", "confidence": 0.0,
                     "source": "guess", "aliases": []},
        "allow": "queue",
        "known": False,
        "history": {"inbound": 0, "outbound": 0, "last_inbound": None,
                    "last_outbound": None, "days_since_contact": None,
                    "first_seen": None, "answered_share": None},
        "thread": [],
        "open_jobs": [],
        "open_owner_rows": [],
        "sources": {},
        "warnings": [],
        "as_of": now(),
        "store_freshness": {},
    }


def _identity(perm: dict, person: dict, contact: dict, comms: dict) -> dict:
    """Best available identity, in the contract's precedence order.

    `permissions` wins outright when it actually names someone: it is the ledger, a
    human put it there, and the contract says so. But a ledger row that only holds
    the literal string `unknown (+18482245096)` is a placeholder - the live ledger
    has one - and it must NOT win, or the person stays unidentified forever, which
    is finding B8 exactly. After that: `person` (learned) beats `contacts` (an
    import), which beats a comms alias, which beats a guess.
    """
    ident = {"name": None, "relationship": "unknown", "confidence": 0.0,
             "source": "guess", "aliases": []}
    notes = [str(perm.get("note") or "")] if perm else []

    raw_perm_name = (perm.get("name") or "").strip() or None
    # A name that is only a placeholder - `unknown (+1845…)`, `?`, `-`, a number -
    # is not a name.
    if raw_perm_name and (re.match(r"^[?\-\s]*$", raw_perm_name)
                          or re.match(r"^(unknown|unnamed|no name|n/?a)\b", raw_perm_name, re.I)
                          or not re.search(r"[A-Za-z]", raw_perm_name)):
        raw_perm_name = None
    perm_name = raw_perm_name
    perm_rel = (perm.get("relationship") or "").strip().lower() or None
    if perm_name or perm_rel:
        ident["name"] = perm_name
        ident["relationship"] = perm_rel if perm_rel in RELATIONSHIPS else (perm_rel or "unknown")
        ident["confidence"] = 0.95 if perm_name else 0.6
        ident["source"] = "permissions"

    if not ident["name"]:
        pname = (person.get("name") or "").strip() or None
        if pname:
            ident["name"] = pname
            ident["confidence"] = float(person.get("confidence") or 0.0) or 0.8
            ident["source"] = "person" if ident["source"] == "guess" else ident["source"]
    cname = (contact.get("name") or "").strip() or None
    if not ident["name"]:
        if cname:
            ident["name"] = cname
            ident["confidence"] = 0.6
            ident["source"] = "contact" if ident["source"] == "guess" else ident["source"]
    if ident["relationship"] in ("", "unknown") and person.get("relationship"):
        ident["relationship"] = str(person["relationship"]).strip().lower()
        if ident["source"] == "guess":
            ident["source"] = "person"
    if ident["relationship"] in ("", "unknown"):
        crel = str(contact.get("relationship") or "").strip().lower()
        tags = str(contact.get("tags_json") or "").lower()
        if crel in ("inner_circle", "family", "friend"):
            ident["relationship"] = "family" if crel == "family" else "friend"
        elif crel in ("trusted", "vendor", "customer", "machine"):
            ident["relationship"] = crel
        elif cname:
            # The contract's own rule: "a contacts hit is `customer` unless the note
            # says otherwise".
            ident["relationship"] = "customer"
        if ident["relationship"] not in ("", "unknown") and ident["source"] == "guess":
            ident["source"] = "contact"
        elif tags and "google-import" in tags and ident["name"] is None and ident["source"] == "guess":
            ident["source"] = "contact"

    # Aliases: every other name the sources used for this number. Kept as aliases so
    # a prompt can say "Weinberg (a.k.a. Weinberg soldering guy)" without either
    # losing the shop's own label or letting it become the name.
    aliases = []
    for candidate in (perm.get("name"), person.get("name"), contact.get("name"),
                      comms.get("customer_name")):
        clean = str(candidate or "").strip()
        if clean and clean != ident["name"] and clean not in aliases:
            aliases.append(clean[:80])
    ident["aliases"] = aliases
    if ident["name"] is None and ident["source"] == "guess" and (aliases or notes):
        ident["source"] = "comms" if comms.get("customer_name") else "guess"
    return ident


def resolve(db_path, phone, *, timeout=20) -> dict:
    """Everything we know about a phone number. NEVER raises; missing data is
    `None`/absent, and every reading carries the source that produced it.

    Order matters and is not an accident: `permissions` is read first and held in a
    local before any other source runs, so a broken app DB, a missing `person`
    table or a dead HTTP endpoint cannot cost the ledger's answer to "may we speak
    to them, and who are they".

    `db_path` may be a path or an open connection; a path is opened through
    `textstore.connect()` when that module is present, so the store is always
    reached the way the rest of the system reaches it.
    """
    out = _empty_result(phone)
    key = norm(phone)
    out["phone"] = e164(phone)
    warnings: list[str] = out["warnings"]
    sources: dict = out["sources"]
    at = now()

    if not key or len(key) < 10:
        out["e164_ok"] = False
        warnings.append(f"not a usable phone number: {phone!r}")
        sources["permissions"] = {"ok": False, "at": at, "error": "no 10-digit number to match"}
        out["as_of"] = now()
        return out

    # Every source result starts as an empty dict so a source that never ran is
    # simply absent, never an unbound name later.
    perm: dict = {}
    person: dict = {}
    contact: dict = {}
    comms: dict = {}
    msgs: dict = {}
    clock: dict = {}

    # -- the store ---------------------------------------------------------- #
    conn = None
    try:
        if hasattr(db_path, "execute"):
            conn = db_path
        else:
            conn = _connect_store(db_path, timeout)
    except Exception as exc:
        warnings.append(f"store unreadable: {type(exc).__name__}: {exc}")
        sources["permissions"] = {"ok": False, "at": at,
                                  "error": f"{type(exc).__name__}: {exc}"}

    if conn is not None:
        # `permissions` FIRST, and its result is read into `perm` before anything
        # else can fail: it is the ledger, and it must survive a later source dying.
        perm, prov, warns = _src_permissions(conn, key)
        sources["permissions"] = prov
        warnings.extend(warns)
        out["allow"] = str(perm.get("allow") or "queue").strip().lower() or "queue"
        if out["allow"] not in ("auto", "queue", "never"):
            warnings.append(f"unknown allow value {out['allow']!r}; treating as queue")
            out["allow"] = "queue"

        person, prov, warns = _src_person(conn, key)
        sources["person"] = prov
        warnings.extend(warns)

        msgs, prov, warns = _src_store_messages(conn, key)
        sources["messages"] = prov
        warnings.extend(warns)

        clock, prov, warns = _src_message_clock(conn)
        sources["clock"] = prov
        warnings.extend(warns)

        open_jobs, prov, warns = _src_open_jobs(conn, key)
        sources["jobs"] = prov
        warnings.extend(warns)
        out["open_jobs"] = open_jobs

        if conn is not db_path and not hasattr(db_path, "execute"):
            _close(conn)

    # -- the app DB, read-only ---------------------------------------------- #
    app = _safe_ro(_app_db_path(), timeout, warnings, sources, "app_db")
    try:
        contact, prov, warns = _src_contacts(app, timeout, key)
        sources["contacts"] = prov
        warnings.extend(warns)

        comms, prov, warns = _src_comms(app, timeout, key)
        sources["comms"] = prov
        warnings.extend(warns)

        rows, prov, warns = _src_queue(app, timeout, key)
        sources["queue"] = prov
        warnings.extend(warns)
        out["open_owner_rows"] = rows
    finally:
        _close(app)

    # -- the store's own counts become history ------------------------------ #
    hist = out["history"]
    hist["inbound"] = int(msgs.get("inbound") or 0)
    hist["outbound"] = int(msgs.get("outbound") or 0)
    hist["last_inbound"] = msgs.get("last_inbound")
    hist["last_outbound"] = msgs.get("last_outbound")
    hist["first_seen"] = msgs.get("first_seen")
    hist["answered_share"] = msgs.get("answered_share")
    out["known"] = bool(hist["inbound"] or hist["outbound"])
    out["thread"] = msgs.get("thread") or []
    out["days_since_contact"] = _days_since(msgs, clock)
    hist["days_since_contact"] = out["days_since_contact"]

    # -- identity ----------------------------------------------------------- #
    # A source that failed contributes nothing: identity is built only from
    # sources that actually answered, so a dead app DB cannot blank a ledger name.
    out["identity"] = _identity(perm if conn_ok(sources, "permissions") else {},
                                person if conn_ok(sources, "person") else {},
                                contact if conn_ok(sources, "contacts") else {},
                                comms if conn_ok(sources, "comms") else {})

    # -- the owner, over HTTP ----------------------------------------------- #
    state, s_prov = _owner_get("/owner/state", timeout)
    sources["owner_state"] = s_prov
    if not s_prov.get("ok"):
        warnings.append(f"owner_state unreachable: {s_prov.get('error')}")
    profile, p_prov = _owner_get("/owner/profile", timeout)
    sources["owner_profile"] = p_prov
    if not p_prov.get("ok"):
        warnings.append(f"owner_profile unreachable: {p_prov.get('error')}")
    out["owner_state"] = state
    out["owner_profile"] = profile

    # -- what the sources said about each other ----------------------------- #
    if out["identity"]["name"] is None:
        warnings.append("identity: no name from any source (permissions, person, contacts)")
    if comms.get("calls") or comms.get("sms"):
        warnings.append(
            "this number is on the business line too: %s dialpad texts / %s calls%s"
            % (comms.get("sms") or 0, comms.get("calls") or 0,
               f" (Dialpad calls them {comms['customer_name']!r})" if comms.get("customer_name") else ""))
    if not out["known"]:
        warnings.append("no correspondence in the store")
    # A store whose newest message is a day old means the sensor stopped, and every
    # silence in it is then unreadable - the text may have arrived and never been
    # reconciled (audit B1: 77 inbound texts Twilio kept and the app never saw).
    lag = clock.get("lag_days")
    if isinstance(lag, (int, float)) and lag >= 1.0:
        warnings.append("store is stale: newest message is %.1f days old" % lag)

    out["as_of"] = now()
    out["store_freshness"] = clock
    return out


def _close(conn) -> None:
    try:
        if conn is not None:
            conn.close()
    except Exception:
        pass


def _connect_store(db_path, timeout):
    """Reach the store the way the rest of the system reaches it - but never die
    because `textstore` is half-available.

    Measured 2026-09-20 on secratary: the module name `textstore` was importable from
    a stale file that had no `connect()`, and a `elif textstore is not None` guard
    accepted it and then raised `AttributeError: module 'textstore' has no attribute
    'connect'`. That killed `permissions`, `person`, `messages` and `jobs` in one
    go - the whole store, four sources, lost to a bad import. The right behaviour is
    the contract's: fall back to opening the file read-only and say in `sources`
    which path was used.
    """
    if textstore is not None and callable(getattr(textstore, "connect", None)):
        try:
            return textstore.connect(db_path)
        except Exception:
            # A textstore that exists but cannot open this path still leaves the file
            # readable directly; the strict read-only open is the safer second try.
            return _open_ro(db_path, timeout=timeout)
    return _open_ro(db_path, timeout=timeout)


def conn_ok(sources: dict, name: str) -> bool:
    return bool((sources.get(name) or {}).get("ok"))


def _safe_ro(path, timeout, warnings, sources, name):
    """Open the app DB once per resolve, recording the failure rather than raising.

    The path does not exist on this Windows laptop (`/home/zabz/...`), and the
    contract's requirement is explicit: report `ok: False` with the error and keep
    going - identity from `permissions` must still come back.
    """
    try:
        return _open_ro(path, timeout=timeout)
    except Exception as exc:
        warnings.append(f"{name}: app DB unreadable: {type(exc).__name__}: {exc}")
        return None


def _src_open_jobs(conn, key) -> tuple[list, dict, list]:
    """Open promises made to this person (`textstore.jobs`). The table is new and
    absent from the live store today; absent is `ok: False`, not a crash."""
    at = now()
    try:
        rows = _q(
            conn,
            """SELECT id, claim, state, created_at, due_at, attempts
               FROM jobs
               WHERE state IN ('open','running')
                 AND substr(replace(replace(phone,'+',''),'-',''),-10)=?
               ORDER BY created_at ASC""",
            (key,)).fetchall()
    except sqlite3.Error as exc:
        missing = "no such table" in str(exc).lower()
        return [], {"ok": False, "at": at,
                    "error": "no jobs table in store" if missing else f"jobs: {exc}"}, []
    return [{"id": r["id"], "claim": r["claim"], "state": r["state"],
             "created_at": r["created_at"], "due_at": r["due_at"],
             "attempts": r["attempts"]} for r in rows], {"ok": True, "at": at, "open": len(rows)}, []


def _days_since(msgs: dict, clock: dict):
    """Days since this person last said anything, against the wall clock.

    The anchor is `now()` on purpose and the earlier attempt to anchor it to the
    store's own newest message was wrong (see `_src_message_clock`): that made the
    figure ~0 for a person who texted three days ago, because the store's newest row
    is usually a system notification to the owner. Staleness has to be measured from
    the present or it does not measure staleness. `as_of` records when "now" was, so
    the number is auditable after the fact.
    """
    last = max([x for x in (_epoch(msgs.get("last_inbound")),
                            _epoch(msgs.get("last_outbound"))) if x is not None] or [None])
    if last is None:
        return None
    return round(max(0.0, (datetime.now(timezone.utc).timestamp() - last) / 86400.0), 2)


# --------------------------------------------------------------------------- #
# render()
# --------------------------------------------------------------------------- #
def _fmt_at(value) -> str:
    """One display shape for every timestamp, always UTC.

    The store mixes Twilio's RFC 2822 with the app's ISO, and on the live store
    (2026-09-20) one thread came back as `2026-09-18T04:02:51+00:00` and
    `Fri, 18 Sep 2026 03:29:39 +0000` inside the same eight lines. Two shapes for one
    fact reads as two kinds of fact. `_parse_ts` already resolves both, so both are
    printed the same way.
    """
    dt = parse_ts(value)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%MZ") if dt else (str(value)[:19] if value else "?")


def _avail(owner_state: dict) -> str | None:
    if not isinstance(owner_state, dict) or not owner_state:
        return None
    inf = owner_state.get("calendar_inference") or {}
    parts = []
    if inf.get("availability"):
        parts.append(str(inf["availability"]))
    if inf.get("until"):
        parts.append(f"until {_fmt_at(inf['until'])}")
    if inf.get("reason"):
        parts.append(str(inf["reason"])[:120])
    override = owner_state.get("manual_availability_override") or {}
    if override.get("label"):
        parts.append(f"override={override['label']}")
        if override.get("reason"):
            parts.append(str(override["reason"])[:120])
    return " · ".join(parts) if parts else None


def _blocks(person: dict) -> tuple[list[str], list[str]]:
    """`(essential, optional)`. Essential is identity + permission + what we know and
    what we do NOT know; optional is context that can be dropped under pressure."""
    ident = person.get("identity") or {}
    hist = person.get("history") or {}
    sources = person.get("sources") or {}
    state = person.get("owner_state") or {}
    profile = person.get("owner_profile") or {}

    name = ident.get("name") or "unknown"
    rel = ident.get("relationship") or "unknown"
    conf = ident.get("confidence")
    conf_s = f"{float(conf):.2f}" if isinstance(conf, (int, float)) else "?"
    line1 = (f"WHO {person.get('phone') or '?'} | {name} | relationship={rel} | "
             f"confidence={conf_s} | identity_source={ident.get('source') or 'guess'}")
    if ident.get("aliases"):
        line1 += " | a.k.a. " + "; ".join(str(a) for a in ident["aliases"][:3])

    known_s = (f"HISTORY {hist.get('inbound', 0)} in / {hist.get('outbound', 0)} out"
               f" | last them {_fmt_at(hist.get('last_inbound'))}"
               f" | last us {_fmt_at(hist.get('last_outbound'))}"
               f" | idle_days {hist.get('days_since_contact')}")
    share = hist.get("answered_share")
    known_s += f" | answered {share:.2f}" if isinstance(share, (int, float)) else " | answered unknown"

    # The explicit "what is NOT known" lines. An omitted field reads as "nothing to
    # know", which is how a decision gets made on an assumption nobody tested.
    unknown = []
    if ident.get("name") is None:
        unknown.append("name")
    if not person.get("known"):
        unknown.append("no text history")
    for field_name, label in (("permissions", "permissions"), ("person", "person table"),
                              ("contacts", "contacts"), ("comms", "business-line comms"),
                              ("messages", "store messages"), ("queue", "owner queue")):
        src = sources.get(field_name) or {}
        if not src.get("ok"):
            unknown.append(f"{label}: {src.get('error') or 'unavailable'}")
    for field_name in ("owner_state", "owner_profile"):
        src = sources.get(field_name) or {}
        if not src.get("ok"):
            unknown.append(f"{field_name}: {src.get('error') or 'unreachable'}")
    if not _avail(state):
        unknown.append("owner availability")
    if not profile:
        unknown.append("owner profile")
    if not person.get("open_jobs"):
        unknown.append("no open job for them")
    if not person.get("open_owner_rows"):
        unknown.append("no open owner question about them")
    unknown_s = "NOT KNOWN: " + "; ".join(unknown) if unknown else "NOT KNOWN: nothing - every source answered"

    essential = [line1,
                 f"PERMISSION allow={person.get('allow') or 'queue'}",
                 known_s,
                 unknown_s]

    optional = []
    allow_row = (sources.get("permissions") or {})
    if allow_row.get("ok"):
        optional.append(f"LEDGER allow={person.get('allow')} read from permissions at {allow_row.get('at')}")
    if person.get("warnings"):
        optional.append("WARN " + " | ".join(str(w)[:160] for w in person["warnings"][:4]))
    avail = _avail(state)
    if avail:
        optional.append(f"OWNER AVAILABILITY {avail}")
    if profile:
        caps = []
        for key in sorted(profile)[:5]:
            entry = profile[key]
            value = entry.get("value") if isinstance(entry, dict) else entry
            caps.append(f"{key}={str(value)[:90]}")
        optional.append("OWNER PROFILE " + " | ".join(caps))
    jobs = person.get("open_jobs") or []
    if jobs:
        optional.append("OPEN JOBS " + " | ".join(
            f"#{j.get('id')} {j.get('state')} {str(j.get('claim'))[:80]}" for j in jobs[:3]))
    rows = person.get("open_owner_rows") or []
    if rows:
        optional.append("OPEN OWNER ROWS " + " | ".join(
            f"#{r.get('id')} {str(r.get('question'))[:120]}" for r in rows[:3]))
    return essential, optional


def render(person: dict, *, budget: int = 1200) -> str:
    """One dense block of prompt text from `resolve()`'s dict, under `budget` BYTES.

    Order is fixed and intentional: who they are, whether we may answer them, what
    has passed between us, the recent turns, then what is open and how available the
    owner is. Truncation happens from the OLDEST end - the oldest turns go first -
    and whole lines are dropped rather than cut in half, because half a line reads
    as a fact. The `NOT KNOWN:` line is essential and survives to the end; it is the
    contract's guard against an omission reading as "there is nothing to know".
    """
    if not isinstance(person, dict):
        return "NOT KNOWN: context unavailable (render got no dict)"
    try:
        limit = int(budget)
    except (TypeError, ValueError):
        limit = 1200
    # A byte budget is a ceiling, so an absurdly small one is honoured as such and
    # never overrun. Below ~120 bytes there is not even room for the identity line,
    # and an empty context is silently worse than a labelled stub, so the floor is a
    # stub that names the person and the permission and says the rest was not shown.
    limit = max(1, limit)

    essential, optional = _blocks(person)

    def size(lines) -> int:
        return len(("\n".join(lines)).encode("utf-8"))

    thread = person.get("thread") or []
    if thread:
        header = "THREAD (oldest first):"
        turns = [f"  {_fmt_at((t or {}).get('at'))} "
                 f"{'them' if (t or {}).get('who') == 'them' else 'us'}: "
                 f"{str((t or {}).get('body') or '').replace(chr(10), ' ').strip()[:BODY_CAP]}"
                 for t in thread[-THREAD_TURNS:]]
    else:
        header = "THREAD: none - we have never exchanged a text with this number"
        turns = []
        # With no thread at all, the line that SAYS so is essential: an omitted thread
        # reads as "nothing to know", which is the one mistake this module exists to
        # prevent. When there are turns, the header belongs to them and is added by
        # `assemble` only if they survive the budget.
        essential.append(header)

    if size(essential) > limit:
        # A budget smaller than the identity line itself. Emit a labelled stub - the
        # person, whether we may answer them, and the fact that the rest is missing -
        # rather than an empty string, which reads as "nothing to know".
        body = [f"CONTEXT OMITTED (budget {limit}B)",
                f"{person.get('phone') or '?'} allow={person.get('allow') or 'queue'}"]
        text = "\n".join(body)
        while len(text.encode("utf-8")) > limit and body:
            body.pop()
            text = "\n".join(body)
        return text

    def assemble(keep_optional, keep_turns, note=None) -> tuple[str, bool]:
        lines = list(essential) + list(keep_optional)
        if keep_turns and header is not None:
            lines.append(header)
            lines += list(keep_turns)
        if note:
            lines.append(note)
        return "\n".join(lines), size(lines) <= limit

    # 1. everything, if it fits.
    text, fits = assemble(optional, turns)
    if fits:
        return text

    # 2. drop context blocks (newest-useful-last order is already the build order),
    #    then thread turns from the OLDEST end, never below the recent few.
    kept_optional = list(optional)
    dropped_optional = 0
    while kept_optional and size(essential + kept_optional + ([header] + turns if turns else [])) > limit:
        kept_optional.pop()
        dropped_optional += 1

    kept_turns = list(turns)
    dropped_turns = 0
    while kept_turns and not assemble(kept_optional, kept_turns)[1]:
        # Oldest first, and all the way to none - a budget that cannot hold the
        # thread is a budget that gets no thread, not a thread cut in half.
        kept_turns.pop(0)
        dropped_turns += 1

    # The truncation marker is disclosure, not content, so it is only spent when
    # there is room for it: the budget is a ceiling on what the model receives.
    note_bits = []
    if dropped_optional:
        note_bits.append(f"{dropped_optional} context block(s) dropped")
    if dropped_turns:
        note_bits.append(f"{dropped_turns} older turn(s) dropped")
    if note_bits:
        text, ok = assemble(kept_optional, kept_turns,
                            "(truncated to fit %d bytes: %s)" % (limit, ", ".join(note_bits)))
        if ok:
            return text
    text, ok = assemble(kept_optional, kept_turns)
    if ok:
        return text
    # Nothing fits alongside the essential block: emit it alone rather than a line
    # cut in half, which is what "never cut mid-line into something misleading" means.
    return "\n".join(essential)


# --------------------------------------------------------------------------- #
def _cli(argv) -> int:
    import argparse
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd")
    s = sub.add_parser("who"); s.add_argument("phone")
    s.add_argument("--store", default=None)
    s = sub.add_parser("render"); s.add_argument("phone")
    s.add_argument("--store", default=None); s.add_argument("--budget", type=int, default=1200)
    sub.add_parser("owner")
    args = p.parse_args(argv)
    if not getattr(args, "cmd", None):
        args = p.parse_args(["owner"])
    if args.cmd == "owner":
        print(json.dumps({"owner_state": owner_state(), "owner_profile": owner_profile()},
                         indent=2, default=str)[:4000])
        return 0
    store = args.store or (textstore.DB_PATH if textstore is not None else None)
    if args.cmd == "who":
        print(json.dumps(resolve(store, args.phone), indent=2, default=str))
        return 0
    print(render(resolve(store, args.phone), budget=args.budget))
    return 0


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
