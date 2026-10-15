#!/usr/bin/env python3
"""Actually do the thing.

This is the module the whole rebuild exists for. In v1, "I'll look into it" was not an
action - `HOLD:` acknowledged the text and then raised an owner-queue row, so the system
could never make a promise it kept (audit finding B4, and the owner named exactly this
as the point of the system on 2026-09-20).

`do(claim, task, ctx, ...)` runs a bounded investigation and comes back with either an
answer worth texting or an honest account of what blocked it.

HOW IT STAYS SAFE

  * Bounded: at most MAX_STEPS model calls and MAX_TOOL_CALLS tool calls, inside a hard
    wall-clock budget. A timeout is a value (`blocked="timeout"`), never a hang
    (journal H609: a killed hop wearing a network failure's name).
  * Read-only, with exactly one exception. Every tool reads. The only write in this
    module is `owner_queue_add`, and it writes a question, not a message.
  * No model, no answer. If the catalog cannot be reached the result is `ok=False,
    blocked="no model"`. Inventing an answer and texting it to the owner's father is
    the worst outcome this system can produce, so it is not reachable.
  * Every result carries `evidence` naming what was actually read. A result with no
    evidence is not a result.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

BASE_DEFAULT = "http://127.0.0.1:8002"
APP_DB_DEFAULT = "/home/zabz/personal-secretary-mvp/data/secretary.db"
OWNER_QUEUE = Path.home() / "bin" / "owner-queue.py"

MAX_STEPS = 3            # model calls per job
MAX_TOOL_CALLS = 10      # tool invocations per job
DEFAULT_TIMEOUT = 240    # seconds, hard
HTTP_TIMEOUT = 30

TOOLS = ("web_search", "memory_search", "owner_state", "owner_profile", "contacts",
         "ledger_query", "charge_lookup",
         "sms_thread", "comms", "app_db_query", "queue_lookup")

SYSTEM = """You are Zabz, working a job for Eliyahu (Lakewood Phone & Tech). A text came
in on his personal line and you told the person you would look into it. Now DO it.

You have these tools, and you may call them by returning JSON:

  "web_search"     {"query": "..."}                     general web search
  "memory_search"  {"query": "..."}                     search our stored memory
  "owner_state"    {}                                   Eliyahu's current state/calendar
  "owner_profile"  {}                                   his learned preferences
  "contacts"       {"phone": "+1..."} or {"name": "..."}  contact records
  "sms_thread"     {"phone": "+1..."}                   the text history with someone
  "comms"          {"phone": "+1..."}                   all comms from this number
  "app_db_query"   {"sql": "SELECT ..."}                read-only SQL on our database
  "queue_lookup"   {}                                   questions already open for him

Return ONE JSON object:

  To use tools - ask for SEVERAL at once when you already know everything you need
  to look up; batching is encouraged, and so is one at a time when you must see a
  result first:
      {"tools": [{"tool": "contacts", "args": {"phone": "+1..."}},
                 {"tool": "memory_search", "args": {"query": "door code"}}]}
  To answer:       {"answer": "the text to send them", "evidence": "what you actually checked"}
  To give up:      {"blocked": "what stopped you"}

A single tool in the short form {"tool": "<name>", "args": {...}} is also accepted.

Rules:
  * Only facts you actually retrieved may appear in an answer. Never invent a price,
    a schedule, an order number or anything about Eliyahu's plans. If you could not
    find it, return {"blocked": "..."} - that is a good outcome, not a failure.
  * The answer is a text message: one to three short sentences, plain English, no
    markdown, no greeting. Do NOT add a signature - that is handled elsewhere.
  * AN ANSWER IS NOT A RECEIPT AND NOT A PROMISE. "Got it", "Noted", "Remembered" and
    "Let me look into it" are not answers; Eliyahu has said so twice in his own words
    and they are refused before they reach his phone. If the only thing you have is a
    receipt or a promise, you have nothing: return {"blocked": "..."} instead.
  * Never commit Eliyahu to anything, never promise a time.
  * You are handling a PERSONAL message - family or a close friend - so be warm and
    human, not corporate.
  * If the job needs HIS money, his decision, or a commitment only he can make, return
    {"blocked": "needs the owner: <one line>"}.
