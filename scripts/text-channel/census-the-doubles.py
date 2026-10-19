#!/usr/bin/env python3
"""census-the-doubles.py - where else is one event written twice?

The same defect has now been found twice: `sms_log` records one send twice (the audit row and the
caller), and `owner_text_turn` opened a second turn for the same sid whenever the first was already
answered. Both were invisible because each row is individually well-formed; only a count against
the event's identity shows them.

So: for every owner-text table, count each event's identity and report where one event has more than
one row. Read-only.
"""
import sqlite3

AUTH = "/root/authority.db"
RELAY = "/root/.owner-text/relay.db"

queries = [
    # (label, db, sql returning (identity, rows, note))
    ("owner_text_turn  same sid", AUTH, """
        select coalesce(sid,'(no sid)') ident, count(*) n, group_concat(distinct reason) reasons
        from owner_text_turn where coalesce(sid,'') <> ''
        group by 1 having count(*) > 1 order by n desc limit 8"""),
    ("owner_text_turn  same body+second", AUTH, """
        select substr(body,1,50) ident, count(*) n, group_concat(distinct reason) reasons
        from owner_text_turn
        group by body having count(*) > 1 order by n desc limit 8"""),
    ("owner_text_decision same code+head+second", AUTH, """
        select substr(created_at,1,19)||' '||code||' '||substr(coalesce(body_head,''),1,24) ident,
               count(*) n, group_concat(distinct allowed) why
        from owner_text_decision
        group by 1 having count(*) > 1 order by n desc limit 8"""),
    ("owner_message_queue same body", AUTH, """
        select substr(body,1,50) ident, count(*) n, group_concat(distinct status) st
        from owner_message_queue
        group by body having count(*) > 1 order by n desc limit 8"""),
    ("relay attempt   same body+second", RELAY, """
        select substr(at,1,19)||' '||substr(body,1,30) ident, count(*) n,
               group_concat(distinct verdict) v
        from attempt group by 1 having count(*) > 1 order by n desc limit 8"""),
    ("relay attempt   same sid", RELAY, """
        select sid ident, count(*) n, group_concat(distinct verdict) v
        from attempt where coalesce(sid,'') <> ''
        group by 1 having count(*) > 1 order by n desc limit 8"""),
]


def run(label, path, sql):
    try:
        c = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
        rows = c.execute(sql).fetchall()
        c.close()
    except Exception as exc:                                   # noqa: BLE001
        print("  %-42s NOT MEASURED: %s" % (label, exc))
        return
    if not rows:
        print("  %-42s clean" % label)
        return
    print("  %-42s %d event(s) with more than one row" % (label, len(rows)))
    for r in rows[:4]:
        print("       %-58s n=%-4s %s" % (str(r[0])[:58], r[1], str(r[2])[:40]))


print("ONE EVENT, TWO ROWS - sweep over every owner-text table")
print("=" * 100)
for label, path, sql in queries:
    run(label, path, sql)
