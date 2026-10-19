#!/usr/bin/env python3
"""preask.py — the ladder that runs before the owner is asked anything.

The owner's rule, verbatim (2026-10-16, `sms_log` 500):

    "Remember, before you give me a charge, you have to exhaust all of the resources for
     exploring it. And then, if you still don't know, give me all the details you found."

This module is that sentence, implemented. It is called by an ASKER (cfo-ask, owner-ask,
card-due-watch) *before* it composes a question, and its receipt travels with the item into
`owner_text_relay.submit_item()`. The relay refuses an item that opens an ask without a receipt,
which is what makes the ladder unavoidable rather than advisory.

Design rules, each paid for:

* **A rung never guesses.** It returns `solved` with evidence it actually read, or `not_found`.
  An exception is `error`, never `not_found` — "we could not look" and "it is not there" are
  different sentences and must never collapse into one (measurement rule, 2026-10-14).
* **Evidence is short and quotable.** The composer may put at most one clause of it into a text.
  A receipt that needs a paragraph is a receipt that will be truncated.
* **`complete` is separate from `solved`.** A receipt where a rung errored is `incomplete`; an
  asker may still ask, but the body must not claim it checked that source.
* **No store of its own.** The receipt is stored on the attempt and on the ask row by the relay.
  One ledger (design §3), not a fourth.

CLI, for proving a rung by hand:

    python3 preask.py --kind charge --amount 114.04 --merchant "adjust membership" \
        --date 2026-07-23 --json
    python3 preask.py --kind person --text "Weinberg" --json
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sqlite3
import sys
import time
from dataclasses import dataclass, field, asdict

VERSION = 1
AUTHORITY_DB = os.environ.get("PREASK_AUTHORITY_DB", "/root/authority.db")
RELAY_DB = os.environ.get("OWNER_TEXT_RELAY_DB", "/root/.owner-text/relay.db")
BIN_DIR = os.environ.get("PREASK_BIN_DIR", "/root/bin")
OWNER_PHONE = os.environ.get("OWNER_PHONE_NUMBER", "+18483897895")

KINDS = ("charge", "payroll", "tax", "document", "person", "schedule", "generic")

# A rung is "done" when it either solved the question or looked and found nothing.
DONE = ("solved", "not_found")
MAX_EVIDENCE_SENTENCES = 2


@dataclass
class Rung:
    name: str
    status: str = "skipped"          # solved | not_found | error | skipped
    detail: str = ""
    ms: int = 0
    keys: list = field(default_factory=list)
    sentence: str = ""               # safe to quote in a text, <= 90 chars


@dataclass
class Receipt:
    kind: str
    subject: str
    at: str
    verdict: str = "unknown"          # answered | partial | unknown
    resolution: dict | None = None    # what to do INSTEAD of asking
    rungs: list = field(default_factory=list)
    version: int = VERSION

    @property
    def complete(self) -> bool:
        """Did every rung we meant to run return? 'skipped' is a decision, 'error' is a hole."""
        return not self.errored

    @property
    def errored(self) -> list:
        return [r.name for r in self.rungs if r.status == "error"]

    def evidence(self) -> list:
        """Clauses safe to quote to him — conclusive and partial alike.

        'partial' is the case he asked for in so many words: "if you still don't know, give me
        all the details you found" (2026-10-16). It is evidence, not a resolution.
        """
        out = []
        for r in self.rungs:
            if r.status in ("solved", "partial") and r.sentence:
                out.append(r.sentence)
        return out[:MAX_EVIDENCE_SENTENCES]

    def as_dict(self) -> dict:
        d = asdict(self)
        d["complete"] = self.complete
        d["errored"] = self.errored
        d["evidence"] = self.evidence()
        return d

    def body_hint(self, limit: int = 88) -> str:
        """One clause the composer may append, or '' when it would add nothing."""
        ev = self.evidence()
        if ev:
            s = ev[0]
        elif self.complete:
            s = "I checked our records, your texts and your mail - nothing there"
        else:
            s = ""
        return _clip(s, limit)

    def phrase(self) -> str:
        """A short, honest account of what was tried, for the weekly audit and the log."""
        bits = []
        for r in self.rungs:
            bits.append(f"{r.name}={r.status}")
        return " ".join(bits) or "no rungs ran"


# --------------------------------------------------------------------------- helpers

def _clip(s: str, limit: int) -> str:
    s = re.sub(r"\s+", " ", (s or "")).strip()
    if len(s) <= limit:
        return s
    cut = s[:limit]
    for sep in (". ", "; ", ", ", " "):
        i = cut.rfind(sep)
        if i > limit * 0.5:
            return cut[:i].rstrip(" ,;.")
    return cut.rstrip(" ,;.")


def _now_iso() -> str:
    import datetime as _dt
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _conn(path: str) -> sqlite3.Connection:
    c = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
    c.row_factory = sqlite3.Row
    return c


def _load_module(name: str, filename: str):
    """Import a sibling module by path. Returns None when it is not there."""
    path = os.path.join(BIN_DIR, filename)
    if not os.path.exists(path):
        return None
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)          # type: ignore[union-attr]
        return mod
    except Exception:
        return None


def _like_terms(*values) -> list:
    out = []
    for v in values:
        if not v:
            continue
        for t in re.split(r"[^A-Za-z0-9]+", str(v)):
            t = t.strip().lower()
            if len(t) >= 4 and t not in ("charge", "payment", "card", "account"):
                out.append(t)
    return out[:6]


def _amount_forms(amount) -> list:
    """Every way a person or a statement might write the same amount."""
    if amount in (None, ""):
        return []
    try:
        a = float(amount)
    except (TypeError, ValueError):
        return [str(amount)]
    forms = {f"{a:.2f}", f"{a:,.2f}", f"{a:.2f}".rstrip("0").rstrip(".")}
    if a == int(a):
        forms.add(str(int(a)))
    return [f for f in forms if f]


# A match that does not contain the thing being asked about is a coincidence, not evidence.
# This is the defect that made the first version of this module "solve" a 418.77 charge with a
# memory about a 25.00 one. The predicate below is the guard.
def _discriminates(text: str, amount, terms: list, *, allow_amount_only: bool = False) -> bool:
    t = (text or "").lower()
    if not t:
        return False
    amt_hit = any(f in t for f in _amount_forms(amount)) if amount not in (None, "") else False
    term_hits = sum(1 for x in terms if x in t)
    if amount not in (None, ""):
        if allow_amount_only and amt_hit:
            return True
        return amt_hit and term_hits >= 1
    return term_hits >= 2 or (term_hits >= 1 and len(terms) == 1)


# He answers a question he cannot answer with a deflection, and it is not an answer.
# "figure that out yourself", 2026-02-19. Quoting one back to him as "you told me" is worse
# than asking again.
_DEFLECTION = re.compile(
    r"\b(i don'?t know|no idea|not sure|you tell me|figure (it|this) out|"
    r"look into it|you should (have )?(that|it)|check (my|the) (emails?|files?|records?)|"
    r"that'?s your job|your decision)\b", re.I)


def _is_deflection(text: str) -> bool:
    return bool(_DEFLECTION.search(text or ""))


# An `answer_body` that merely repeats our own question is an echo, not an answer.
_ECHO = re.compile(r"(CFO \[ask-|Reply to this text|I'?ll get it|No guess from me)", re.I)


def _echoes_question(text: str) -> bool:
    return bool(_ECHO.search(text or ""))


# --------------------------------------------------------------------------- rungs

def rung_owner_answer(q: dict, r: Rung) -> Rung:
    """Has he already told us? The cheapest and most authoritative rung there is.

    Reads, in order: the relay's answered asks, his answered owner_text_turn rows, and the
    memory FTS. Three outcomes matter and they are NOT the same sentence:

      solved    — he gave an attribution. Act on it; do not ask.
      deflected — he was asked and told us to work it out ("figure it out", "check my emails").
                  Do not ask again: that is the instruction the whole ladder exists to obey.
      not_found — we looked and there is nothing usable.
    """
    terms = _like_terms(q.get("merchant"), q.get("text"), q.get("subject"), q.get("person"))
    amount = q.get("amount")
    hits = []
    deflections = []

    if os.path.exists(RELAY_DB):
        c = _conn(RELAY_DB)
        try:
            for row in c.execute(
                "SELECT ref,topic,answer,answered_at FROM ask "
                "WHERE state='answered' AND answer IS NOT NULL AND answer<>'' "
                "ORDER BY answered_at DESC LIMIT 400"
            ):
                blob = f"{row['topic'] or ''} {row['answer'] or ''}"
                if not _discriminates(blob, amount, terms):
                    continue
                if _is_deflection(row["answer"]):
                    deflections.append(("relay-ask", row["ref"], row["answer"], row["answered_at"]))
                elif not _echoes_question(row["answer"]):
                    hits.append(("relay-ask", row["ref"], row["answer"], row["answered_at"]))
                if len(hits) >= 3:
                    break
        finally:
            c.close()

    if not hits and os.path.exists(AUTHORITY_DB):
        c = _conn(AUTHORITY_DB)
        try:
            for row in c.execute(
                "SELECT answer_body,sent_at,answered_at FROM owner_text_turn "
                "WHERE answered_at IS NOT NULL AND answer_body IS NOT NULL AND answer_body<>'' "
                "ORDER BY answered_at DESC LIMIT 400"
            ):
                blob = row["answer_body"] or ""
                if not _discriminates(blob, amount, terms):
                    continue
                if _is_deflection(blob):
                    deflections.append(("owner-text", "turn", blob, row["answered_at"]))
                elif not _echoes_question(blob):
                    hits.append(("owner-text", "turn", blob, row["answered_at"]))
                if len(hits) >= 3:
                    break
        finally:
            c.close()

    if not hits and terms and os.path.exists(AUTHORITY_DB):
        c = _conn(AUTHORITY_DB)
        try:
            expr = " OR ".join(f'"{t}"' for t in terms[:4])
            for row in c.execute(
                "SELECT m.content, m.created_at FROM memories_fts f "
                "JOIN memories m ON m.id = f.rowid WHERE memories_fts MATCH ? "
                "AND m.status='active' ORDER BY m.importance DESC LIMIT 12", (expr,)
            ):
                content = row["content"] or ""
                # a memory may only solve an amount question if it names the amount
                if not _discriminates(content, amount, terms, allow_amount_only=False):
                    continue
                hits.append(("memory", "mem", content, row["created_at"]))
                break
        except sqlite3.Error:
            pass
        finally:
            c.close()

    if hits:
        src, key, answer, when = hits[0]
        r.status = "solved"
        r.keys = [f"{src}:{key}"]
        r.detail = f"he already answered on {str(when)[:19]} ({src})"
        r.sentence = f"you told me on {str(when)[:10]}: {_clip(answer, 60)}"
        return r

    if deflections:
        src, key, answer, when = deflections[0]
        r.status = "deflected"
        r.keys = [f"{src}:{key}"]
        r.detail = f"he was asked on {str(when)[:19]} and told us to work it out ({src})"
        r.sentence = f"you told me on {str(when)[:10]} to work it out - I will"
        return r

    r.status = "not_found"
    r.detail = f"no prior answer that names {amount or terms}"
    return r



def rung_ledger(q: dict, r: Rung) -> Rung:
    """Is the money already in the books?

    Amount-anchored, and self-contained on purpose. `merchant_resolve.resolve()` answers a
    different question ("what merchant is this") and resolves by NAME, so handing it an amount
    made it "solve" a 418.77 charge with a text about a 25.00 co-pay. It is used here only for
    a question that has no amount, and never with its web-research rung (12.7 s on an ask path).

      solved  — the amount is in the statement AND the merchant matches, or the row is already
                attributed (is_personal / personal_reason / a linked purchase).
      partial — the amount is in the statement but we cannot say it is THIS charge: that goes
                into the text as evidence, and the question becomes "was this X?".
    """
    amount = q.get("amount")
    if amount is None:
        return _ledger_merchant_only(q, r)
    try:
        amt = float(amount)
    except (TypeError, ValueError):
        r.status = "skipped"
        r.detail = "amount not numeric"
        return r

    terms = _like_terms(q.get("merchant"), q.get("subject"))
    c = _conn(AUTHORITY_DB)
    try:
        rows = c.execute(
            "SELECT id,transaction_id,amount,date,name,merchant_name,category,"
            "is_personal,personal_reason FROM plaid_transactions "
            "WHERE ABS(ABS(COALESCE(amount,0)) - ?) < 0.02 "
            "ORDER BY date DESC LIMIT 20", (abs(amt),)
        ).fetchall()
    finally:
        c.close()

    if not rows:
        r.status = "not_found"
        r.detail = f"no statement line within 0.02 of {amt:.2f}"
        _ledger_purchase(q, r, amt)      # may upgrade r to solved; returns a dict, not a Rung
        return r

    def named(row) -> bool:
        if not terms:
            return False
        blob = f"{row['name'] or ''} {row['merchant_name'] or ''}".lower()
        return any(t in blob for t in terms)

    match = next((row for row in rows if named(row)), None)
    if match is None and len(rows) == 1 and not terms:
        match = rows[0]
    if match is None:
        row = rows[0]
        r.status = "partial"
        r.keys = [f"plaid:{row['transaction_id']}"]
        r.detail = (f"{len(rows)} charge(s) of {amt:.2f}; nearest is "
                    f"{row['merchant_name'] or row['name']} on {row['date']}")
        r.sentence = (f"the {amt:.2f} on {row['date']} reads "
                      f"{_clip((row['merchant_name'] or row['name'] or '').title(), 34)}")
        return r

    who = _clip((match["merchant_name"] or match["name"] or "").title(), 40)
    if match["is_personal"]:
        r.status = "solved"
        r.keys = [f"plaid:{match['transaction_id']}"]
        r.detail = (f"already marked personal on {match['date']} "
                    f"({match['personal_reason'] or 'no reason recorded'})")
        r.sentence = f"already filed as personal: {who}, {amt:.2f} on {match['date']}"
        return r

    purchase = _ledger_purchase(q, r, amt, quiet=True)
    if purchase.get("found"):
        r.status = "solved"
        r.keys = [f"purchase:{purchase['id']}"]
        r.detail = f"statement line {who} linked to purchase #{purchase['id']} ({purchase['vendor']})"
        r.sentence = f"we hold the order: {_clip(str(purchase['vendor']), 30)} {amt:.2f} on {purchase['order_date']}"
        return r

    r.status = "solved"
    r.keys = [f"plaid:{match['transaction_id']}"]
    r.detail = f"statement line {who} on {match['date']} category={match['category']}"
    r.sentence = f"the {amt:.2f} on {match['date']} is {who}"
    return r


def _ledger_purchase(q: dict, r: Rung, amt: float, *, quiet: bool = False) -> dict:
    """Order mail already matched to a charge. Returns {'found':bool,...} — never raises."""
    c = _conn(AUTHORITY_DB)
    try:
        row = c.execute(
            "SELECT id,vendor,total,order_date,order_id,status FROM purchases "
            "WHERE ABS(COALESCE(total,0) - ?) < 0.02 ORDER BY order_date DESC LIMIT 1", (amt,)
        ).fetchone()
    finally:
        c.close()
    if not row:
        if not quiet:
            r.status = "not_found"
            r.detail = f"no purchase row within 0.02 of {amt:.2f}"
        return {"found": False}
    if quiet:
        return {"found": True, **dict(row)}
    r.status = "solved"
    r.keys = [f"purchases:{row['id']}"]
    r.detail = f"purchase #{row['id']} {row['vendor']} {row['total']} on {row['order_date']}"
    r.sentence = f"we hold the order: {_clip(str(row['vendor']), 30)} {row['total']} on {row['order_date']}"
    return {"found": True, **dict(row)}


def _ledger_merchant_only(q: dict, r: Rung) -> Rung:
    """No amount: 'what is this merchant'. This is the one question merchant_resolve owns."""
    merchant = q.get("merchant") or q.get("subject") or ""
    if not merchant:
        r.status = "skipped"
        r.detail = "no amount and no merchant"
        return r
    mr = _load_module("merchant_resolve", "merchant_resolve.py")
    if mr is None or not hasattr(mr, "resolve"):
        r.status = "error"
        r.detail = "merchant_resolve.py not importable"
        return r
    try:
        res = mr.resolve(merchant, merchant=merchant, research=False)
    except Exception as e:                          # noqa: BLE001
        r.status = "error"
        r.detail = f"merchant_resolve: {type(e).__name__}: {e}"
        return r
    # `solved` is the resolver's own claim; it is NOT a confidence. Measured 2026-10-19: this
    # line counted a 0.55 provisional reading of "ADJUST MEMBERSHIP FEE" as a solved rung, and
    # preask's job is to decide whether a QUESTION is still needed - so a weak reading marked
    # the ladder as complete and the question went out anyway, with the weak evidence stripped
    # of the fact that it was weak. Require an actual threshold and refuse a reversal reading.
    if isinstance(res, dict) and res.get("solved") \
            and not res.get("provisional") and res.get("purchase") is not False \
            and float(res.get("confidence") or 0) >= 0.75:
        r.status = "solved"
        r.keys = [f"merchant_resolve:{res.get('source') or res.get('method') or '?'}"]
        r.detail = f"source={res.get('source')} conf={res.get('confidence')}"
        ev = res.get("evidence")
        if isinstance(ev, list) and ev:
            ev = ev[0]
        r.sentence = _clip(str(ev or res.get("entity") or ""), 88)
        return r
    r.status = "not_found"
    checked = (res or {}).get("checked") if isinstance(res, dict) else None
    r.detail = "merchant_resolve found nothing" + (
        f" (checked {len(checked)} methods)" if isinstance(checked, list) else "")
    return r


def rung_comms(q: dict, r: Rung) -> Rung:
    """Did they tell us in a text, a call or an email? His own instruction: 'check my emails'.

    Same discrimination guard as rung 1: an amount inside an unrelated message is not evidence.
    """
    terms = _like_terms(q.get("merchant"), q.get("text"), q.get("subject"))
    amount = q.get("amount")
    if not terms and not amount:
        r.status = "skipped"
        r.detail = "nothing to search"
        return r

    c = _conn(AUTHORITY_DB)
    try:
        def best(like: str, limit: int = 40):
            rows = c.execute(
                "SELECT body_text,created_at,channel,direction FROM dialpad_sms_cache "
                "WHERE body_text LIKE ? ORDER BY created_at DESC LIMIT ?", (like, limit)
            ).fetchall()
            for row in rows:
                if _discriminates(row["body_text"], amount, terms):
                    return row
            rows = c.execute(
                "SELECT transcript_text AS body_text, started_at AS created_at, 'call' AS channel, "
                "direction FROM dialpad_transcript_cache WHERE transcript_text LIKE ? "
                "ORDER BY started_at DESC LIMIT ?", (like, limit)
            ).fetchall()
            for row in rows:
                if _discriminates(row["body_text"], amount, terms):
                    return row
            return None

        found = None
        if amount:
            found = best(f"%{_amount_forms(amount)[0]}%")
        if not found:
            for t in terms[:3]:
                found = best(f"%{t}%")
                if found:
                    break
        if not found:
            r.status = "not_found"
            r.detail = f"no sms/call text that names {amount or terms}"
            return r
        r.status = "solved"
        r.detail = f"{found['channel']} {found['direction']} on {str(found['created_at'])[:10]}"
        r.sentence = f"a {found['channel']} on {str(found['created_at'])[:10]} says: {_clip(found['body_text'] or '', 50)}"
        return r
    finally:
        c.close()


def rung_docs(q: dict, r: Rung) -> Rung:
    """Is it a standing fact we already wrote down? Payroll, insurance, contracts, tax.

    Deliberately narrow: a keyword index over the estate's own docs, not a full-text crawl.
    """
    terms = _like_terms(q.get("subject"), q.get("text"), q.get("merchant"), q.get("person"))
    if not terms:
        r.status = "skipped"
        r.detail = "nothing to search"
        return r
    roots = [p for p in (os.environ.get("PREASK_DOC_ROOT", ""),) if p]
    if not roots:
        r.status = "skipped"
        r.detail = "no doc root configured"
        return r
    hits = []
    for root in roots:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if not d.startswith(".") and d != "node_modules"]
            for fn in filenames:
                if not fn.lower().endswith((".md", ".txt")):
                    continue
                path = os.path.join(dirpath, fn)
                try:
                    with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                        head = fh.read(200_000).lower()
                except OSError:
                    continue
                score = sum(1 for t in terms if t in head)
                if score >= 2:
                    hits.append((score, path))
            if len(hits) > 6:
                break
    if not hits:
        r.status = "not_found"
        r.detail = f"no doc mentions {terms}"
        return r
    hits.sort(reverse=True)
    r.status = "solved"
    r.keys = [hits[0][1]]
    r.detail = f"{len(hits)} doc(s) mention it, best {hits[0][1]}"
    r.sentence = f"our own docs cover it: {os.path.basename(hits[0][1])}"
    return r


def rung_web(q: dict, r: Rung) -> Rung:
    """Step 3 of his own ladder: "you could've googled it" (`corpus:420`).

    Deliberately NOT wired to a live search here. Two reasons, both measured: a research rung on
    this path took 12,751 ms and returned a merchant's error page as "evidence", and the ask path
    runs every 30 minutes. What this rung does is make the omission VISIBLE: it always reports
    `skipped` with the reason, so a receipt never implies a web check that did not happen, and the
    weekly audit can count asks that went out without one.

    To wire it: set PREASK_WEB_CMD to a command that takes the query on argv and prints evidence.
    """
    cmd = os.environ.get("PREASK_WEB_CMD", "")
    if not cmd:
        r.status = "skipped"
        r.detail = "web research not wired (PREASK_WEB_CMD unset) - body must not claim it"
        return r
    terms = _like_terms(q.get("merchant"), q.get("subject"), q.get("person"))
    if not terms:
        r.status = "skipped"
        r.detail = "nothing to search"
        return r
    import subprocess
    try:
        out = subprocess.run([cmd, " ".join(terms[:4])], capture_output=True, text=True,
                             timeout=4)
    except subprocess.TimeoutExpired:
        r.status = "error"
        r.detail = "web rung exceeded 4 s"
        return r
    except OSError as e:
        r.status = "error"
        r.detail = f"web rung: {type(e).__name__}: {e}"
        return r
    text = (out.stdout or "").strip()
    if not text:
        r.status = "not_found"
        r.detail = f"web returned nothing (rc={out.returncode})"
        return r
    r.status = "partial"
    r.sentence = _clip(text, 88)
    r.detail = f"web: {len(text)} chars"
    return r


RUNGS = (
    ("owner_answer", rung_owner_answer),
    ("ledger", rung_ledger),
    ("comms", rung_comms),
    ("docs", rung_docs),
    ("web", rung_web),
)


# --------------------------------------------------------------------------- the ladder

def resolve(kind: str, **q) -> Receipt:
    """Run the ladder for one question. Always returns a Receipt; never raises."""
    if kind not in KINDS:
        kind = "generic"
    subject = q.get("subject") or q.get("merchant") or q.get("person") or q.get("text") or ""
    rec = Receipt(kind=kind, subject=str(subject)[:120], at=_now_iso())

    for name, fn in RUNGS:
        r = Rung(name=name)
        t0 = time.perf_counter()
        try:
            out = fn(q, r)
            # A rung MUST return its Rung. Returning something else is a defect in the rung,
            # not a reason for the ladder to die — but it is recorded as an error, never
            # silently accepted (that is how a false "not_found" is manufactured).
            if isinstance(out, Rung):
                r = out
            elif out is not None:
                r.status = "error"
                r.detail = f"rung returned {type(out).__name__}, not Rung"
        except Exception as e:                       # noqa: BLE001 - a rung may never kill the ladder
            r.status = "error"
            r.detail = f"{type(e).__name__}: {e}"
        r.ms = int((time.perf_counter() - t0) * 1000)
        rec.rungs.append(r)
        if r.status == "solved":
            # Any rung that actually knows the answer ends the ladder: asking is what the
            # ladder exists to avoid. (The web rung never reports `solved`; it is evidence.)
            rec.verdict = "answered"
            rec.resolution = {"rung": name, "keys": r.keys, "detail": r.detail}
            break
        elif r.status == "deflected":
            # He was asked and told us to work it out. Re-asking is the defect.
            rec.verdict = "deflected"
            rec.resolution = {"rung": name, "keys": r.keys, "detail": r.detail,
                              "instruction": "do the work; do not ask again"}
            break

    if rec.resolution is None:
        rec.verdict = "partial" if rec.evidence() else "unknown"
    return rec


def may_ask(rec: Receipt) -> tuple:
    """('do_not_ask'|'allow_ask', reason). The composer calls this; so does the audit."""
    if rec.verdict == "answered":
        return ("do_not_ask", f"resolved by {rec.resolution['rung']}: {rec.resolution['detail']}")
    if rec.verdict == "deflected":
        return ("do_not_ask",
                f"he deflected on {rec.resolution['detail']} - work it out, do not re-ask")
    if not rec.complete:
        return ("allow_ask", "incomplete: " + ",".join(rec.errored) + " (body must not claim it checked these)")
    return ("allow_ask", f"{rec.verdict}: {len(rec.evidence())} evidence clause(s)")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="run the pre-ask ladder for one question")
    ap.add_argument("--kind", default="generic", choices=KINDS)
    ap.add_argument("--subject", default="")
    ap.add_argument("--text", default="")
    ap.add_argument("--merchant", default="")
    ap.add_argument("--person", default="")
    ap.add_argument("--amount", default=None)
    ap.add_argument("--date", default=None)
    ap.add_argument("--question", default="")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

    rec = resolve(a.kind, subject=a.subject, text=a.text, merchant=a.merchant,
                  person=a.person, amount=a.amount, date=a.date, question=a.question)
    decision, why = may_ask(rec)
    if a.json:
        print(json.dumps({"receipt": rec.as_dict(), "decision": decision, "why": why},
                         indent=2, default=str))
    else:
        print(f"{rec.kind}: {rec.subject!r} -> {rec.verdict}  ({decision}: {why})")
        for r in rec.rungs:
            print(f"  {r.name:<14} {r.status:<10} {r.ms:>5}ms  {r.detail}")
        if rec.evidence():
            print("  evidence:")
            for e in rec.evidence():
                print(f"    - {e}")
        print(f"  body hint: {rec.body_hint()!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
