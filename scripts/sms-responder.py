#!/usr/bin/env python3
"""The texting responder: read the inbox, decide, answer - or ask the owner.

Companion to sms-inbox.py (the sensor). That one guarantees the texts are
*seen*; this one decides what happens to each of them. The rule is the owner's
own, 2026-09-18:

    "...if you know what to respond and you're pretty sure you have permission
     for me to respond right away. If not, send it into the owner queue for
     something that needs attention."

So there are exactly three outcomes per inbound text, and no fourth:

    auto   answer it now, from the AI line, and record what was sent
    queue  raise ONE owner-queue row for that correspondent, and say why
    never  record it and stop (machines, dealers, anyone opted out)

Permission comes from the ledger in sms-inbox.py's store - per phone number,
`allow = auto | queue | never`. **No row means queue**, never auto: absence of a
decision is not permission. The ledger is the thing the owner widens over time.

SAFETY
    --dry-run is the default for anything that would send. Never assume: pass
    --send to actually reply.
    A hard cap on sends per run (--max-sends, default 3) so a loop cannot run
    away with the owner's number.
    The model is resolved at RUNTIME from the gateway's own catalog and falls
    back to queueing rather than sending if it cannot answer. A model that
    cannot be reached must never be mistaken for a model that answered.

USAGE
    python3 ~/bin/sms-responder.py pending            # what is waiting, and why
    python3 ~/bin/sms-responder.py run --dry-run      # decide, send nothing
    python3 ~/bin/sms-responder.py run --send --max-sends 1
    python3 ~/bin/sms-responder.py history --limit 20
"""
from __future__ import annotations

import argparse
import base64
import json
import re
import sqlite3
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import importlib.util

_spec = importlib.util.spec_from_file_location(
    "sms_inbox", str(Path(__file__).resolve().parent / "sms-inbox.py")
)
inbox = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(inbox)

# The wake queue: how a reply becomes a session instead of a notification.
_wspec = importlib.util.spec_from_file_location(
    "wake_mod", str(Path(__file__).resolve().parent / "wake.py")
)
wake_mod = importlib.util.module_from_spec(_wspec)
_wspec.loader.exec_module(wake_mod)

STORE = inbox.STORE
ENV_FILE = inbox.ENV_FILE
QUEUE = Path.home() / "bin" / "owner-queue.py"
GATEWAY = "http://127.0.0.1:8002/v1"
OWNER_QUEUE_DEDUP_HOURS = 20

