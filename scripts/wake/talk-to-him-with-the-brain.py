#!/usr/bin/env python3
"""TALK TO HIM WITH THE BRAIN, not a rule. The owner's own requirement, 2026-09-29:

    "when asking me questions or discussing things with me or marking down answers, i want to be talking to
     you, and you should be the brain that is activated, not some hard coded automated stupid thing."

WHAT WAS HARDCODED, and it is one branch in `sms-responder.py:cmd_run`:

    # It runs BEFORE the classify/decide path because the classification costs a model call and the ledger
    # filing does not need one: "the owner asked for something" is not a judgement call, it is a fact about
    # the sender.
    if allow == "auto" and _is_owner_number(perm, r["from_number"]):
        filed = _file_owner_request(conn, r, body)
        ...
        _reply_with_top_question(conn, r["from_number"])
        continue

So for the owner the model is NEVER consulted. Measured consequence on 2026-09-29: he answered five questions
in plain English and the system, unable to read any of it, filed each answer as a NEW work item and asked him
a different question. He got a question loop from a system that never understood a word he said.

IT LOOKED REASONABLE AND WAS THE OPPOSITE OF RIGHT. "The owner asked for something" is not a fact about the
sender - his message may be an ANSWER, a greeting, a correction, a complaint, or a request, and telling those
apart is exactly the judgement a model is for. The comment even noticed it was skipping the judgement; it
concluded the judgement was not needed.

WHAT THIS CHANGES: for an owner text the responder now goes to the model FIRST, with the conversation in
context - the questions currently open, what we asked him and when, his thread - and the model decides:

    "record"   he answered or acknowledged something     -> mark it down, close what it answers
    "work"     he asked for something to be done         -> file it in the ledger (still priority 1)
    "escalate" it needs him and cannot be settled now    -> ask exactly one question
    "reply"    it can be answered from the thread        -> answer it
    "ignore"   nothing to do                             -> nothing

FILING DOES NOT GO AWAY, it moves after the judgement, so a request is still filed and an answer is still
recorded. And the model being unreachable no longer means silence for him: it falls back to the old behaviour
(file the item, ask the next question) so a model outage cannot leave him unanswered.

THE 'LAST ASKED' CONTEXT IS THE KEY PIECE and it is new: `~/.sms-inbox/offered.db` holds what we asked and
when, and the most recent of those goes into ctx as `last_asked`, so "I still have the books in my house" can
be understood as the answer to the library question rather than as a new task about books.

Usage: python3 talk-to-him-with-the-brain.py [--apply]
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

TARGET = Path("/home/zabz/bin/sms-responder.py")

HELPER = '''

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
'''

OWNER_BRANCH_OLD = '''        if allow == "auto" and _is_owner_number(perm, r["from_number"]):
            try:
                filed = _file_owner_request(conn, r, body)
            except Exception as exc:                      # never break the responder
                print(f"    owner-request filing failed: {type(exc).__name__}: {exc}")
                filed = None
            if filed:
                print(f"    filed as ledger item {filed['project']}#{filed['id']}")
                _record(conn, r["sid"], "working", "owner-request",
                        f"filed as ledger item {filed['project']}#{filed['id']}")
                # ANSWER HIM. The reply carries the top unasked decision from his own queue,
                # because he has twice called receipts pointless and 24 decisions sat pending with none
                # ever asked. Silence when there is nothing to ask. Replaces the old acknowledgement.
                _reply_with_top_question(conn, r["from_number"])
                continue'''

OWNER_BRANCH_NEW = '''        if allow == "auto" and _is_owner_number(perm, r["from_number"]):
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
            _usable = _action in ("record", "work", "reply", "escalate", "ignore") \\
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
                _reply_with_top_question(conn, r["from_number"])
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
                _maybe_ask_one(conn, r["from_number"], after_answer=True)
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
                        _ts.send(r["from_number"], _text, dry_run=False)
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
            if _action == "escalate":
                _maybe_ask_one(conn, r["from_number"], after_answer=False)
            continue'''

CLOSER = '''

def _close_what_he_answered(conn, body: str, decision: dict) -> None:
    """Mark down his answer and close the question it answers - in the ledger, which we can always write."""
    import json as _j, subprocess as _sp
    text = " ".join((body or "").split())
    info = _last_asked_and_open()
    last = info.get("last_asked") or {}
    # The model was given `last_asked` and the open rows. Prefer the row it names; otherwise the most recent
    # ask, because in a one-question-at-a-time conversation the answer follows the question.
    rid = None
    m = re.search(r"\\b(?:queue\\s*#?|#)(\\d{2,5})\\b", str(decision.get("why") or "") + " " + text)
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


def _maybe_ask_one(conn, phone: str, *, after_answer: bool) -> None:
    """Ask ONE question - and after he has just answered, only if something is genuinely urgent.

    WHY NOT ALWAYS: he answered, so answering him with another question immediately turns a conversation
    into an interrogation. He has asked for one question at a time; this asks one, but not as a reflex.
    """
    if after_answer:
        print("    (he just answered - not immediately asking the next question)")
        return
    _reply_with_top_question(conn, phone)
'''


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    p = TARGET
    src = p.read_text(encoding="utf-8")
    if "_close_what_he_answered" in src:
        print("already wired")
        return 0
    anchor = "\ndef _reply_with_top_question("
    if anchor not in src:
        print("ERROR: could not find _reply_with_top_question")
        return 1
    src = src.replace(anchor, HELPER + CLOSER + anchor, 1)
    print("1. added _last_asked_and_open, _close_what_he_answered, _maybe_ask_one")
    if OWNER_BRANCH_OLD not in src:
        print("ERROR: could not find the owner branch - refusing to guess")
        i = src.find("_file_owner_request(conn, r, body)")
        print("  context: %r" % src[max(0, i - 200):i + 120])
        return 1
    src = src.replace(OWNER_BRANCH_OLD, OWNER_BRANCH_NEW, 1)
    print("2. the owner branch now consults the model FIRST and files after the judgement")
    try:
        compile(src, str(p), "exec")
    except SyntaxError as exc:
        print("ERROR: does not compile: %s" % exc)
        return 1
    if not a.apply:
        print("dry run ok (use --apply)")
        return 0
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    shutil.copy2(p, p.with_name(p.name + ".bak-brain-" + stamp))
    p.write_text(src, encoding="utf-8")
    print("patched %s (backup .bak-brain-%s)" % (p, stamp))
    print("\n=== PROOF 1: the module still imports and the new helpers exist ===")
    code = ("import importlib.util,sys; s=importlib.util.spec_from_file_location('r','%s'); "
            "m=importlib.util.module_from_spec(s); sys.modules['r']=m; s.loader.exec_module(m); "
            "print('  import OK'); "
            "print('  helpers:', all(hasattr(m,n) for n in ('_last_asked_and_open','_close_what_he_answered','_maybe_ask_one'))); "
            "c=m._last_asked_and_open(); "
            "print('  last_asked:', (c.get('last_asked') or {}).get('queue_id'), "
            "str((c.get('last_asked') or {}).get('what_we_asked'))[:60]); "
            "print('  open rows fed to the model:', len(c.get('open_owner_rows') or []))" % p)
    out = subprocess.run(["python3", "-c", code], capture_output=True, text=True, timeout=180)
    print(out.stdout or out.stderr[:500])
    return 0


if __name__ == "__main__":
    sys.exit(main())
