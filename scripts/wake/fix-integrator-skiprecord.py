#!/usr/bin/env python3
"""Fix the skip record's missing key, so a skipped project prints cleanly and exits 0.

MY BUG, visible in the patch's own proof output: the skip record I insert lacks the
`recent_unmerged` key that the summary loop reads, so printing a skipped project raised KeyError and
the traceback landed in the middle of the report. The report is the only evidence a human reads from
this tool; a tool whose evidence includes a traceback is a tool people stop believing.

Usage: python3 fix-integrator-skiprecord.py [--apply]
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

TARGET = Path("/home/zabz/bin/work-integrator.py")

OLD = '''        state, detail = sync_clone(repo)
        if state in ("diverged", "dirty", "error"):
            report.append({"project": pid, "repo": real, "skipped": state,
                           "why": detail, "recent_unmerged": None, "filed": []})
            print("%-18s SKIPPED (%s): %s" % (pid, state, detail), file=sys.stderr)
            continue
'''
NEW = '''        state, detail = sync_clone(repo)
        if state in ("diverged", "dirty", "error"):
            # EVERY KEY THE PRINTER READS MUST BE PRESENT. The first version of this record lacked
            # recent_unmerged/older_unmerged/merged, so the summary loop raised KeyError and dumped a
            # traceback into the report - the one output a human reads.
            report.append({"project": pid, "repo": real, "skipped": state, "why": detail,
                           "base": None, "recent_unmerged": 0, "older_unmerged": 0, "merged": 0,
                           "filed": [], "older_sample": []})
            print("%-18s SKIPPED (%s): %s" % (pid, state, detail), file=sys.stderr)
            continue
'''


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    src = TARGET.read_text(encoding="utf-8")
    if "EVERY KEY THE PRINTER READS" in src:
        print("already fixed")
        return 0
    if OLD not in src:
        # tolerate whitespace drift by matching the essentials
        m = re.search(r'\n(\s*)report\.append\(\{"project": pid, "repo": real, "skipped": state,.*?\n\s*continue\n', src, re.S)
        if not m:
            raise SystemExit("ERROR: could not find the skip record - refusing to guess")
        src = src[:m.start()] + NEW.rstrip("\n") + src[m.end():]
    else:
        src = src.replace(OLD, NEW, 1)
    compile(src, str(TARGET), "exec")
    if not a.apply:
        print("dry run ok (use --apply)")
        return 0
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    shutil.copy2(TARGET, TARGET.with_name(TARGET.name + ".bak-skiprec-" + stamp))
    TARGET.write_text(src, encoding="utf-8")
    print("patched %s" % TARGET)

    print("\n=== PROOF: exit code and a clean report ===")
    r = subprocess.run([sys.executable, str(TARGET), "--dry-run"], capture_output=True,
                       text=True, encoding="utf-8", errors="replace", timeout=600)
    out = (r.stdout or "") + (r.stderr or "")
    print("  exit code: %d" % r.returncode)
    print("  traceback present: %s" % ("yes" if "Traceback" in out else "NO"))
    for line in out.splitlines():
        if "SKIPPED" in line or "integration item" in line or "base=" in line:
            print("  " + line.strip()[:110])
    return 0 if r.returncode == 0 and "Traceback" not in out else 1


if __name__ == "__main__":
    sys.exit(main())
