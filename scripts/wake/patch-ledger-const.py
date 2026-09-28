#!/usr/bin/env python3
"""Add the missing LEDGER constant to project-keepalive.py.

WHY: the ledger-driven contract patch (patch-shift-contract.py) referenced `{LEDGER}` inside
standing_contract() without defining it at module level, so the source raised
    NameError: name 'LEDGER' is not defined
the first time it rendered a prompt. A prompt template that cannot render is worse than the
old one: it fails at the moment a session was supposed to start, in a cron log nobody reads.

This adds the definition and then PROVES the contract renders, because the previous patch was
verified with `--verify` (which only greps for strings) and not by actually calling it. The
lesson is recorded: verify a template by rendering it, not by inspecting it.

Usage: python3 patch-ledger-const.py --apply
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

TARGET = Path("/home/zabz/bin/sources/project-keepalive.py")

CONST = '''
# The work ledger CLI, on the authority. This is where the backlog, the claim, the attempt
# record (what was tried, the proving command, its output, what is left) and the item's
# definition of done live. Added 2026-09-28 with the ledger-driven standing_contract(); the
# first version of that patch referenced this name without defining it and raised
# NameError the first time a prompt was rendered. A source that cannot render a prompt is a
# source that starts nothing.
LEDGER = "python3 ~/bin/work.py"
'''


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--rollback", metavar="BACKUP")
    ap.add_argument("--target", default=str(TARGET))
    a = ap.parse_args()
    p = Path(a.target)

    if a.rollback:
        shutil.copy2(a.rollback, p)
        print("rolled back from %s" % a.rollback)
        return 0

    src = p.read_text(encoding="utf-8")
    if re.search(r"^LEDGER\s*=", src, re.M):
        print("LEDGER already defined; nothing to do")
    else:
        anchor = "# --------------------------------------------------------------------------- #\n# the standing worker contract"
        if anchor not in src:
            raise SystemExit("ERROR: could not find the contract banner - refusing to guess")
        src = src.replace(anchor, CONST.strip() + "\n\n\n" + anchor, 1)
        print("LEDGER constant added")

    new = src
    compile(new, str(p), "exec")
    if a.apply:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        bak = p.with_suffix(".py.bak-ledger-const-%s" % stamp)
        shutil.copy2(p, bak)
        p.write_text(new, encoding="utf-8")
        print("written (backup %s)" % bak.name)
    else:
        print("dry run ok (use --apply)")

    # PROVE IT RENDERS. This is the check the previous patch lacked.
    r = subprocess.run([sys.executable, "/tmp/render-contract.py", "lpt-website"],
                       capture_output=True, text=True, timeout=120)
    print("render rc=%d" % r.returncode)
    print((r.stdout or "").strip()[:1200])
    if r.returncode != 0:
        print("STDERR:", (r.stderr or "").strip()[-800:])
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
