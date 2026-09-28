#!/usr/bin/env bash
# THE LEAN BRIDGE PROOF. The full-database copy proved impractical: /tmp is a 12 GB RAM-backed tmpfs and the
# app database is 12 GB, so the copy cannot fit there (that was the `disk I/O error`), and in /home/zabz a
# full VACUUM INTO of 12 GB takes minutes. So prove the bridge with a MINIMAL app database carrying only the
# `sms_log` table - which is all the mirror reads - plus a copy of the inbox, which is 2.6 MB.
#
# WHAT THIS PROVES: a new inbound row lands in the app store, the REAL mirror moves it into the REAL inbox
# schema, it appears as state='new', the REAL responder worklist selects it, and a second run inserts
# nothing. Production is only ever READ.
set -u
date -u
T=/home/zabz/_leanproof-$$
mkdir -p "$T"
APP="$T/app.db"
INBOX="$T/inbox.db"

echo "=== minimal app db: only sms_log, schema taken from the real table ==="
python3 - "$APP" <<'PY'
import sqlite3, sys
src = sqlite3.connect("file:/home/zabz/personal-secretary-mvp/data/secretary.db?mode=ro", uri=True, timeout=60)
ddl = src.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='sms_log'").fetchone()[0]
dst = sqlite3.connect(sys.argv[1])
dst.execute(ddl)
rows = src.execute("SELECT * FROM sms_log").fetchall()
cols = [d[0] for d in src.execute("SELECT * FROM sms_log LIMIT 1").description]
dst.executemany("INSERT INTO sms_log VALUES (%s)" % ",".join("?" * len(cols)), rows)
dst.commit()
print("  sms_log copied: %d rows, %d columns" % (len(rows), len(cols)))
src.close(); dst.close()
PY

echo
echo "=== inbox copy (2.6 MB) ==="
python3 - "$INBOX" <<'PY'
import os, sqlite3, sys
s = sqlite3.connect("file:/home/zabz/.sms-inbox/inbox.db?mode=ro", uri=True, timeout=30)
s.execute("VACUUM INTO ?", (sys.argv[1],))
s.close()
print("  inbox copied: %s bytes" % os.path.getsize(sys.argv[1]))
PY

echo
echo "=== a NEW inbound row arrives in the app copy, as his text would ==="
python3 - "$APP" <<'PY'
import datetime, sqlite3, sys, time
c = sqlite3.connect(sys.argv[1], timeout=20)
now = datetime.datetime.now(datetime.timezone.utc).isoformat()
sid = "SM_leanproof_%d" % int(time.time())
c.execute("INSERT INTO sms_log (twilio_sid, direction, from_number, to_number, body, status, agent_id, "
          "created_at, updated_at, template_id, error_message) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
          (sid, "inbound", "+18483897895", "+17324447361",
           "the lpt website portal login is broken again, please look", "received", "orchestrator",
           now, now, None, None))
c.commit(); c.close()
print("  inserted %s" % sid)
PY

echo
echo "=== run the REAL mirror against the copies ==="
SMS_MIRROR_APP_DB="$APP" SMS_INBOX_DB="$INBOX" \
  python3 /home/zabz/bin/mirror-owner-sms.py --apply 2>&1 | sed 's/^/  /'

echo
echo "=== the row in the inbox copy, in the schema the responder reads ==="
sqlite3 "$INBOX" "select '  '||sid||' | '||direction||' | '||from_number||' | state='||state||' | '||substr(body,1,46) from messages where sid like 'SM_leanproof%';"

echo
echo "=== THE RESPONDER'S OWN worklist() OVER THAT COPY - the decisive check ==="
SMS_INBOX_DB="$INBOX" python3 - "$INBOX" <<'PY'
import importlib.util, sqlite3, sys
spec = importlib.util.spec_from_file_location("resp", "/home/zabz/bin/sms-responder.py")
m = importlib.util.module_from_spec(spec)
sys.modules["resp"] = m
spec.loader.exec_module(m)
conn = sqlite3.connect(sys.argv[1])
conn.row_factory = sqlite3.Row
rows = m.worklist(conn, None, 5)
print("  worklist returned %d row(s)" % len(rows))
for r in rows:
    print("    %s  %s -> %s  %s" % (r["date_sent"][:19] if r["date_sent"] else "?",
                                    r["from_number"], r["to_number"], (r["body"] or "")[:44]))
ok = any("leanproof" in (r["sid"] or "") for r in rows)
print("  %s the mirrored row is SELECTED by the responder's own worklist" % ("PROVEN:" if ok else "FAIL:"))
conn.close()
PY

echo
echo "=== IDEMPOTENCE: a second mirror run must insert nothing ==="
SMS_MIRROR_APP_DB="$APP" SMS_INBOX_DB="$INBOX" \
  python3 /home/zabz/bin/mirror-owner-sms.py --apply 2>&1 | grep -E "to insert|already present" | sed 's/^/  /'

echo
echo "=== cleanup, and confirm production was never written ==="
rm -rf "$T" && echo "  removed $T"
printf "  live app rows with a proof sid   : %s\n" "$(sqlite3 /home/zabz/personal-secretary-mvp/data/secretary.db "select count(*) from sms_log where twilio_sid like 'SM_leanproof%' or twilio_sid like 'SM_bridgeproof%';")"
printf "  live inbox awaiting a decision   : %s\n" "$(sqlite3 /home/zabz/.sms-inbox/inbox.db "select count(*) from messages where direction='inbound' and state='new';")"
printf "  live app sms_log row count       : %s\n" "$(sqlite3 /home/zabz/personal-secretary-mvp/data/secretary.db 'select count(*) from sms_log;')"
