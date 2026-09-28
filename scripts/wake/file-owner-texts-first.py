#!/usr/bin/env python3
"""File the OWNER'S OWN TEXT at priority 1 instead of 3 - at the source, not by a promotion afterwards.

THE FINDING, measured 2026-09-28 23:03Z. `sms-responder.py:_file_owner_request` builds its ledger call with a
HARDCODED priority:

    "--priority", "3", "--source", "owner-sms"

so every request the owner sends by text arrives behind the whole queue. Measured consequence: his 15:57 text
was still unclaimed at 23:01Z, seven hours later, while the log said "filed as housekeeping#52" and looked like
a response. Last round I moved those three items to priority 1 BY HAND with `promote-owner-texts.py` - and
that script is on NO schedule (cron entries: 0, not in the sources chain), so the next text he sends would have
been buried again. Fixing a symptom with a script nobody runs is the same defect this session has found nine
times: a mechanism that is not scheduled does not exist.

WHY p1 AND NOT p0: p0 is the SMS channel's own repair (#8). An owner request is the highest-value work that is
not that channel, so p1 places it above every project and integration item.

WHY THE RESPONDER IS THE RIGHT PLACE: it is the thing that files the item, it already knows the text came from
the owner (that is its whole branch), and it already sets `--source owner-sms`. The priority belongs beside the
source. A separate promoter would also have to win a race against the shift picker, which runs every 15 minutes.

KEPT: the promoter stays, as a repair for items already filed at the wrong priority (and it is idempotent), but
it is no longer load-bearing.

Usage: python3 file-owner-texts-first.py [--apply]
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
OLD = '''           "--why", "%s (message %s from %s at %s)" % (why, row["sid"], row["from_number"], row["date_sent"]),
           "--priority", "3", "--source", "owner-sms"]'''
NEW = '''           "--why", "%s (message %s from %s at %s)" % (why, row["sid"], row["from_number"], row["date_sent"]),
           # PRIORITY 1, NOT 3. Measured 2026-09-28: with 3, the owner's own 15:57 text was still unclaimed
           # seven hours later, behind #8 (p0), #54 and #65 (p1) and a queue of p2 project items - so his
           # request changed nothing while the log looked like a response. He noticed and said "nothing
           # responded". An owner request outranks every project and integration item; only the SMS channel's
           # own repair sits above it. Do not lower this without a measurement.
           "--priority", "1", "--source", "owner-sms"]'''


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    p = TARGET
    src = p.read_text(encoding="utf-8")
    if '"--priority", "1", "--source", "owner-sms"' in src:
        print("already at priority 1")
        return 0
    if OLD not in src:
        print("ERROR: could not find the filing call - refusing to guess")
        m = re.search(r'.*"--priority".*', src)
        print("  what is there: %r" % (m.group(0)[:160] if m else "nothing"))
        return 1
    src = src.replace(OLD, NEW, 1)
    try:
        compile(src, str(p), "exec")
    except SyntaxError as exc:
        print("ERROR: does not compile: %s" % exc)
        return 1
    if not a.apply:
        print("dry run ok (use --apply)")
        return 0
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    shutil.copy2(p, p.with_name(p.name + ".bak-ownerprio-" + stamp))
    p.write_text(src, encoding="utf-8")
    print("patched %s (backup .bak-ownerprio-%s)" % (p, stamp))

    print("\n=== PROOF: call the REAL filing function and read the priority it used ===")
    code = r'''
import importlib.util, os, sqlite3, sys, types
os.environ["SMS_INBOX_DB"] = "/tmp/ownerprio-probe.db"
spec = importlib.util.spec_from_file_location("resp", "/home/zabz/bin/sms-responder.py")
m = importlib.util.module_from_spec(spec); sys.modules["resp"] = m; spec.loader.exec_module(m)
import inspect
srccall = inspect.getsource(m._file_owner_request)
print("  the priority in the source:", "1" if '"--priority", "1"' in srccall else "3 or unknown")
# and prove the argument list it builds, without touching the real ledger
import subprocess
captured = {}
real_run = subprocess.run
def spy(cmd, *a, **k):
    captured.setdefault("cmd", cmd)
    class R: stdout = 'item-filed {"id": 999}'; stderr = ""; returncode = 0
    return R()
subprocess.run = spy
try:
    conn = sqlite3.connect(":memory:"); conn.row_factory = sqlite3.Row
    row = {"sid": "SM_probe", "from_number": "+18483897895", "date_sent": "2026-09-28T23:00:00Z"}
    m._file_owner_request(conn, row, "Please check the LPT website portal login, it is broken again")
finally:
    subprocess.run = real_run
cmd = captured.get("cmd") or []
if "--priority" in cmd:
    i = cmd.index("--priority")
    print("  the argument list it actually builds: --priority %s" % cmd[i+1])
    print("  %s" % ("CORRECT - an owner text files at priority 1" if cmd[i+1] == "1" else "WRONG - still %s" % cmd[i+1]))
else:
    print("  could not capture the argument list")
'''
    out = subprocess.run(["python3", "-c", code], capture_output=True, text=True, timeout=180)
    print(out.stdout or out.stderr[:400])
    return 0


if __name__ == "__main__":
    sys.exit(main())