"""


# --------------------------------------------------------------------------- #
# AN ANSWER IS NOT A RECEIPT AND NOT A PROMISE
# --------------------------------------------------------------------------- #
# WHY THIS IS HERE. This module composes the text that goes back to whoever asked, and it
# used to hand whatever the model produced straight to the sender. Measured on the owner's
# own thread, 2026-09-30 -> 2026-10-02: a job that answered with "Let me pull the current
# state so I act on the latest info" was SENT, and he then had to text "Are you still
# diagnosing?" three times. The work had run; the answer was the promise.
#
# The rule is not repeated here in this file's own words. It lives in ONE place -- the
# outbound classification gate in `textsend.py`, which every sender passes through -- and
# this module CONSULTS it, so the composer and the sender can never disagree about what a
# non-answer is. The gate is loaded by path, reused from `sys.modules` when the process
# already has one (that is the copy the responder actually sends with), and optional: a
# tree without `textsend.py` degrades to the prompt's own instruction rather than crashing.
#
# IT APPLIES ONLY TO THE OWNER. A reply to a family member -- "Sure, I'll be there." -- is
# a legitimate commitment and is not this rule's business; the owner's channel is, because
# rule 2 of the workstream brief is his: the work runs and its RESULT goes out.
_TEXTSEND = None
NON_ANSWER_CODES = ("acknowledgement_only", "promise_only", "probe", "internal_instruction")


def _textsend_module():
    """The gate's own module, or None. Cached; never raises."""
    global _TEXTSEND
    if _TEXTSEND is None:
        mod = sys.modules.get("textsend")
        if mod is None:
            try:
                import importlib.util as _ilu
                spec = _ilu.spec_from_file_location(
                    "textsend", str(Path(__file__).resolve().parent / "textsend.py"))
                mod = _ilu.module_from_spec(spec)
                spec.loader.exec_module(mod)
                sys.modules["textsend"] = mod
            except Exception:
                mod = False
        _TEXTSEND = mod or False
    return _TEXTSEND or None


def non_answer_reason(answer: str, ctx: dict | None = None) -> str:
    """Why this answer must not be sent, or '' when it is an answer.

    Returns a plain sentence naming the reason, so the blocked row a day later says what
    happened instead of "textwork returned nothing usable".
    """
    phone = str((ctx or {}).get("phone") or "")
    text = str(answer or "").strip()
    if not phone or not text:
        return ""
    ts = _textsend_module()
    if ts is None:
        return ""
    try:
        if not ts._is_owner(phone, ts._config(None))[0]:
            return ""
        verdict = ts.classify_owner_body(text)
    except Exception:
        return ""                      # a gate that cannot be consulted is not a veto
    if verdict.get("refused") and not verdict.get("salvaged") \
            and verdict.get("code") in NON_ANSWER_CODES:
        return str(verdict.get("reason") or verdict.get("code"))
    return ""


@dataclass
class WorkResult:
    ok: bool
    answer: str | None = None
    evidence: str = ""
    blocked: str | None = None
    escalated: dict | None = None
    steps: int = 0
    tools_used: list = field(default_factory=list)
    model: str | None = None
    elapsed_s: float = 0.0

    def as_dict(self) -> dict:
        return {"ok": self.ok, "answer": self.answer, "evidence": self.evidence,
                "blocked": self.blocked, "escalated": self.escalated,
                "steps": self.steps, "tools_used": self.tools_used,
                "model": self.model, "elapsed_s": round(self.elapsed_s, 2)}


def _base() -> str:
    return (os.environ.get("SECRETARY_API_BASE") or BASE_DEFAULT).rstrip("/")


def _app_db() -> Path:
    return Path(os.environ.get("SECRETARY_DB") or APP_DB_DEFAULT)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --------------------------------------------------------------------------- #
# Tools. All read-only. Each returns (ok, text) and never raises.
# --------------------------------------------------------------------------- #
def _http(path: str, *, method: str = "GET", payload: dict | None = None,
          timeout: int = HTTP_TIMEOUT) -> tuple[bool, str]:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(_base() + path, data=data, method=method)
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read().decode()
        try:
            obj = json.loads(body)
        except Exception:
            return True, body[:3000]
        return True, json.dumps(obj)[:6000]
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}: {e.read().decode()[:200]}"
    except Exception as exc:
        return False, str(exc)


def tool_web_search(query: str) -> tuple[bool, str]:
    ok, body = _http("/web/search", method="POST", payload={"query": query})
    if not ok:
        return False, body
    try:
        results = (json.loads(body) or {}).get("results") or []
    except Exception:
        return True, body
    lines = [f"- {r.get('title', '')[:100]}: {str(r.get('snippet') or r.get('content') or '')[:300]}"
             for r in results[:6]]
    return True, "\n".join(lines) or "(no results)"


def tool_memory_search(query: str) -> tuple[bool, str]:
    ok, body = _http("/semantic-memory/search?q=" + urllib.parse.quote(query))
    if not ok:
        return False, body
    try:
        results = (json.loads(body) or {}).get("results") or []
    except Exception:
        return True, body[:2000]
    return True, "\n".join(f"- {str(r.get('text') or '')[:300]}" for r in results[:6]) or "(no results)"


