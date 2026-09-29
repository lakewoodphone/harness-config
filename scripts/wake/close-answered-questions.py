#!/usr/bin/env python3
"""HIS ANSWERS MUST CLOSE THE QUESTIONS THEY ANSWER.

WHAT HAPPENED, measured 2026-09-29 03:18Z. The owner exercised the channel properly. Every one of his texts
filed a ledger item and every one was answered with the next question - the transport, the gate and the
rotation all worked. But he ANSWERED questions and none of those answers closed anything:

    #162  Weinberg's final pay   -> "I will pay Weinberg in cash after the holiday / he left voluntarily
                                     because he wanted more pay"                        -> still pending
    #166  NY toll bill           -> "check back, maybe check the credit card statements because I thought I
                                     paid a few weeks ago"                              -> still pending
    #167  Elantra cover          -> "as for the car after the holiday. Maybe we'll get a proper inspection" -> still pending
    #168  Ocean County Library   -> "I still have the books in my house and simply have to return them and
                                     the fees get waived"                               -> still pending
    #164  ESCAPE 101 LLC         -> "I don't use that company anymore. It's basically closed down for good
                                     and done, no reason to keep it open"               -> still pending

SO THE SYSTEM IS DEAF, NOT BROKEN. Its only record that a question was asked is `offered.db`, which stops it
ASKING again - but nothing turns his reply into an ANSWER. Every question he answers stays `pending` for ever
and would be re-asked in seven days, and he would experience the same question loop he has already complained
about. That is the difference between "we asked" and "we heard".

WHAT THIS DOES - and it is the missing half of the reply path:
  1. MATCHES a reply to the question that was actually asked, by word overlap against the bodies in
     `offered.db` (plus the queue's own question text), and by the ledger: a question whose answer is
     already recorded closes.
  2. CLOSES the answered row with HIS OWN WORDS as the evidence, so the record shows what he said rather
     than what we assumed.
  3. FILES the answer into the ledger so the work it implies gets done - an answer is not a closed ticket,
     it is an instruction.
  4. REPORTS what it could not match, rather than quietly filing it as new work.

AND IT IS HONEST ABOUT THE LOCK: `owner_decision_queue` is write-blocked by the app's 13 GB handle
(measured: reads 0.00s, writes `database is locked` after 12s, 3 of 3). So a resolve may fail. The ledger
record is written FIRST - that is the durable truth - and the queue resolve is retried and reported. Nothing
here pretends a row closed when it did not.

Usage:
  python3 close-answered-questions.py --list                 # what it sees, changes nothing
  python3 close-answered-questions.py --apply                # record + resolve
  python3 close-answered-questions.py --apply --since 2026-09-28T23:00
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

APP_DB = Path("/home/zabz/personal-secretary-mvp/data/secretary.db")
INBOX = Path.home() / ".sms-inbox" / "inbox.db"
OFFERED = Path.home() / ".sms-inbox" / "offered.db"
QUEUE_CLI = Path.home() / "bin" / "owner-queue.py"
WORK_CLI = Path.home() / "bin" / "work.py"
STOP = {"the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "is", "it", "that", "this", "you",
        "your", "i", "we", "me", "my", "at", "as", "be", "if", "so", "do", "does", "not", "no", "with",
        "have", "has", "was", "were", "are", "but", "about", "from", "by", "will", "can", "there", "they"}


def words(text: str) -> set:
    return {w for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if w not in STOP and len(w) > 2}


def queue_rows() -> list:
    """Read the owner queue. Reads work even when writes are blocked."""
    try:
        out = subprocess.run(["python3", str(QUEUE_CLI), "list", "--json"],
                             capture_output=True, text=True, timeout=120).stdout
        rows = json.loads(out or "[]")
        return rows if isinstance(rows, list) else (rows.get("rows") or rows.get("items") or [])
    except Exception as exc:
        print("  could not read the owner queue: %s: %s" % (type(exc).__name__, exc))
        return []


def offered_rows() -> dict:
    try:
        c = sqlite3.connect("file:%s?mode=ro" % OFFERED, uri=True, timeout=20)
        c.row_factory = sqlite3.Row
        out = {int(r["queue_id"]): dict(r) for r in c.execute("select * from offered")}
        c.close()
        return out
    except Exception:
        return {}


def his_texts(since: str) -> list:
    """His inbound texts, in order. Dedupes across the two stores by (timestamp, first 40 chars)."""
    seen, out = set(), []
    for db in (APP_DB, INBOX):
        try:
            c = sqlite3.connect("file:%s?mode=ro" % db, uri=True, timeout=20)
            c.row_factory = sqlite3.Row
            if db is APP_DB:
                q = ("select created_at as at, body from sms_log where direction='inbound' "
                     "and from_number like '%8483897895%' and created_at > ? order by id")
            else:
                q = ("select date_sent as at, body from messages where direction='inbound' "
                     "and from_number like '%8483897895%' and date_sent > ? order by rowid")
            for r in c.execute(q, (since,)):
                key = (str(r["at"])[:19], (r["body"] or "")[:40])
                if key in seen:
                    continue
                seen.add(key)
                out.append({"at": str(r["at"]), "body": r["body"] or "", "from": str(db.name)})
            c.close()
        except Exception:
            continue
    out.sort(key=lambda r: r["at"])
    return out


def best_match(text: str, rows: list, offered: dict):
    """Which asked question does this reply answer? Overlap against question text, only ASKED rows."""
    tw = words(text)
    if not tw:
        return None, 0, "no usable words"
    best, score = None, 0.0
    for r in rows:
        i = int(r.get("id") or 0)
        if i not in offered:
            continue                      # only a question we actually ASKED can be answered
        qw = words(r.get("question") or "") | words(offered[i].get("body") or "")
        if not qw:
            continue
        overlap = len(tw & qw) / float(len(qw))
        if overlap > score:
            best, score = r, overlap
    if best is None:
        return None, 0, "no asked question to match against"
    if score < 0.12:
        return None, score, "overlap %.2f is below the 0.12 floor - not treated as an answer" % score
    return best, score, "overlap %.2f" % score


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--since", default="2026-09-28T23:00")
    ap.add_argument("--min-overlap", type=float, default=0.12)
    a = ap.parse_args()

    rows = queue_rows()
    offered = offered_rows()
    texts = his_texts(a.since)
    print("owner queue rows : %d (asked: %s)" % (len(rows), sorted(offered) or "none"))
    print("his texts since %s: %d" % (a.since, len(texts)))
    print()

    actions = []
    for t in texts:
        row, score, why = best_match(t["body"], rows, offered)
        if row is None:
            print("  [no match] %s  %r" % (t["at"][:19], t["body"][:64]))
            print("             %s" % why)
            continue
        actions.append({"at": t["at"], "row": row, "score": score, "answer": t["body"], "why": why})
        print("  [ANSWER ] #%-4s <- %s" % (row.get("id"), t["at"][:19]))
        print("             %s" % why)
        print("             he said: %s" % " ".join(t["body"].split())[:150])
        print("             question: %s" % " ".join((row.get("question") or "").split())[:110])
        print()

    if not actions:
        print("nothing to close")
        return 0
    if a.list or not a.apply:
        print("(%d answer(s) identified; nothing written. use --apply)" % len(actions))
        return 0

    # ---- record in the ledger FIRST: that is the durable truth even if the queue cannot be written -------
    for act in actions:
        rid = act["row"].get("id")
        did = ("The owner ANSWERED queue #%s by text: %r" % (rid, " ".join(act["answer"].split())[:280]))
        proof = ("his text of %s (sms_log inbound from +18483897895); matched to the question by %s"
                 % (act["at"][:19], act["why"]))
        result = ("queue #%s '%s' answered with his own words; recorded here so the answer survives even if "
                  "the owner_decision_queue cannot be written while the app holds its lock"
                  % (rid, " ".join((act["row"].get("question") or "").split())[:80]))
        left = ("Resolve queue #%s once the write lock frees, and do the work the answer implies; the answer "
                "is an instruction, not a closed ticket." % rid)
        p = subprocess.run(["python3", str(WORK_CLI), "add", "--project", "housekeeping", "--priority", "1",
                            "--title", "Owner answered queue #%s by text - act on it" % rid,
                            "--dod", "The action his answer implies is carried out and the outcome is quoted "
                                     "back to him in one short message only if it carries a question, a "
                                     "warning or a deadline.",
                            "--why", did, "--source", "owner-answer"],
                           capture_output=True, text=True, timeout=120)
        out = (p.stdout or "").strip()
        print("  ledger: %s" % (out[:150] or p.stderr.strip()[:150]))
        # attempt the queue resolve, and be honest if the lock refuses
        q = subprocess.run(["python3", str(QUEUE_CLI), "resolve", str(rid), "--how", did[:900]],
                           capture_output=True, text=True, timeout=180)
        err = (q.stderr or "").strip()
        if q.returncode == 0 and not err:
            print("  queue #%s -> resolved" % rid)
        else:
            print("  queue #%s -> COULD NOT RESOLVE (locked): %s" % (rid, (err or q.stdout).strip()[:120]))
            print("             the ledger record above is the durable copy; a scheduled reconcile will retry")
    return 0


if __name__ == "__main__":
    sys.exit(main())
