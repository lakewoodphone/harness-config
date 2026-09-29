#!/usr/bin/env python3
"""The texting responder, v2: read the inbox, understand who is talking, decide,
answer - or do the work and then answer.

Companion to `sms-inbox.py` (the sensor). That one guarantees the texts are *seen*;
this one decides what happens to each of them.

The owner's rule, 2026-09-18, unchanged:

    "...if you know what to respond and you're pretty sure you have permission
     for me to respond right away. If not, send it into the owner queue for
     something that needs attention."

What changed in v2 (see docs/ai-text-line-audit-2026-09-20.md for the evidence):

  * The line is PERSONAL - owner, family, close friends. Customers are Dialpad, and
    this system never touches them. (Owner, 2026-09-20.)
  * A text is never met with silence. `allow=queue` means *do not auto-send to this
    person*; it no longer means nobody ever answers them (finding B3).
  * The owner himself is answerable. The old ledger filed his own texts as `queue`,
    which is why he stopped using the line in May (finding B2).
  * "I'll look into it" is now real work with a follow-through reply, tracked in the
    `jobs` table so a promise cannot be lost (finding B4).
  * The decision sees real context - owner state, availability, contacts, thread,
    memory, open jobs - not just the ledger (findings B7, B8).
  * The model returns JSON, and a parse failure is never a reply (finding B9).

MODULES (each fails soft; a missing one degrades, never crashes):
    textstore.py    schema + every write to the store
    textctx.py      who is this, and what is going on
    textdecide.py   what should happen to this text
    textwork.py     actually do the thing
    textsend.py     get it to them, and know that it went
    (sms-inbox.py   the sensor)

USAGE
    python3 ~/bin/sms-responder.py pending            # what is waiting, and why
    python3 ~/bin/sms-responder.py run --dry-run      # decide, send nothing
    python3 ~/bin/sms-responder.py run --send --max-sends 1
    python3 ~/bin/sms-responder.py report             # does this thing work
    python3 ~/bin/sms-responder.py jobs               # open promises
    python3 ~/bin/sms-responder.py history --limit 20
    python3 ~/bin/sms-responder.py learn --apply
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
import os

HERE = Path(__file__).resolve().parent


def _load(name: str, filename: str):
    """Import a sibling module whose filename is not a valid identifier.

    Returns the module, or None when the file is absent - a missing module must
    degrade this responder, never stop it. The v2 modules land in stages.
    """
    path = HERE / filename
    if not path.exists():
        return None
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


inbox = _load("sms_inbox", "sms-inbox.py")
wake_mod = _load("wake_mod", "wake.py")
store = _load("textstore", "textstore.py")
ctx_mod = _load("textctx", "textctx.py")
decide_mod = _load("textdecide", "textdecide.py")
work_mod = _load("textwork", "textwork.py")
send_mod = _load("textsend", "textsend.py")

QUEUE = Path.home() / "bin" / "owner-queue.py"
OWNER_QUEUE_DEDUP_HOURS = 20


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def have(*mods) -> bool:
    return all(m is not None for m in mods)


# --------------------------------------------------------------------------- #
# Compatibility shims: each returns something safe when its module is missing,
# so a partially-deployed tree still behaves predictably instead of raising.
# --------------------------------------------------------------------------- #
def safe_resolve(conn, phone: str) -> dict:
    """The context, or a safe empty one.

    A partial answer is still an answer: if textctx returns a dict with a usable
    identity we take it as-is and only backfill keys it left out. Deciding "the
    module failed" because one optional field is absent is how a single missing
    table turns into a person we refuse to recognise.

    Observed 2026-09-20 in the smoke test: a store with no `awaited` table made
    textctx return identity.name=None while `permissions` held the name, and an
    `if got.get("identity")` test threw the good answer away.
    """
    fallback = {
        "phone": phone, "e164_ok": True,
        "identity": {"name": None, "relationship": "unknown", "confidence": 0.0,
                     "source": "none", "aliases": []},
        "allow": "queue", "known": False,
        "history": {"inbound": 0, "outbound": 0, "last_inbound": None,
                    "last_outbound": None, "days_since_contact": None,
                    "first_seen": None, "answered_share": None},
        "thread": [], "open_jobs": [], "open_owner_rows": [],
        "sources": {}, "warnings": ["textctx unavailable"], "as_of": now(),
    }
    if ctx_mod is None:
        return fallback
    try:
        got = ctx_mod.resolve(inbox.STORE, phone)
    except Exception as exc:
        fallback["warnings"].append(f"textctx.resolve raised: {exc}")
        return fallback
    if not isinstance(got, dict):
        fallback["warnings"].append("textctx.resolve returned a non-dict")
        return fallback
    for k, v in fallback.items():
        got.setdefault(k, v)
    if not isinstance(got.get("identity"), dict):
        got["identity"] = fallback["identity"]
    if "warnings" not in got or got["warnings"] is None:
        got["warnings"] = []
    return got


def safe_decide(text: str, ctx: dict) -> dict:
    if decide_mod is None:
        return {"action": "escalate", "text": None, "holding": None,
                "kind": "unknown", "urgency": "normal",
                "why": "textdecide unavailable", "confidence": 0.0, "needs_owner": True,
                "work": None, "escalation": None, "model": None}
    try:
        return decide_mod.choose(text, ctx)
    except Exception as exc:
        return {"action": "escalate", "text": None, "holding": None,
                "kind": "unknown", "urgency": "normal",
                "why": f"textdecide raised: {exc}", "confidence": 0.0, "needs_owner": True,
                "work": None, "escalation": None, "model": None}


def safe_can_send(phone: str, ctx: dict):
    if send_mod is None:
        return False, "textsend unavailable"
    try:
        return send_mod.can_send_to(phone, ctx, None)
    except Exception as exc:
        return False, f"gate raised: {exc}"


# ONE PLACE THAT COUNTS WHAT ACTUALLY LEFT. Measured 2026-09-29: `sent this run: 0` was
# printed by a run that answered the owner, because `sent` only increments in the non-owner
# classify branch. A counter that under-reports is the same defect as a log line that
# claims a send that did not happen.
_SENT_TOTAL = 0


def _count_send(res):
    """Count a send that really went, and only one that really went."""
    global _SENT_TOTAL
    if isinstance(res, dict) and res.get("ok") and not res.get("dry_run"):
        _SENT_TOTAL += 1
    return res


def safe_send(phone: str, body: str, dry_run: bool) -> dict:
    if send_mod is None:
        return {"ok": False, "sid": None, "channel": None, "dry_run": dry_run,
                "error": "textsend unavailable", "detail": ""}
    try:
        return _count_send(send_mod.send(phone, body, dry_run=dry_run))
    except Exception as exc:
        return {"ok": False, "sid": None, "channel": None, "dry_run": dry_run,
                "error": str(exc), "detail": ""}


def safe_notify(body: str, dry_run: bool) -> dict:
    if send_mod is None:
        return {"ok": False, "channel": "none", "dry_run": dry_run,
                "error": "textsend unavailable", "detail": ""}
    try:
        return send_mod.notify_owner(body, dry_run=dry_run)
    except Exception as exc:
        return {"ok": False, "channel": "none", "dry_run": dry_run,
                "error": str(exc), "detail": ""}


# --------------------------------------------------------------------------- #
# Owner queue - kept from v1, it is the one thing about v1 that worked.
# --------------------------------------------------------------------------- #
def _open_queue_row_for(phone: str) -> bool | None:
    """Is there already an unresolved owner-queue row about this person?

    Dedup against the QUEUE ITSELF, not against our own message state. Returns
    True (a row is open), False (none), or None when the queue could not be READ.
    None is not False: failing open on a read error would silently raise
    duplicates, and failing closed would silently drop a person's question. The
    caller raises the row anyway and marks it dedup-unverified, because a
    duplicate the owner can dismiss is far better than a text nobody answers.
    """
    tail = "".join(ch for ch in (phone or "") if ch.isdigit())[-10:]
    if not tail:
        return False
    try:
        c = sqlite3.connect(f"file:{inbox.APP_DB}?mode=ro", uri=True, timeout=20)
        rows = c.execute(
            "SELECT question FROM owner_decision_queue WHERE status='pending'").fetchall()
        c.close()
    except Exception as exc:
        print(f"    (could not read the queue for dedup: {exc}) - "
              "raising anyway, marked as unverified")
        return None
    for (q,) in rows:
        if tail in re.sub(r"\D", "", q or ""):
            return True
    return False


def queue_for_owner(conn, perm: dict, msg, why: str, suggested: str | None = None) -> bool:
    """Raise ONE owner-queue row for this correspondent, deduped by phone."""
    open_row = _open_queue_row_for(msg["from_number"])
    if open_row is True:
        print("    an owner-queue row for this person is already open - not raising again")
        return False
    if open_row is None:
        why = why + " (dedup could not be verified - the queue was unreadable)"
    name = perm.get("name") or msg["from_number"]
    question = (
        f"{name} ({msg['from_number']}) texted your AI line and I have not answered: "
        f"{(msg['body'] or '')[:160]!r}. Should I answer them, and may I answer this "
        f"person directly from now on?"
    )
    rec = ("Send the draft I prepared, if it reads right to you: " + suggested
           if suggested else
           "Tell me the one-line answer and I will send it, then set this person to a "
           "standing allow so the next text does not need you.")
    ctx = (f"Seen {msg['date_sent']}. Ledger says allow={perm.get('allow')} "
           f"relationship={perm.get('relationship')}. Reason I did not send it: {why}. "
           f"Full thread: python3 ~/bin/sms-inbox.py show {msg['from_number']}")
    cmd = ["python3", str(QUEUE), "add",
           "--question", question,
           "--recommendation", rec,
           "--options", "Send the draft as-is|Send it with my edits|Leave it unanswered",
           "--context", ctx,
           "--blocks", f"Answering {name} on the AI text line"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            print(f"    owner-queue add FAILED: {(r.stderr or r.stdout)[:200]}")
            return False
        print("    raised an owner-queue row")
        return True
    except Exception as exc:
        print(f"    owner-queue add raised {exc}")
        return False


# --------------------------------------------------------------------------- #
def ledger_view(ctx: dict, phone: str) -> dict:
    """The permission shape the queue code expects, taken from an ALREADY-RESOLVED
    context.

    Resolving twice per text would double every HTTP and DB read on a hot path
    that runs every five minutes; more importantly it could produce two different
    answers about the same person within one decision.
    """
    ident = (ctx or {}).get("identity") or {}
    return {"phone": phone,
            "name": ident.get("name"),
            "relationship": ident.get("relationship") or "unknown",
            "allow": (ctx or {}).get("allow") or "queue",
            "note": "via textctx"}


def permission_for(conn: sqlite3.Connection, phone: str) -> dict:
    """The ledger row, or the honest default. One definition, from textctx."""
    if ctx_mod is not None:
        try:
            return ledger_view(safe_resolve(conn, phone), phone)
        except Exception:
            pass
    tail = "".join(ch for ch in (phone or "") if ch.isdigit())[-10:]
    row = conn.execute(
        "SELECT * FROM permissions WHERE substr(replace(replace(replace(phone,'+',''),"
        "'-',''),' ',''),-10)=?", (tail,)).fetchone()
    if row:
        return dict(row)
    return {"phone": phone, "name": None, "relationship": "unknown",
            "allow": "queue", "note": "no ledger row - absence is not permission"}


def cheap_first(body: str, ctx: dict) -> str | None:
    """Free classification before any token is spent.

    Returns a terminal action ('ignore' | 'record') when the text plainly needs no
    model, else None. A mailbox full of "ok" and "thanks" must not cost a model
    call each - and a greeting from a friend must not be mistaken for noise.
    """
    if decide_mod is None or not hasattr(decide_mod, "classify_text"):
        return None
    try:
        c = decide_mod.classify_text(body, ctx)
    except Exception:
        return None
    kind = (c or {}).get("kind")
    if kind == "noise":
        return "ignore"
    if kind == "ack":
        # An acknowledgement from a real person does not need an answer, but it is
        # still recorded as seen - it is correspondence, not noise.
        return "record"
    return None



def thread_context(conn: sqlite3.Connection, phone: str, limit: int = 6) -> str:
    tail = "".join(ch for ch in (phone or "") if ch.isdigit())[-10:]
    rows = conn.execute(
        """SELECT direction, body, date_sent FROM messages
           WHERE from_number LIKE ? OR to_number LIKE ?
           ORDER BY date_sent DESC LIMIT ?""",
        (f"%{tail}", f"%{tail}", limit)).fetchall()
    out = []
    for r in reversed(rows):
        who = "them" if r["direction"] == "inbound" else "us"
        out.append(f"{who}: {(r['body'] or '')[:300]}")
    return "\n".join(out)


def worklist(conn: sqlite3.Connection, only: str | None, limit: int):
    """Inbound texts awaiting a decision, oldest first.

    NOT `ORDER BY date_sent`. That column is TEXT holding two shapes - Twilio's
    RFC-2822 ("Fri, 18 Sep 2026 03:29:39 +0000") next to the app's ISO - so SQL sorts
    it by weekday name and answers people in an order that is not chronological.
    Measured 2026-09-20: `MAX(date_sent)` on the live store returned "Wed, 29 Jul
    2026" while the true newest message was "Fri, 18 Sep 2026", making a 2-day-old
    store look 53 days stale. Sort the parsed value in Python instead.
    """
    from email.utils import parsedate_to_datetime

    def when(value):
        try:
            got = parsedate_to_datetime(value or "")
        except Exception:
            try:
                got = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
            except Exception:
                return datetime(1970, 1, 1, tzinfo=timezone.utc)
        if got is not None and got.tzinfo is None:
            got = got.replace(tzinfo=timezone.utc)
        return got or datetime(1970, 1, 1, tzinfo=timezone.utc)

    sql = "SELECT * FROM messages WHERE direction='inbound' AND state='new'"
    params: list = []
    if only:
        sql += " AND from_number LIKE ?"
        params.append(f"%{''.join(ch for ch in only if ch.isdigit())[-10:]}")
    rows = conn.execute(sql).fetchall()
    rows.sort(key=lambda r: when(r["date_sent"]))
    return rows[:limit]


def _record(conn, sid: str, state: str, by: str, reason: str,
            reply_sid: str | None = None) -> None:
    conn.execute(
        "UPDATE messages SET state=?, decided_by=?, decided_at=?, reason=?, reply_sid=? "
        "WHERE sid=?", (state, by, now(), reason[:400], reply_sid, sid))
    conn.commit()


# --------------------------------------------------------------------------- #
def cmd_pending(args) -> int:
    conn = inbox.connect()
    rows = worklist(conn, args.only, args.limit)
    print(f"{len(rows)} inbound text(s) awaiting a decision")
    for r in rows:
        perm = permission_for(conn, r["from_number"])
        print("  %-16s %-20s allow=%-6s %s"
              % (r["from_number"], perm.get("name") or "-", perm["allow"],
                 (r["body"] or "")[:60]))
    return 0


def _send_holding(r, ctx, text: str | None, args, label: str = "holding") -> None:
    """Tell the person something while their thing is being sorted out.

    One path for every branch that leaves a human waiting, so no branch can quietly do
    nothing: the gate decides whether it goes, and the gate is never bypassed here.
    """
    if not text:
        return
    allowed, why = safe_can_send(r["from_number"], ctx)
    if not allowed:
        print(f"    {label} withheld by the send gate: {why}")
        return
    if args.dry_run:
        print(f"    DRY-RUN - would send {label}: {text!r}")
        return
    res = safe_send(r["from_number"], text, dry_run=False)
    print(f"    {label} {'SENT' if res.get('ok') else 'FAILED'}: "
          f"{res.get('sid') or res.get('error')}")


def _do_work(conn, r, ctx: dict, decision: dict, args, name: str) -> None:
    """action=work: send the holding line, then actually do it and reply."""
    w = decision.get("work") or {}
    claim = (w.get("claim") or "look into it")[:300]
    task = w.get("task") or claim
    job_id = None
    if store is not None:
        try:
            job_id = store.open_job(conn, r["from_number"], r["sid"], claim, task)
        except Exception as exc:
            print(f"    could not open a job row: {exc}")

    holding = decision.get("holding")
    if holding and not args.dry_run:
        allowed, why = safe_can_send(r["from_number"], ctx)
        if allowed:
            res = safe_send(r["from_number"], holding, dry_run=False)
            print(f"    holding {'SENT' if res.get('ok') else 'FAILED'}: "
                  f"{res.get('sid') or res.get('error')}")
        else:
            print(f"    holding withheld by the send gate: {why}")
    elif holding:
        print(f"    DRY-RUN - would send holding: {holding!r}")

    if work_mod is None:
        print("    textwork unavailable - recording the promise, not resolving it")
        _record(conn, r["sid"], "working", "work",
                f"promise recorded; textwork missing. job={job_id}")
        return "no-worker"

    print(f"    working on it: {task[:100]}")
    try:
        result = work_mod.do(claim, task, ctx,
                             deliverable=w.get("deliverable") or "a text back to them")
    except Exception as exc:
        result = None
        print(f"    textwork raised: {exc}")

    ok = bool(getattr(result, "ok", False))
    answer = getattr(result, "answer", None)
    evidence = (getattr(result, "evidence", "") or "")[:800]
    blocked = getattr(result, "blocked", None)

    if ok and answer:
        allowed, why = safe_can_send(r["from_number"], ctx)
        if allowed:
            res = safe_send(r["from_number"], answer, dry_run=args.dry_run)
            print(f"    follow-through {'DRY-RUN' if args.dry_run else ('SENT' if res.get('ok') else 'FAILED')}: "
                  f"{res.get('sid') or res.get('error')}")
            _record(conn, r["sid"], "answered", "work",
                    f"worked then answered: {answer[:120]}", res.get("sid"))
            if store is not None and job_id:
                store.job_set(conn, job_id, state="done", answer=answer, evidence=evidence)
            return "answered"
        else:
            _record(conn, r["sid"], "working", "work", f"answer ready, gate closed: {why}")
            if store is not None and job_id:
                store.job_set(conn, job_id, state="done", answer=answer, evidence=evidence)
            queue_for_owner(conn, permission_for(conn, r["from_number"]), r,
                            f"I did the work but the send gate is closed ({why})",
                            suggested=answer)
            return "blocked"
    else:
        _record(conn, r["sid"], "blocked", "work", f"blocked: {blocked or 'no answer'}")
        if store is not None and job_id:
            store.job_set(conn, job_id, state="blocked", evidence=evidence,
                          answer=answer)
        esc = getattr(result, "escalated", None)
        if esc:
            try:
                subprocess.run(
                    ["python3", str(QUEUE), "add",
                     "--question", esc.get("question", claim),
                     "--recommendation", esc.get("recommendation", ""),
                     "--options", "|".join(esc.get("options") or []) or "Yes|No",
                     "--context", evidence or task,
                     "--blocks", f"{name} waiting on the AI text line"],
                    capture_output=True, text=True, timeout=120)
                print("    escalated to the owner queue")
            except Exception as exc:
                print(f"    escalation failed: {exc}")
        else:
            queue_for_owner(conn, permission_for(conn, r["from_number"]), r,
                            f"I could not resolve it: {blocked or 'no answer'}")
    return "blocked"


def _acquire_run_lock():
    """ONE responder run at a time. Returns (handle, None), (None, why_it_was_refused), or
    (False, why_it_is_UNGUARDED) - the last so a host without fcntl says so instead of
    pretending to be protected.

    The cron fires every 5 minutes, and a run that reaches the worker carries the tool loop
    (textwork.py: up to 3 model steps and up to 10 tool calls) which can outlast that interval.
    Measured 2026-09-29: an owner text routed through the worker no longer finishes inside a
    120-second window, and nothing here or in sms-inbox.py guarded against overlap, so two ticks
    could take the same row from the worklist and both answer it.
    """
    try:
        import fcntl
    except Exception:
        return (False, "fcntl unavailable on this host")
    try:
        fh = open(str(Path.home() / ".sms-inbox" / "sms-responder.lock"), "w")
    except Exception as exc:
        return (False, "cannot open the lock file (%s)" % type(exc).__name__)
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        try:
            fh.close()
        except Exception:
            pass
        return (None, "another responder run holds the lock")
    try:
        fh.write("%s\n" % datetime.now(timezone.utc).isoformat(timespec="seconds"))
        fh.flush()
    except Exception:
        pass
    return (fh, None)


def cmd_run(args) -> int:
    _lock, _lock_why = _acquire_run_lock()
    if _lock is None:
        print("  %s - skipping this tick; the cron comes round again in 5 minutes"
              % _lock_why)
        return 0
    if _lock is False:
        print("  WARNING: overlapping runs are NOT guarded: %s" % _lock_why)
    conn = inbox.connect()
    if store is not None:
        try:
            migrated = store.ensure_schema(conn)
            if migrated.get("created"):
                print(f"  migrated the store: created {migrated['created']}")
        except Exception as exc:
            print(f"  schema ensure failed: {exc}")

    rows = worklist(conn, args.only, args.limit)
    print(f"{len(rows)} to decide   mode={'SEND' if args.send else 'DRY-RUN'}"
          f"   modules={_module_banner()}")
    if not rows:
        return 0

    sent = 0
    for r in rows:
        body = r["body"] or ""
        # Resolve ONCE per text; the decision and the queue logic both read this.
        ctx = safe_resolve(conn, r["from_number"])
        perm = ledger_view(ctx, r["from_number"])
        name = perm.get("name") or r["from_number"]
        allow = perm["allow"]
        print(f"\n<{r['date_sent']}> {name} [{allow}]: {body[:90]!r}")

        # FIRST: is this the answer to something we asked for?
        if wake_mod is not None:
            try:
                aw = wake_mod.consume_await(conn, r["from_number"])
            except Exception:
                aw = None
            if aw:
                print(f"    this is the reply we were waiting for: {aw['what'][:70]}")
                prompt = (
                    f"{aw['name'] or r['from_number']} ({r['from_number']}) has just "
                    f"replied to a message we sent them from the AI line.\n\n"
                    f"DO THE WORK BELOW, AND THEN REPLY TO THE PERSON. A human is "
                    f"waiting on an answer; do not finish without sending one. Reply "
                    f"with:\n"
                    f"    python3 ~/bin/send-from-ai-line.py --to {r['from_number']} "
                    f"--body-file <file> --send\n"
                    f"Short, plain English, and signed '- Daniel' on its own last line.\n\n"
                    f"WORK: {aw['what']}\n\n"
                    f"Their reply: {body[:600]}\n\n"
                    f"Full thread: python3 ~/bin/sms-inbox.py show {r['from_number']}")
                filed = wake_mod._file_wake(
                    conn, subject=f"await:{r['from_number']}:{r['sid']}", prompt=prompt,
                    context=f"awaited since {aw['sent_at']}", kind="sms-await",
                    priority="high")
                print("    filed a wake row" if filed else "    wake row already filed")
                _record(conn, r["sid"], "woken", "await",
                        f"awaited reply -> wake: {aw['what'][:110]}")
                continue

        # ---------------------------------------------------------------------------
        # THE OWNER'S OWN TEXT IS A WORK ORDER.
        #
        # Added 2026-09-28. Before this, an owner text became at best an owner-queue row asking
        # him about himself - so he still had to open a session to get anything done. Now a
        # request or question from the owner files a real item in the work ledger and is tagged
        # with the message sid, so the text and the item point at each other.
        #
        # It runs BEFORE the classify/decide path because the classification costs a model call
        # and the ledger filing does not need one: "the owner asked for something" is not a
        # judgement call, it is a fact about the sender.
        # ---------------------------------------------------------------------------
        if allow == "auto" and _is_owner_number(perm, r["from_number"]):
            # TALK TO HIM WITH THE BRAIN. Owner, 2026-09-29: "i want to be talking to you, and you should be
            # the brain that is activated, not some hard coded automated stupid thing."
            #
            # This branch used to file the text as a work item and ask the next question WITHOUT EVER
            # CONSULTING THE MODEL, on the reasoning that "the owner asked for something is not a judgement
            # call, it is a fact about the sender". That is wrong: his message may be an ANSWER, a greeting,
            # a correction, a complaint or a request, and telling those apart is precisely the judgement a
            # model is for. Measured cost of getting it wrong: he answered five questions in plain English
            # and the system, unable to read any of it, filed each answer as new work and asked him something
            # else - a question loop produced by never understanding a word he said.
            #
            # So the judgement comes FIRST, with the conversation in context, and the filing happens after it
            # according to what he actually meant.
            _conv = _last_asked_and_open()
            ctx = dict(ctx or {})
            if _conv.get("last_asked"):
                ctx["last_asked"] = _conv["last_asked"]
            if _conv.get("asked_recently"):
                ctx["asked_recently"] = _conv["asked_recently"]
            if _conv.get("open_owner_rows"):
                ctx["open_owner_rows"] = _conv["open_owner_rows"]

            _decision = safe_decide(body, ctx)
            _action = _decision.get("action")
            print(f"    owner text -> the model says: {_action}  ({_decision.get('why')})")

            # THE FALLBACK STILL ANSWERS HIM. A model outage must never leave him with silence, so when the
            # decision is unusable we keep the old behaviour: file it and ask the next question.
            _usable = _action in ("record", "work", "reply", "escalate", "ignore") \
                and _decision.get("model") not in (None, "", "none")
            if not _usable:
                print("    no usable model decision - falling back to filing + next question")
                try:
                    filed = _file_owner_request(conn, r, body)
                except Exception as exc:
                    print(f"    owner-request filing failed: {type(exc).__name__}: {exc}")
                    filed = None
                if filed:
                    _record(conn, r["sid"], "working", "owner-request",
                            f"filed as ledger item {filed['project']}#{filed['id']}")
                _reply_with_top_question(conn, r["from_number"], dry_run=args.dry_run)
                continue

            # WHAT HE MEANT IS AN ANSWER: mark it down and close the question it answers.
            if _action == "record":
                _record(conn, r["sid"], "seen", "model",
                        _decision.get("why") or "the model read this as an answer or acknowledgement")
                try:
                    _close_what_he_answered(conn, body, _decision)
                except Exception as exc:
                    print(f"    answer-close failed: {type(exc).__name__}: {exc}")
                # He answered - do NOT immediately ask the next question. A conversation is not an
                # interrogation, and he has said plainly that one question at a time is what he wants.
                _maybe_ask_one(conn, r["from_number"], after_answer=True, dry_run=args.dry_run)
                continue

            if _action == "reply":
                _text = (_decision.get("text") or "").strip()
                if _text:
                    try:
                        import importlib.util as _il
                        _spec = _il.spec_from_file_location(
                            "textsend", str(Path.home() / "bin" / "textsend.py"))
                        _ts = _il.module_from_spec(_spec)
                        _spec.loader.exec_module(_ts)
                        _ts.send(r["from_number"], _text, dry_run=args.dry_run)
                        print(f"    replied from the brain: {_text[:70]!r}")
                    except Exception as exc:
                        print(f"    brain reply failed to send: {type(exc).__name__}: {exc}")
                _record(conn, r["sid"], "answered", "model", _decision.get("why") or "replied")
                continue

            if _action == "ignore":
                _record(conn, r["sid"], "ignored", "model", _decision.get("why") or "nothing to do")
                continue

            # "work" and "escalate" both keep the item: a request is still a request, and something needing
            # him is still work. Filing happens HERE, after the judgement rather than instead of it.
            try:
                filed = _file_owner_request(conn, r, body)
            except Exception as exc:
                print(f"    owner-request filing failed: {type(exc).__name__}: {exc}")
                filed = None
            if filed:
                print(f"    filed as ledger item {filed['project']}#{filed['id']}")
                _record(conn, r["sid"], "working", "model",
                        f"filed as ledger item {filed['project']}#{filed['id']}")
            # HE ENGAGED, AND THE INVARIANT IS EXACTLY ONE OUTBOUND: the answer, or one
            # question. Never zero (his 03:20:01Z text produced none while 32 questions sat
            # pending and only 5 had ever been put to him by text), and never two.
            if _action == "work":
                # THE BRAIN, FOR HIM TOO. His own words, quoted above the owner fast path:
                # "i want to be talking to you, and you should be the brain that is activated,
                # not some hard coded automated stupid thing." The ledger item is filed FIRST
                # so a failed loop loses nothing, and the holding receipt is dropped because a
                # receipt is what he called pointless on 2026-09-28.
                _brain_decision = dict(_decision)
                _brain_decision["holding"] = None
                _outcome = _do_work(conn, r, ctx, _brain_decision, args, name)
                if _outcome != "answered":
                    _maybe_ask_one(conn, r["from_number"], after_answer=False,
                                   dry_run=args.dry_run)
                continue
            # escalate: the question IS the outbound, so ask exactly one.
            _maybe_ask_one(conn, r["from_number"], after_answer=False, dry_run=args.dry_run)
            continue


        # ---------------------------------------------------------------------------
        # KEEP THE THREAD: record what we owe him and match his reply to it.
        #
        # Owner, 2026-09-28: "you have to really try to monitor that thread for when I respond and
        # what you last sent out." A request from him that produced a ledger item is a PROMISE, and
        # `jobs` is this store's record of promises (phone, claim, answer, state, evidence). Closing
        # the oldest open job for his number with his own words is what turns a pile of texts into a
        # conversation a future reader can follow.
        # ---------------------------------------------------------------------------
        if _is_owner_number(perm, r["from_number"]):
            try:
                _track_owner_thread(conn, r, body)
            except Exception as exc:
                print(f"    owner thread tracking failed: {type(exc).__name__}: {exc}")

        if allow == "never":
            print("    never - recorded, not answered")
            conn.execute("UPDATE messages SET state='ignored', decided_by='policy', "
                         "decided_at=?, reason='allow=never' WHERE sid=?",
                         (now(), r["sid"]))
            conn.commit()
            continue

        # Free classification first. Neither "ok" nor a machine shortcode may cost
        # a model call - this line carries a 5-minute clock. `ctx` was resolved
        # once at the top of this iteration.
        terminal = cheap_first(body, ctx)
        if terminal == "ignore":
            print("    cheap classify: noise - recorded, not answered")
            _record(conn, r["sid"], "ignored", "classify", "noise (no model call spent)")
            continue
        if terminal == "record":
            print("    cheap classify: an acknowledgement - recorded as seen")
            _record(conn, r["sid"], "seen", "classify", "ack (no model call spent)")
            continue

        decision = safe_decide(body, ctx)
        action = decision.get("action")
        print(f"    verdict: {action}  ({decision.get('why')})")

        if action == "ignore":
            _record(conn, r["sid"], "ignored", "decide", decision.get("why") or "ignore")
            continue

        if action == "record":
            _record(conn, r["sid"], "seen", "decide", decision.get("why") or "record")
            continue

        if action == "reply":
            text = decision.get("text") or ""
            allowed, why = safe_can_send(r["from_number"], ctx)
            if not allowed:
                print(f"    send gate closed ({why}) - drafting for the owner instead")
                _record(conn, r["sid"], "queued", "policy", f"gate closed: {why}")
                queue_for_owner(conn, perm, r, why, suggested=text)
                continue
            if args.dry_run:
                print(f"    DRY-RUN - would send: {text!r}")
                _record(conn, r["sid"], "answered", "decide",
                        f"dry-run reply: {text[:120]}")
                continue
            if sent >= args.max_sends:
                print(f"    send cap ({args.max_sends}) reached - next run")
                continue
            res = safe_send(r["from_number"], text, dry_run=False)
            print(f"    {'SENT' if res.get('ok') else 'SEND FAILED'}: "
                  f"{res.get('sid') or res.get('error')}")
            if not res.get("ok"):
                _record(conn, r["sid"], "new", "decide", f"send failed: {res.get('error')}")
                continue
            sent += 1
            _record(conn, r["sid"], "answered", "decide", f"reply: {text[:120]}",
                    reply_sid=res.get("sid"))
            continue

        if action == "work":
            _do_work(conn, r, ctx, decision, args, name)
            continue

        # escalate (the default and the safest)
        esc = decision.get("escalation") or {}
        _record(conn, r["sid"], "queued", "decide", decision.get("why") or "escalate")
        # A real person is told something. Escalating to the owner while leaving the
        # sender in silence is the exact failure this rebuild exists to remove - the
        # owner's father was told nothing for 11 days after he reported our own mistake
        # (journal P2123, lesson L2099).
        holding = decision.get("holding")
        if holding:
            _send_holding(r, ctx, holding, args)

            print("    DRY-RUN - would raise an owner-queue row")
            continue
        queue_for_owner(conn, perm, r, decision.get("why") or "needs the owner",
                        suggested=decision.get("text") or esc.get("recommendation"))

    print(f"\nsent this run: {_SENT_TOTAL}")
    if _SENT_TOTAL != sent:
        print(f"  (the per-branch counter says {sent}; it only increments in the non-owner"
              f" classify branch, so {_SENT_TOTAL} is what actually left)")
    return 0


def _module_banner() -> str:
    names = [("store", store), ("ctx", ctx_mod), ("decide", decide_mod),
             ("work", work_mod), ("send", send_mod)]
    return " ".join(f"{n}={'ok' if m else 'MISSING'}" for n, m in names)


def cmd_jobs(args) -> int:
    conn = inbox.connect()
    if store is None:
        # A missing module is a degraded deployment, not an error: say so and exit 0
        # so a cron run never looks like a crash when the tree is only part-deployed.
        print("textstore unavailable - no job tracking in this deployment")
        return 0
    try:
        store.ensure_schema(conn)
    except Exception:
        pass
    rows = store.jobs_open(conn)
    print(f"{len(rows)} open job(s)")
    for r in rows:
        print("  #%-4s %-16s %-9s %s  %s"
              % (r["id"], r["phone"], r["state"], (r["created_at"] or "")[:16],
                 (r["claim"] or "")[:70]))
    return 0


def cmd_report(args) -> int:
    """Does this thing work? Self-report, so silence is never mistaken for health."""
    conn = inbox.connect()
    print(f"== AI text line: {' '.join(_module_banner().split())} ==")
    print(f"  as of            {now()}")

    q = "SELECT COUNT(*) FROM messages WHERE direction='inbound'"
    total = conn.execute(q).fetchone()[0]
    undecided = conn.execute(
        "SELECT COUNT(*) FROM messages WHERE direction='inbound' AND state='new'"
    ).fetchone()[0]
    print(f"  inbound held     {total}")
    print(f"  awaiting a decision  {undecided}")

    print("\n  replies actually sent, by who decided:")
    for row in conn.execute(
        "SELECT decided_by, COUNT(*) FROM messages WHERE direction='inbound' "
        "AND state IN ('answered','working','woken') GROUP BY decided_by"):
        print(f"    {row[0] or '-':<12} {row[1]}")

    print("\n  people waiting on us (inbound, no reply after it):")
    lastout = _last_outbound_by_phone(conn)
    waiting = []
    for r in conn.execute("SELECT from_number, date_sent, body, state FROM messages "
                          "WHERE direction='inbound'"):
        t = "".join(ch for ch in (r["from_number"] or "") if ch.isdigit())[-10:]
        if not t:
            continue
        # Our own plumbing is not a person waiting. `probe` excludes it for the same
        # reason - counting test traffic as correspondence is how a health number
        # stops meaning anything.
        if getattr(inbox, "is_test_traffic", None) and \
                inbox.is_test_traffic(r["from_number"], r["body"]):
            continue
        mine = _when(r["date_sent"])
        theirs = lastout.get(t)
        if theirs is not None and mine is not None and theirs >= mine:
            continue
        # Not answered by v1 either? v1 wrote outbound to the app's sms_log, so a
        # person whose last text was answered that way is NOT waiting. Counting them
        # as waiting would make this number useless, and this number is the whole
        # point of the report.
        if _answered_in_app(t):
            continue
        waiting.append((mine, t, (r["body"] or "")[:50], r["state"]))
    waiting.sort(key=lambda x: (x[0] is None, x[0]))
    for d, t, b, s in waiting[-12:]:
        print(f"    {d.isoformat()[:16] if d else '?':<17} {t:<12} [{s}] {b!r}")
    print(f"  => {len(waiting)} inbound text(s) with no reply recorded anywhere")


def _when(value):
    """Parse a stored date. `date_sent` mixes RFC-2822 and ISO, so never compare it
    as text (see journal L2123)."""
    if not value:
        return None
    from email.utils import parsedate_to_datetime
    try:
        got = parsedate_to_datetime(value)
    except Exception:
        try:
            got = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except Exception:
            return None
    if got is not None and got.tzinfo is None:
        got = got.replace(tzinfo=timezone.utc)
    return got


def _last_outbound_by_phone(conn) -> dict:
    out: dict = {}
    for r in conn.execute("SELECT to_number, date_sent FROM messages WHERE direction='outbound'"):
        t = "".join(ch for ch in (r["to_number"] or "") if ch.isdigit())[-10:]
        got = _when(r["date_sent"])
        if t and got and (t not in out or got > out[t]):
            out[t] = got
    return out


def _answered_in_app(tail10: str) -> bool:
    """Has the app ever sent an outbound SMS to this number? v1's answered texts live
    in `sms_log`, not in the store, so the store alone cannot tell."""
    try:
        c = sqlite3.connect(f"file:{inbox.APP_DB}?mode=ro", uri=True, timeout=15)
        row = c.execute(
            "SELECT 1 FROM sms_log WHERE direction='outbound' "
            "AND substr(replace(replace(replace(to_number,'+',''),'-',''),' ',''),-10)=? "
            "LIMIT 1", (tail10,)).fetchone()
        c.close()
        return row is not None
    except Exception:
        # Unknown is not "waiting": claiming someone is waiting when we cannot check
        # would make this report cry wolf, which is how a real alert stops being read.
        return True


    if store is not None:
        try:
            store.ensure_schema(conn)
            print("\n  open promises (jobs):")
            for r in store.jobs_open(conn):
                print(f"    #{r['id']} {r['phone']} [{r['state']}] "
                      f"{(r['claim'] or '')[:60]}  since {(r['created_at'] or '')[:16]}")
            swept = store.job_sweep(conn)
            if swept.get("requeued") or swept.get("blocked"):
                print(f"    swept: requeued={swept['requeued']} blocked={swept['blocked']}")
        except Exception as exc:
            print(f"  job read failed: {exc}")

    print("\n  ledger:")
    for r in conn.execute("SELECT allow, COUNT(*) FROM permissions GROUP BY allow"):
        print(f"    allow={r[0]:<6} {r[1]}")

    print("\n  last real inbound:")
    rows = conn.execute("SELECT from_number, date_sent, body FROM messages "
                        "WHERE direction='inbound' ORDER BY first_seen DESC LIMIT 1").fetchall()
    for r in rows:
        print(f"    {r['date_sent']}  {r['from_number']}  {(r['body'] or '')[:60]!r}")
    print("  (a healthy line has a recent real inbound; silence here is the thing to check first)")
    return 0


def cmd_history(args) -> int:
    conn = inbox.connect()
    rows = conn.execute(
        "SELECT * FROM messages WHERE direction='inbound' AND state!='new' "
        "ORDER BY decided_at DESC LIMIT ?", (args.limit,)).fetchall()
    print(f"{len(rows)} decided text(s)")
    for r in rows:
        print("  %-16s %-8s %-9s %s"
              % (r["from_number"], r["state"], r["decided_by"] or "-",
                 (r["reason"] or "")[:70]))
    return 0


POSITIVE = re.compile(
    r"\b(send|sent|answer|answered|yes|yeah|yep|ok|okay|sure|go ahead|do it|"
    r"fine|approved?|allow|permission)\b", re.I)
NEGATIVE = re.compile(
    r"\b(no|nope|don'?t|do not|leave it|stop|never|drop it|ignore|deny|refuse)\b", re.I)


def _queue_rows(done: set[int]):
    try:
        c = sqlite3.connect(f"file:{inbox.APP_DB}?mode=ro", uri=True, timeout=20)
        c.row_factory = sqlite3.Row
        rows = c.execute(
            """SELECT id, question, answer, status FROM owner_decision_queue
               WHERE answer IS NOT NULL AND answer != ''
                 AND question LIKE '%texted your AI line%'
               ORDER BY id""").fetchall()
        c.close()
        return [r for r in rows if r["id"] not in done]
    except Exception as exc:
        print(f"  (owner queue unreadable: {exc})", file=sys.stderr)
        return []


def cmd_learn(args) -> int:
    """Turn the owner's ANSWERS into standing ledger rows.

    Only on an UNAMBIGUOUS answer - one matching a positive or a negative pattern
    and not both. Guessing at a permission is how you send a message the owner
    would not have sent.
    """
    conn = inbox.connect()
    conn.executescript(
        """CREATE TABLE IF NOT EXISTS learned (
               question_id INTEGER PRIMARY KEY,
               phone       TEXT,
               allow       TEXT,
               learned_at  TEXT)""")
    done = {r["question_id"] for r in conn.execute("SELECT question_id FROM learned")}
    rows = _queue_rows(done)
    if not rows:
        print("nothing new to learn from")
        return 0

    changed = 0
    for r in rows:
        m = re.search(r"\+1\d{10}", r["question"] or "")
        if not m:
            print(f"  #{r['id']}: no phone in the question - skipped")
            continue
        phone = m.group(0)
        answer = (r["answer"] or "").strip()
        pos, neg = bool(POSITIVE.search(answer)), bool(NEGATIVE.search(answer))
        if pos == neg:
            print(f"  #{r['id']} {phone}: AMBIGUOUS, left alone -> {answer[:90]!r}")
            continue
        allow = "auto" if pos else "never"
        got = conn.execute(
            "SELECT name FROM permissions"
            " WHERE substr(replace(phone,'+',''),-10)=substr(?,-10)", (phone,)).fetchone()
        label = (got["name"] if got and got["name"] else phone)
        print(f"  #{r['id']} {phone} ({label}): -> allow={allow}   from {answer[:70]!r}")
        if args.apply:
            conn.execute(
                """INSERT INTO permissions
                     (phone,name,relationship,allow,note,learned_from,updated_at)
                   VALUES(?,?,'unknown',?,?,?,?)
                   ON CONFLICT(phone) DO UPDATE SET allow=excluded.allow,
                     note=excluded.note, learned_from=excluded.learned_from,
                     updated_at=excluded.updated_at""",
                (phone, label, allow,
                 f"learned from owner-queue #{r['id']}: {answer[:180]}",
                 f"owner-answer #{r['id']}", now()))
            conn.execute(
                "INSERT OR REPLACE INTO learned(question_id,phone,allow,learned_at)"
                " VALUES(?,?,?,?)", (r["id"], phone, allow, now()))
            changed += 1
    conn.commit()
    print(f"\n{'applied' if args.apply else 'would apply'}: {changed} ledger change(s)")
    if not args.apply:
        print("(re-run with --apply to write them)")
    return 0



# --------------------------------------------------------------------------- #
# THE OWNER'S TEXTS BECOME LEDGER ITEMS
# --------------------------------------------------------------------------- #
WORK_CLI = os.environ.get("WORK_CLI") or str(Path.home() / "bin" / "work.py")


def _is_owner_number(perm: dict, phone: str) -> bool:
    """True only for the owner's own numbers. Both sources are deliberate: the ledger's
    relationship, and OWNER_PHONE_NUMBER. A context that merely SAYS 'owner' is not trusted."""
    if (perm.get("relationship") or "").lower().startswith("owner"):
        return True
    env_owner = os.environ.get("OWNER_PHONE_NUMBER")
    if env_owner:
        strip = lambda s: re.sub(r"\D", "", s or "")[-10:]  # noqa: E731
        if strip(env_owner) and strip(env_owner) == strip(phone):
            return True
    return False


def _guess_project(body: str) -> tuple:
    """(project_id, why). A text may name its own project; otherwise the honest default is the
    project that owns housekeeping, and the reason says so rather than implying a guess was a fact."""
    b = (body or "").lower()
    named = [
        (("website", "lpt website", "www", "portal", "storefront", "homepage"), "lpt-website"),
        (("filter", "kosher", "content filter", "blocking"), "kosher-ai-filter"),
        (("sync", "dialpad", "hub", "production db", "database"), "lpt-sync"),
        (("cfo", "quickbooks", "books", "invoice", "payroll"), "cfo"),
        (("personality",), "personality-system"),
        (("rental", "rent"), "rental-system"),
        (("bible", "chumash", "codes"), "chumash"),
    ]
    # WORD-BOUNDARY MATCH, NOT SUBSTRING. Measured 2026-09-29 (housekeeping #95): the bare
    # substring 'hub' matched inside 'GitHub' and filed a conversational owner text as an
    # lpt-sync work order. A keyword names a project only as a whole word, so 'sync' still
    # matches 'dialpad sync broken' and 'lpt-sync', but 'hub' no longer matches 'GitHub'.
    for words, pid in named:
        for w in words:
            if re.search(r"(?<![0-9a-z])" + re.escape(w) + r"(?![0-9a-z])", b):
                return pid, f"the text names '{w}'"
    return "housekeeping", "no project was named in the text, so it defaults to housekeeping"


def _one_line(s: str, n: int = 140) -> str:
    return " ".join((s or "").split())[:n]


# ---------------------------------------------------------------------------
# IS THIS A QUESTION OR A REQUEST AT ALL?
#
# Measured 2026-09-29 (housekeeping #95): the model-outage fallback called _file_owner_request
# with every owner text and it filed ALL of them as work. A conversational remark - "It's
# probably a no reply ... the GitHub token depends who uses the token and what it's for ... you
# did not have to bring that to my attention." - became an lpt-sync work order. Filing is for a
# question or a request; a remark is neither. The gate is explicit on purpose: a wrong 'yes'
# costs a shift doing imaginary work, a wrong 'no' only means we ask him instead of guessing.
# A defect report ("dialpad sync broken") is an implicit request to fix it and still files.
# ---------------------------------------------------------------------------
_ASK_PATTERNS = (
    "please", "can you", "could you", "would you", "will you",
    "i need", "i want", "we need", "make sure", "be sure",
    "don't forget", "do not forget", "remind me", "let me know",
    "take care of", "look into", "follow up", "figure out", "find out",
    "is there", "are there", "do we", "does the", "did you", "have you",
    "can we", "how do", "how can", "why is", "why are", "why did",
    "why does", "when will", "where is", "who is",
)
_ASK_VERBS = (
    "check", "fix", "add", "send", "call", "schedule", "cancel", "book",
    "update", "change", "remove", "delete", "create", "handle", "investigate",
    "review", "confirm", "verify", "text", "email", "remind", "build",
    "install", "repair", "move", "copy", "backup", "restore", "test", "run",
    "start", "stop", "open", "close", "pay",
)
_DEFECT_WORDS = (
    "broken", "broke", "down", "failed", "failing", "failure", "error",
    "bug", "crash", "crashed", "not working", "doesn't work", "does not work",
    "stopped", "outage", "stuck", "missing", "frozen", "hung",
)


def _word_in(needle: str, hay: str) -> bool:
    return bool(re.search(r"(?<![0-9a-z])" + re.escape(needle) + r"(?![0-9a-z])", hay))


def _looks_like_request(body: str) -> bool:
    """True only when the text is a question, an ask, or a defect report - not conversation."""
    t = (body or "").strip()
    if not t:
        return False
    if "?" in t:
        return True
    low = t.lower()
    for pat in _ASK_PATTERNS:
        if _word_in(pat, low):
            return True
    for d in _DEFECT_WORDS:
        if d in low:
            return True
    first = re.match(r"\s*([a-z']+)", low)
    if first and first.group(1) in _ASK_VERBS:
        return True
    return False


def _file_owner_request(conn, row, body: str) -> dict | None:
    """File the owner's request as a ledger item. Returns {'id':..,'project':..} or None.

    DEDUPE IS THE LEDGER'S JOB, not this function's: `work.py add` refuses a second open item with
    the same title and returns the existing id, which is exactly the "don't do the same work twice"
    guard the owner asked for. So a repeated text does not create a second shift.
    """
    text = _one_line(body, 200)
    if len(text) < 8:
        return None                      # "ok", "?" and similar are conversation, not work
    if not _looks_like_request(body):
        # Measured 2026-09-29 (housekeeping #95): this used to file ANY text over 8 chars, and
        # a conversational remark ("...the GitHub token depends who uses the token...") became
        # an lpt-sync work order. Filing is for a question or a request; a remark is neither.
        return None
    project, why = _guess_project(body)
    title = "owner asked by text: %s" % text
    dod = ("the requester's question is answered with evidence - quote the command, the file or "
           "the source that settles it - and the answer is written back to the ledger item")
    cmd = ["python3", WORK_CLI, "add",
           "--project", project, "--title", title, "--dod", dod,
           "--why", "%s (message %s from %s at %s)" % (why, row["sid"], row["from_number"], row["date_sent"]),
           # PRIORITY 1, NOT 3. Measured 2026-09-28: with 3, the owner's own 15:57 text was still unclaimed
           # seven hours later, behind #8 (p0), #54 and #65 (p1) and a queue of p2 project items - so his
           # request changed nothing while the log looked like a response. He noticed and said "nothing
           # responded". An owner request outranks every project and integration item; only the SMS channel's
           # own repair sits above it. Do not lower this without a measurement.
           "--priority", "1", "--source", "owner-sms"]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    out = (p.stdout or "").strip()
    m = re.search(r'"(?:id|item)":\s*(\d+)', out)
    if not m:
        print("    work.py add said: %s" % (out[:160] or p.stderr[:160]))
        return None
    return {"id": int(m.group(1)), "project": project, "already": "already-filed" in out}



def _track_owner_thread(conn, row, body: str) -> None:
    """Close the oldest open promise for this phone with his reply, or open one from a request.

    NEVER raises into the caller: this is bookkeeping around the conversation, and a bookkeeping
    failure must not stop a tick that has real work to do.
    """
    try:
        cols = {c[1] for c in conn.execute("PRAGMA table_info(jobs)").fetchall()}
    except Exception:
        return                                  # no jobs table: nothing to track, not an error
    if not cols:
        return
    now = datetime.now(timezone.utc).isoformat()
    phone = row["from_number"]
    try:
        open_job = conn.execute(
            "SELECT id, claim FROM jobs WHERE phone=? AND state IN ('open','running') "
            "ORDER BY id LIMIT 1", (phone,)).fetchone()
        # A short reply to an open promise is his ANSWER. A long one is new material.
        if open_job and len((body or "").split()) <= 40:
            conn.execute("UPDATE jobs SET state='done', answer=?, updated_at=?, "
                         "evidence=coalesce(evidence,'') || ? WHERE id=?",
                         (body[:600], now,
                          "\n[closed by inbound %s at %s]" % (row["sid"], row["date_sent"]),
                          open_job[0]))
            conn.commit()
            print("    closed promise #%s with his reply" % open_job[0])
            return
        # Otherwise, if this text produced work, open a promise for it.
        if len((body or "").strip()) >= 8:
            claim = "answer this: %s" % " ".join((body or "").split())[:180]
            conn.execute(
                "INSERT INTO jobs(phone, inbound_sid, claim, state, created_at, updated_at) "
                "VALUES(?,?,?,'open',?,?)",
                (phone, row["sid"], claim, now, now))
            conn.commit()
            print("    opened a promise for his request")
    except Exception as exc:
        print("    thread bookkeeping skipped: %s: %s" % (type(exc).__name__, exc))



def _offered_conn():
    """The record of what we have already put to the owner by text. A store WE own."""
    import sqlite3 as _s
    p = Path.home() / ".sms-inbox" / "offered.db"
    c = _s.connect(str(p), timeout=10)
    c.execute("CREATE TABLE IF NOT EXISTS offered ("
              "queue_id INTEGER PRIMARY KEY, body TEXT, offered_at TEXT)")
    return c


def _already_offered(queue_id) -> bool:
    """True if this question was put to him within the re-ask window. Unreadable store -> False (ask)."""
    try:
        c = _offered_conn()
        row = c.execute("SELECT offered_at FROM offered WHERE queue_id=?", (int(queue_id),)).fetchone()
        c.close()
        if not row or not row[0]:
            return False
        when = datetime.fromisoformat(str(row[0]).replace("Z", "+00:00"))
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        age_days = (datetime.now(timezone.utc) - when).total_seconds() / 86400.0
        return age_days < 7
    except Exception as exc:
        print(f"    (offered-store read failed, will ask: {type(exc).__name__})")
        return False


def _record_offered(queue_id, body) -> None:
    """Record that this question went out. Unstampable here would mean it repeats - so print loudly."""
    try:
        c = _offered_conn()
        c.execute("INSERT INTO offered (queue_id, body, offered_at) VALUES (?,?,?) "
                  "ON CONFLICT(queue_id) DO UPDATE SET body=excluded.body, offered_at=excluded.offered_at",
                  (int(queue_id), (body or "")[:500],
                   datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")))
        c.commit()
        got = c.execute("SELECT offered_at FROM offered WHERE queue_id=?", (int(queue_id),)).fetchone()
        c.close()
        if not got:
            print("    WARNING: could not record the ask - this question WILL repeat")
        else:
            print(f"    recorded as offered ({got[0]}); will not re-ask for 7 days")
    except Exception as exc:
        print(f"    WARNING: could not record the ask ({type(exc).__name__}: {exc}) - it WILL repeat")


def _last_asked_and_open() -> dict:
    """What we most recently asked him, and what is still open. Feeds the model's context.

    Reads `~/.sms-inbox/offered.db` - the store WE own - because the owner queue is write-blocked by the
    app's 13 GB handle and columns there cannot be relied on. Read-only and failure-tolerant: an unreadable
    store simply means the model gets less context, never an error.
    """
    out = {"last_asked": None, "asked_recently": []}
    try:
        import sqlite3 as _s, json as _j, subprocess as _sp
        c = _s.connect(str(Path.home() / ".sms-inbox" / "offered.db"), timeout=10)
        c.row_factory = _s.Row
        rows = [dict(r) for r in c.execute(
            "select queue_id, body, offered_at from offered order by offered_at desc limit 5")]
        c.close()
        if rows:
            out["last_asked"] = {"queue_id": rows[0]["queue_id"],
                                 "what_we_asked": (rows[0]["body"] or "")[:400],
                                 "when": rows[0]["offered_at"]}
            out["asked_recently"] = [{"queue_id": r["queue_id"],
                                      "asked": (r["body"] or "")[:200],
                                      "when": r["offered_at"]} for r in rows]
        # and the still-open questions themselves, so the model can match an answer to one of them
        try:
            raw = _sp.run(["python3", str(Path.home() / "bin" / "owner-queue.py"), "list", "--json"],
                          capture_output=True, text=True, timeout=90).stdout
            q = _j.loads(raw or "[]")
            q = q if isinstance(q, list) else (q.get("rows") or q.get("items") or [])
            pend = [{"id": x.get("id"), "question": (x.get("question") or "")[:220]}
                    for x in q if str(x.get("status")) == "pending"][:12]
            out["open_owner_rows"] = pend
        except Exception:
            pass
    except Exception as exc:
        out["error"] = "%s: %s" % (type(exc).__name__, exc)
    return out


def _close_what_he_answered(conn, body: str, decision: dict) -> None:
    """Mark down his answer and close the question it answers - in the ledger, which we can always write."""
    import json as _j, subprocess as _sp
    text = " ".join((body or "").split())
    info = _last_asked_and_open()
    last = info.get("last_asked") or {}
    # The model was given `last_asked` and the open rows. Prefer the row it names; otherwise the most recent
    # ask, because in a one-question-at-a-time conversation the answer follows the question.
    rid = None
    m = re.search(r"\b(?:queue\s*#?|#)(\d{2,5})\b", str(decision.get("why") or "") + " " + text)
    if m:
        rid = int(m.group(1))
    if rid is None and last.get("queue_id") is not None:
        rid = int(last["queue_id"])
    if rid is None:
        print("    the model recorded something but named no question - nothing to close")
        return
    did = ("The owner ANSWERED queue #%s by text. His words: %r" % (rid, text[:560]))
    proof = ("his inbound text from +18483897895; the model read it as an answer (%s)"
             % (decision.get("why") or "no reason given"))
    left = ("Act on what he said, and resolve queue #%s once the write lock frees. An answer is an "
            "instruction, not a closed ticket." % rid)
    try:
        _sp.run(["python3", str(Path.home() / "bin" / "work.py"), "add", "--project", "housekeeping",
                 "--priority", "1", "--source", "owner-answer",
                 "--title", "Owner answered queue #%s - do what he said" % rid,
                 "--dod", "What he asked for in the answer is carried out, with the outcome quoted back.",
                 "--why", did], capture_output=True, text=True, timeout=120)
        print(f"    recorded his answer to queue #{rid} in the ledger")
    except Exception as exc:
        print(f"    could not record the answer: {type(exc).__name__}: {exc}")
    # try to close the queue row too; the lock may refuse, and that is reported rather than hidden
    try:
        q = _sp.run(["python3", str(Path.home() / "bin" / "owner-queue.py"), "resolve", str(rid),
                     "--how", did[:900]], capture_output=True, text=True, timeout=180)
        if q.returncode == 0 and not (q.stderr or "").strip():
            print(f"    queue #{rid} resolved")
        else:
            print(f"    queue #{rid} NOT resolved (write lock): {(q.stderr or q.stdout).strip()[:100]}")
            print("             the ledger record above is the durable copy")
    except Exception as exc:
        print(f"    queue resolve attempt failed: {type(exc).__name__}: {exc}")


def _maybe_ask_one(conn, phone: str, *, after_answer: bool, dry_run: bool = False) -> None:
    """Ask ONE question - and after he has just answered, only if something is genuinely urgent.

    WHY NOT ALWAYS: he answered, so answering him with another question immediately turns a conversation
    into an interrogation. He has asked for one question at a time; this asks one, but not as a reflex.
    """
    if after_answer:
        print("    (he just answered - not immediately asking the next question)")
        return
    _reply_with_top_question(conn, phone, dry_run=dry_run)

def _reply_with_top_question(conn, phone: str, *, dry_run: bool = False) -> bool:
    """Reply to the owner with the TOP UNASKED decision from his own queue. True if something was sent.

    WHY THIS EXISTS, in his words: he texted "Text me the top question you have for me right now" and, before
    that, "Are you sure you're even replying to someone?" - while 24 decisions sat pending, the oldest from
    2026-09-16, and not one had ever been texted. The old acknowledgement said "Got it - filed as
    housekeeping#76", which is a message he has twice called pointless.

    SO THE REPLY CARRIES THE QUESTION. It is already written, already ranked, and already has a
    recommendation attached. Every owner text becomes one question and nothing else, which is his stated
    preference: "ask me one at a time".

    SILENCE WHEN THERE IS NOTHING TO ASK. A reply that carries no question, no warning and no deadline is
    the thing we were told not to send.
    """
    import json as _json
    import subprocess as _sp
    import os as _os
    queue = _os.environ.get("OWNER_QUEUE_CLI") or str(Path.home() / "bin" / "owner-queue.py")
    try:
        raw = _sp.run(["python3", queue, "list", "--json"], capture_output=True, text=True,
                      timeout=60).stdout
        rows = _json.loads(raw or "[]")
        if isinstance(rows, dict):
            rows = rows.get("rows") or rows.get("items") or []
    except Exception as exc:
        print(f"    queue read failed: {type(exc).__name__}: {exc}")
        return False

    # RANK BY DATED CONSEQUENCE, not by recency: a collector and a closing window outrank a fresh idea.
    SIGNALS = [("collector", 6), ("collections", 6), ("revoked", 6), ("revocation", 6), ("overdue", 5),
               ("no cover", 5), ("lapsed", 4), ("suspend", 5), ("past the", 4), ("deadline", 5),
               ("expires", 4), ("penalt", 4), ("owed", 3), ("final", 3)]
    cands = []
    for r in rows:
        if str(r.get("status")) != "pending":
            continue
        # NEVER ASK THE SAME QUESTION TWICE.
        if "asked_by_text" in (r.get("context") or "") or r.get("asked_at_text"):
            continue
        # AND THE GUARD THAT ACTUALLY WORKS: the owner queue is write-blocked by the app's 13 GB handle, so a
        # stamp there can silently fail. This one lives in a store we own and cannot be blocked.
        if _already_offered(r.get("id")):
            continue
        q = (r.get("question") or "")
        low = q.lower()
        score = sum(w for sig, w in SIGNALS if sig in low)
        if re.search(r"\b\d{2,}", q):
            score += 2
        if not q.strip():
            continue
        cands.append((score, -int(r.get("id") or 0), r))
    if not cands:
        print("    no unasked owner question - staying silent rather than sending a receipt")
        return False
    # ORDER BY THE QUEUE'S OWN AUTHORITY. The keyword score above is only a tie-breaker: the order the
    # owner queue itself recommends is `owner-queue.py next`, and on 2026-09-28 the two disagreed - the
    # SMS path would have texted #168 [medium] (a 487-dollar library bill) while the queue's own top row
    # was #162 [high] BLOCKING (the Gusto wage-claim close-out). A reply path that asks a different
    # question than the queue's own `next` is asking the owner the wrong question, so `next` wins.
    rank = {}
    try:
        peek = _sp.run(["python3", queue, "next", "--peek", "50"], capture_output=True, text=True,
                       timeout=60).stdout or ""
        rank = {int(m): i for i, m in enumerate(re.findall(r"(?m)^\s*#(\d+)\b", peek))}
    except Exception as exc:
        print(f"    queue next order unavailable ({type(exc).__name__}); using the keyword score")
    cands.sort(key=lambda t: (rank.get(int(t[2].get("id") or 0), 10 ** 6), -t[0], t[1]))
    row = cands[0][2]

    question = " ".join((row.get("question") or "").split())
    rec = " ".join((row.get("recommendation") or "").split())

    # A TEXT HE CAN ACT ON, NOT A SENTENCE CUT IN HALF.
    # Measured 2026-09-29: 3 of the 4 texts this path sent him ended mid-word at exactly 300
    # characters, every one of them inside the recommendation - the old code was
    # `body[:297] + "..."`. The recommendation is the part he answers, so the QUESTION now
    # absorbs the trim and either half is cut only at a sentence boundary. The recommendation
    # is never dropped: the question gives way first. textsend's own SOFT_LIMIT is 930.
    def _trim(text: str, limit: int) -> str:
        if len(text) <= limit:
            return text
        window = text[:limit]
        for end in (". ", "? ", "! "):
            at = window.rfind(end)
            if at >= limit // 2:
                return window[:at + 1].rstrip()
        at = window.rfind(" ")
        return window[:at].rstrip() if at > 0 else window.rstrip()

    BUDGET = 600
    if not rec:
        body = _trim(question, BUDGET)
    else:
        tail = " I recommend: " + rec
        room = BUDGET - len(tail)
        if room >= 80:
            body = _trim(question, room) + tail
        else:
            head = _trim(question, 160)
            body = head + " I recommend: " + _trim(rec, BUDGET - len(head) - 14)
    if len(body) < len(question) + len(rec) + 1:
        print("    (trimmed to %d chars at a sentence boundary; the full text is in queue "
              "#%s)" % (len(body), row.get("id")))

    try:
        import importlib.util as _il
        spec = _il.spec_from_file_location("textsend", str(Path.home() / "bin" / "textsend.py"))
        ts = _il.module_from_spec(spec)
        spec.loader.exec_module(ts)
        res = _count_send(ts.send(phone, body, dry_run=dry_run))
        print(f"    {'DRY-RUN, would reply' if dry_run else 'replied'} with queue "
              f"#{row.get('id')}: {body[:70]}")
        if dry_run:
            # A DRY RUN MUST NOT CONSUME THE QUESTION. Measured 2026-09-29: the defer stamp and
            # _record_offered ran regardless of mode, so a dry run marked a question as asked -
            # re-askable only in seven days - without ever putting it to him.
            print("    DRY-RUN: not stamping it asked and not recording it offered - the "
                  "question is still unasked")
            return True
        # STAMP IT ASKED so it is never repeated, and record that the ask happened by text.
        try:
            # --until IS REQUIRED by `owner-queue.py defer`. Without it the call exits with a usage
            # error, `capture_output=True` swallows the message, nothing is recorded and the row stays
            # eligible - so the SAME question goes out again on his next text. Measured 2026-09-28: the
            # stamp silently failed and the selector picked #164 again. Seven days is long enough that a
            # repeat follows only a genuine silence, and short enough that an unanswered question returns.
            _stamp = _sp.run(["python3", queue, "defer", str(row.get("id")),
                              "--until", "+7d",
                              "--note", "asked_by_text %s - put to him by SMS; awaiting his reply"
                              % datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")],
                             capture_output=True, text=True, timeout=60)
            # AND READ THE RESULT. A stamp whose effect is never checked is not a stamp: the identical
            # defect is what let a supposedly-intercepted test send the owner two duplicate texts.
            _err = (_stamp.stderr or "").strip()
            if _stamp.returncode != 0 or _err:
                print(f"    WARNING: the asked-stamp did NOT take (rc={_stamp.returncode}): "
                      f"{(_err or _stamp.stdout or '')[:160]}")
                print("    -> this question WILL repeat on his next text until it is stamped")
            else:
                print(f"    stamped #{row.get('id')} as asked (re-askable in 7 days)")
        except Exception as exc:
            print(f"    (asked, but could not stamp it as asked: {type(exc).__name__})")
        _record_offered(row.get("id"), body)
        return True
    except Exception as exc:
        print(f"    reply failed: {type(exc).__name__}: {exc}")
        return False

def _ack_owner_request(phone: str, filed: dict, body: str) -> None:
    """Send the owner a one-line acknowledgement. OFF unless AITEXT_ACK_OWNER_REQUESTS=1.

    WRITTEN BUT NOT ENABLED, deliberately: nothing in this system sends the owner anything until
    he has approved that behaviour, and he has not. See
    ~/code/harness-config/docs/outbound-comms-hard-stop.md.
    """
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("textsend", str(Path.home() / "bin" / "textsend.py"))
        ts = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ts)
        if filed.get("already"):
            body_out = "Already on it (%s#%d)." % (filed["project"], filed["id"])
        else:
            body_out = "Got it - filed as %s#%d." % (filed["project"], filed["id"])
        ts.send(phone, body_out, dry_run=False)
        print("    acknowledged to the owner")
    except Exception as exc:
        print(f"    ack failed: {type(exc).__name__}: {exc}")

def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd")
    s = sub.add_parser("pending"); s.add_argument("--only")
    s.add_argument("--limit", type=int, default=25); s.set_defaults(func=cmd_pending)
    s = sub.add_parser("run")
    s.add_argument("--only"); s.add_argument("--limit", type=int, default=25)
    s.add_argument("--send", action="store_true", help="actually send (default is dry-run)")
    s.add_argument("--dry-run", action="store_true", help="explicit dry run (the default)")
    s.add_argument("--max-sends", type=int, default=3)
    s.set_defaults(func=cmd_run)
    s = sub.add_parser("report"); s.set_defaults(func=cmd_report)
    s = sub.add_parser("jobs"); s.set_defaults(func=cmd_jobs)
    s = sub.add_parser("history"); s.add_argument("--limit", type=int, default=20)
    s.set_defaults(func=cmd_history)
    s = sub.add_parser("learn")
    s.add_argument("--apply", action="store_true",
                   help="write the unambiguous ledger changes (default: show them)")
    s.set_defaults(func=cmd_learn)
    args = p.parse_args()
    if not getattr(args, "func", None):
        args = p.parse_args(["pending"])
    if getattr(args, "send", False):
        args.dry_run = False
    else:
        args.dry_run = True
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
