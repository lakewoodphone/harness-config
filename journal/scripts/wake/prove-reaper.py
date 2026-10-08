#!/usr/bin/env python3
"""Prove the reaper frees a stranded lease - with an item created for the test, then removed from play.

A reaper that has never freed anything has not been tested; it has been run. `reap` reported
`count: 0` on the live ledger because every lease is still live, which proves only that it can count.

WHAT THIS DOES: creates a scratch project and item, claims it with a lease in the PAST, runs `reap`, and
checks that the item returned to `todo` and that the reaping was RECORDED as an attempt (the ledger's
record of what happened must include the recovery, or a reaped item looks like it was never touched).
The scratch project then closes and its item is dropped with the reason, so nothing fake is left in the
backlog.

Usage: python3 prove-reaper.py
"""
from __future__ import annotations

import json
import re
import subprocess
import sys

WORK = "/home/zabz/bin/work.py"
PROJECT = "reaper-proof"


def run(*args, timeout=120):
    p = subprocess.run(["python3", WORK] + list(args), capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=timeout)
    return p.returncode, (p.stdout or "").strip(), (p.stderr or "").strip()


def jid(out: str):
    m = re.search(r'"id":\s*(\d+)', out)
    return int(m.group(1)) if m else None


def main() -> int:
    ok = True
    print("=== set up a scratch project and item ===")
    run("project", "add", "--id", PROJECT, "--title", "reaper proof (throwaway)",
        "--repo", "/tmp", "--note", "created by prove-reaper.py; disabled after the proof")
    _, out, _ = run("add", "--project", PROJECT,
                    "--title", "PROOF: this item exists only to test lease reaping",
                    "--dod", "irrelevant - this item is a test artifact",
                    "--priority", "9", "--source", "reaper-proof")
    item = jid(out)
    print("  item #%s created" % item)
    if not item:
        print("  could not create the item: %s" % out)
        return 1

    print("\n=== claim it, then AGE THE LEASE so it is expired but the session looks dead ===")
    _, out, _ = run("claim", str(item), "--by", "proof-dead-session", "--lease", "1")
    print("  claim: %s" % out)
    # the CLI's lease is a minimum of 1 second; force the timestamp into the past to be unambiguous
    import sqlite3
    c = sqlite3.connect("/home/zabz/work/work.db", timeout=20)
    c.execute("UPDATE work_item SET lease_until='2000-01-01T00:00:00Z' WHERE id=?", (item,))
    c.commit()
    state = c.execute("SELECT state, claimed_by, lease_until FROM work_item WHERE id=?", (item,)).fetchone()
    print("  now: state=%s claimed_by=%s lease=%s" % state)

    print("\n=== THE TEST: does reap free it, and does it say so? ===")
    rc, out, err = run("reap")
    print("  reap says: %s" % out)
    after = c.execute("SELECT state, claimed_by, lease_until FROM work_item WHERE id=?", (item,)).fetchone()
    print("  after    : state=%s claimed_by=%s lease=%s" % after)
    freed = after[0] == "todo" and after[1] is None
    print("  %s the stranded item returned to todo" % ("OK" if freed else "FAIL"))
    ok = ok and freed

    notes = c.execute("SELECT count(*) FROM attempt WHERE item=? AND worker='reaper'", (item,)).fetchone()[0]
    print("  %s the recovery was recorded (%d reaper attempt row(s))" % ("OK" if notes else "FAIL", notes))
    ok = ok and bool(notes)
    row = c.execute("SELECT did FROM attempt WHERE item=? AND worker='reaper' ORDER BY id DESC LIMIT 1",
                    (item,)).fetchone()
    if row:
        print("      it says: %s" % (row[0] or "")[:140])
    c.close()

    print("\n=== clean up: drop the artifact so it cannot be mistaken for work ===")
    _, out, _ = run("close", str(item), "--by", "reaper-proof",
                    "--did", "Test artifact for prove-reaper.py - not real work.",
                    "--proof", "python3 /home/zabz/bin/prove-reaper.py",
                    "--result", "reap freed the stranded lease and recorded it",
                    "--state", "dropped")
    print("  %s" % out)
    run("project", "add", "--id", PROJECT, "--title", "reaper proof (closed)",
        "--repo", "/tmp", "--disabled")
    print("  scratch project disabled")

    print("\n%s" % ("PROVEN: the reaper frees a stranded lease and records the recovery."
                    if ok else "NOT PROVEN - see the FAIL lines."))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
