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

  To use a tool:   {"tool": "<name>", "args": {...}, "why": "one line"}
  To answer:       {"answer": "the text to send them", "evidence": "what you actually checked"}
  To give up:      {"blocked": "what stopped you"}

Rules:
  * Only `queue_lookup`-verified facts may appear in an answer. Never invent a price,
    a schedule, an order number or anything about Eliyahu's plans. If you could not
    find it, return {"blocked": "..."} - that is a good outcome, not a failure.
  * The answer is a text message: one to three short sentences, plain English, no
    markdown, no greeting. Do NOT add a signature - that is handled elsewhere.
  * Never commit Eliyahu to anything, never promise a time.
  * You are handling a PERSONAL message - family or a close friend - so be warm and
    human, not corporate.
  * If the job needs HIS money, his decision, or a commitment only he can make, return
    {"blocked": "needs the owner: <one line>"}.
"""


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


def _decode_json(raw: str | None) -> dict | None:
    if not raw:
        return None
    s = raw.strip()
    s = re.sub(r"^```(?:json)?\s*", "", s)
    s = re.sub(r"\s*```$", "", s)
    try:
        got = json.loads(s)
        return got if isinstance(got, dict) else None
    except Exception:
        pass
    depth, start = 0, None
    for i, ch in enumerate(s):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start is not None:
                try:
                    got = json.loads(s[start:i + 1])
                    if isinstance(got, dict):
                        return got
                except Exception:
                    start = None
    return None


# --------------------------------------------------------------------------- #
def do(claim: str, task: str, ctx: dict | None = None, *,
       deliverable: str = "a text back to them", timeout: int = DEFAULT_TIMEOUT,
       decider=None, llm=None) -> WorkResult:
    """Run a bounded investigation and come back with an answer or an honest block."""
    started = time.monotonic()
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
                return WorkResult(False, blocked=f"no model: decider unavailable ({exc})",
                                  evidence="textdecide could not be loaded")
        model = d.resolve_model()
        if not model:
            return WorkResult(False, blocked=f"no model: {d.last_error or 'catalog empty'}",
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

        if call is not None:
            raw = call(SYSTEM, conversation)
        else:
            try:
                raw = d.call(SYSTEM, conversation, max_tokens=400,
                             timeout=max(20, min(90, int(timeout - (time.monotonic() - started)))))
            except Exception as exc:
                raw = None
                notes.append(f"model call raised: {exc}")
        parsed = _decode_json(raw)

        if not parsed:
            if step == 1:
                # One retry: models sometimes wrap JSON in prose. A second failure is
                # a real failure, not something to paper over with a guess.
                conversation += ("\n\nYour last reply was not a JSON object. Reply with "
                                 "ONE JSON object and nothing else.")
                continue
            return WorkResult(False, blocked="the model returned no usable JSON",
                              steps=step, tools_used=tools_used, model=model,
                              evidence=_evidence(tools_used, notes),
                              elapsed_s=time.monotonic() - started)

        if parsed.get("answer"):
            answer = str(parsed["answer"]).strip()
            if len(answer) > 480:
                answer = answer[:470].rsplit(" ", 1)[0] + "..."
            # The model's own account of what it read is a CLAIM. The tools it
            # actually called are the PROOF, and both belong in the record - a
            # result whose evidence cannot be traced was the exact failure the
            # audit called out.
            claimed = str(parsed.get("evidence") or "").strip()
            real = _evidence(tools_used, notes)
            evidence = f"{claimed} | {real}" if claimed else real
            return WorkResult(True, answer=answer, evidence=evidence,
                              steps=step, tools_used=tools_used, model=model,
                              elapsed_s=time.monotonic() - started)

        if parsed.get("blocked"):
            reason = str(parsed["blocked"]).strip()[:400]
            return _blocked(reason, tools_used, notes, step, model, started, ctx, claim, task)

        tool = str(parsed.get("tool") or "").strip()
        if not tool:
            conversation += ("\n\nThat was neither a tool call nor an answer. Reply "
                             "with {'tool': ...} or {'answer': ...} or {'blocked': ...}.")
            continue
        # Priority matters: a job whose clock ran out reports a TIMEOUT even if it also
        # happened to spend its tool budget. Reporting the wrong limit sends the next
        # person looking in the wrong place (journal H609: a killed hop wearing a
        # network failure's name).
        if time.monotonic() - started > timeout:
            return WorkResult(False, blocked="timeout", steps=step,
                              tools_used=tools_used, model=model,
                              evidence=_evidence(tools_used, notes),
                              elapsed_s=time.monotonic() - started)

        if len(tools_used) >= MAX_TOOL_CALLS:
            return WorkResult(False, blocked=f"tool budget exhausted ({MAX_TOOL_CALLS})",
                              steps=step, tools_used=tools_used, model=model,
                              evidence=_evidence(tools_used, notes),
                              elapsed_s=time.monotonic() - started)

        ok, out = _invoke(tool, parsed.get("args") or {})
        tools_used.append(tool)
        notes.append(f"{tool}: {'ok' if ok else 'FAILED'}")
        conversation += (f"\n\n--- result of {tool} ---\n{out[:4000]}\n"
                         f"--- end {tool} ---\n"
                         f"Now either call another tool, or give the answer, or say blocked.")

    return WorkResult(False, blocked=f"no answer after {MAX_STEPS} steps",
                      steps=MAX_STEPS, tools_used=tools_used, model=model,
                      evidence=_evidence(tools_used, notes),
                      elapsed_s=time.monotonic() - started)


def _blocked(reason: str, tools_used, notes, steps, model, started, ctx, claim, task) -> WorkResult:
    """A block is a result. Decide whether it is a question for the owner or not."""
    escalated = None
    if re.search(r"needs the owner|his (decision|money|call)|commit", reason, re.I):
        phone = ctx.get("phone") or ""
        name = ((ctx.get("identity") or {}).get("name")) or phone
        escalated = {
            "question": f"{name} ({phone}) texted: {claim[:160]!r}. {reason[:200]}",
            "recommendation": "Tell me the answer and I will send it as a text.",
            "options": ["Send it as I say", "Draft it for me", "Leave it unanswered"],
        }
    return WorkResult(False, blocked=reason, escalated=escalated, steps=steps,
                      tools_used=tools_used, model=model,
                      evidence=_evidence(tools_used, notes),
                      elapsed_s=time.monotonic() - started)


def _evidence(tools_used, notes) -> str:
    if not tools_used:
        return "nothing was read"
    return f"read via: {', '.join(tools_used)}" + (
        f" ({'; '.join(notes[-4:])})" if notes else "")


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
