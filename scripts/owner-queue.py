#!/usr/bin/env python3
"""owner-queue — the queue of things that genuinely need the OWNER, and only those.

WHY THIS EXISTS. The owner's instruction, 2026-09-11: *"you work on all of them as they
come up, and the ones that absolutely need me and you can't solve you bring up with me one
at a time throughout different conversation sessions, they should be in a queue you read
from when we have time."*

The company already had `owner_message_queue`, and by 2026-09-11 it had 595 undelivered
rows and had sent nothing since 2026-07-19 — 54 days. That queue is a *message* queue: it
fills with briefings, sync-breaker alerts and freshness notices, so it became noise and
then it became invisible. This is a *decision* queue: one row per thing the owner actually
has to decide, with a recommendation already attached, and resolved rows closed rather than
left to rot.

WHAT BELONGS HERE
  - money, customers, legal or contractual posture, family, anything irreversible
  - genuine taste calls
  - a blocker I could not resolve myself

WHAT DOES NOT BELONG HERE
  - anything I can fix. Fix it. A queue row is an admission that I could not.
  - a menu of five. One question, options, one marked Recommended.

USAGE
  owner-queue.py next                 # the single next thing to raise with him
  owner-queue.py next --peek 3        # the next few (for my own planning)
  owner-queue.py add --question ... --recommendation ... [--options a|b|c]
                                      [--context ...] [--blocks ...] [--ages-days N]
  owner-queue.py resolve ID --how "what I did / what he said"
  owner-queue.py resolve ID --dismissed "why it never needed him"
  owner-queue.py answer ID --answer "his words"
  owner-queue.py list [--all]
  owner-queue.py stats

AGEING. `next` sorts by (blocks-others first, severity, age). An item that is blocking
other work outranks a merely old one: keeping a decision queued while it stalls the
company is the expensive failure, not the decision itself.
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sqlite3
import sys
import textwrap

DEFAULT_DB = os.environ.get(
    "OWNER_QUEUE_DB", "/home/zabz/personal-secretary-mvp/data/secretary.db"
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS owner_decision_queue (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    asked_at      TEXT NOT NULL,
    question      TEXT NOT NULL,
    context       TEXT,
    options_json  TEXT,
    recommendation TEXT,
    severity      TEXT NOT NULL DEFAULT 'medium',
    blocks        TEXT,
    source        TEXT,
    age_days      INTEGER,
    status        TEXT NOT NULL DEFAULT 'pending',
    answered_at   TEXT,
    answer        TEXT,
    resolved_at   TEXT,
    resolution    TEXT
);
CREATE INDEX IF NOT EXISTS idx_odq_status ON owner_decision_queue(status, severity);
"""

# One-line ordering: unresolved, blocking first, then severity, then age.
SEV_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def connect(path: str) -> sqlite3.Connection:
    con = sqlite3.connect(path, timeout=20)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    con.commit()
    return con


def fmt(row: sqlite3.Row) -> str:
    out = []
    out.append("=" * 78)
    out.append(f"QUEUE #{row['id']}  [{row['severity']}]  asked {row['asked_at'][:16]}"
               + (f"  (about {row['age_days']}d of history)" if row["age_days"] else ""))
    if row["blocks"]:
        out.append(f"BLOCKING  {row['blocks']}")
    out.append("")
    for line in textwrap.wrap(row["question"], 76):
        out.append("  " + line)
    if row["context"]:
        out.append("")
        out.append("  CONTEXT")
        for para in str(row["context"]).split("\n"):
            for line in textwrap.wrap(para, 74) or [""]:
                out.append("    " + line)
    opts = row["options_json"]
    if opts:
        import json
        try:
            items = json.loads(opts)
        except Exception:
            items = []
        if items:
            out.append("")
            out.append("  OPTIONS")
            for i, o in enumerate(items, 1):
                out.append(f"    {i}) {o}")
    if row["recommendation"]:
        out.append("")
        out.append("  MY RECOMMENDATION: " + row["recommendation"])
    if row["source"]:
        out.append("")
        out.append("  SOURCE: " + row["source"])
    out.append("=" * 78)
    return "\n".join(out)


def cmd_add(con, a) -> int:
    cur = con.execute(
        """INSERT INTO owner_decision_queue
           (asked_at, question, context, options_json, recommendation, severity,
            blocks, source, age_days, status)
           VALUES (?,?,?,?,?,?,?,?,?, 'pending')""",
        (now(), a.question, a.context, a.options, a.recommendation, a.severity,
         a.blocks, a.source, a.age_days),
    )
    con.commit()
    print(f"queued #{cur.lastrowid} [{a.severity}] {a.question[:70]}")
    return 0


