#!/usr/bin/env python3
"""Selftest for lpt-reconcile's D1 identity guard (2026-10-27, ledger item 946).

Runs against a COPY of the live ledger, never the live one. Proves the exact defect that closed
item 946 with its work still sitting in an unmerged pull request:

  * an item whose attempt text quotes the INTEGRATION REF'S OWN TIP ("head=<sha>") must NOT be
    reported open-but-landed - that sha is an ancestor of itself, always;
  * the run must still complete and still report the other classes.

Exit 0 = the guard holds. 1 = it does not. 2 = the harness could not run.

  selftest-reconcile-d1.py [--tool PATH]
"""
import json
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path("/root/repos/phone-and-tech-full")
LEDGER = Path("/root/work/work.db")
DEFAULT_TOOL = "/root/bin/lpt-reconcile.py"
SYNTH_ID = 90998


def git(*args):
    return subprocess.run(["git", "-C", str(REPO), *args],
                          capture_output=True, text=True).stdout.strip()


def main() -> int:
    tool = DEFAULT_TOOL
    if "--tool" in sys.argv:
        tool = sys.argv[sys.argv.index("--tool") + 1]
    git("fetch", "--quiet", "origin", "test")
    tip = git("rev-parse", "origin/test")
    if not tip:
        print("SELFTEST: cannot read origin/test from %s" % REPO, file=sys.stderr)
        return 2
    print("origin/test tip  = %s   (tool: %s)" % (tip[:10], tool))

    tmpdir = Path(tempfile.mkdtemp(prefix="reconcile-selftest-"))
    db = tmpdir / "work.db"
    shutil.copy2(LEDGER, db)
    conn = sqlite3.connect(db)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(work_item)")]
    row = {c: None for c in cols}
    row.update({"id": SYNTH_ID, "project": "lpt-website", "title": "SYNTHETIC selftest row",
                "why": "prove the D1 identity guard", "dod": "the selftest exits 0",
                "state": "todo", "priority": 9, "created_at": "2026-10-27T00:00:00Z",
                "updated_at": "2026-10-27T00:00:00Z", "source": "selftest"})
    conn.execute("INSERT INTO work_item(%s) VALUES(%s)" % (
        ",".join(cols), ",".join("?" * len(cols))), [row[c] for c in cols])

    acols = [r[1] for r in conn.execute("PRAGMA table_info(attempt)")]
    arow = {c: None for c in acols}
    arow.update({
        "item": SYNTH_ID, "worker": "selftest", "started_at": "2026-10-27T00:00:01Z",
        "ended_at": "2026-10-27T00:00:02Z", "state_after": "todo", "exit_code": 0,
        "did": "Synthetic: quoted the integration head in my proof, as item 946's last attempt did.",
        "proof": "git -C /root/repos/phone-and-tech-full log -1 origin/test",
        "result": "checkout MATCH branch=test head=%s" % tip[:9],
        "left_over": "nothing - this row exists only to prove the guard",
    })
    if "id" in acols:
        arow["id"] = 990001
    conn.execute("INSERT INTO attempt(%s) VALUES(%s)" % (
        ",".join(acols), ",".join("?" * len(acols))), [arow[c] for c in acols])
    conn.commit()
    conn.close()
    print("synthetic item   = #%d (todo) quoting head=%s in its attempt" % (SYNTH_ID, tip[:9]))

    p = subprocess.run([sys.executable, tool, "--db", str(db), "--json"],
                       capture_output=True, text=True, timeout=900)
    if p.returncode not in (0, 1):
        print("SELFTEST: the tool exited %s\n%s" % (p.returncode, p.stderr[-900:]), file=sys.stderr)
        return 2
    try:
        data = json.loads(p.stdout)
    except json.JSONDecodeError:
        print('SELFTEST: rc=%s stdout was not JSON: %r stderr=%r' % (p.returncode, p.stdout[:300], p.stderr[-300:]), file=sys.stderr)
        return 2
    d1 = [r["id"] for r in data.get("d1_open_but_landed", [])]
    unatt = [r["id"] for r in data.get("d1_landed_but_unattributed", [])]
    print("d1 open-but-landed         = %s" % d1)
    print("d1 landed-but-unattributed = %s" % unatt)
    print("other classes: d2=%d d3=%d d4=%d d5=%d" % (
        len(data.get("d2_box_ticked_but_open", [])), len(data.get("d3_box_unchecked_but_done", [])),
        len(data.get("d4_done_but_not_landed", [])), len(data.get("d5_live_row_no_box", []))))
    ok = SYNTH_ID not in d1
    print("GUARD: synthetic row NOT reported open-but-landed -> %s" % ("PASS" if ok else "FAIL"))
    shutil.rmtree(tmpdir, ignore_errors=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

