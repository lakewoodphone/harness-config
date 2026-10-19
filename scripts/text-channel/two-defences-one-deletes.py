#!/usr/bin/env python3
"""two-defences-one-deletes.py - does the rescue save what tool_factory throws away?

`tool_factory.send_due_reminders` keeps a reminder PENDING instead of texting it when its message
names a path, a file or a task row:

    if re.search(r"(?:lpt-hub|docs/|/home/|~/|\\.md\\b|\\.py\\b|\\btask\\s*#?\\d{3,})", msg):
        remaining.append(r); continue

That was written before the relay could rewrite anything, and dropping was the lesser evil then.
Since 2026-10-19 the relay RESCUES a reminder-class body - it strips the scaffolding and sends the
readable remainder - so dropping now deletes what the gate would have delivered.

This drives both mechanisms over the real reminder bodies and answers one question per body: does
the filter discard something the rescue would have made deliverable?

Read-only.
"""
import re
import sys

sys.path.insert(0, "/root/bin")
import owner_text_relay as R  # noqa: E402

OWNER = "+18483897895"
FILTER = re.compile(r"(?:lpt-hub|docs/|/home/|~/|\.md\b|\.py\b|\btask\s*#?\d{3,})", re.I)

BODIES = [
    "\u23f0 Reminder: VS Code session: present ONE numbered owner-approval ask \u2014 (1) #27836 SD-card SMS, "
    "(2) #27745 Rubin SMS, (3) #27907 Global Direct Parts email, (4) #27888 Seedr. All blocked 2+ days.",
    "\u23f0 Reminder: Pay Yisroel Weinberg 597.29 net CASH settlement (owner decided after Sukkot). "
    "Record date+amount in lpt-hub/docs/operations/payroll/Weinberg-2026-09-28/ and append to the "
    "wages table.",
    "\u23f0 Reminder: NY Tolls by Mail bill 20072952714, account 773667772: 52.36 due and overdue "
    "since 07/31/26 (toll 12.03, already overdue 35.33, late fee 5.00).",
    "\u23f0 Reminder: NJ ST-50 sales tax for 2026 Q3 is due Tue 2026-10-20. Pack ready: taxable sales "
    "25,629.19, tax due 1,697.93. Nothing has been filed.",
    "\u23f0 Reminder: drop the library books - they are in your car. Lakewood branch, 301 Lexington "
    "Ave, open Mon-Thu 9-9. Book drop is fine.",
]

print("%-6s %-7s %-52s %s" % ("FILTER", "RESCUE", "body", "verdict"))
print("-" * 116)
lost = 0
for b in BODIES:
    dropped = bool(FILTER.search(b))
    out, note = R._rescue_reminder(b, OWNER, "cron.reminder")
    rescued = bool(note and "rewritten" in str(note))
    still_refused = bool(R.internal_prose(out))
    if dropped and rescued and not still_refused:
        verdict = "THE FILTER DELETES A REMINDER THE GATE WOULD DELIVER"
        lost += 1
    elif dropped and still_refused:
        verdict = "filter and rescue agree it is not for him"
    elif dropped:
        verdict = "filter drops it; rescue would have kept it as-is"
        lost += 1
    else:
        verdict = "sent either way"
    print("%-6s %-7s %-52s %s"
          % ("DROP" if dropped else "-", "REWRITE" if rescued else "-", b[:52], verdict))

print()
print("BODIES THE FILTER KEEPS PENDING THAT THE GATE WOULD DELIVER: %d" % lost)