def cmd_next(con, a) -> int:
    rows = con.execute(
        "SELECT * FROM owner_decision_queue WHERE status='pending'"
    ).fetchall()
    if not rows:
        print("QUEUE EMPTY — nothing is waiting on the owner.")
        return 0

    def key(r):
        return (
            0 if (r["blocks"] or "").strip() else 1,
            SEV_RANK.get((r["severity"] or "medium").lower(), 2),
            -(r["age_days"] or 0),
            r["id"],
        )

    rows.sort(key=key)
    if a.peek and a.peek > 1:
        for r in rows[:a.peek]:
            print(f"  #{r['id']:<4} [{r['severity']:<8}] "
                  f"{'BLOCKING ' if (r['blocks'] or '').strip() else '         '}"
                  f"{r['question'][:90]}")
        return 0
    print(fmt(rows[0]))
    n = len(rows)
    print(f"({n} pending)" if n > 1 else "(last one)")
    return 0


def cmd_list(con, a) -> int:
    q = "SELECT * FROM owner_decision_queue"
    if not a.all:
        q += " WHERE status='pending'"
    q += " ORDER BY CASE severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END, id"
    rows = con.execute(q).fetchall()
    if getattr(a, "json", False):
        # machine-readable, so the journal can mirror the queue instead of restating it
        import json
        print(json.dumps([dict(r) for r in rows], indent=1, default=str))
        return 0
    print(f"{len(rows)} row(s)\n")
    for r in rows:
        flag = "!" if (r["blocks"] or "").strip() else " "
        print(f"{flag} #{r['id']:<4} {r['status']:<10} [{r['severity']:<8}] "
              f"{r['asked_at'][:10]}  {r['question'][:78]}")
        if a.all and r["resolution"]:
            print(f"      -> {r['resolution'][:100]}")
    return 0


def cmd_stats(con, a) -> int:
    for st, n in con.execute("SELECT status, COUNT(*) FROM owner_decision_queue GROUP BY 1"):
        print(f"  {st}: {n}")
    r = con.execute("SELECT MIN(asked_at), MAX(asked_at) FROM owner_decision_queue WHERE status='pending'").fetchone()
    if r and r[0]:
        print(f"  oldest pending: {r[0][:16]}   newest: {r[1][:16]}")
    return 0


def _close(con, a, status: str, text: str) -> int:
    row = con.execute("SELECT id, status FROM owner_decision_queue WHERE id=?", (a.id,)).fetchone()
    if not row:
        print(f"no such queue row: {a.id}")
        return 1
    con.execute(
        "UPDATE owner_decision_queue SET status=?, resolved_at=?, resolution=? WHERE id=?",
        (status, now(), text, a.id),
    )
    con.commit()
    print(f"#{a.id} -> {status}")
    return 0


def cmd_resolve(con, a) -> int:
    if a.dismissed:
        return _close(con, a, "dismissed", a.dismissed)
    if not a.how:
        print("resolve needs --how or --dismissed")
        return 1
    return _close(con, a, "resolved", a.how)


def cmd_answer(con, a) -> int:
    row = con.execute("SELECT 1 FROM owner_decision_queue WHERE id=?", (a.id,)).fetchone()
    if not row:
        print(f"no such queue row: {a.id}")
        return 1
    con.execute(
        "UPDATE owner_decision_queue SET status='answered', answered_at=?, answer=? WHERE id=?",
        (now(), a.answer, a.id),
    )
    con.commit()
    print(f"#{a.id} -> answered")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=DEFAULT_DB)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("add")
    p.add_argument("--question", required=True)
    p.add_argument("--context")
    p.add_argument("--options", help="pipe-separated")
    p.add_argument("--recommendation")
    p.add_argument("--severity", default="medium",
                   choices=["critical", "high", "medium", "low"])
    p.add_argument("--blocks", help="what other work this is holding up")
    p.add_argument("--source")
    p.add_argument("--age-days", type=int)

    p = sub.add_parser("next")
    p.add_argument("--peek", type=int, default=1)

    p = sub.add_parser("list")
    p.add_argument("--all", action="store_true")
    p.add_argument("--json", action="store_true", help="machine-readable, for the journal mirror")

    sub.add_parser("stats")

    p = sub.add_parser("resolve")
    p.add_argument("id", type=int)
    p.add_argument("--how")
    p.add_argument("--dismissed")

    p = sub.add_parser("answer")
    p.add_argument("id", type=int)
    p.add_argument("--answer", required=True)

    a = ap.parse_args()
    con = connect(a.db)
    fn = {"add": cmd_add, "next": cmd_next, "list": cmd_list,
          "stats": cmd_stats, "resolve": cmd_resolve, "answer": cmd_answer}[a.cmd]
    return fn(con, a)


if __name__ == "__main__":
    sys.exit(main())