SYSTEM = """You are Zabz, the AI assistant of Eliyahu (Lakewood Phone & Tech). You are
handling a text message that arrived on his personal line. Decide what should go back to the sender
RIGHT NOW.

There are exactly three possible outputs.

1. A plain answer - when you can genuinely answer it. This covers general knowledge, definitions,
   how things work, calculations, measurements, troubleshooting and technical advice (cars, phones,
   computers, appliances), and anything you can say factually and safely. For example, a question
   about why a car will not start with a suspected starter motor is answerable: say what is worth
   checking and what the usual cause is. Be useful, not timid.
   Example output: If the battery is holding charge and it still will not turn over, the starter is
   the usual suspect. A quick check is whether the lights dim when you turn the key.

2. A holding reply, starting with exactly `HOLD: ` - when you cannot answer the substance (it needs
   Eliyahu's decision, his money, his customers, his schedule, or a commitment only he can make) but
   a short human acknowledgement is still far better than silence. Say plainly that you have passed
   it to him. Never guess, never commit him, never promise a time.
   Example output: HOLD: I have passed this to Eliyahu - he will come back to you on it.

3. Exactly `QUEUE` and nothing else - only when neither applies: spam, a wrong number, a machine
   message, or when even an acknowledgement would be wrong or confusing.

Never do these: invent anything about Eliyahu, his schedule, his prices or his customers; mention
cost, margins, suppliers or marketplace links for anything the shop sells; promise, agree a deadline,
or speak for him.

Style when you answer: one to three short sentences. A text message, not an email. Plain English, no
jargon, no greeting, no emoji, no markdown. Finish every message with a new line reading exactly
`- Daniel`. Everything sent from this line is signed Daniel - that is the owner's standing rule
(2026-09-18), and it is the only name you ever sign. Never sign as Eliyahu and never sign as Zabz.
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --------------------------------------------------------------------------- #
def permission_for(conn: sqlite3.Connection, phone: str) -> dict:
    tail = inbox.norm(phone)
    row = conn.execute(
        "SELECT * FROM permissions WHERE substr(replace(replace(replace(phone,'+',''),'-',''),' ',''),-10)=?",
        (tail,),
    ).fetchone()
    if row:
        return dict(row)
    return {"phone": phone, "name": None, "relationship": "unknown",
            "allow": "queue", "note": "no ledger row - absence is not permission"}


def thread_context(conn: sqlite3.Connection, phone: str, limit: int = 6) -> str:
    rows = conn.execute(
        """SELECT direction, body, date_sent FROM messages
           WHERE from_number LIKE ? OR to_number LIKE ?
           ORDER BY date_sent DESC LIMIT ?""",
        (f"%{inbox.norm(phone)}", f"%{inbox.norm(phone)}", limit),
    ).fetchall()
    out = []
    for r in reversed(rows):
        who = "them" if r["direction"] == "inbound" else "us"
        out.append(f"{who}: {(r['body'] or '')[:300]}")
    return "\n".join(out)


# --------------------------------------------------------------------------- #
def gateway_models() -> list[str]:
    try:
        with urllib.request.urlopen(GATEWAY + "/models", timeout=15) as r:
            data = json.loads(r.read().decode())
        return [m["id"] for m in data.get("data", [])]
    except Exception as exc:
        print(f"  gateway catalog unreadable: {exc}", file=sys.stderr)
        return []


def pick_model(preferred=("secretary-fast", "secretary-auto")) -> str | None:
    """Resolve at runtime and DROP anything the catalog does not list."""
    known = gateway_models()
    if not known:
        return None
    for want in preferred:
        if want in known:
            return want
    return known[0] if known else None


def llm_reply(model: str, thread: str, incoming: str, sender_name: str) -> str | None:
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content":
                f"Recent messages on this thread (oldest first):\n{thread}\n\n"
                f"New text from {sender_name or 'this person'}:\n{incoming}\n\n"
                "Answer it, or reply QUEUE."},
        ],
        "temperature": 0.2,
        "max_tokens": 200,
    }
    req = urllib.request.Request(
        GATEWAY + "/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            data = json.loads(r.read().decode())
        return (data["choices"][0]["message"]["content"] or "").strip()
    except Exception as exc:
        print(f"  model call failed ({exc}) - queueing instead of guessing", file=sys.stderr)
        return None


def send_sms(cfg: dict, to: str, body: str) -> tuple[bool, str]:
    sid = cfg["TWILIO_ACCOUNT_SID"]
    tok = cfg["TWILIO_AUTH_TOKEN"]
    frm = cfg.get("TWILIO_PHONE_NUMBER") or inbox.AI_LINE_DEFAULT
    data = urllib.parse.urlencode({"From": frm, "To": to, "Body": body}).encode()
    req = urllib.request.Request(
        f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
        data=data, method="POST",
    )
    req.add_header("Authorization",
                   "Basic " + base64.b64encode(f"{sid}:{tok}".encode()).decode())
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            res = json.loads(r.read().decode())
        return True, str(res.get("sid") or "sent")
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}: {e.read().decode()[:200]}"
    except Exception as exc:
        return False, str(exc)


def _open_queue_row_for(phone: str) -> bool:
    """Is there already an unresolved owner-queue row about this person?

    Dedup against the QUEUE ITSELF, not against our own message state. The first
    version looked for a recently-queued message row in our store, and a one-time
    reset of that state (to re-decide under a changed policy) wiped the marker and
    made it raise every row again - six duplicates for three people, observed
    2026-09-18. The queue is the source of truth about what is already open.
    """
    tail = inbox.norm(phone)
    if not tail:
        return False
    try:
        c = sqlite3.connect(f"file:{inbox.APP_DB}?mode=ro", uri=True, timeout=20)
        rows = c.execute(
            "SELECT question FROM owner_decision_queue WHERE status='pending'"
        ).fetchall()
        c.close()
    except Exception as exc:
        print(f"    (could not read the queue for dedup: {exc})")
        return False
    for (q,) in rows:
        if tail in re.sub(r"\D", "", q or ""):
            return True
    return False


def queue_for_owner(conn, perm: dict, msg: sqlite3.Row, why: str,
                    suggested: str | None = None) -> bool:
    """Raise ONE owner-queue row for this correspondent, deduped by phone."""
    if _open_queue_row_for(msg["from_number"]):
        print("    an owner-queue row for this person is already open - not raising again")
        return False
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
def worklist(conn: sqlite3.Connection, only: str | None, limit: int) -> list[sqlite3.Row]:
    sql = "SELECT * FROM messages WHERE direction='inbound' AND state='new'"
    params: list = []
    if only:
        sql += " AND from_number LIKE ?"
        params.append(f"%{inbox.norm(only)}")
    sql += " ORDER BY date_sent ASC LIMIT ?"
    params.append(limit)
    return conn.execute(sql, params).fetchall()


def classify(draft: str | None) -> tuple[str, str | None]:
    """Turn the model's raw output into (answer|hold|queue, text-to-send).

    The model does not always obey the format. Observed on 2026-09-18: asked for
    the bare token QUEUE it returned `**QUEUE**\n\n### Reasoning\n...` followed by
    two suggested reply drafts. A naive `startswith("QUEUE")` check would have
    failed on the bold markers and SENT that entire scratch pad to the owner's
    father. So: normalise, then refuse to send anything that looks like working.
    """
    if not draft or not draft.strip():
        return "queue", None

    lines = [l for l in draft.strip().splitlines()]
    first = ""
    for l in lines:
        s = re.sub(r"^[\s*_`>#\-]+", "", l).strip()
        s = re.sub(r"[\s*_`]+$", "", s)
        if s:
            first = s
            break

    up = first.upper()
    if up.startswith("QUEUE"):
        return "queue", None
    if up.startswith("HOLD"):
        rest = first.split(":", 1)[1].strip() if ":" in first else ""
        if not rest:
            rest = " ".join(
                re.sub(r"^[\s*_`>#\-]+", "", l).strip() for l in lines[1:]
            ).strip()
        return ("hold", rest) if rest else ("queue", None)

    body = draft.strip()
    # Refuse to text scratch work: headings, reasoning sections, option lists,
    # anything that is not a short plain message.
    if re.search(r"(?m)^\s*#{1,6}\s|^\s*\*\*Option|\bReasoning\b", body):
        return "queue", None
    if len(body) > 400:
        return "queue", None
    body = "\n".join(l.strip() for l in body.splitlines() if l.strip()).strip()
    return ("answer", body) if body else ("queue", None)


def _record(conn, sid: str, state: str, by: str, reason: str,
            reply_sid: str | None = None) -> None:
    conn.execute(
        "UPDATE messages SET state=?, decided_by=?, decided_at=?, reason=?, reply_sid=? "
        "WHERE sid=?",
        (state, by, now(), reason[:400], reply_sid, sid),
    )
    conn.commit()


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


def cmd_run(args) -> int:
    cfg = inbox.env()
    conn = inbox.connect()
    rows = worklist(conn, args.only, args.limit)
    print(f"{len(rows)} to decide   mode={'SEND' if args.send else 'DRY-RUN'}")
    if not rows:
        return 0

    model = pick_model() if any(
        permission_for(conn, r["from_number"])["allow"] == "auto" for r in rows
    ) else None
    if model:
        print(f"  model (resolved from the catalog): {model}")

    sent = 0
    for r in rows:
        perm = permission_for(conn, r["from_number"])
        name = perm.get("name") or r["from_number"]
        allow = perm["allow"]
        print(f"\n<{r['date_sent']}> {name} [{allow}]: {(r['body'] or '')[:90]!r}")

        # FIRST: is this the answer to something we asked for? If so it is WORK,
        # not a judgement call - it becomes a wake row so a session gets started,
        # and it does NOT become another owner-decision row.
        aw = wake_mod.consume_await(conn, r["from_number"])
        if aw:
            print(f"    this is the reply we were waiting for: {aw['what'][:70]}")
            # The session MUST answer the person. Filing work and leaving a human
            # waiting is the exact failure this whole system exists to prevent -
            # observed live on 2026-09-18, when Weinberg replied, a session was
            # correctly released, and it reported back to nobody while he waited.
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
                f"Their reply: {(r['body'] or '')[:600]}\n\n"
                f"Full thread: python3 ~/bin/sms-inbox.py show {r['from_number']}"
            )
            filed = wake_mod._file_wake(
                conn,
                subject=f"await:{inbox.norm(r['from_number'])}:{r['sid']}",
                prompt=prompt,
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

        # One model call decides the outcome for everyone - including the
        # queue-permission senders, so the owner-queue row carries a drafted
        # answer he can just approve instead of a bare notification.
        draft = llm_reply(model, thread_context(conn, r["from_number"]),
                          r["body"] or "", name) if model else None
        verdict, text = classify(draft)
        print(f"    verdict: {verdict}" + (f" -> {text!r}" if text else ""))

        if allow != "auto":
            why = ("no ledger row" if perm.get("relationship") == "unknown"
                   else f"allow={allow} for {perm.get('relationship')}")
            queue_for_owner(conn, perm, r, why, suggested=text)
            _record(conn, r["sid"], "queued", "policy", why)
            continue

        # allow == auto
        if not model:
            print("    allow=auto but no model resolved - queueing, never guessing")
            queue_for_owner(conn, perm, r, "model unavailable")
            _record(conn, r["sid"], "queued", "policy", "model unavailable")
            continue

        if verdict == "queue":
            said = "the model returned QUEUE" if draft else "the model gave no answer"
            print(f"    {said} - queueing, sending nothing")
            queue_for_owner(conn, perm, r, said)
            _record(conn, r["sid"], "queued", "model", f"declined: {said}")
            continue

        # "answer" sends the answer; "hold" sends an acknowledgement AND still
        # routes it to the owner, because a hold means it needs him.
        if not args.send:
            print(f"    DRY-RUN - would send: {text!r}")
            if verdict == "hold":
                print("    (and would raise an owner-queue row: a hold means it needs him)")
            continue
        if sent >= args.max_sends:
            print(f"    send cap ({args.max_sends}) reached - leaving it for the next run")
            continue

        ok, ref = send_sms(cfg, r["from_number"], text)
        print(f"    {'SENT' if ok else 'SEND FAILED'}: {ref}")
        if not ok:
            _record(conn, r["sid"], "new", "model", f"send failed: {ref}")
            continue
        sent += 1
        _record(conn, r["sid"], "answered", "model",
                f"{verdict}: {text}", reply_sid=ref)
        conn.execute(
            """INSERT OR REPLACE INTO messages
               (sid, direction, from_number, to_number, body, date_sent, status,
                first_seen, app_has_it, state, decided_by, decided_at, reason)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (ref, "outbound", cfg.get("TWILIO_PHONE_NUMBER"), r["from_number"],
             text, now(), "sent", now(), None, "answered", "zabz", now(),
             f"auto-{verdict}"),
        )
        conn.commit()
        if verdict == "hold":
            queue_for_owner(conn, perm, r, "I sent a holding reply; the substance needs him",
                            suggested=text)
    print(f"\nsent this run: {sent}")
    return 0