def tool_owner_state() -> tuple[bool, str]:
    ok, body = _http("/owner/state")
    if not ok:
        return False, body
    try:
        obj = json.loads(body)
    except Exception:
        return True, body[:2000]
    val = obj.get("value") if isinstance(obj.get("value"), dict) else obj
    cal = (val or {}).get("calendar_inference") or {}
    bits = []
    if cal.get("availability"):
        bits.append(f"availability={cal['availability']}")
    if cal.get("reason"):
        bits.append(f"reason={cal['reason']}")
    if cal.get("as_of"):
        bits.append(f"as_of={cal['as_of']}")
    return True, "; ".join(bits) or json.dumps(val)[:1500]


def tool_owner_profile() -> tuple[bool, str]:
    ok, body = _http("/owner/profile")
    if not ok:
        return False, body
    try:
        prof = (json.loads(body) or {}).get("profile") or {}
    except Exception:
        return True, body[:2000]
    items = []
    for k, v in list(prof.items())[:25]:
        if isinstance(v, dict):
            items.append(f"{k}={str(v.get('value'))[:120]} (conf {v.get('confidence')})")
        else:
            items.append(f"{k}={str(v)[:120]}")
    return True, "\n".join(items) or "(none)"


def tool_contacts(phone: str | None = None, name: str | None = None) -> tuple[bool, str]:
    if phone:
        ok, body = _http("/api/v1/comms/by-phone/" + urllib.parse.quote(
            "".join(ch for ch in phone if ch.isdigit())[-10:]))
        if ok:
            return True, body[:3000]
        return False, body
    ok, body = _http("/contacts")
    if not ok:
        return False, body
    try:
        contacts = (json.loads(body) or {}).get("contacts") or []
    except Exception:
        return True, body[:2000]
    if name:
        low = name.lower()
        contacts = [c for c in contacts if low in str(c.get("name", "")).lower()]
    return True, json.dumps(contacts[:8])[:3000] or "(no match)"


def tool_sms_thread(phone: str) -> tuple[bool, str]:
    return _http("/sms/thread/" + urllib.parse.quote(
        "".join(ch for ch in phone if ch.isdigit())[-10:]))


def tool_comms(phone: str) -> tuple[bool, str]:
    return _http("/api/v1/comms/by-phone/" + urllib.parse.quote(
        "".join(ch for ch in phone if ch.isdigit())[-10:]))


def tool_queue_lookup() -> tuple[bool, str]:
    """Questions already open for the owner, so we never ask one twice."""
    try:
        c = sqlite3.connect(f"file:{_app_db()}?mode=ro", uri=True, timeout=20)
        rows = c.execute(
            "SELECT id, question FROM owner_decision_queue WHERE status='pending' "
            "ORDER BY id DESC LIMIT 40").fetchall()
        c.close()
    except Exception as exc:
        return False, str(exc)
    return True, "\n".join(f"#{i}: {str(q)[:160]}" for i, q in rows) or "(none open)"


SELECT_ONLY = re.compile(r"^\s*select\b", re.I)
FORBIDDEN_SQL = re.compile(
    r"\b(insert|update|delete|drop|alter|create|replace|attach|detach|pragma|vacuum|"
    r"reindex|truncate|grant|revoke)\b", re.I)


def tool_app_db_query(sql: str) -> tuple[bool, str]:
    """SELECT-only, guarded, bounded. The one place a bad instruction could hurt."""
    s = (sql or "").strip().rstrip(";")
    if not SELECT_ONLY.match(s):
        return False, "refused: only SELECT statements are allowed"
    if FORBIDDEN_SQL.search(s):
        return False, "refused: the statement contains a write keyword"
    if ";" in s:
        return False, "refused: one statement per call"
    try:
        c = sqlite3.connect(f"file:{_app_db()}?mode=ro", uri=True, timeout=20)
        c.row_factory = sqlite3.Row
        cur = c.execute(s)
        rows = cur.fetchmany(200)
        c.close()
    except Exception as exc:
        return False, f"query failed: {exc}"
    if not rows:
        return True, "(0 rows)"
    return True, json.dumps([dict(r) for r in rows])[:6000]


def owner_queue_add(question: str, recommendation: str = "", options: str = "",
                    context: str = "", blocks: str = "") -> tuple[bool, str]:
    """The ONLY write in this module: a question for the owner, never a message."""
    cmd = ["python3", str(OWNER_QUEUE), "add",
           "--question", (question or "")[:900],
           "--recommendation", (recommendation or "")[:500],
           "--options", options or "Yes|No",
           "--context", (context or "")[:1500],
           "--blocks", (blocks or "a text on the AI line")[:200]]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            return False, f"owner-queue add failed: {(r.stderr or r.stdout)[:200]}"
        return True, (r.stdout or "raised").strip()[:300]
    except Exception as exc:
        return False, str(exc)


