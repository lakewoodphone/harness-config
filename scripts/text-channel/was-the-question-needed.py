#!/usr/bin/env python3
"""was-the-question-needed.py - of every question the CFO sent, how many did our own records
answer anyway, and how many did he leave completely unanswered?

If a question is later resolved by auto_resolved, then asking it was never necessary: the answer
was in our records at the time the asker chose not to look. That count is the size of the defect.
"""
import sqlite3

s = sqlite3.connect("file:/root/.cfo-asks/asks.db?mode=ro", uri=True)

total = s.execute("select count(*) from ask").fetchone()[0]
sent = s.execute("select count(*) from ask where sent=1").fetchone()[0]
auto = s.execute("select count(*) from ask where coalesce(auto_resolved,0)=1").fetchone()[0]
resolved = s.execute("select count(*) from ask where resolved_at is not null").fetchone()[0]
answered = s.execute("select count(*) from ask where answered_at is not null").fetchone()[0]
unanswered = total - answered
refused = s.execute("select count(*) from ask where coalesce(provider_ok,1)=0").fetchone()[0]

print("THE CFO ASK STORE — 66 rows, the whole history")
print("  rows                       %3d" % total)
print("  actually sent to him       %3d" % sent)
print("  provider refused it        %3d" % refused)
print("  he answered                %3d" % answered)
print("  he never answered          %3d  (%.0f%% of what he was sent)"
      % (unanswered, 100.0 * unanswered / sent if sent else 0))
print("  resolved by our own records %3d  (auto_resolved)" % auto)
print("  resolved at all            %3d" % resolved)

print()
print("  questions that were never needed because the answer was already ours:")
print("    %d of %d sent (%.0f%%)"
      % (auto, sent, 100.0 * auto / sent if sent else 0))

print()
print("  the 57 unanswered, by merchant (the tail he is actually being asked about)")
for r in s.execute("""
select coalesce(merchant,'(none)') m, count(*) n
from ask where answered_at is null
group by 1 order by 2 desc limit 12
"""):
    print("    %-46s %d" % (str(r[0])[:46], r[1]))

print()
print("BACKLOG, for scale")
acc = sqlite3.connect("file:/root/accounting-data/live/accounting.db?mode=ro", uri=True)
unc = acc.execute("""select count(*) from transactions t
where not exists (select 1 from transaction_categories tc
                  where tc.transaction_id=t.id)""").fetchone()[0]
tot = acc.execute("select count(*) from transactions").fetchone()[0]
print("  %d uncategorised of %d (%.2f%%)" % (unc, tot, 100.0 * unc / tot))
print("  ratio: %.1f questions asked per uncategorised charge"
      % (sent / unc if unc else 0))
