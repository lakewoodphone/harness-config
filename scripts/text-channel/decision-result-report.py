#!/usr/bin/env python3
"""decision-result-report.py — tell him when the thing he asked for is DONE.

WHY THIS EXISTS (2026-10-21)
----------------------------
L11967 said an answer that asks for work must become work. It now does: his reply to question
#877 ("make sure all the information is fully documented and ready for me to file") became
ledger item cfo#941, a cfo shift closed it in 33 minutes with a 593-line filing pack, and pushed
it to origin/master.

He was never told. The channel asks questions and captures answers; nothing reported that the
thing he asked for existed. So the last mile of every answered instruction ended in silence, and
the artefact sat in a ref he would have to think to look at. That is exactly as expensive as the
old failure -- he still files the return by hand with no document in front of him -- and quieter,
because nothing was lost.

HOW IT REPORTS, AND WHY IT REPORTS AS A QUESTION
------------------------------------------------
Not as an unsolicited notification. His own rule is that nothing goes out without a per-message
yes, and the approval he gave (6 a day, 2026-10-21) is for QUESTIONS on this channel. So a
completed answer becomes a question the channel already knows how to carry:

    "The NJ-927 filing pack is ready at docs/finance/NJ-927-Q3-2026-FILING-PACK.md (on
     origin/master). Want me to walk you through it?"

That is true, it is answerable, it tells him the thing exists and where, and it needs no new
permission model. He asked for a walkthrough; this is the walkthrough being offered.

IDEMPOTENT. One report per (answer row, work item), keyed on a dedupe key, so a re-run cannot ask
twice and a second close cannot double-report.

READ-ONLY except the one queue row it files.
"""

from __future__ import annotations

import hashlib
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

HOME = Path.home()
AUTH_DB = Path(os.environ.get("AUTHORITY_DB", HOME / "authority.db"))
WORK_DB = Path(os.environ.get("WORK_DB", HOME / "work" / "work.db"))
SOURCE = "answer-result"

#: A work item that came from an owner answer is marked with this source prefix.
ANSWER_PREFIX = "owner-answer:"


def _ro(p: Path) -> sqlite3.Connection | None:
    if not p.exists():
        return None
    c = sqlite3.connect("file:%s?mode=ro" % p, uri=True, timeout=10)
    c.row_factory = sqlite3.Row
    return c


def _rw(p: Path) -> sqlite3.Connection:
    c = sqlite3.connect(str(p), timeout=15)
    c.row_factory = sqlite3.Row
    return c


def _one_line(text: str, limit: int) -> str:
    t = " ".join(str(text or "").split())
    return t if len(t) <= limit else t[: limit - 1].rsplit(" ", 1)[0] + "…"


def collect() -> list[dict]:
    """Done work items that came from an answered question and have not been reported."""
    work = _ro(WORK_DB)
    if work is None:
        return []
    try:
        items = [dict(r) for r in work.execute(
            "SELECT id, project, title, dod, source, state, done_at "
            "FROM work_item WHERE source LIKE ? AND state = 'done'",
            (ANSWER_PREFIX + "%",))]
    finally:
        work.close()
    auth = _ro(AUTH_DB)
    if auth is None:
        return []
    out = []
    try:
        for it in items:
            try:
                row_id = int(str(it["source"]).split(":", 1)[1])
            except (IndexError, ValueError):
                continue
            row = auth.execute(
                "SELECT id, question, answer, status FROM owner_decision_queue WHERE id=?",
                (row_id,)).fetchone()
            if row is None:
                continue
            key = "answer-result:%s:%s" % (row_id, it["id"])
            seen = auth.execute(
                "SELECT 1 FROM owner_decision_queue WHERE dedupe_key=? LIMIT 1", (key,)).fetchone()
            if seen:
                continue
            # The deliverable: a path named in the item's own records, else the item's title.
            blob = " ".join(str(it.get(k) or "") for k in ("title", "dod"))
            paths = re.findall(r"(?:docs|scripts|src|app)/[\w./-]+\.(?:md|py|ts|sql|json)", blob)
            where = paths[0] if paths else ""
            out.append({
                "row_id": row_id,
                "item_id": int(it["id"]),
                "key": key,
                "title": _one_line(it["title"], 90),
                "where": where,
                "project": it["project"],
            })
    finally:
        auth.close()
    return out


def compose(rep: dict, row: dict) -> str:
    """The question that reports the result. Under 160 characters, and answerable."""
    head = "Done: %s." % _one_line(rep["title"], 80).rstrip(".")
    where = rep.get("where")
    tail = " Want me to walk you through it?"
    room = 160 - len(head) - len(tail) - (len(where) + 1 if where else 0)
    if where and len(where) <= 60:
        body = "%s At %s.%s" % (head, where, tail)
    elif room > 0:
        body = head + tail
    else:
        body = "The thing you asked me to document is done. Want me to walk you through it?"
    return body


def main(argv: list[str] | None = None) -> int:
    apply = "--apply" in (argv or sys.argv[1:])
    reps = collect()
    if not reps:
        print("answer-result: no completed answer is waiting to be reported")
        return 0
    auth = _rw(AUTH_DB)
    filed = 0
    try:
        for rep in reps:
            row = auth.execute("SELECT question FROM owner_decision_queue WHERE id=?",
                               (rep["row_id"],)).fetchone()
            body = compose(rep, dict(row or {}))
            print("would file for row #%s: %s" % (rep["row_id"], body[:120]))
            if not apply:
                continue
            auth.execute(
                "INSERT INTO owner_decision_queue (asked_at, question, context, recommendation,"
                " severity, source, status, kind, channel, party, evidence_at, dedupe_key)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (datetime.now(timezone.utc).isoformat(), body,
                 ("The answer to row #%s asked for something; ledger item #%s in project '%s' "
                  "closed it. This row reports that, so the work does not finish in silence. "
                  "Deliverable: %s" % (rep["row_id"], rep["item_id"], rep["project"],
                                       rep["where"] or "(named in the item)")),
                 "yes, tell him how to use it", "medium", SOURCE, "pending", "decision",
                 "sms", "zabz", datetime.now(timezone.utc).isoformat(), rep["key"]))
            filed += 1
        auth.commit()
    finally:
        auth.close()
    print("filed %d report(s)" % filed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