def _ledger_db() -> Path:
    """The accounting ledger: where charges, cards and now Amazon orders live."""
    return Path(os.environ.get("CFO_ACCT_DB")
                or (Path.home() / "accounting-data" / "live" / "accounting.db"))


def tool_ledger_query(sql: str) -> tuple[bool, str]:
    """SELECT-only against the accounting ledger.

    `app_db_query` reads the secretary app DB, which has no `transactions` table --
    measured 2026-10-02, that is why the owner's "what was this charge" text came
    back as `app_db_query: FAILED` with no explanation. The money, the cards and the
    Amazon orders are all in the ledger, so the loop needs a read path to it.
    """
    s = (sql or "").strip().rstrip(";")
    if not SELECT_ONLY.match(s):
        return False, "refused: only SELECT statements are allowed"
    if FORBIDDEN_SQL.search(s):
        return False, "refused: the statement contains a write keyword"
    if ";" in s:
        return False, "refused: one statement per call"
    path = _ledger_db()
    if not path.exists():
        return False, "the accounting ledger is not present at %s" % path
    try:
        c = sqlite3.connect("file:%s?mode=ro" % path, uri=True, timeout=20)
        c.row_factory = sqlite3.Row
        rows = c.execute(s).fetchmany(200)
        c.close()
    except Exception as exc:
        return False, "ledger query failed: %s: %s" % (type(exc).__name__, exc)
    if not rows:
        return True, "(0 rows)"
    return True, json.dumps([dict(r) for r in rows])[:6000]


def tool_charge_lookup(amount: str = "", merchant: str = "", date: str = "") -> tuple[bool, str]:
    """Everything the ledger holds about one charge: card, statement line, order match.

    This is the owner's own request, 2026-10-02: "give me the card number, or give me
    what was bought. Maybe match it up against emails, if you can find anything."
    Returns the raw material; composing the sentence is the caller's job.
    """
    out: dict = {}
    try:
        import sys as _sys
        if str(Path.home() / "bin") not in _sys.path:
            _sys.path.insert(0, str(Path.home() / "bin"))
        import charge_msg  # the same composer the CFO asks use
    except Exception as exc:
        return False, "charge_msg unavailable: %s" % exc
    try:
        conn = charge_msg.connect(str(_ledger_db()))
    except Exception as exc:
        return False, "ledger unreadable: %s" % exc
    try:
        # `cents` exists on the merchant path too: exactness is computed for
        # every row below. Measured 2026-10-02 - the merchant path raised
        # UnboundLocalError, which would have been recorded as
        # "charge_lookup: FAILED" and told nobody why. 0 means "no amount asked".
        cents = 0
        like = ("%%%s%%" % merchant.lower().strip()) if merchant.strip() else None
        if like:
            rows = conn.execute(
                """SELECT id, transaction_date, amount_cents, account_id, account_name,
                          normalized_merchant, raw_payload_json
                     FROM transactions
                    WHERE duplicate_of_transaction_id IS NULL
                      AND normalized_merchant LIKE ?
                    ORDER BY transaction_date DESC LIMIT 8""", (like,)).fetchall()
        elif amount.strip():
            cents = int(round(float(str(amount).replace(",", "").replace("$", "")) * 100))
            # Rank exact first and be explicit when it is not exact: measured
            # 2026-10-02, a search for 41.99 returned a 42.00 "US MOBILE" charge and
            # labelled it with the 41.99 Amazon order's match, because the tolerance
            # was 5 cents and the matcher only looked at amount and date.
            rows = conn.execute(
                """SELECT id, transaction_date, amount_cents, account_id, account_name,
                          normalized_merchant, raw_payload_json
                     FROM transactions
                    WHERE duplicate_of_transaction_id IS NULL
                      AND ABS(amount_cents - ?) < 5
                    ORDER BY (ABS(amount_cents - ?) = 0) DESC,
                             ABS(amount_cents - ?), transaction_date DESC
                    LIMIT 8""", (cents, cents, cents)).fetchall()
        else:
            return False, "give me an amount or a merchant"
        charges = []
        for r in rows:
            card = charge_msg.card_last4(r, conn)
            off = abs((r["amount_cents"] or 0) - cents)
            exact = (not cents) or off == 0
            charges.append({
                "match": "exact" if exact
                         else "approximate (%s off)" % charge_msg.fmt_money(off),
                "date": r["transaction_date"],
                "amount": charge_msg.fmt_money(r["amount_cents"]),
                "card_last4": card,
                "merchant": r["normalized_merchant"],
                "statement_line": charge_msg.bank_words(r),
                "account_id": r["account_id"],
                # An approximate amount must never borrow an exact order's match.
                "order_match": ((charge_msg.order_match(
                    conn, r["amount_cents"], r["transaction_date"] or "") or None)
                    if exact else None),
            })
        out["charges"] = charges
        if charges:
            out["composed_body"] = charge_msg.compose(
                conn, charges[0]["merchant"] or "")
    finally:
        conn.close()
    return True, json.dumps(out, indent=1)[:6000]


