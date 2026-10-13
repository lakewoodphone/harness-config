#!/usr/bin/env python3
"""owner-queue-sweep.py -- one shop rule, one question. A bulk-intake guard.

WHY THIS EXISTS (measured, not argued)
--------------------------------------
Two one-shot sweeps are 100 of the 157 pending rows on the authority, read
2026-10-12 21:2xZ with:

    sqlite3 'file:/root/authority.db?mode=ro' \
      "SELECT source, COUNT(*) FROM owner_decision_queue \
        WHERE status='pending' GROUP BY source ORDER BY 2 DESC;"

    lpt-work-order-sweep    90
    lpt-board-walk-20261008 10

Each row was a raw per-order "was this paid / did this get collected?" question.
That turns ONE shop rule -- the P2936 worked example, "a finished order in
READY_FOR_PICKUP with no payment row is collected unless the case file says
otherwise" -- into 90 questions the owner has to answer one at a time, from a
queue whose only currency is his attention, whose head (#228, the subsidy
question, genuinely his) then waits 10.6 days behind the pile.

WHAT IT CHANGES
---------------
A sweep may no longer file raw rows. It hands its findings to this tool, each
finding carrying a stable ``subject``: the rule, or the smallest group of orders
that share one answer. The tool:

  * groups findings by normalised subject;
  * files AT MOST ONE owner question per subject, and the question text IS the
    subject, so the queue's own pending-duplicate check (owner-queue.py add, and
    app.owner_question_dedupe behind it) matches it across runs;
  * puts the per-order detail in ``context`` -- the row shows the evidence, it
    does not become N asks;
  * refuses a finding with no subject;
  * caps a run at ``--max-rows`` distinct subjects (default 3), so a wide sweep
    becomes a short list;
  * never sets OWNER_QUEUE_ALLOW_DUPLICATE, so an already-pending question is
    refused by the queue itself rather than re-asked.

INPUT
-----
JSON lines on stdin (or --findings FILE), one finding per line:

  {"subject": "Finished order with no payment row is collected unless the case file says otherwise",
   "context": "WO2512230003 ...; WO2601150002 ...",
   "recommendation": "Adopt the rule, then close the matching rows.",
   "options": "Adopt the rule|Keep deciding case by case",
   "severity": "medium",
   "blocks": "closing the open work orders"}

``subject`` and ``context`` are required. ``subject`` is deduped on casefold +
whitespace collapse.

OUTPUT
------
One line per subject on stdout:
    filed #612  <subject>
    refused    #612 already pending  <subject>
    skipped    over --max-rows        <subject>
A run that cannot reach owner-queue.py exits 1. Nothing is ever written to the
database directly: every row goes through the sanctioned ``owner-queue.py add``.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

DEFAULT_QUEUE = os.path.expanduser("~/bin/owner-queue.py")
MAX_CONTEXT = 6000


def norm_subject(text: str) -> str:
    return " ".join(str(text or "").split()).strip()


def load_findings(path: str):
    stream = sys.stdin if path in ("-", "") else open(path, encoding="utf-8")
    try:
        for lineno, line in enumerate(stream, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                yield lineno, json.loads(line)
            except Exception as exc:  # noqa: BLE001
                print("line %d: not JSON (%s)" % (lineno, exc), file=sys.stderr)
                yield lineno, None
    finally:
        if stream is not sys.stdin:
            stream.close()


def add_one(queue: str, source: str, subject: str, rec: str, options: str,
            context: str, severity: str, blocks: str, dry_run: bool) -> tuple[int, str]:
    if dry_run:
        return 0, "dry-run"
    args = [sys.executable or "python3", queue, "add",
            "--question", subject,
            "--context", context,
            "--recommendation", rec,
            "--options", options,
            "--severity", severity,
            "--source", source]
    if blocks:
        args += ["--blocks", blocks]
    env = dict(os.environ)
    env.pop("OWNER_QUEUE_ALLOW_DUPLICATE", None)  # the guard; never re-ask a pending row
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=120, env=env)
    except Exception as exc:  # noqa: BLE001
        return 1, "owner-queue.py could not be run: %s" % exc
    txt = ((p.stdout or "") + (p.stderr or "")).strip()
    return p.returncode, txt


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--findings", default="-", help="JSON-lines file, or - for stdin")
    ap.add_argument("--source", required=True,
                    help="the generator's source label, e.g. lpt-work-order-sweep")
    ap.add_argument("--max-rows", type=int, default=3,
                    help="most distinct subjects this run may file (default 3)")
    ap.add_argument("--queue", default=DEFAULT_QUEUE, help="path to owner-queue.py")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    if not os.path.isfile(a.queue):
        print("no owner-queue.py at %s" % a.queue, file=sys.stderr)
        return 1

    groups: dict[str, dict] = {}
    order: list[str] = []
    bad = 0
    for lineno, obj in load_findings(a.findings):
        if obj is None:
            bad += 1
            continue
        subject = norm_subject(obj.get("subject"))
        if not subject:
            print("line %d: REFUSED - a finding needs a 'subject' (the rule or group); "
                  "a raw per-order row may not be filed" % lineno, file=sys.stderr)
            bad += 1
            continue
        key = subject.casefold()
        g = groups.get(key)
        if g is None:
            groups[key] = g = {"subject": subject, "ctx": [], "rec": "", "options": "",
                               "severity": obj.get("severity") or "medium",
                               "blocks": obj.get("blocks") or "", "n": 0}
            order.append(key)
        g["n"] += 1
        if obj.get("context"):
            g["ctx"].append("(%d) %s" % (g["n"], str(obj["context"]).strip()))
        for fld in ("recommendation", "options", "blocks"):
            if obj.get(fld) and not g[fld]:
                g[fld] = str(obj[fld]).strip()
        if obj.get("severity"):
            g["severity"] = str(obj["severity"])

    filed = refused = skipped = 0
    for i, key in enumerate(order):
        g = groups[key]
        subject = g["subject"]
        if i >= a.max_rows:
            print("skipped    over --max-rows (%d distinct subjects)  %s" % (a.max_rows, subject[:110]))
            skipped += 1
            continue
        context = ("%d finding(s) grouped under one rule by owner-queue-sweep.py.\n%s"
                   % (g["n"], "\n".join(g["ctx"])))[:MAX_CONTEXT]
        rc, txt = add_one(a.queue, a.source, subject, g["rec"], g["options"],
                          context, g["severity"], g["blocks"], a.dry_run)
        if rc == 0:
            print("filed      %s  %s" % (txt[:40] or "ok", subject[:110]))
            filed += 1
        elif rc == 4:
            print("refused    %s  %s" % (txt.splitlines()[0][:80], subject[:110]))
            refused += 1
        else:
            print("FAILED rc=%s %s" % (rc, txt[:200]), file=sys.stderr)
            return 1

    print("summary: %d distinct subject(s); filed=%d refused=%d skipped=%d bad=%d"
          % (len(order), filed, refused, skipped, bad))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
