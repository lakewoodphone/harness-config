#!/usr/bin/env python3
"""One-off: reconcile the retired journal/QUESTIONS.md into owner_decision_queue.

Run on the authority. Only the rows that are genuinely the owner's are added; the
rest are dev decisions (mine) or already answered, and are recorded as such in
journal/archive/README.md. Idempotent by a marker in `source`.
"""
import sqlite3
import os
import sys

DB = os.environ.get("OWNER_QUEUE_DB") or "/home/zabz/personal-secretary-mvp/data/secretary.db"
if not os.path.exists(DB):
    DB = next((p for p in ("/home/zabz/personal-secretary-mvp/data/secretary.db",
                           "/home/zabz/data/secretary.db",
                           "/home/zabz/secretary.db") if os.path.exists(p)), None)

ROWS = [
    dict(
        question="**The company has delivered nothing to you since 2026-07-19.** "
                 "296 messages are 'held', the newest 'sent' row is 2026-07-19T02:32Z, and your own "
                 "2026-09-11 kill-switch decision (SMS off) is being honoured by a system that then says "
                 "nothing at all — including 6,284 consecutive Google Voice auth failures and a Telnyx "
                 "negative balance. Which channel should reach you?",
        recommendation="Let me build the internal badge first (free, silent, no permission needed) and "
                       "bring you a measured recommendation for the outbound channel with real volume "
                       "numbers, rather than wiring SMS back on tonight.",
        options="internal badge only, and I measure for a week |badge plus an SMS when something is CRITICAL, "
                "costed per message |badge plus one daily email digest at a fixed hour",
        severity="critical",
        source="journal/QUESTIONS.md (retired) row 56 'How should a finding reach you' + P55, reconciled 2026-09-14",
        blocks="any finding reaching the owner at all",
        age_days=3,
    ),
    dict(
        question="**The email reply loop has never once completed.** 292 drafts have been written for you, "
                 "3 have ever been sent, none in 30 days, and 36 currently sit in pending_review — already "
                 "created in Gmail's Drafts folder, most from the last two weeks. Nothing surfaces them.",
        recommendation="I open Gmail's drafts and hold each one up to you in batches: you say send, edit, "
                       "or kill, one at a time, and nothing sends without your word.",
        options="walk the 36 drafts with you one at a time (recommended) |one digest of all 36, and you "
                "triage from the list |stop auto-drafting until a review surface exists",
        severity="high",
        source="journal/QUESTIONS.md (retired) row 14, reconciled 2026-09-14",
        blocks="customer replies, and the value of every future draft",
        age_days=3,
    ),
    dict(
        question="**Yocheved's machine: may her assistant WRITE customer records in week one, or only read "
                 "them?** Her box is now the LPT manager workstation. Technical blockers are solved and the "
                 "rails are in (workspace-write only, cannot push to the company repo, every commit "
                 "machine-tagged). How far her write access reaches on real customer data is your call.",
        recommendation="Read-only customer data for the first week — she can look up any customer, job, "
                       "part or price, and asks for changes; I enable writes once you have watched a week.",
        options="read-only customer data week one (recommended) |full read/write from day one, every edit "
                "tagged as from her machine |read-only forever, edits only through the existing shop app",
        severity="high",
        source="journal/QUESTIONS.md (retired) row 57, reconciled 2026-09-14",
        blocks="Yocheved's day-one usefulness",
        age_days=0,
    ),
    dict(
        question="**May the Home Assistant app on your iPhone have your location?** You asked me to know "
                 "when you are home and when you are at the office. Today "
                 "`sensor.iphone_15_location_permission` reads 'Not determined', so the GPS tracker has no "
                 "coordinates. Your other device reports fine, and the delivery path is already built.",
        recommendation="Grant it — HA app, Settings, Companion app, Location, Always, with Precise Location "
                       "on — and I learn your home from the first fix so you never type an address.",
        options="grant it, Always + Precise (recommended) |leave it off, I keep using network signals only "
                "(which can say 'not at the shop' but never 'at home') |grant it, and I store nothing",
        severity="medium",
        source="journal/QUESTIONS.md (retired) row 52, reconciled 2026-09-14",
        blocks="presence-aware behaviour, and the home/office distinction",
        age_days=3,
    ),
    dict(
        question="**What should happen to Google Voice?** Your two GV lines (`+17325691594` = "
                 "eliyahuzabrowsky, `+17329943420`) are still `OWNER_PHONE_NUMBER`, and GV monitoring has "
                 "6,284 consecutive auth failures with nothing delivered through it since 2026-07-02. "
                 "Re-login needs a browser transport the headless host does not have.",
        recommendation="Keep the numbers, stop using GV as a delivery path, and let me repair monitoring "
                       "with CDP over the tailnet as one bounded job — nothing is cancelled and no number "
                       "is lost.",
        options="repair monitoring over CDP, keep the numbers (recommended) |retire GV as a delivery path "
                "entirely and move to a paid number |leave it exactly as is until you decide",
        severity="high",
        source="journal/QUESTIONS.md (retired) row 61, reconciled 2026-09-14",
        blocks="every outbound SMS and the voicemail/call harvest",
        age_days=0,
    ),
]


def main() -> int:
    if not DB:
        print("no database found")
        return 1
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    added = skipped = 0
    for r in ROWS:
        # idempotent: the reconciled rows all carry this marker in `source`
        exists = con.execute(
            "SELECT id FROM owner_decision_queue WHERE source LIKE ?",
            ("journal/QUESTIONS.md (retired)%",),
        ).fetchall()
        marker = r["source"]
        dup = [e for e in exists if con.execute(
            "SELECT 1 FROM owner_decision_queue WHERE source=? AND question=?",
            (marker, r["question"])).fetchone()]
        if dup:
            skipped += 1
            continue
        cur = con.execute(
            """INSERT INTO owner_decision_queue
               (asked_at, question, context, options_json, recommendation, severity,
                blocks, source, age_days, status)
               VALUES (datetime('now'),?,?,?,?,?,?,?,?, 'pending')""",
            (r["question"], None, __import__("json").dumps(r["options"].split("|")),
             r["recommendation"], r["severity"], r["blocks"], r["source"], r["age_days"]),
        )
        print(f"queued #{cur.lastrowid} [{r['severity']}] {r['question'][:70]}")
        added += 1
    con.commit()
    print(f"\nadded={added} skipped={skipped}")
    pend = con.execute("SELECT COUNT(*) FROM owner_decision_queue WHERE status='pending'").fetchone()[0]
    print(f"pending now: {pend}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