def _invoke(tool: str, args: dict) -> tuple[bool, str]:
    args = args or {}
    try:
        if tool == "web_search":
            return tool_web_search(str(args.get("query") or ""))
        if tool == "memory_search":
            return tool_memory_search(str(args.get("query") or ""))
        if tool == "owner_state":
            return tool_owner_state()
        if tool == "owner_profile":
            return tool_owner_profile()
        if tool == "contacts":
            return tool_contacts(args.get("phone"), args.get("name"))
        if tool == "sms_thread":
            return tool_sms_thread(str(args.get("phone") or ""))
        if tool == "comms":
            return tool_comms(str(args.get("phone") or ""))
        if tool == "queue_lookup":
            return tool_queue_lookup()
        if tool == "app_db_query":
            return tool_app_db_query(str(args.get("sql") or ""))
        if tool == "ledger_query":
            return tool_ledger_query(str(args.get("sql") or ""))
        if tool == "charge_lookup":
            return tool_charge_lookup(str(args.get("amount") or ""),
                                      str(args.get("merchant") or ""),
                                      str(args.get("date") or ""))
    except Exception as exc:
        return False, f"tool {tool} raised: {exc}"
    return False, f"unknown tool {tool!r}; known: {', '.join(TOOLS)}"


def playbook_titles() -> list:
    """The investigations this module knows how to run."""
    return [
        "general question -> web search and memory",
        "anything about an order, device or repair -> app_db_query + comms + thread",
        "anything about Eliyahu's day or availability -> owner_state",
        "anything he has a standing preference about -> owner_profile",
        "a question needing his money, his call, or a commitment -> escalate",
    ]


def _decode_json(raw: str | None):
    """Every JSON object in the reply, as a list. Empty list when there is none.

    A LIST, not one object, because the gateway can hand back several: measured
    2026-09-20, `secretary-auto` splits batched lookups into multiple native tool
    calls whose arguments arrive concatenated - `{"phone": "+1..."}\\n{"query":
    "door code"}` - so a parser that insists on exactly one object throws away a
    perfectly good plan.
    """
    if not raw:
        return []
    s = raw.strip()
    s = re.sub(r"^```(?:json)?\s*", "", s)
    s = re.sub(r"\s*```$", "", s)
    try:
        got = json.loads(s)
        if isinstance(got, dict):
            return [got]
        if isinstance(got, list):
            return [o for o in got if isinstance(o, dict)]
    except Exception:
        pass
    out, depth, start = [], 0, None
    for i, ch in enumerate(s):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start is not None:
                try:
                    obj = json.loads(s[start:i + 1])
                    if isinstance(obj, dict):
                        out.append(obj)
                except Exception:
                    pass
                start = None
    return out


def _tool_requests(objects: list) -> list:
    """Pull (tool, args) pairs out of whatever shape the model returned.

    Accepts `{"tool": ...}`, `{"tools": [...]}`, and bare argument objects - the last
    because the gateway's native tool-call path delivers only the arguments, with the
    tool's NAME in `function.name` where `_decode_json` cannot see it. In that case the
    arguments alone still identify a usable call: a lone `query` is a search, a lone
    `sql` is a query, a lone `phone` is a contact lookup.
    """
    reqs = []
    for obj in objects or []:
        if not isinstance(obj, dict):
            continue
        if obj.get("tool"):
            reqs.append((str(obj["tool"]).strip(), obj.get("args") or
                         {k: v for k, v in obj.items() if k not in ("tool", "args", "why")}))
            continue
        if isinstance(obj.get("tools"), list):
            for t in obj["tools"]:
                if isinstance(t, dict) and t.get("tool"):
                    reqs.append((str(t["tool"]).strip(),
                                 t.get("args") or {k: v for k, v in t.items()
                                                   if k not in ("tool", "args", "why")}))
            continue
        # A bare argument object. Infer the tool from the single key, if we can.
        keys = set(obj)
        if keys == {"query"}:
            reqs.append(("memory_search", {"query": str(obj["query"])}))
        elif keys == {"sql"}:
            reqs.append(("app_db_query", {"sql": str(obj["sql"])}))
        elif keys == {"phone"}:
            reqs.append(("contacts", {"phone": str(obj["phone"])}))
        elif keys == {"name"}:
            reqs.append(("contacts", {"name": str(obj["name"])}))
    return reqs


