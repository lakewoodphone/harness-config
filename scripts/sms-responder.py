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
        if isinstance(got, dict) and got.get("identity"):
            return got
    except Exception as exc:
        fallback["warnings"].append(f"textctx.resolve raised: {exc}")
    return fallback


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


def safe_send(phone: str, body: str, dry_run: bool) -> dict:
    if send_mod is None:
        return {"ok": False, "sid": None, "channel": None, "dry_run": dry_run,
                "error": "textsend unavailable", "detail": ""}
    try:
        return send_mod.send(phone, body, dry_run=dry_run)
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
def permission_for(conn: sqlite3.Connection, phone: str) -> dict:
    """The ledger row, or the honest default.

    Delegates to textctx when present so there is exactly ONE definition of what
    the ledger says about a person (audit B8).
    """
    if ctx_mod is not None:
        try:
            got = safe_resolve(conn, phone)
            ident = got.get("identity") or {}
            return {"phone": phone, "name": ident.get("name"),
                    "relationship": ident.get("relationship") or "unknown",
                    "allow": got.get("allow") or "queue",
                    "note": "via textctx"}
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
    sql = "SELECT * FROM messages WHERE direction='inbound' AND state='new'"
    params: list = []
    if only:
        sql += " AND from_number LIKE ?"
        params.append(f"%{''.join(ch for ch in only if ch.isdigit())[-10:]}")
    sql += " ORDER BY date_sent ASC LIMIT ?"
    params.append(limit)
    return conn.execute(sql, params).fetchall()


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
        return

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
        else:
            _record(conn, r["sid"], "working", "work", f"answer ready, gate closed: {why}")
            if store is not None and job_id:
                store.job_set(conn, job_id, state="done", answer=answer, evidence=evidence)
            queue_for_owner(conn, permission_for(conn, r["from_number"]), r,
                            f"I did the work but the send gate is closed ({why})",
                            suggested=answer)
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


def cmd_run(args) -> int:
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
        perm = permission_for(conn, r["from_number"])
        name = perm.get("name") or r["from_number"]
        allow = perm["allow"]
        body = r["body"] or ""
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

        if allow == "never":
            print("    never - recorded, not answered")
            conn.execute("UPDATE messages SET state='ignored', decided_by='policy', "
                         "decided_at=?, reason='allow=never' WHERE sid=?",
                         (now(), r["sid"]))
            conn.commit()
            continue

        ctx = safe_resolve(conn, r["from_number"])
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
        if args.dry_run:
            print("    DRY-RUN - would raise an owner-queue row")
            continue
        queue_for_owner(conn, perm, r, decision.get("why") or "needs the owner",
                        suggested=decision.get("text") or esc.get("recommendation"))

    print(f"\nsent this run: {sent}")
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
    lastout: dict[str, str] = {}
    for r in conn.execute("SELECT to_number, date_sent FROM messages WHERE direction='outbound'"):
        t = "".join(ch for ch in (r["to_number"] or "") if ch.isdigit())[-10:]
        if t and (t not in lastout or (r["date_sent"] or "") > lastout[t]):
            lastout[t] = r["date_sent"] or ""
    waiting = []
    for r in conn.execute("SELECT from_number, date_sent, body, state FROM messages "
                          "WHERE direction='inbound'"):
        t = "".join(ch for ch in (r["from_number"] or "") if ch.isdigit())[-10:]
        if t and (t not in lastout or (r["date_sent"] or "") > lastout[t]):
            waiting.append((r["date_sent"], t, (r["body"] or "")[:50], r["state"]))
    waiting.sort()
    for d, t, b, s in waiting[-12:]:
        print(f"    {(d or '')[:16]}  {t:<12} [{s}] {b!r}")
    print(f"  => {len(waiting)} unanswered inbound text(s)")

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