def cmd_history(args) -> int:
    conn = inbox.connect()
    rows = conn.execute(
        "SELECT * FROM messages WHERE direction='inbound' AND state!='new' "
        "ORDER BY decided_at DESC LIMIT ?", (args.limit,)
    ).fetchall()
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


def _queue_rows(done: set[int]) -> list[sqlite3.Row]:
    """Read the owner queue out of the APP database, read-only."""
    try:
        c = sqlite3.connect(f"file:{inbox.APP_DB}?mode=ro", uri=True, timeout=20)
        c.row_factory = sqlite3.Row
        rows = c.execute(
            """SELECT id, question, answer, status FROM owner_decision_queue
               WHERE answer IS NOT NULL AND answer != ''
                 AND question LIKE '%texted your AI line%'
               ORDER BY id"""
        ).fetchall()
        c.close()
        return [r for r in rows if r["id"] not in done]
    except Exception as exc:
        print(f"  (owner queue unreadable: {exc})", file=sys.stderr)
        return []


def cmd_learn(args) -> int:
    """Turn the owner's ANSWERS into standing ledger rows.

    The owner's model, 2026-09-18: he should not have to decide the same person
    twice. So when he answers a queue row this responder raised, read what he
    actually said and widen or close the ledger for that person.

    It only acts on an UNAMBIGUOUS answer - one matching a positive or a negative
    pattern and not both. Anything else is printed and left alone, because
    guessing at a permission is how you send a message the owner would not have
    sent. The queue lives in the app's database; the ledger lives in ours.
    """
    conn = inbox.connect()
    conn.executescript(
        """CREATE TABLE IF NOT EXISTS learned (
               question_id INTEGER PRIMARY KEY,
               phone       TEXT,
               allow       TEXT,
               learned_at  TEXT)"""
    )
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
            " WHERE substr(replace(phone,'+',''),-10)=substr(?,-10)",
            (phone,),
        ).fetchone()
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
                 f"owner-answer #{r['id']}", now()),
            )
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
    s = sub.add_parser("pending"); s.add_argument("--only"); s.add_argument("--limit", type=int, default=25)
    s.set_defaults(func=cmd_pending)
    s = sub.add_parser("run")
    s.add_argument("--only"); s.add_argument("--limit", type=int, default=25)
    s.add_argument("--send", action="store_true", help="actually send (default is dry-run)")
    s.add_argument("--max-sends", type=int, default=3)
    s.set_defaults(func=cmd_run)
    s = sub.add_parser("history"); s.add_argument("--limit", type=int, default=20)
    s.set_defaults(func=cmd_history)
    s = sub.add_parser("learn")
    s.add_argument("--apply", action="store_true",
                   help="write the unambiguous ledger changes (default: show them)")
    s.set_defaults(func=cmd_learn)
    args = p.parse_args()
    if not getattr(args, "func", None):
        args = p.parse_args(["pending"])
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