# --------------------------------------------------------------------------- #
def _blocked_result(reason: str, claim: str, ctx: dict, *, steps: int = 0,
                    tools_used=None, model=None, evidence: str = "") -> "WorkResult":
    """A block that carries the question the owner has to answer.

    Every blocked investigation produces this. Measured 2026-10-02: three owner texts
    died at "the model returned no usable JSON" (a 502 from the gateway) and returned
    `escalated=None`, so the responder filed a generic "I could not resolve it" row and
    the question he had actually answered was lost. A block with no question in it is
    indistinguishable from a bug.
    """
    phone = (ctx or {}).get("phone") or ""
    name = (((ctx or {}).get("identity") or {}).get("name")) or phone or "someone"
    return WorkResult(
        False,
        blocked=reason,
        escalated={
            "question": ("%s (%s) asked: %r. I could not resolve it: %s"
                         % (name, phone or "?", str(claim or "")[:200], str(reason or "")[:220])),
            "recommendation": "Tell me the answer and I will send it as a text.",
            "options": ["Send it as I say", "Draft it for me", "Leave it unanswered"],
        },
        steps=steps,
        tools_used=tools_used or [],
        model=model,
        evidence=evidence or "nothing was read",
        elapsed_s=0.0,
    )


def do(claim: str, task: str, ctx: dict | None = None, *,
       deliverable: str = "a text back to them", timeout: int = DEFAULT_TIMEOUT,
       decider=None, llm=None) -> WorkResult:
    """Run a bounded investigation and come back with an answer or an honest block."""
    started = time.monotonic()
    # Never below 1 s. `timeout=0` must mean "as soon as possible", not a job that
    # slips past its own check because the monotonic clock had not ticked yet.
    timeout = max(1, int(timeout))
    ctx = ctx or {}
    dossier = _render_dossier(claim, task, ctx, deliverable)

    # Resolve the model before spending anything. No model, no answer, ever.
    call = llm
    model = None
    if call is None:
        d = decider
        if d is None:
            try:
                import importlib.util
                spec = importlib.util.spec_from_file_location(
                    "textdecide", str(Path(__file__).resolve().parent / "textdecide.py"))
                td = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(td)
                d = td.Decider()
            except Exception as exc:
                # `step`, `tools_used` and `model` do not exist yet at this point: the loop
                # has not started. Referencing them here raised NameError OUT OF `do()`
                # (measured 2026-10-02, reading the code) -- so the one path that exists to
                # report "the decider could not be loaded" crashed instead of reporting.
                return _blocked_result(
                    f"no model: decider unavailable ({exc})", claim, ctx or {},
                    steps=0, tools_used=[], model=None,
                    evidence="textdecide could not be loaded")
        model = d.resolve_model()
        if not model:
            return _blocked_result(
                f"no model: {d.last_error or 'catalog empty'}", claim, ctx or {},
                steps=1, tools_used=tools_used, model=model,
                evidence="gateway catalog unreachable; nothing was invented")

    notes: list[str] = []
    tools_used: list[str] = []
    conversation = dossier

    for step in range(1, MAX_STEPS + 1):
        if time.monotonic() - started > timeout:
            return WorkResult(False, blocked="timeout", steps=step - 1,
                              tools_used=tools_used, model=model,
                              evidence=_evidence(tools_used, notes),
                              elapsed_s=time.monotonic() - started)

        # Both branches catch. An injected `llm=` is how the failure paths are tested, and
        # the failure that matters most (a gateway 502) arrives as an exception -- so a
        # raise from a stub must land in the same place as a raise from the real decider,
        # not propagate out of `do()`.
        try:
            if call is not None:
                raw = call(SYSTEM, conversation)
            else:
                raw = d.call(SYSTEM, conversation, max_tokens=400,
                             timeout=max(20, min(90, int(timeout - (time.monotonic() - started)))))
        except Exception as exc:
            raw = None
            notes.append(
                ("an injected model raised: " if call is not None else "model call raised: ")
                + str(exc))
        parsed_list = _decode_json(raw)

        # Any object in the reply that carries an answer or a block ends the job. A
        # batch that also mentions tools is still an answer - the answer is the point.
        terminal = next((o for o in parsed_list if o.get("answer") or o.get("blocked")),
                        None)

        if parsed_list == [] or terminal is None and not _tool_requests(parsed_list):
            if step == 1 or (step == 2 and not tools_used):
                # One retry: models wrap JSON in prose, and a first-round miss is
                # usually formatting. A second failure is a real failure, and must
                # not be papered over with a guess.
                conversation += ("\n\nYour last reply was not a JSON object I could use. "
                                 "Reply with ONE JSON object: {\"tools\": [...]}, "
                                 "{\"answer\": ...} or {\"blocked\": ...}.")
                continue
            return _blocked_result(
                "the model returned no usable JSON"
                + (f" ({d.last_error})" if (call is None and d.last_error) else ""),
                claim, ctx or {}, steps=step, tools_used=tools_used, model=model,
                evidence=_evidence(tools_used, notes))

        if terminal is not None and terminal.get("answer"):
            answer = str(terminal["answer"]).strip()
            if len(answer) > 480:
                answer = answer[:470].rsplit(" ", 1)[0] + "..."
            # THE LAST THING BEFORE THIS BECOMES A TEXT. A receipt or a promise is not an
            # answer, and sending one is what produced "Are you still diagnosing?" See
            # `non_answer_reason`: the rule lives in `textsend.py`, not in a second copy
            # here.
            why_not = non_answer_reason(answer, ctx)
            if why_not:
                return _blocked_result(
                    "the answer was not an answer: " + why_not, claim, ctx or {},
                    steps=step, tools_used=tools_used, model=model,
                    evidence=_evidence(tools_used, notes) + " | answer withheld: %s"
                             % answer[:120])
            # The model's own account of what it read is a CLAIM. The tools it
            # actually called are the PROOF, and both belong in the record - a
            # result whose evidence cannot be traced was the exact failure the
            # audit called out.
            claimed = str(terminal.get("evidence") or "").strip()
            real = _evidence(tools_used, notes)
            evidence = f"{claimed} | {real}" if claimed else real
            return WorkResult(True, answer=answer, evidence=evidence,
                              steps=step, tools_used=tools_used, model=model,
                              elapsed_s=time.monotonic() - started)

        if terminal is not None and terminal.get("blocked"):
            reason = str(terminal["blocked"]).strip()[:400]
            return _blocked(reason, tools_used, notes, step, model, started, ctx, claim, task)

        requests = _tool_requests(parsed_list)
        if not requests:
            conversation += ("\n\nThat was neither a tool call nor an answer. Reply "
                             "with {\"tools\": [...]} or {\"answer\": ...} or "
                             "{\"blocked\": ...}.")
            continue
        if len(tools_used) + len(requests) > MAX_TOOL_CALLS:
            requests = requests[:max(0, MAX_TOOL_CALLS - len(tools_used))]
            notes.append("dropped tool calls past the budget")

        # Priority matters: a job whose clock ran out reports a TIMEOUT even if it also
        # happened to spend its tool budget. Reporting the wrong limit sends the next
        # person looking in the wrong place (journal H609: a killed hop wearing a
        # network failure's name).
        if time.monotonic() - started > timeout:
            return WorkResult(False, blocked="timeout", steps=step,
                              tools_used=tools_used, model=model,
                              evidence=_evidence(tools_used, notes),
                              elapsed_s=time.monotonic() - started)

        bundle = []
        for tool, targs in requests:
            # ONE invocation per request. This block used to call `_invoke`, append the
            # tool, call it AGAIN and append it again, and append the result bundle twice
            # (measured 2026-10-02, reading the code): every tool ran twice, `tools_used`
            # and `notes` counted double, and the model was handed the same result twice.
            ok, out = _invoke(tool, targs)
            tools_used.append(tool)
            # The error text, not just the verdict. Measured 2026-10-02: a job whose
            # only problem was an HTTP 502 from the model gateway was recorded as
            # "app_db_query: FAILED", which is undiagnosable a day later. First line
            # only, truncated -- enough to tell a lock from a 502 from a bad query.
            detail = " ".join(str(out or "").split())[:160] if not ok else ""
            notes.append("%s: %s%s" % (tool, "ok" if ok else "FAILED",
                                       (" -- " + detail) if detail else ""))
            bundle.append(f"--- result of {tool} ---\n{out[:3000]}\n--- end {tool} ---")
        conversation += ("\n\n" + "\n".join(bundle)
                         + "\nNow either call more tools, or give the answer, "
                           "or say blocked.")

    return _blocked_result(
        f"no answer after {MAX_STEPS} steps", claim, ctx or {}, steps=MAX_STEPS,
        tools_used=tools_used, model=model, evidence=_evidence(tools_used, notes))


