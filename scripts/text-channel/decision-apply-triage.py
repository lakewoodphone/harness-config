#!/usr/bin/env python3
"""decision-apply-triage.py — write the triage's verdict back onto the rows it judged.

THE GAP THIS CLOSES (2026-10-21)
-------------------------------
Thirty-three rounds of classification left the queue at 46 "pending" rows when only 20 of them are
decisions. The other 26 were judged -- 13 echoes of his own phone, 7 digests, 4 passive notes the
system should just do, 1 duplicate, 1 judge gap -- and every one of those verdicts lived only in
the triage's output. `owner-queue.py next` and `brief` read the DATABASE, so they still showed 46.

That is the opposite of what this programme exists for. A queue that is "the single list of
everything that needs him" must contain what needs him, and a disposition nobody writes down is a
disposition he pays for every time he opens the list.

WHAT IT WRITES
  ECHO        -> dismissed  "his own inbound message; he already has it on his phone"
  INFORM      -> resolved   "information only; visible in the brief, never texted"
  SYSTEM      -> resolved   "passive record-keeping; filed as ledger work instead of asking"
  DUPLICATE   -> dismissed  "same conversation as #N; the newer row carries it"
  NOISE       -> dismissed  with the triage's own reason
  STALE       -> dismissed  with the triage's own reason
  JUDGE_GAP   -> LEFT ALONE (a model must re-judge it; it is genuinely unfinished)
  SEND_NOW    -> LEFT ALONE (it is the work)
  CONTROL     -> LEFT ALONE
  ENGINEERING -> LEFT ALONE here; those are decided by a session and resolved with its reasoning

SAFETY
  * dry run by default; --apply writes.
  * only rows whose status is still 'pending' are touched, so a row answered or resolved by anyone
    else in the meantime is never overwritten.
  * every close carries the triage's own `why` as the resolution text, so the record says why.
  * nothing is deleted.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HOME = Path.home()
AUTH_DB = Path(os.environ.get("AUTHORITY_DB", HOME / "authority.db"))
TRIAGE = Path("/root/bin/decision-triage.py")

#: disposition -> (status written, plain-language reason used when the triage gave none)
WRITE = {
    "ECHO": ("dismissed", "his own inbound message, already on his phone"),
    "INFORM": ("resolved", "information only: visible in the brief, never texted"),
    "SYSTEM": ("resolved", "passive record-keeping: filed as ledger work instead of asking"),
    "DUPLICATE": ("dismissed", "same conversation as another row, which carries it"),
    "NOISE": ("dismissed", "noise"),
    "STALE": ("dismissed", "superseded or no longer true"),
}
LEAVE = {"SEND_NOW", "JUDGE_GAP", "CONTROL", "ENGINEERING", "COMPOSE"}


def rows() -> list[dict]:
    try:
        out = subprocess.run([sys.executable, str(TRIAGE), "--json"],
                             capture_output=True, text=True, timeout=900).stdout
        return json.loads(out).get("rows", [])
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        print("decision-apply-triage: cannot read the triage (%s)" % exc)
        return []


def main(argv: list[str] | None = None) -> int:
    apply = "--apply" in (argv or sys.argv[1:])
    todo = [r for r in rows() if r.get("disposition") in WRITE]
    if not todo:
        print("decision-apply-triage: nothing to write")
        return 0
    c = sqlite3.connect(str(AUTH_DB), timeout=20)
    c.row_factory = sqlite3.Row
    counts: dict[str, int] = {}
    skipped = 0
    now = datetime.now(timezone.utc).isoformat()
    try:
        for r in todo:
            rid = int(r["id"])
            disp = r["disposition"]
            status, fallback = WRITE[disp]
            why = str(r.get("why") or fallback).strip() or fallback
            cur = c.execute("SELECT status FROM owner_decision_queue WHERE id=?", (rid,)).fetchone()
            if cur is None or cur["status"] != "pending":
                skipped += 1
                continue
            counts[disp] = counts.get(disp, 0) + 1
            if not apply:
                continue
            c.execute("UPDATE owner_decision_queue SET status=?, resolved_at=?, resolution=?"
                      " WHERE id=? AND status='pending'", (status, now, why, rid))
        if apply:
            c.commit()
    finally:
        c.close()
    print("%s: %s" % ("wrote" if apply else "would write",
                      ", ".join("%s %d" % (k, v) for k, v in sorted(counts.items())) or "nothing"))
    if skipped:
        print("skipped %d row(s) that were no longer pending" % skipped)
    return 0


if __name__ == "__main__":
    sys.exit(main())
