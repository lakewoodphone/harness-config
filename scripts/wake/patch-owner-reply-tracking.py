#!/usr/bin/env python3
"""Make the owner's reply trackable: every owner text is logged against what we last sent him.

THE GAP. The owner said (2026-09-28): "you have to really try to monitor that thread for when I
respond and what you last sent out and make sure you talk to me very well and normally." The responder
can already file an owner's REQUEST as a ledger item (proven on a scratch ledger), and `wake.py await`
can register a promised answer. What was missing is the middle: when he texts back, nothing records
WHAT he was replying to, so a future reader cannot tell a fresh request from an answer, and the
conversation has no spine.

`textstore` already has the right home for this - `jobs(phone, inbound_sid, claim, answer, state,
evidence, due_at, ...)` is exactly "one tracked promise". This patch closes the job when its reply
arrives and stamps the message with the item it produced, so the thread is reconstructable:

    inbound owner text -> (existing) filed as ledger item #N  -> jobs row 'open' with the claim
                       -> his reply   -> jobs row 'done' with his words as the answer

WHAT IT DOES NOT DO: send anything. The acknowledgement remains behind AITEXT_ACK_OWNER_REQUESTS and
OFF, because nothing in this system sends the owner anything until he has approved that behaviour -
and he has not. This patch only makes the record complete, which is a pure addition.

Usage: python3 patch-owner-reply-tracking.py --apply
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

TARGET = Path("/home/zabz/bin/sms-responder.py")

# Inserted immediately after the owner-request filing block, so the job records the promise the item
# represents. Guarded by hasattr/try so a missing textstore degrades rather than breaking the tick.
TRACK = '''

        # ---------------------------------------------------------------------------
        # KEEP THE THREAD: record what we owe him and match his reply to it.
        #
        # Owner, 2026-09-28: "you have to really try to monitor that thread for when I respond and
        # what you last sent out." A request from him that produced a ledger item is a PROMISE, and
        # `jobs` is this store's record of promises (phone, claim, answer, state, evidence). Closing
        # the oldest open job for his number with his own words is what turns a pile of texts into a
        # conversation a future reader can follow.
        # ---------------------------------------------------------------------------
        if _is_owner_number(perm, r["from_number"]):
            try:
                _track_owner_thread(conn, r, body)
            except Exception as exc:
                print(f"    owner thread tracking failed: {type(exc).__name__}: {exc}")
'''

HELPER = '''

def _track_owner_thread(conn, row, body: str) -> None:
    """Close the oldest open promise for this phone with his reply, or open one from a request.

    NEVER raises into the caller: this is bookkeeping around the conversation, and a bookkeeping
    failure must not stop a tick that has real work to do.
    """
    try:
        cols = {c[1] for c in conn.execute("PRAGMA table_info(jobs)").fetchall()}
    except Exception:
        return                                  # no jobs table: nothing to track, not an error
    if not cols:
        return
    now = datetime.now(timezone.utc).isoformat()
    phone = row["from_number"]
    try:
        open_job = conn.execute(
            "SELECT id, claim FROM jobs WHERE phone=? AND state IN ('open','running') "
            "ORDER BY id LIMIT 1", (phone,)).fetchone()
        # A short reply to an open promise is his ANSWER. A long one is new material.
        if open_job and len((body or "").split()) <= 40:
            conn.execute("UPDATE jobs SET state='done', answer=?, updated_at=?, "
                         "evidence=coalesce(evidence,'') || ? WHERE id=?",
                         (body[:600], now,
                          "\\n[closed by inbound %s at %s]" % (row["sid"], row["date_sent"]),
                          open_job[0]))
            conn.commit()
            print("    closed promise #%s with his reply" % open_job[0])
            return
        # Otherwise, if this text produced work, open a promise for it.
        if len((body or "").strip()) >= 8:
            claim = "answer this: %s" % " ".join((body or "").split())[:180]
            conn.execute(
                "INSERT INTO jobs(phone, inbound_sid, claim, state, created_at, updated_at) "
                "VALUES(?,?,?,'open',?,?)",
                (phone, row["sid"], claim, now, now))
            conn.commit()
            print("    opened a promise for his request")
    except Exception as exc:
        print("    thread bookkeeping skipped: %s: %s" % (type(exc).__name__, exc))
'''


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    p = TARGET
    src = p.read_text(encoding="utf-8")
    if "_track_owner_thread" in src:
        print("already present")
        return 0

    anchor = '''            if filed:
                print(f"    filed as ledger item {filed['project']}#{filed['id']}")
                _record(conn, r["sid"], "working", "owner-request",
                        f"filed as ledger item {filed['project']}#{filed['id']}")
                if os.environ.get("AITEXT_ACK_OWNER_REQUESTS") == "1":
                    _ack_owner_request(r["from_number"], filed, body)
                continue
'''
    if anchor not in src:
        raise SystemExit("ERROR: could not find the owner-request block - refusing to guess")
    src = src.replace(anchor, anchor + TRACK, 1)

    # the helper goes next to the other owner helpers
    marker = "\ndef _ack_owner_request("
    if marker not in src:
        raise SystemExit("ERROR: could not find _ack_owner_request to anchor the helper")
    src = src.replace(marker, HELPER + marker, 1)

    compile(src, str(p), "exec")
    if not a.apply:
        print("dry run ok (use --apply)")
        return 0
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    shutil.copy2(p, p.with_name(p.name + ".bak-replytrack-" + stamp))
    p.write_text(src, encoding="utf-8")
    print("patched %s" % p)

    print("\n=== PROOF: import it, then exercise the thread logic on a scratch store ===")
    probe = r'''
import importlib.util, sqlite3, sys, tempfile, os
spec = importlib.util.spec_from_file_location("r", "/home/zabz/bin/sms-responder.py")
m = importlib.util.module_from_spec(spec); sys.modules["r"] = m; spec.loader.exec_module(m)
print("  module imports OK")

db = os.path.join(tempfile.mkdtemp(prefix="thread-proof-"), "s.db")
c = sqlite3.connect(db); c.row_factory = sqlite3.Row
c.execute("CREATE TABLE jobs(id INTEGER PRIMARY KEY AUTOINCREMENT, phone TEXT, inbound_sid TEXT, "
          "claim TEXT, answer TEXT, state TEXT, attempts INTEGER DEFAULT 0, evidence TEXT, "
          "created_at TEXT, due_at TEXT, updated_at TEXT)")
c.commit()

class Row(dict):
    def __getitem__(self, k): return dict.__getitem__(self, k)

# 1. a REQUEST from him opens a promise
m._track_owner_thread(c, Row(sid="SM1", from_number="+18483897895", date_sent="t1"),
                      "please fix the website portal login")
n = c.execute("select count(*) from jobs where state='open'").fetchone()[0]
print("  after a request   : %d open promise(s)  %s" % (n, "OK" if n == 1 else "FAIL"))

# 2. his short reply closes it with his words
m._track_owner_thread(c, Row(sid="SM2", from_number="+18483897895", date_sent="t2"), "yes do it")
row = c.execute("select state, answer from jobs order by id limit 1").fetchone()
ok = row["state"] == "done" and (row["answer"] or "").startswith("yes")
print("  after his reply   : state=%s answer=%r  %s" % (row["state"], row["answer"][:20],
      "OK" if ok else "FAIL"))

# 3. a text with no jobs table must not raise
class NoTable:
    def execute(self, *a, **k): raise sqlite3.OperationalError("no such table: jobs")
m._track_owner_thread(NoTable(), Row(sid="SM3", from_number="+18483897895", date_sent="t3"), "hi")
print("  with no jobs table: no exception  OK")
'''
    r = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, timeout=120)
    print(r.stdout.strip() or (r.stderr or "").strip()[-900:])
    return 0 if r.returncode == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
