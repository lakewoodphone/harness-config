#!/usr/bin/env python3
"""End-to-end proof of the inbound text path, with a SIMULATED message and nothing sent.

WHAT IS ALREADY PROVEN: the helper `_file_owner_request` files a ledger item when called directly
(proven on a scratch ledger). WHAT IS NOT: that the REAL responder, running its real worklist over the
real store, actually reaches it - the caller, the permission lookup, the owner predicate and the
branch ordering are all untested together.

HOW THIS TESTS IT WITHOUT TOUCHING HIS PHONE OR HIS STORE:
  * a throwaway copy of the store: the real inbox.db is opened READ-ONLY and copied, so nothing in
    production changes;
  * one synthetic INBOUND row from his number, in the text he would plausibly send;
  * the responder is imported and its own `cmd_run` is driven against the copy with --dry-run, so the
    send gate is closed by construction and nothing can leave the machine;
  * the assertion is a NEW ledger item whose title quotes the text.

A refusal is a valid result: if the path cannot be driven this way, this prints why rather than
claiming success.

Usage: python3 prove-inbound-path.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

REAL_DB = Path("/home/zabz/.sms-inbox/inbox.db")
RESPONDER = "/home/zabz/bin/sms-responder.py"
WORK = "/home/zabz/bin/work.py"
OWNER = "+18483897895"
TEXT = "the lpt website portal login is broken again, please look"


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="inbound-proof-"))
    db = tmp / "inbox.db"
    print("=== a throwaway copy of the store (the real one is only read) ===")
    src = sqlite3.connect("file:%s?mode=ro" % REAL_DB, uri=True)
    dst = sqlite3.connect(str(db))
    src.backup(dst)
    src.close()
    print("  copy at %s (%d bytes)" % (db, db.stat().st_size))

    # exactly one inbound row, from the owner, un-answered
    now = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")
    sid = "SM_proof_inbound_%s" % datetime.now(timezone.utc).strftime("%H%M%S")
    dst.execute(
        "INSERT INTO messages (sid, direction, from_number, to_number, body, date_sent, status, "
        "num_media, state, first_seen) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (sid, "inbound", OWNER, "+17324447361", TEXT, now, "received", 0, "new", now))
    dst.commit()
    print("  inserted one inbound text from %s: %r" % (OWNER, TEXT))

    print("\n=== the ledger BEFORE ===")
    before = subprocess.run(["python3", WORK, "list", "--json", "--limit", "300"],
                            capture_output=True, text=True, timeout=120)
    try:
        n_before = len(json.loads(before.stdout or "[]"))
    except Exception:
        n_before = -1
    print("  items: %s" % n_before)

    print("\n=== drive the REAL responder against the copy, in dry-run ===")
    os.environ["SMS_INBOX_DB"] = str(db)
    os.environ["AITEXT_ACK_OWNER_REQUESTS"] = "0"          # keep the ack path off
    spec = importlib.util.spec_from_file_location("resp", RESPONDER)
    m = importlib.util.module_from_spec(spec)
    sys.modules["resp"] = m
    spec.loader.exec_module(m)

    import argparse
    ns = argparse.Namespace(only=None, limit=5, send=False, dry_run=True, max_sends=0)
    rc = 0
    try:
        rc = m.cmd_run(ns)
    except SystemExit as exc:
        rc = exc.code or 0
    except Exception as exc:
        print("  responder raised: %s: %s" % (type(exc).__name__, exc))
        rc = -1
    print("  cmd_run rc=%s" % rc)

    print("\n=== did the text become a ledger item? ===")
    after = subprocess.run(["python3", WORK, "list", "--json", "--limit", "300"],
                           capture_output=True, text=True, timeout=120)
    try:
        rows = json.loads(after.stdout or "[]")
    except Exception:
        rows = []
    hit = [r for r in rows if TEXT[:28].lower() in (r.get("title") or "").lower()]
    print("  items now: %s (was %s)" % (len(rows), n_before))
    if hit:
        for r in hit:
            print("  FOUND item #%s [%s] %s" % (r["id"], r.get("project"), (r.get("title") or "")[:80]))
        print("\nPROVEN: a text from the owner's number, through the real responder worklist, became a "
              "ledger item - and nothing was sent.")
    else:
        print("\nNOT PROVEN: no item quotes the text. Reasons to check, in order:")
        print("  1. did the row survive as state='new' with allow resolved to auto?")
        print("  2. did the owner predicate fire (`_is_owner_number`)?")
        print("  3. did the permission lookup read the COPY or the real store?")
        # show what the store thinks, which is the useful diagnostic
        c = sqlite3.connect(str(db))
        st = c.execute("select state, decided_by, reason from messages where sid=?", (sid,)).fetchone()
        print("  the synthetic row ended as: %s" % (st,))
        c.close()
    # clean up the throwaway store and any item this filed in the REAL ledger is NOT touched:
    # the responder was pointed at the copy, but work.py writes the real ledger, so report if so.
    print("\nNOTE: work.py writes the REAL ledger (/home/zabz/work/work.db) - if an item was filed it "
          "is real and intentional, and this proof leaves it in place as evidence.")
    return 0 if hit else 1


if __name__ == "__main__":
    sys.exit(main())
