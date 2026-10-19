#!/usr/bin/env python3
"""reminders-at-risk.py - did the internal-prose guard start silently killing real reminders?

A refused reminder is a reminder he never receives, and a reminder is the one class where "do not
send" can mean "he never learns about it". This counts, over the delivered history, how many
reminder-class texts the GATE would refuse - measured through the gate, i.e. after the relay's
`_rescue_reminder()` has had its chance to rewrite an instruction-shaped reminder into a sentence.

A body is reminder-class when it carries the marker this system's own composer puts on the wire
(a clock glyph, a siren glyph, or the word Reminder at the start).
"""
import sqlite3
import sys

sys.path.insert(0, "/root/bin")
import owner_text_relay as R  # noqa: E402

OWNER = "+18483897895"
a = sqlite3.connect("file:/root/authority.db?mode=ro", uri=True)
rows = a.execute("""
select created_at, coalesce(agent_id,''), body
from sms_log
where to_number=? and direction='outbound'
  and status in ('delivered','sent') and body is not null
order by created_at
""", (OWNER,)).fetchall()

seen = set()
reminders, refused, rescued = [], [], []
for when, agent, body in rows:
    key = (body or "")[:120]
    if key in seen:
        continue
    seen.add(key)
    low = " " + (body or "").lower() + " "
    if not ("\u23f0" in low or "\U0001f6a8" in low or low.lstrip().startswith("reminder")):
        continue
    reminders.append((when, agent, body))
    out, note = R._rescue_reminder(body, OWNER, "cron.reminder")
    if note and "rewritten" in str(note):
        rescued.append((when, note, body, out))
    why = R.internal_prose(out) or R.credential_request(out)
    if why:
        refused.append((when, agent, why, body))

print("distinct reminder-class texts delivered      : %d" % len(reminders))
print("REWRITTEN by the gate (kept, made readable)  : %d" % len(rescued))
print("still REFUSED by the gate (lost)             : %d" % len(refused))
print()
if rescued:
    print("== rescued: what he would now receive instead of nothing")
    for when, note, body, out in rescued[:6]:
        print("  %s  %s" % (when[:16], note))
        print("      WAS: %s" % " ".join((body or "").split())[:110])
        print("      NOW: %s" % " ".join(str(out).split())[:110])
        print()
if refused:
    print("== still lost - each must be rewritten by its own composer")
    for when, agent, why, body in refused:
        print("  %s %-14s %s" % (when[:16], str(agent)[:14], str(why)[:70]))
        print("      %s" % " ".join((body or "").split())[:150])
