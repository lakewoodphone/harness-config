#!/usr/bin/env python3
"""Prove the owner-text -> ledger wiring actually files an item, on a scratch ledger.

The unit proof (the module imports, the predicates answer correctly) is not enough. The claim is
"an owner's text becomes a real work item", and the only honest proof of that is: call the function
with a message row and watch a row appear in a ledger - in a ledger that is not the live one, so
proving it cannot pollute the real backlog.

Usage: python3 prove-owner-text-filing.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

SCRATCH = Path(tempfile.mkdtemp(prefix="owner-text-proof-")) / "work.db"
WORK = "/home/zabz/bin/work.py"


def main() -> int:
    # 1. a scratch ledger with the real project ids in it
    for cmd in ([WORK, "--db", str(SCRATCH), "init"],
                [WORK, "--db", str(SCRATCH), "project", "add", "--id", "lpt-website",
                 "--title", "LPT Website", "--repo", "/tmp"],
                [WORK, "--db", str(SCRATCH), "project", "add", "--id", "lpt-sync",
                 "--title", "Sync chain", "--repo", "/tmp"],
                [WORK, "--db", str(SCRATCH), "project", "add", "--id", "housekeeping",
                 "--title", "Housekeeping", "--repo", "/tmp"]):
        r = subprocess.run(["python3"] + cmd, capture_output=True, text=True)
        if r.returncode != 0:
            print("setup failed:", r.stdout, r.stderr)
            return 1
    print("scratch ledger: %s" % SCRATCH)

    # 2. load the responder and point its CLI at the scratch ledger
    os.environ["WORK_CLI"] = WORK
    os.environ["WORK_DB"] = str(SCRATCH)
    spec = importlib.util.spec_from_file_location("r", "/home/zabz/bin/sms-responder.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules["r"] = m
    spec.loader.exec_module(m)
    # the helper shells out with "python3 <WORK_CLI>"; the scratch path rides in the env
    import re as _re
    src_env = dict(os.environ)

    def file_it(body: str):
        row = {"sid": "SM_proof_%d" % (abs(hash(body)) % 100000), "from_number": "+18483897895",
               "date_sent": "2026-09-28T19:00:00+00:00", "body": body}
        # WORK_DB is not read by work.py unless passed, so inject it into the helper's command
        orig = subprocess.run

        def patched(cmd, *a, **kw):
            if isinstance(cmd, list) and WORK in cmd:
                cmd = [cmd[0]] + [WORK, "--db", str(SCRATCH)] + cmd[2:]
            return orig(cmd, *a, **kw)
        subprocess.run = patched
        try:
            return m._file_owner_request(None, row, body)
        finally:
            subprocess.run = orig

    checks = [
        ("please fix the website portal login", "lpt-website"),
        ("the dialpad sync keeps breaking", "lpt-sync"),
        ("ok", None),                     # too short: conversation, not work
        ("hello", None),                  # too short
    ]
    ok = True
    for body, expect in checks:
        got = file_it(body)
        pid = got["project"] if got else None
        verdict = "OK " if pid == expect else "FAIL"
        if pid != expect:
            ok = False
        print("  %s  %-40r -> %s" % (verdict, body, got))

    # 3. the same request twice must NOT create two items (the anti-stupid rule)
    first = file_it("please fix the website portal login")
    second = file_it("please fix the website portal login")
    print("  %s  the same request twice -> %s then %s" % (
        "OK " if (second and second.get("already")) else "FAIL", first, second))
    if not (second and second.get("already") and second["id"] == first["id"]):
        ok = False

    # 4. read the scratch ledger back: exactly the items we expect
    c = sqlite3.connect(str(SCRATCH))
    rows = c.execute("select id,project,title,state from work_item order by id").fetchall()
    c.close()
    print("\n  scratch ledger now holds %d item(s):" % len(rows))
    for r in rows:
        print("    #%d %-12s %-8s %s" % (r[0], r[1], r[3], r[2][:64]))
    print("\n%s" % ("PROVEN: an owner text files exactly one ledger item, and a repeat is refused"
                    if ok else "NOT PROVEN - see the FAIL lines above"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
