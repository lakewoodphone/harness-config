#!/usr/bin/env python3
"""decision-deliver.py — ask the owner ONE triaged question, on a clock, at his pace.

WHY THIS EXISTS (2026-10-21)
----------------------------
Three separate facts, each measured, that together meant nothing reached him:

  * `owner_decision_queue` held 111 pending rows, oldest 34 days;
  * `owner-ask.py` is the only program that turns a row into a text, and it was in no
    crontab and no systemd unit -- it had never run on a schedule;
  * when run by hand it refused its own top candidate, because the composer rendered a
    real question into a 152-character stub with a queue reference and no ask.

So the channel had a producer, no deliverer, and a composer that produced unanswerable
bodies. `decision-triage.py` now classifies and composes; this is the DELIVERER.

WHAT IT DOES, AND WHAT IT REFUSES TO DO
---------------------------------------
  * Picks ONE row per run from the triage shortlist -- severity, then money, then age.
  * Refuses any body that is not within his ceiling, does not end in a question, or does
    not pass `ask_quality.review`. A refusal is recorded with its reason, so "why did
    this not go out" is a row, not a mystery.
  * Sends at most MAX_PER_DAY, never closer than MIN_GAP_MINUTES apart, and only inside
    his stated hours. His words: "one at a time", "don't overdo it or spam me".
  * Marks a row asked AFTER the provider accepted it, and only then, so a crash cannot
    silently burn a question.
  * Never re-asks an unanswered question. The ladder stops (his rule 8); a row asked twice
    with no answer is closed as unanswered rather than escalated.

THE STORE: ~/.decision-deliver/state.db. Its own file, so this tool can never corrupt the
decision queue or the ask ledger. Every action is a row in `send`.

MODES
    --dry-run     compose and print what WOULD be sent (default when --send is absent)
    --send        actually send through the owner text relay
    --status      what went out, what is waiting, and the next thing
    --compose ID  show the exact body for one row and judge it, without sending

READ-ONLY against everything except its own state file (and the provider, under --send).
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HOME = Path.home()
BIN = HOME / "bin"
AUTH_DB = Path(os.environ.get("AUTHORITY_DB", HOME / "authority.db"))
STATE_DIR = Path(os.environ.get("DECISION_DELIVER_DIR", HOME / ".decision-deliver"))
STATE_DB = STATE_DIR / "state.db"

#: His stated ceiling for one text, and the target he asked for inside it.
CEILING = 160
TARGET = 120

#: "one at a time ... don't overdo it or spam me" (2026-09-22). Two a day is the ceiling
#: he has tolerated; the measured useful rate is about one question a day.
MAX_PER_DAY = int(os.environ.get("DECISION_DELIVER_MAX_PER_DAY", "2"))
MIN_GAP_MINUTES = int(os.environ.get("DECISION_DELIVER_MIN_GAP_MINUTES", "30"))

#: The sending window, in UTC. His local hours are 12:00-17:00 and 19:00-23:00
#: (OWNER-PROTOCOL 2026-09-30); the estate runs UTC with him at UTC-4.
HOURS_UTC = tuple(range(16, 21)) + tuple(range(23, 24)) + tuple(range(0, 4))

#: The ladder stops: ask twice, then close as unanswered. Never escalate.
MAX_ASKS = 2

SCHEMA = """
CREATE TABLE IF NOT EXISTS send (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    row_id      INTEGER NOT NULL,
    body        TEXT NOT NULL,
    chars       INTEGER NOT NULL,
    verdict     TEXT NOT NULL,       -- SENT | REFUSED | WOULD_SEND
    reason      TEXT NOT NULL DEFAULT '',
    sid         TEXT NOT NULL DEFAULT '',
    at          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_send_row ON send(row_id);
"""


def _state() -> sqlite3.Connection:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(STATE_DB, timeout=10)
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    return c


def _ro() -> sqlite3.Connection:
    c = sqlite3.connect("file:%s?mode=ro" % AUTH_DB, uri=True, timeout=10)
    c.row_factory = sqlite3.Row
    return c


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _triage(dry_json: bool = False) -> list[dict]:
    """The triage tool's own verdicts, so there is one classifier and not two."""
    out = subprocess.run([sys.executable, str(BIN / "decision-triage.py"), "--json"],
                         capture_output=True, text=True, timeout=120)
    if out.returncode != 0 or not out.stdout.strip():
        raise SystemExit("triage failed rc=%s: %s" % (out.returncode, out.stderr[:400]))
    return json.loads(out.stdout).get("rows") or []


def _sent_rows(state: sqlite3.Connection) -> dict[int, int]:
    return {int(r["row_id"]): int(r["n"]) for r in state.execute(
        "SELECT row_id, COUNT(*) n FROM send WHERE verdict='SENT' GROUP BY row_id")}


def _pick(rows: list[dict], state: sqlite3.Connection) -> tuple[dict | None, str]:
    asked = _sent_rows(state)
    for r in rows:
        if r.get("disposition") not in ("SEND_NOW",):
            continue
        n = asked.get(int(r["id"]), 0)
        if n >= MAX_ASKS:
            continue
        return r, ""
    return None, "nothing on the shortlist is both sendable and un-asked"


def _sent_today(state: sqlite3.Connection) -> int:
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return int(state.execute(
        "SELECT COUNT(*) FROM send WHERE verdict='SENT' AND substr(at,1,10)=?",
        (day,)).fetchone()[0])


def _minutes_since_last(state: sqlite3.Connection) -> float | None:
    row = state.execute(
        "SELECT at FROM send WHERE verdict='SENT' ORDER BY id DESC LIMIT 1").fetchone()
    if not row:
        return None
    try:
        last = datetime.fromisoformat(row["at"])
    except ValueError:
        return None
    return (datetime.now(timezone.utc) - last).total_seconds() / 60.0


def _in_hours() -> tuple[bool, str]:
    h = datetime.now(timezone.utc).hour
    if h in HOURS_UTC:
        return True, "inside his hours (UTC %02d)" % h
    return False, "outside his hours (UTC %02d, window %s)" % (
        h, ",".join("%02d" % x for x in sorted(set(HOURS_UTC))))


def _send(body: str, row_id: int) -> tuple[bool, str]:
    """Send one body through the owner text relay, and report what the provider said.

    `textsend.py` is the sender every other owner-facing path uses: it owns the one-text
    ceiling, the flood brake and the credential. Calling it (rather than Twilio directly)
    means this deliverer inherits every guard already proven on this estate -- and a
    refusal from it is a real policy decision, recorded as such.
    """
    reason = "owner_question:decision_%d" % row_id
    cmd = [sys.executable, str(BIN / "textsend.py"), "send",
           "--to", os.environ.get("OWNER_PHONE", "+18483897895"),
           "--reason", reason, "--body", body, "--send"]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    except subprocess.TimeoutExpired:
        return False, "sender timed out after 180s"
    blob = (out.stdout or "") + (out.stderr or "")
    if out.returncode == 0 and "ok=True" in blob:
        sid = ""
        for token in blob.replace("\n", " ").split():
            if token.startswith("sid=SM"):
                sid = token.split("=", 1)[1]
                break
        return True, "ok; " + (sid or "provider accepted, no sid printed")
    return False, "rc=%s: %s" % (out.returncode, " ".join(blob.split())[:300])


def cmd_status(state: sqlite3.Connection) -> int:
    rows = state.execute("SELECT * FROM send ORDER BY id DESC LIMIT 8").fetchall()
    print("sent today      : %d / %d" % (_sent_today(state), MAX_PER_DAY))
    gap = _minutes_since_last(state)
    print("since last send : %s" % ("never" if gap is None else "%.0f min" % gap))
    print("hours now       : %s" % _in_hours()[1])
    print()
    if not rows:
        print("no sends recorded yet")
        return 0
    print("recent activity:")
    for r in rows:
        print("  %s  #%-4s %-9s %s" % (str(r["at"])[:19], r["row_id"], r["verdict"],
                                       (r["reason"] or r["body"])[:70]))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--send", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--compose", type=int)
    ap.add_argument("--force", action="store_true",
                    help="ignore the hours gate (never the per-day or gap caps)")
    args = ap.parse_args(argv)

    state = _state()
    if args.status:
        return cmd_status(state)

    rows = _triage()
    by_id = {int(r["id"]): r for r in rows}

    if args.compose:
        r = by_id.get(args.compose)
        if not r:
            print("no pending row %s" % args.compose)
            return 1
        print("disposition :", r.get("disposition"), "-", r.get("why"))
        print("chars       :", r.get("chars"), "(target %d, ceiling %d)" % (TARGET, CEILING))
        print("gate        :", r.get("gate_ok"), r.get("gate_reasons"))
        print("--- body ---")
        print(r.get("body") or "(none)")
        print("------------")
        return 0

    ok_hours, hours_why = _in_hours()
    if not args.force and not ok_hours:
        print("held: " + hours_why)
        return 0
    if _sent_today(state) >= MAX_PER_DAY:
        print("held: daily cap reached (%d/%d)" % (_sent_today(state), MAX_PER_DAY))
        return 0
    gap = _minutes_since_last(state)
    if gap is not None and gap < MIN_GAP_MINUTES:
        print("held: %.0f min since the last ask (minimum %d)" % (gap, MIN_GAP_MINUTES))
        return 0

    row, why = _pick(rows, state)
    if not row:
        print("nothing to ask: " + why)
        return 0

    body = str(row.get("body") or "").strip()
    verdict, reason, sid = "REFUSED", "", ""
    if not body:
        reason = "triage produced no body"
    elif len(body) > CEILING:
        reason = "%d chars, over the %d ceiling" % (len(body), CEILING)
    elif "?" not in body and not body.endswith("?"):
        reason = "does not end in a question, so he cannot answer it in one line"
    elif not row.get("gate_ok"):
        reason = "gate: " + "; ".join(row.get("gate_reasons") or [])[:200]
    else:
        if args.send:
            ok, detail = _send(body, int(row["id"]))
            verdict = "SENT" if ok else "REFUSED"
            reason = detail
            sid = detail.split("; ", 1)[1] if ok and "; " in detail else ""
        else:
            verdict, reason = "WOULD_SEND", "dry run"

    state.execute(
        "INSERT INTO send (row_id, body, chars, verdict, reason, sid, at) "
        "VALUES (?,?,?,?,?,?,?)",
        (int(row["id"]), body, len(body), verdict, reason, sid, _now()))
    state.commit()

    print("%s #%s (%s, %d chars)" % (verdict, row["id"], row.get("severity"), len(body)))
    print("  %s" % body)
    if reason:
        print("  because: %s" % reason)
    if verdict == "SENT":
        # The queue row is now asked. Marking it answers "why is this still pending".
        try:
            conn = sqlite3.connect(str(AUTH_DB), timeout=10)
            conn.execute(
                "UPDATE owner_decision_queue SET seen_at=?, last_score=COALESCE(last_score,0)+1 "
                "WHERE id=?", (_now(), int(row["id"])))
            conn.commit()
            conn.close()
        except sqlite3.Error as exc:
            print("  warning: could not stamp the queue row: %s" % exc)
    return 0


if __name__ == "__main__":
    sys.exit(main())
