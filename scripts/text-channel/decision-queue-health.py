#!/usr/bin/env python3
"""decision-queue-health.py — run the triage on a clock and record how the queue MOVES.

WHY THIS EXISTS (2026-10-21)
----------------------------
`decision-triage.py` classifies the queue whenever someone runs it. That is a tool, not a
loop: on 2026-10-21 the queue had 111 pending rows and the oldest was 34 days old, because
nothing ever assessed it. Two failures follow from a queue nobody measures:

  * rows ACCUMULATE and nobody notices -- 111 is not a backlog anyone chose;
  * rows ROT -- a question whose moment has passed still reads `pending`, and the next
    person to look cannot tell it from a live one.

So this runs after the triage and writes one line of history per tick: how many are pending,
how many are deliverable, the oldest, and how many are being delivered. A queue whose
deliverable count grows and whose delivered count stays zero is a blackout in slow motion,
and that is visible here as a trend rather than an incident nobody measured.

It also files ONE wake flag a day when the queue is structurally unable to drain
(deliverable > 0 and nothing delivered for 2 days), because that is work, not a question
for the owner.

READ-ONLY against the queue; writes only its own history line and, on that condition, a flag.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HOME = Path.home()
BIN = HOME / "bin"
AUTH_DB = Path(os.environ.get("AUTHORITY_DB", HOME / "authority.db"))
HIST = HOME / ".decision-deliver" / "queue-history.jsonl"
DELIVER_STATE = HOME / ".decision-deliver" / "state.db"

#: A queue that has deliverable rows and has delivered nothing for this long is not waiting
#: its turn; it is stopped. Two days is beyond every pacing rule this estate uses.
STALL_HOURS = 48

#: Without an approval, nothing is supposed to send -- so the finding is not "nothing sent"
#: but "one word has been owed for a week while the queue ages". Said once, at this point.
APPROVAL_STALE_DAYS = 5.0


def _ro(path: Path) -> sqlite3.Connection | None:
    if not path.exists():
        return None
    try:
        c = sqlite3.connect("file:%s?mode=ro" % path, uri=True, timeout=10)
        c.row_factory = sqlite3.Row
        return c
    except sqlite3.Error:
        return None


def _triage() -> dict:
    out = subprocess.run([sys.executable, str(BIN / "decision-triage.py"), "--json"],
                         capture_output=True, text=True, timeout=120)
    if out.returncode != 0:
        return {"error": "triage rc=%s: %s" % (out.returncode, out.stderr[:200])}
    try:
        return json.loads(out.stdout)
    except ValueError as exc:
        return {"error": "triage output unparsable: %s" % exc}


def _delivered() -> tuple[int, str | None]:
    c = _ro(DELIVER_STATE)
    if c is None:
        return 0, None
    try:
        n = c.execute("SELECT COUNT(*) FROM send WHERE verdict='SENT'").fetchone()[0]
        last = c.execute("SELECT at FROM send WHERE verdict='SENT' "
                         "ORDER BY id DESC LIMIT 1").fetchone()
        return int(n), (last[0] if last else None)
    except sqlite3.Error:
        return 0, None
    finally:
        c.close()


def _age_hours(stamp: str | None) -> float | None:
    if not stamp:
        return None
    try:
        t = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - t).total_seconds() / 3600.0


def main() -> int:
    d = _triage()
    if d.get("error"):
        print("decision-queue-health: " + d["error"])
        return 0
    counts = d.get("counts") or {}
    rows = d.get("rows") or []
    deliverable = int(counts.get("SEND_NOW", 0))
    oldest_days = max((r.get("age_days") or 0) for r in rows) if rows else 0.0
    sent_total, last_sent = _delivered()
    since = _age_hours(last_sent)

    record = {
        "at": datetime.now(timezone.utc).isoformat(),
        "pending": int(counts.get("SEND_NOW", 0)) + int(counts.get("COMPOSE", 0))
                   + int(counts.get("SYSTEM", 0)) + int(counts.get("STALE", 0))
                   + int(counts.get("NOISE", 0)) + int(counts.get("DUPLICATE", 0)),
        "counts": counts,
        "oldest_days": round(oldest_days, 1),
        "sent_total": sent_total,
        "hours_since_last_send": None if since is None else round(since, 1),
    }
    HIST.parent.mkdir(parents=True, exist_ok=True)
    if HIST.exists() and HIST.stat().st_size > 2_000_000:
        HIST.rename(HIST.with_suffix(".jsonl.1"))
    with HIST.open("a") as fh:
        fh.write(json.dumps(record, sort_keys=True) + "\n")

    # A FLAG MUST MEAN WORK, NOT A DECISION STATE. Measured immediately after writing the
    # first version: it filed "decision-queue-not-draining" on the very first tick, because
    # the approval sentinel was absent -- and an absent sentinel is the owner's decision to
    # wait, not a fault. Flagging it would be the estate's oldest error (a monitor that
    # pages about its own configuration).
    #
    # Two conditions are genuinely work:
    #   * approval EXISTS and nothing has gone out for STALL_HOURS -- a real stall in the
    #     delivery path, which the deliverer records refusals for;
    #   * no approval for APPROVAL_STALE_DAYS -- the queue is ageing while one word is owed,
    #     which the owner should hear once, not daily.
    approved = (HOME / ".decision-deliver" / "APPROVED").exists()
    stale_days = (oldest_days or 0)
    should_flag, subject, why = False, "", ""
    if approved and deliverable and (since is None or since > STALL_HOURS):
        should_flag = True
        subject = "decision-delivery-stalled:%s" % datetime.now(timezone.utc).strftime("%Y-%m-%d")
        why = ("approval is present but %d deliverable question(s) have not sent for %s"
               % (deliverable, "ever" if since is None else "%.0f h" % since))
    elif (not approved) and deliverable and stale_days > APPROVAL_STALE_DAYS:
        should_flag = True
        subject = "decision-approval-outstanding:%s" % datetime.now(timezone.utc).strftime("%Y-%m-%d")
        why = ("%d questions are waiting on one approval and the oldest is %.0f days old"
               % (deliverable, stale_days))

    if should_flag:
        subprocess.run([
            sys.executable, str(BIN / "wake.py"), "flag",
            "--subject", subject,
            "--prompt",
            ("%s. Run /root/bin/decision-triage.py for the shortlist, "
             "/root/bin/decision-deliver.py --status for the pacing state, and read "
             "/root/.decision-deliver/queue-history.jsonl for the trend. %s"
             % (why,
                "The deliverer records every refusal with its reason in "
                "~/.decision-deliver/state.db -- find the refusing check before changing "
                "anything." if approved else
                "Nothing may be sent without the owner's per-message yes; the correct action "
                "is to put ONE plain question in front of him, not to send the queue.")),
            "--kind", "owner-decision", "--source", "decision-queue-health",
            "--priority", "normal"],
            capture_output=True, text=True, timeout=60)


    print("pending=%d deliverable=%d oldest=%.1fd sent=%d since=%s"
          % (record["pending"], deliverable, oldest_days, sent_total,
             "never" if since is None else "%.0fh" % since))
    return 0


if __name__ == "__main__":
    sys.exit(main())
