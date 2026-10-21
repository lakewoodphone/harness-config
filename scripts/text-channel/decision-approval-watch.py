#!/usr/bin/env python3
"""decision-approval-watch.py — act on the owner's answer about the decision channel.

WHY THIS EXISTS (2026-10-21)
----------------------------
The channel is built, paced, triaged and proven, and it sends nothing because one approval is
outstanding. That approval lived only in a chat window, which assumes he is reading it at the
moment it is written -- and the whole reason this queue exists is that chat is not a durable
surface. So the approval is now a ROW in `owner_decision_queue` (source
`decision-channel-approval`, kind `approval`), the triage classifies it CONTROL so the channel
can never text a question about itself, and this program is what turns his answer into the
switch.

TWO WAYS HE CAN ANSWER, and both are honoured:
  * the row is marked `answered` in the queue (he said it to whoever he was talking to);
  * he TEXTS an explicit approval to the line after the row was filed. A text is the surface
    he actually uses, so refusing to hear the answer there would be the same mistake as
    putting the question only in chat. Only an EXPLICIT affirmative counts, and only inside
    the window -- a "yes" to something else must never switch the channel on.

WHAT IT DOES
  approval  -> create ~/.decision-deliver/APPROVED, resolve the row with his words, log it
               and raise one wake flag so a session watches the first sends happen.
  refusal   -> leave the sentinel absent, resolve the row as dismissed, log it, and never
               raise it again (the row is closed, so nothing regenerates it).
  neither   -> say so every run. Silence here would be indistinguishable from a crash.

READ-ONLY except: the sentinel file, the row's status/answer, and one flag on approval.
"""

from __future__ import annotations

import os
import re
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HOME = Path.home()
BIN = HOME / "bin"
AUTH_DB = Path(os.environ.get("AUTHORITY_DB", HOME / "authority.db"))
SENTINEL = Path(os.environ.get("DECISION_APPROVAL_SENTINEL",
                               HOME / ".decision-deliver" / "APPROVED"))
SOURCE = "decision-channel-approval"
OWNER_PHONE = os.environ.get("OWNER_PHONE", "+18483897895")

#: How far back a text can be and still be an answer to the approval row.
WINDOW_HOURS = float(os.environ.get("DECISION_APPROVAL_WINDOW_HOURS", "72"))

#: Explicit only. A bare "yes" is deliberately NOT enough outside the queue, because the owner
#: says "yes" to many things and a misfire here sends him up to 56 messages.
YES = re.compile(
    r"\b(turn (it|the channel|the queue) on|go ahead and (send|start)|"
    r"approve (the|it|the channel|the queue)|start sending|yes,? (send|start|turn|go)|"
    r"send (them|the questions)|ok(ay)? to send)\b", re.I)
NO = re.compile(
    r"\b(don'?t send|do not send|not yet|leave it off|no,? (don'?t|do not|leave)|"
    r"hold (off|on)|turn it off|stop sending)\b", re.I)


def _ro() -> sqlite3.Connection:
    c = sqlite3.connect("file:%s?mode=ro" % AUTH_DB, uri=True, timeout=10)
    c.row_factory = sqlite3.Row
    return c


def _rw() -> sqlite3.Connection:
    c = sqlite3.connect(str(AUTH_DB), timeout=15)
    c.row_factory = sqlite3.Row
    return c


def _dt(v):
    if not v:
        return None
    try:
        t = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def _flag(subject: str, prompt: str) -> None:
    try:
        subprocess.run([sys.executable, str(BIN / "wake.py"), "flag",
                        "--subject", subject, "--prompt", prompt,
                        "--kind", "owner-decision", "--source", "decision-approval-watch",
                        "--priority", "high"],
                       capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        pass


def main() -> int:
    ro = _ro()
    try:
        row = ro.execute(
            "SELECT id, asked_at, status, answer, answered_at FROM owner_decision_queue "
            "WHERE source=? ORDER BY id DESC LIMIT 1", (SOURCE,)).fetchone()
        if row is None:
            print("no approval row exists -- file one with status='pending' to ask again")
            return 0
        asked = _dt(row["asked_at"])
        recent = ro.execute(
            "SELECT created_at, body FROM sms_log WHERE direction='inbound' "
            "AND from_number=? AND created_at >= ? ORDER BY created_at",
            (OWNER_PHONE, asked.isoformat() if asked else "1970-01-01")).fetchall()
    finally:
        ro.close()

    status = str(row["status"] or "")
    if status == "answered":
        said = str(row["answer"] or "")
    else:
        said = ""
        for m in recent:
            when = _dt(m["created_at"])
            if asked and when and (when - asked).total_seconds() > WINDOW_HOURS * 3600:
                continue
            text = str(m["body"] or "")
            # A refusal wins over an approval in the same window: if he said both, the safer
            # reading is the one that sends nothing.
            if NO.search(text):
                said = text
                break
            if YES.search(text):
                said = text
                break

    if not said:
        n = len(recent)
        print("awaiting his answer: approval row #%s is %s, %d text(s) since it was filed, "
              "none of them an explicit approval or refusal"
              % (row["id"], status or "unknown", n))
        return 0

    approved = bool(YES.search(said)) and not NO.search(said)
    rw = _rw()
    try:
        if approved:
            SENTINEL.parent.mkdir(parents=True, exist_ok=True)
            SENTINEL.write_text(
                "Approved 2026-10-21. Owner said: %s\n" % said.strip().replace("\n", " ")[:200])
            rw.execute("UPDATE owner_decision_queue SET status='answered', answered_at=?, "
                       "answer=? WHERE id=?",
                       (datetime.now(timezone.utc).isoformat(), said, row["id"]))
            rw.commit()
            print("APPROVED -- sentinel created at %s from his words: %r"
                  % (SENTINEL, said.strip()[:80]))
            _flag("decision-channel-approved:2026-10-21",
                  "The owner approved the decision channel. ~/.decision-deliver/APPROVED now "
                  "exists, so decision-deliver.py will send up to 2 questions a day in his "
                  "hours. Watch the FIRST sends specifically: run "
                  "/root/bin/decision-deliver.py --status after each cron tick, confirm the "
                  "body that went out reads as a real question, and confirm an answer lands "
                  "back on the row via decision-answer-capture.py. If a message goes out that "
                  "he would not have wanted, remove the sentinel immediately (that stops every "
                  "send with no deploy) and report it. Do not raise his volume above 2/day.")
        else:
            rw.execute("UPDATE owner_decision_queue SET status='dismissed', resolved_at=?, "
                       "resolution=? WHERE id=?",
                       (datetime.now(timezone.utc).isoformat(),
                        "Owner declined the decision channel: %s" % said.strip()[:300],
                        row["id"]))
            rw.commit()
            print("DECLINED -- sentinel left absent; row #%s closed with his words: %r"
                  % (row["id"], said.strip()[:80]))
    finally:
        rw.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
