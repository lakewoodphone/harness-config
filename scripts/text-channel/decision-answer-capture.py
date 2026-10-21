#!/usr/bin/env python3
"""decision-answer-capture.py — close the loop from "what we asked" to "what he said".

WHY THIS EXISTS (2026-10-21)
----------------------------
The queue could record that a question was SENT and nothing recorded what came back. That
made every delivery a dead end: `owner_queue_feedback` learns from rows whose `answer` is
filled, `_feedback_from_history` copies closes into it, and `_learning_profile` ranks with
it -- but a question texted to the owner never got its answer written onto its row, so the
profile could not learn from the only class of question the channel actually asks.

Measured before writing this: 802 feedback rows, all backfilled from closes a human or a
session performed; zero from a texted decision.

WHY ONE-OPEN-QUESTION-AT-A-TIME IS THE ATTRIBUTION KEY
------------------------------------------------------
Two texts arriving ten minutes apart cannot be told apart by content. But the channel's own
rule -- the owner's rule, 2026-09-25: "one question at a time" -- means at most ONE decision
question is open at any moment. So an inbound message from him that arrives after a question
was sent, and before the next one was, is the answer to that question. That is not a guess
about meaning; it is the structural consequence of the pacing.

The window closes both ways:
  * a message BEFORE the send is not an answer to it;
  * a message AFTER the next send belongs to the next question (except when it arrives in the
    same few seconds as the next send, in which case the earlier question is still the one he
    is replying to -- tested below by comparing against the send boundaries).

This tool writes only when it is certain:
  * the row was delivered (present in `decision_sent`);
  * the row is still `pending` (never overwrite a status someone else set);
  * an inbound owner message exists inside the window;
  * the message is not an opt-out or an auto-reply.

READ-ONLY except the write it exists to make: the queue row's status/answered_at/answer.
Never deletes, never rewrites a question, never touches a closed row.

USAGE
    decision-answer-capture.py              # report what it would attribute
    decision-answer-capture.py --apply      # write the attributions
"""

from __future__ import annotations

import argparse
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

HOME = Path.home()
AUTH_DB = Path(os.environ.get("AUTHORITY_DB", HOME / "authority.db"))

#: The owner's own number -- the only sender whose message can answer a question we asked him.
OWNER_PHONE = os.environ.get("OWNER_PHONE", "+18483897895")

#: An answer arriving later than this is not an answer to that question; it is a new thought.
MAX_ANSWER_HOURS = float(os.environ.get("DECISION_ANSWER_MAX_HOURS", "72"))

#: These are not answers, whatever their position in the window.
NOT_AN_ANSWER = re.compile(
    r"^\s*(stop|unsubscribe|opt ?out|cancel)\s*$|"
    r"^\s*(thanks?|thank you|ok(ay)?|got it|k|ty)\s*[.!]*\s*$", re.I)


def _ro(path: Path) -> sqlite3.Connection:
    c = sqlite3.connect("file:%s?mode=ro" % path, uri=True, timeout=10)
    c.row_factory = sqlite3.Row
    return c


def _rw(path: Path) -> sqlite3.Connection:
    c = sqlite3.connect(str(path), timeout=15)
    c.row_factory = sqlite3.Row
    return c


def _dt(value):
    if not value:
        return None
    try:
        t = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def collect() -> list[dict]:
    """Pair each delivered question with the one inbound message that answers it."""
    ro = _ro(AUTH_DB)
    try:
        sends = [dict(r) for r in ro.execute(
            "SELECT row_id, sender, sent_at, substr(body,1,120) body FROM decision_sent "
            "ORDER BY sent_at")]
        inbound = [dict(r) for r in ro.execute(
            "SELECT id, created_at, body FROM sms_log "
            "WHERE direction='inbound' AND from_number=? ORDER BY created_at",
            (OWNER_PHONE,))]
        pending = {int(r["id"]): dict(r) for r in ro.execute(
            "SELECT id, status, substr(question,1,90) q FROM owner_decision_queue "
            "WHERE status='pending'")}
    finally:
        ro.close()

    out = []
    for i, s in enumerate(sends):
        rid = int(s["row_id"])
        if rid not in pending:
            continue  # already answered, resolved or dismissed by someone else
        start = _dt(s["sent_at"])
        if start is None:
            continue
        end = _dt(sends[i + 1]["sent_at"]) if i + 1 < len(sends) else None
        best = None
        for m in inbound:
            when = _dt(m["created_at"])
            if when is None or when <= start:
                continue
            if end is not None and when >= end:
                # After the next send: it belongs to the next question. But a reply that
                # lands within the same minute as the next send is still to the earlier one,
                # so allow a 60-second grace across the boundary.
                if (when - end).total_seconds() > 60:
                    continue
            age_h = (when - start).total_seconds() / 3600.0
            if age_h > MAX_ANSWER_HOURS:
                continue
            text = " ".join(str(m["body"] or "").split())
            if not text or NOT_AN_ANSWER.search(text):
                continue
            best = {"sms_id": m["id"], "at": m["created_at"], "text": text,
                    "age_h": round(age_h, 2)}
            break  # the FIRST message in the window is the answer
        out.append({
            "row_id": rid,
            "question": pending[rid]["q"],
            "sent_at": s["sent_at"],
            "sender": s["sender"],
            "answer": best,
        })
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args(argv)

    pairs = collect()
    attributed = [p for p in pairs if p["answer"]]
    print("delivered questions still pending: %d" % len(pairs))
    print("with an inbound reply inside the window: %d" % len(attributed))
    for p in attributed:
        print("  #%-4s %-22s %s" % (p["row_id"], str(p["at"] if False else p["sent_at"])[:19],
                                    p["question"][:50]))
        print("        said: %s" % p["answer"]["text"][:90])

    if not attributed:
        return 0
    if not args.apply:
        print("\n(dry run: nothing written. use --apply)")
        return 0

    rw = _rw(AUTH_DB)
    written = 0
    try:
        for p in attributed:
            a = p["answer"]
            cur = rw.execute(
                "UPDATE owner_decision_queue SET status='answered', answered_at=?, answer=? "
                "WHERE id=? AND status='pending'",
                (a["at"], a["text"], p["row_id"]))
            if cur.rowcount:
                written += 1
        rw.commit()
    finally:
        rw.close()
    print("\nrecorded %d answer(s) on their rows" % written)
    return 0


if __name__ == "__main__":
    sys.exit(main())