def _blocked(reason: str, tools_used, notes, steps, model, started, ctx, claim, task) -> WorkResult:
    """A block is a result. Decide whether it is a question for the owner or not."""
    escalated = None
    phone = ctx.get("phone") or ""
    name = ((ctx.get("identity") or {}).get("name")) or phone
    # ALWAYS, not only when the prose happens to contain a magic word. Measured
    # 2026-10-02: a block caused by a model 502 matched nothing, so `escalated` was
    # None, and the owner got "I could not resolve it" with no trace of the question
    # he had actually answered. The structured question is what makes the blocked row
    # readable and answerable a day later.
    escalated = {
        "question": f"{name} ({phone}) asked: {claim[:200]!r}. I could not resolve it: {reason[:220]}",
        "recommendation": ("Tell me the answer and I will send it as a text."
                           if not re.search(r"needs the owner|his (decision|money|call)|commit",
                                            reason, re.I)
                           else "This one is your call: tell me the answer and I will send it."),
        "options": ["Send it as I say", "Draft it for me", "Leave it unanswered"],
    }
    return WorkResult(False, blocked=reason, escalated=escalated, steps=steps,
                      tools_used=tools_used, model=model,
                      evidence=_evidence(tools_used, notes),
                      elapsed_s=time.monotonic() - started)


