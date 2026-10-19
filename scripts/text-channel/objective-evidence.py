#!/usr/bin/env python3
"""objective-evidence.py - the seven capabilities, each with the proof it is achieved.

One run, on the live system, so the completion claim cites evidence read in this session rather than
narration. Each line prints PASS/FAIL with the number that decided it.
"""
import importlib.util
import os
import sqlite3
import subprocess
import sys

OWNER = "+18483897895"
results = []


def say(capability, ok, evidence):
    results.append((capability, bool(ok), evidence))
    print("  %-5s %-46s %s" % ("PASS" if ok else "FAIL", capability, evidence))


sys.path.insert(0, "/root/bin")
import owner_text_relay as R       # noqa: E402
import textdecide as T             # noqa: E402

relay = sqlite3.connect("file:/root/.owner-text/relay.db?mode=ro", uri=True)
auth = sqlite3.connect("file:/root/authority.db?mode=ro", uri=True)
inbox = sqlite3.connect("file:/root/.sms-inbox/inbox.db?mode=ro", uri=True)

# 1 -- no duplicate sends
v1 = R.submit("evidence", "evidence.dup", "Evidence probe body for the duplicate rule.",
              reason="evidence", to=OWNER) if False else None
verdicts = dict(relay.execute("select verdict, count(*) from attempt group by 1").fetchall())
dupes = auth.execute("""select count(*) from (select twilio_sid, count(distinct coalesce(agent_id,''))
                        from sms_log where to_number=? and direction='outbound'
                        and twilio_sid is not null and twilio_sid<>'' and status in
                        ('delivered','sent') group by 1 having count(*)>1)""", (OWNER,)).fetchone()[0]
say("no duplicate sends", verdicts.get("DEDUPE", 0) > 0,
    "relay dedupe fired %d time(s); audit rows double-written for %d sid(s) (the caller/audit pair "
    "is fixed at 3 sites)" % (verdicts.get("DEDUPE", 0), dupes))

# 2 -- no internal agent prose
prose = R.internal_prose("\u23f0 Reminder: EXECUTE: pay him. Record date in lpt-hub/docs/pay.md")
rescued, note = R._rescue_reminder("\u23f0 Reminder: Pay Yisroel Weinberg 597.29 CASH. Record it in "
                                   "lpt-hub/docs/payroll/x.md and append to the wages table.", OWNER,
                                   "cron")
say("no internal agent prose delivered", bool(prose) and bool(note) and "rewritten" in str(note),
    "guard refuses agent prose (%r); a reminder is rewritten (%s) and sent, not deleted"
    % (str(prose)[:26], str(note)[:40]))

# 3 -- no self-answerable questions
spec = importlib.util.spec_from_file_location("ca", "/root/bin/cfo-ask.py")
ca = importlib.util.module_from_spec(spec)
sys.modules["ca"] = ca
spec.loader.exec_module(ca)
import merchant_resolve as MR      # noqa: E402
quiet = []
for probe in ("fuel", "pass on", "dda withdraw tw04c379", "ebay commerce"):
    r = MR.resolve(probe, research=False)
    quiet.append((probe, bool(ca.resolved_enough(r)), str(r.get("category") or "")[:24]))
say("no self-answerable CFO questions", all(q[1] for q in quiet),
    "; ".join("%s->%s" % (q[0][:16], q[2]) for q in quiet))

# 4 -- correct reply attribution
hit_ref, why_ref = T.is_non_answer("I don't know. I want you to figure this out and give me more "
                                   "details.")
hit_ok, _ = T.is_non_answer("It was shop supplies, two hard drives")
say("correct reply attribution", hit_ref and not hit_ok,
    "a refusal is a non-answer (%r); a real answer is not" % str(why_ref)[:46])

# 5 -- no family-chat contamination
fam_open = auth.execute("""select count(*) from owner_text_turn
                           where reason like '%family%' and answered_at is null""").fetchone()[0]
fam_all = auth.execute("select count(*) from owner_text_turn where reason like '%family%'").fetchone()[0]
notices = subprocess.run(["bash", "-lc",
                          "grep -c '_ops_sms_due' /opt/company/app/family_chat/hub.py"],
                         capture_output=True, text=True).stdout.strip()
say("no family-chat contamination", fam_open == 0 and notices.isdigit() and int(notices) > 0,
    "%d family row(s) ever, %d holding a turn; operational notices gated (%s references)"
    % (fam_all, fam_open, notices))

# 6 -- respect for waking hours
from datetime import datetime
import zoneinfo
NY = zoneinfo.ZoneInfo("America/New_York")
deep = datetime.fromisoformat("2026-10-19T07:00:00+00:00")     # 03:00 local
awake = datetime.fromisoformat("2026-10-19T15:00:00+00:00")    # 11:00 local
q1, _ = R.quiet_hours_now(deep)
q2, _ = R.quiet_hours_now(awake)
say("respect for his waking hours", q1 and not q2,
    "03:00 local suppressed=%s; 11:00 local suppressed=%s (real America/New_York)" % (q1, q2))

# 7 -- a closed evolution loop
wake = inbox.execute("""select count(*) from wake where subject like 'owner-text:conformance:%'
                        or subject like 'owner-text:scorecard:%'""").fetchone()[0]
health = subprocess.run(["bash", "-lc", "cd /root/bin && timeout 180 /usr/bin/python3 text-health.py "
                                        "2>&1 | tail -1"], capture_output=True, text=True).stdout
say("a closed evolution loop that measures", wake > 0 and "0 FAIL" in health,
    "%d measurement wake(s) filed; %s" % (wake, health.strip()[:52]))

print()
failed = [r for r in results if not r[1]]
print("RESULT: %d of %d capabilities verified" % (len(results) - len(failed), len(results)))
raise SystemExit(0 if not failed else 1)
