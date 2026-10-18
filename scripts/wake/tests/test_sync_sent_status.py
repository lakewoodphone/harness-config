#!/usr/bin/env python3
"""Prove the write-back on a throwaway pair of stores. Never touches production.

Builds two temp databases with the real schemas, six rows that cover every branch, runs the
sync twice, and asserts the exact counts. Exits non-zero on any deviation, so it is a gate.
"""
import os
import sqlite3
import subprocess
import sys
import tempfile

SCRIPT = "/root/bin/sync-sent-status-to-app.py"

APP_SCHEMA = """CREATE TABLE sms_log (
  id INTEGER PRIMARY KEY, twilio_sid TEXT, direction TEXT, from_number TEXT, to_number TEXT,
  body TEXT, template_id INTEGER, status TEXT, error_message TEXT, agent_id INTEGER,
  created_at TEXT, updated_at TEXT);"""

MIR_SCHEMA = """CREATE TABLE messages (
  sid TEXT, direction TEXT, from_number TEXT, to_number TEXT, body TEXT, date_sent TEXT,
  status TEXT, num_media INTEGER, price TEXT, first_seen TEXT, app_has_it INTEGER);"""

CASES = [
    ("SM_A", "outbound", "queued",    "delivered"),   # change
    ("SM_B", "outbound", "queued",    "failed"),      # change
    ("SM_C", "outbound", "delivered", "delivered"),   # already same
    ("SM_D", "outbound", "delivered", "failed"),      # CONFLICT, left alone
    ("SM_E", "outbound", "queued",    None),          # no mirror row
    ("SM_F", "outbound", "queued",    ""),            # mirror not terminal
    ("SM_G", "inbound",  "received",  "delivered"),   # out of scope
    ("SM_I", "outbound", "sent",      "delivered"),   # an upgrade, not a conflict
]

d = tempfile.mkdtemp(prefix="syncproof-")
app_p, mir_p = os.path.join(d, "app.db"), os.path.join(d, "mirror.db")

app = sqlite3.connect(app_p); app.executescript(APP_SCHEMA)
mir = sqlite3.connect(mir_p); mir.executescript(MIR_SCHEMA)
for sid, direction, app_status, mir_status in CASES:
    app.execute("INSERT INTO sms_log (twilio_sid,direction,status,created_at,updated_at)"
                " VALUES (?,?,?,'2026-10-01T00:00:00+00:00','2026-10-01T00:00:00+00:00')",
                (sid, direction, app_status))
    if mir_status is not None:
        mir.execute("INSERT INTO messages (sid,direction,status) VALUES (?,?,?)",
                    (sid, direction, mir_status))
app.commit(); mir.commit()
# A row from the 2026-08-30 Twilio-retirement relabel: sms_log says failed for an explained
# reason while the mirror holds Twilio's delivered verdict. It must be NAMED, not reported as
# an unexplained conflict.
app.execute("INSERT INTO sms_log (twilio_sid,direction,status,error_message,created_at,updated_at)"
            " VALUES ('SM_H','outbound','failed',?, '2026-02-17T00:00:00+00:00','2026-08-30T00:00:00+00:00')",
            ("S3b 2026-08-30: Twilio outbound retired (no from-number configured). Message never"
             " delivered; kept as audit record.",))
mir.execute("INSERT INTO messages (sid,direction,status) VALUES ('SM_H','outbound','delivered')")
app.commit(); mir.commit()
app.close(); mir.close()

def run(*extra):
    p = subprocess.run([sys.executable, SCRIPT, "--db", app_p, "--mirror", mir_p, *extra],
                       capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr

rc, out = run()
print(out.strip())
fail = 0
for needle in ("to_change=3", "retired_relabel=1", "conflicts=1", "already_same=1",
               "no_mirror_row=1", "mirror_not_terminal=1", "dry run: nothing written"):
    if needle not in out:
        print("FAIL: expected %r in the dry run" % needle); fail += 1
if rc != 0:
    print("FAIL: dry run rc=%d" % rc); fail += 1

rc, out = run("--apply")
print("\n" + out.strip())
if "wrote 3 status update(s)" not in out:
    print("FAIL: expected 3 writes"); fail += 1

rc, out2 = run("--apply")
print("\nSECOND APPLY (must be a no-op):\n" + out2.strip())
if "wrote 0 status update(s)" not in out2:
    print("FAIL: second apply was not idempotent"); fail += 1

app = sqlite3.connect(app_p)
got = dict(app.execute("SELECT twilio_sid, status FROM sms_log").fetchall())
app.close()
expect = {"SM_A": "delivered", "SM_B": "failed", "SM_C": "delivered",
          "SM_D": "delivered", "SM_E": "queued", "SM_F": "queued", "SM_G": "received",
          "SM_H": "failed", "SM_I": "delivered"}   # the known class is named, never overwritten
for k, v in expect.items():
    if got.get(k) != v:
        print("FAIL: %s is %r, expected %r" % (k, got.get(k), v)); fail += 1
print("final statuses: %s" % ", ".join("%s=%s" % (k, got.get(k)) for k in sorted(got)))

print("\n%s  %d failure(s)" % ("RESULT: FAIL" if fail else "RESULT: PASS", fail))
print("throwaway stores left at %s (temporary, safe to remove)" % d)
sys.exit(1 if fail else 0)