def _dedupe_notes(notes) -> list:
    """First occurrence in order, repeats folded into "(xN)"."""
    seen: dict = {}
    order: list = []
    for n in notes or []:
        text = str(n or "").strip()
        if not text:
            continue
        if text in seen:
            seen[text] += 1
        else:
            seen[text] = 1
            order.append(text)
    return [t if seen[t] == 1 else "%s (x%d)" % (t, seen[t]) for t in order]


def _evidence(tools_used, notes) -> str:
    """What was actually read, and if nothing was, WHY.

    `"nothing was read"` is the honest answer when an investigation found nothing to
    read. It is a lie of omission when the read never happened -- measured 2026-10-02, a
    block whose only cause was an HTTP 502 from the gateway recorded those three words and
    dropped the error, so the row could not be diagnosed a day later (L3234).
    """
    clean = _dedupe_notes(notes)
    # Keep the TAIL: the most recent notes are the ones that explain how it ended.
    shown = clean[-4:]
    tail = f" ({'; '.join(shown)})" if shown else ""
    if not tools_used:
        return ("nothing was read; " + "; ".join(shown)) if shown else "nothing was read"
    return f"read via: {', '.join(tools_used)}" + tail


def _render_dossier(claim: str, task: str, ctx: dict, deliverable: str) -> str:
    ident = ctx.get("identity") or {}
    hist = ctx.get("history") or {}
    lines = [
        "THE JOB",
        f"  what we told them we would do: {claim}",
        f"  so that they get: {deliverable}",
        f"  detail: {str(task)[:900]}",
        "",
        "WHO IS WAITING",
        f"  {ident.get('name') or 'unknown'} ({ctx.get('phone') or '?'}), "
        f"relationship={ident.get('relationship') or 'unknown'}, "
        f"allow={ctx.get('allow') or 'queue'}",
        f"  correspondence: {hist.get('inbound', 0)} in / {hist.get('outbound', 0)} out",
    ]
    if hist.get("last_inbound"):
        lines.append(f"  last we heard from them: {hist['last_inbound']}")
    thread = ctx.get("thread") or []
    if thread:
        lines += ["", "RECENT THREAD (oldest first)"]
        for t in thread[-6:]:
            lines.append(f"  {'them' if t.get('who') == 'them' else 'us'}: "
                         f"{str(t.get('body') or '')[:250]}")
    jobs = ctx.get("open_jobs") or []
    if jobs:
        lines += ["", "PROMISES ALREADY OPEN TO THEM"]
        for j in jobs[:3]:
            lines.append(f"  #{j.get('id')} [{j.get('state')}] {str(j.get('claim'))[:120]}")
    rows = ctx.get("open_owner_rows") or []
    if rows:
        lines += ["", "QUESTIONS ALREADY WAITING FOR HIM ABOUT THEM"]
        for r in rows[:2]:
            lines.append(f"  #{r.get('id')} {str(r.get('question'))[:140]}")
    warns = ctx.get("warnings") or []
    if warns:
        lines += ["", "CONTEXT WARNINGS: " + "; ".join(str(w) for w in warns[:4])]
    lines.append("")
    lines.append("Start by calling the most useful tool.")
    return "\n".join(lines)


def main() -> int:
    import argparse
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("claim", nargs="?", default="look into it")
    p.add_argument("--task", default=None)
    p.add_argument("--phone", default="+15551234567")
    p.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    p.add_argument("--playbooks", action="store_true")
    a = p.parse_args()
    if a.playbooks:
        for t in playbook_titles():
            print(f"  - {t}")
        return 0
    ctx = {"phone": a.phone, "allow": "queue",
           "identity": {"name": None, "relationship": "unknown"},
           "history": {}, "thread": [], "open_jobs": [], "open_owner_rows": [],
           "warnings": []}
    r = do(a.claim, a.task or a.claim, ctx, timeout=a.timeout)
    print(json.dumps(r.as_dict(), indent=2))
    return 0 if r.ok else 1


if __name__ == "__main__":
    sys.exit(main())
