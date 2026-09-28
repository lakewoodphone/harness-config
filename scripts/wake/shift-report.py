#!/usr/bin/env python3
"""THE PATH FROM A FINISHED SHIFT BACK TO THE OWNER - and the discipline that keeps it from becoming noise.

WHY THIS EXISTS, in the owner's own words:
  "why would it text me this, whats the point, is there a question or clarification you need from me or a
   warning you need to give me?"
and:
  "daily briefings are completely useless."

So the rule this implements is NOT "tell him what happened". It is:

    A FINISHED JOB IS RECORDED IN THE LEDGER. A TEXT HAPPENS ONLY WHEN IT CARRIES A QUESTION, A WARNING,
    OR A DECISION WITH A DEADLINE.

The failure this is built to prevent has already happened twice today in the other direction: 595 messages
reached him as "waiting for the owner" when 383 of them were engineering faults that were never his. A
mechanism that forwards outcomes indiscriminately is that same failure with a new name.

WHAT IT DOES, and the two paths are DIFFERENT ON PURPOSE:

  record  (the common case)
      The shift finished. The outcome is already in the ledger's `attempt` row (did / proof / result /
      left_over). This path writes NOTHING ELSE and sends NOTHING. It prints one line saying so, so a shift
      that calls it cannot think it has notified anyone.

  decision  (the rare case)
      Something genuinely needs him: money, a customer, legal, family, something irreversible, real taste,
      or a blocker the shift could not resolve. Then:
        1. ONE owner-queue row is filed, with the question and a RECOMMENDATION (never a menu);
        2. the exact text that WOULD go to his phone is PRINTED, in a fenced block;
        3. IT IS NOT SENT. `textsend.py notify` defaults to a dry run and that default is kept here,
           because approval is per message and a shift is not a person who can approve one.
      `--send --approved-by-owner` sends it. That flag exists so the ONE case where a human has already
      approved these exact words can be executed, and it is deliberately awkward to pass, because the
      rule it guards is the one that was broken on 2026-09-24 by a six-item questionnaire nobody had seen.

WHAT IT REFUSES TO DO:
  * it will not file a queue row without a `--question` and a `--recommendation`;
  * it will not file a queue row whose question looks like a status report - if the text has no question
    mark and no deadline and no warning, it says so and declines, because a non-question in a decision queue
    is how a decision queue becomes noise;
  * it never sends on the `record` path.

Usage:
  shift-report.py record  --item 42 --outcome "merged, tests 112/119 passed, branch pushed"
  shift-report.py decision --item 42 --question "..." --recommendation "..." [--warning] [--body-file F]
  shift-report.py --status        # what is waiting on him right now
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

QUEUE = "/home/zabz/bin/owner-queue.py"
SEND = "/home/zabz/bin/textsend.py"
OWNER = os.environ.get("OWNER_PHONE_NUMBER", "+18483897895")

# A question must carry at least one of these, or it is not a question.
QUESTION_MARKERS = ("?", "by ", "before ", "due ", "deadline", "choose", "approve", "confirm",
                    "which", "should i", "do you want", "warning", "risk", "overdue", "expires")


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ledger_outcome(item: int) -> str:
    """What the ledger already records for this item - so `record` can prove it wrote nothing extra."""
    try:
        import sqlite3
        c = sqlite3.connect("file:/home/zabz/work/work.db?mode=ro", uri=True, timeout=20)
        r = c.execute("select id, state, coalesce(done_at,'') from work_item where id=?", (item,)).fetchone()
        a = c.execute("select id, coalesce(state_after,''), coalesce(result,'') from attempt "
                      "where item=? order by id desc limit 1", (item,)).fetchone()
        c.close()
        if not r:
            return "(no such item)"
        return "item #%s is %s%s; newest attempt #%s -> %s" % (
            r[0], r[1], (" at " + r[2]) if r[2] else "",
            a[0] if a else "-", a[1] if a else "-")
    except Exception as exc:
        return "(could not read the ledger: %s)" % exc


def looks_like_a_question(text: str) -> tuple[bool, str]:
    low = (text or "").lower()
    if "?" in low:
        return True, "carries a question mark"
    for m in QUESTION_MARKERS:
        if m in low:
            return True, "carries %r" % m
    return False, "no question mark and none of the markers %s" % (QUESTION_MARKERS,)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--status", action="store_true", help="show what is waiting on the owner")
    sub = ap.add_subparsers(dest="cmd")

    r = sub.add_parser("record", help="a finished job: recorded in the ledger, NOTHING sent")
    r.add_argument("--item", type=int, required=True)
    r.add_argument("--outcome", required=True)

    d = sub.add_parser("decision", help="something genuinely his: queue row + the exact text, NOT sent")
    d.add_argument("--item", type=int, required=True)
    d.add_argument("--question", required=True)
    d.add_argument("--recommendation", required=True)
    d.add_argument("--context", default="")
    d.add_argument("--warning", action="store_true", help="a warning, not a question")
    d.add_argument("--deadline", default="")
    d.add_argument("--body-file", default="", help="the exact prose for the text, if it is not the question")
    d.add_argument("--send", action="store_true", help="actually send - requires --approved-by-owner")
    d.add_argument("--approved-by-owner", action="store_true")
    d.add_argument("--dry-run-test", action="store_true", help=argparse.SUPPRESS)

    a = ap.parse_args()

    if a.status or not a.cmd:
        print("=== what is waiting on the owner (owner_decision_queue) ===")
        for args in (["next"], ["stats"]):
            p = subprocess.run(["python3", QUEUE] + args, capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=90)
            out = (p.stdout or p.stderr or "").strip()
            print(out[:1800] if out else "(nothing)")
            print()
        return 0

    if a.cmd == "record":
        print("RECORDED IN THE LEDGER, NOTHING SENT.")
        print("  item    : #%s" % a.item)
        print("  outcome : %s" % a.outcome)
        print("  ledger  : %s" % ledger_outcome(a.item))
        print("  a finished job is recorded, never announced - the owner's rule: a text carries a question,")
        print("  a warning, or a decision with a deadline. This carried none of them.")
        return 0

    # ---- decision ------------------------------------------------------------------------------
    ok, why = looks_like_a_question(a.question)
    if not ok and not a.warning:
        print("REFUSED: this does not read like something that needs him.")
        print("  because: %s" % why)
        print("  a decision queue that accepts status reports becomes the message queue it replaced -")
        print("  595 rows, nothing delivered for 54 days. Either phrase it as a question, mark it")
        print("  --warning, or use `record`.")
        return 3

    body = a.question
    if a.body_file:
        try:
            body = Path(a.body_file).read_text(encoding="utf-8").strip()
        except Exception as exc:
            print("error: could not read --body-file: %s" % exc)
            return 2

    # 1. ONE queue row, with a recommendation.
    qargs = ["add", "--question", a.question, "--recommendation", a.recommendation]
    if a.context:
        qargs += ["--context", a.context]
    p = subprocess.run(["python3", QUEUE] + qargs, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=120)
    out = (p.stdout or "").strip()
    print("queue row: %s" % (out[:200] or p.stderr.strip()[:200]))

    # 2. show the exact words, and do not send them.
    print()
    print("THE EXACT TEXT THAT WOULD GO TO HIM (not sent):")
    print("```")
    print(body.strip())
    print("```")
    print("  to      : %s" % OWNER)
    print("  from    : the AI line")

    if not a.send:
        print("\nNOT SENT. Approval is per message: `textsend.py notify` defaults to a dry run and this")
        print("keeps that default. To send these exact words, the owner must have approved THIS text.")
        return 0
    if not a.approved_by_owner:
        print("\nREFUSED: --send without --approved-by-owner.")
        print("  A shift is not a person who can approve a message. The 2026-09-24 failure was a six-item")
        print("  questionnaire the owner had never seen; this flag exists so that cannot happen again.")
        return 3

    # 3. the only path that sends.
    tmp = Path("/tmp/shift-report-body.txt")
    tmp.write_text(body.strip(), encoding="utf-8")
    p = subprocess.run(["python3", SEND, "notify", "--body-file", str(tmp), "--send"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    print("\nsend result: %s" % ((p.stdout or p.stderr or "").strip()[:300]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
